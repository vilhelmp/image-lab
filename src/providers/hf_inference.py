"""Image generation through Hugging Face Inference Providers (`image_backend: hf`, spec section 5).

Needs only `HF_TOKEN`. The model id and the routed provider come from `config/models.yaml`
(`hf_model`, `hf_provider`), so adding a model is config-only. Returns PNG bytes. A call costs
money, so only 429 and 503 are retried, never a timeout or a dropped connection. Nothing from a
prompt, a response or an exception message is logged.
"""

from __future__ import annotations

import asyncio
import io
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from huggingface_hub import InferenceClient
from huggingface_hub.errors import HfHubHTTPError, InferenceTimeoutError

from src.config import Settings
from src.errors import BudgetReachedError, ProviderError, ProviderTimeoutError, RateLimitedError
from src.providers.base import Aspect, ImageProvider, ImageRequest, ImageResult
from src.providers.http import UNBILLED_RETRY_STATUSES, Retry, run_with_retries

logger = logging.getLogger(__name__)

IMAGE_TIMEOUT_SECONDS = 45.0  # spec section 8: hard timeout for Create
SIZES: dict[Aspect, tuple[int, int]] = {
    "square": (768, 768),
    "landscape": (1024, 576),
    "portrait": (576, 1024),
}
_FAL = "fal-ai"


class HFImageProvider(ImageProvider):
    def __init__(
        self,
        token: str,
        settings: Settings,
        *,
        client: Any = None,
        timeout: float = IMAGE_TIMEOUT_SECONDS,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._token = token
        self._sleep = sleep
        self._settings = settings
        self._client = client  # one client per model provider, created on first use
        self._clients: dict[str | None, Any] = {}
        self._timeout = timeout

    def _client_for(self, provider: str | None) -> Any:
        if self._client is not None:
            return self._client
        if provider not in self._clients:
            self._clients[provider] = InferenceClient(
                provider=provider or "auto", api_key=self._token, timeout=self._timeout
            )
        return self._clients[provider]

    async def generate(self, req: ImageRequest) -> ImageResult:
        model = self._settings.models.image_models[req.model_key]
        if not model.hf_model:
            raise ProviderError  # config error: the model has no hf_model
        client = self._client_for(model.hf_provider)
        width, height = SIZES[req.aspect]
        extra = {"enable_safety_checker": True} if model.hf_provider == _FAL else None
        started = time.monotonic()

        async def attempt(remaining: float) -> Any:
            try:
                # The SDK's fal route downloads the image with a blocking call, so the whole call
                # runs in a worker thread: the event loop stays free and the timeout can fire.
                return await asyncio.wait_for(
                    asyncio.to_thread(
                        client.text_to_image,
                        req.prompt,
                        model=model.hf_model,
                        width=width,
                        height=height,
                        extra_body=extra,
                    ),
                    timeout=remaining,
                )
            except (TimeoutError, InferenceTimeoutError, httpx.TimeoutException):
                logger.warning("hf image %s: timeout", req.model_key)
                raise ProviderTimeoutError from None
            except HfHubHTTPError as exc:
                status = exc.response.status_code if exc.response is not None else 0
                if status in UNBILLED_RETRY_STATUSES:
                    logger.warning("hf image %s: HTTP %d", req.model_key, status)
                    raise Retry(
                        RateLimitedError(), exc.response.headers.get("retry-after")
                    ) from None
                if status == 402:
                    logger.error(
                        "hf image %s: HTTP 402, the inference credit is used up", req.model_key
                    )
                    raise BudgetReachedError from None
                logger.error("hf image %s: HTTP %d, not retried", req.model_key, status)
                raise ProviderError from None
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("hf image %s: %s", req.model_key, type(exc).__qualname__)
                raise ProviderError from None

        image = await run_with_retries(attempt, total_timeout=self._timeout, sleep=self._sleep)
        try:
            png = await asyncio.to_thread(_to_png, image)
        except Exception as exc:
            logger.error("hf image %s: unusable image (%s)", req.model_key, type(exc).__qualname__)
            raise ProviderError from None
        return ImageResult(
            image=png,
            model_key=req.model_key,
            seconds=time.monotonic() - started,
            est_cost=model.est_cost_usd,
        )


def _to_png(image: Any) -> bytes:
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="PNG")
    return buffer.getvalue()
