"""Image generation and editing through Hugging Face Inference Providers (spec section 5).

Needs only `HF_TOKEN`. The model id and the routed provider come from `config/models.yaml`
(`hf_model`, `hf_provider`), so adding a model is config-only. Returns PNG bytes. A call costs
money, so only 429 and 503 are retried, never a timeout or a dropped connection. Nothing from a
prompt, a response or an exception message is logged.
"""

from __future__ import annotations

import asyncio
import functools
import io
import logging
import time
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import httpx
from huggingface_hub import InferenceClient
from huggingface_hub.errors import HfHubHTTPError, InferenceTimeoutError
from huggingface_hub.utils import is_pillow_available
from PIL import Image

from src.config import Settings
from src.errors import BudgetReachedError, ProviderError, ProviderTimeoutError, RateLimitedError
from src.providers.base import (
    Aspect,
    EditProvider,
    EditRequest,
    ImageProvider,
    ImageRequest,
    ImageResult,
)
from src.providers.http import UNBILLED_RETRY_STATUSES, Retry, run_with_retries

logger = logging.getLogger(__name__)

# The SDK caches its Pillow check on first use, and threads that ask at the same time see "not
# installed" (an ImportError on the first burst of requests). Ask once, before any thread does.
is_pillow_available()

IMAGE_TIMEOUT_SECONDS = 45.0  # spec section 8: hard timeout for Create
EDIT_TIMEOUT_SECONDS = 60.0  # spec section 8: hard timeout for an edit chip
SIZES: dict[Aspect, tuple[int, int]] = {
    "square": (768, 768),
    "landscape": (1024, 576),
    "portrait": (576, 1024),
}
_FAL = "fal-ai"
_SDK_THREADS = ThreadPoolExecutor(max_workers=16, thread_name_prefix="hf-sdk")


def safety_extra(provider: str | None) -> dict[str, Any] | None:
    """The strictest safety flag a provider understands; only fal takes one through the router."""
    return {"enable_safety_checker": True} if provider == _FAL else None


class HFRunner:
    """Runs one SDK call safely and returns PNG bytes: typed errors, billing-safe retries, a hard
    deadline, and a worker thread so a blocking download cannot freeze the event loop."""

    def __init__(
        self,
        token: str,
        *,
        client: Any = None,
        timeout: float,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._token = token
        self._client = client  # a stand-in for tests; otherwise one client per provider
        self._clients: dict[str | None, Any] = {}
        self._timeout = timeout
        self._sleep = sleep

    def _client_for(self, provider: str | None) -> Any:
        if self._client is not None:
            return self._client
        if provider not in self._clients:
            self._clients[provider] = InferenceClient(
                provider=provider or "auto", api_key=self._token, timeout=self._timeout
            )
        return self._clients[provider]

    async def png(
        self, label: str, provider: str | None, method: str, *args: Any, **kwargs: Any
    ) -> bytes:
        call = getattr(self._client_for(provider), method)

        async def attempt(remaining: float) -> Any:
            try:
                # The SDK's fal route downloads the image with a blocking call, so the whole call
                # runs in a worker thread: the event loop stays free and the timeout can fire.
                # A pool of its own, so slow image calls never starve photo decoding and reads.
                return await asyncio.wait_for(
                    asyncio.get_running_loop().run_in_executor(
                        _SDK_THREADS, functools.partial(call, *args, **kwargs)
                    ),
                    timeout=remaining,
                )
            except (TimeoutError, InferenceTimeoutError, httpx.TimeoutException):
                logger.warning("%s: timeout", label)
                raise ProviderTimeoutError from None
            except HfHubHTTPError as exc:
                status = exc.response.status_code if exc.response is not None else 0
                if status in UNBILLED_RETRY_STATUSES:
                    logger.warning("%s: HTTP %d", label, status)
                    raise Retry(
                        RateLimitedError(), exc.response.headers.get("retry-after")
                    ) from None
                if status == 402:
                    logger.error("%s: HTTP 402, the inference credit is used up", label)
                    raise BudgetReachedError from None
                logger.error("%s: HTTP %d, not retried", label, status)
                raise ProviderError from None
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("%s: %s", label, type(exc).__qualname__)
                raise ProviderError from None

        image = await run_with_retries(attempt, total_timeout=self._timeout, sleep=self._sleep)
        try:
            return await asyncio.to_thread(_to_png, image)
        except Exception as exc:
            logger.error("%s: unusable image (%s)", label, type(exc).__qualname__)
            raise ProviderError from None


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
        self._settings = settings
        self._runner = HFRunner(token, client=client, timeout=timeout, sleep=sleep)

    async def generate(self, req: ImageRequest) -> ImageResult:
        model = self._settings.models.image_models[req.model_key]
        if not model.hf_model:
            raise ProviderError  # config error: the model has no hf_model
        width, height = SIZES[req.aspect]
        started = time.monotonic()
        png = await self._runner.png(
            f"hf image {req.model_key}",
            model.hf_provider,
            "text_to_image",
            req.prompt,
            model=model.hf_model,
            width=width,
            height=height,
            extra_body=safety_extra(model.hf_provider),
        )
        return ImageResult(
            image=png,
            model_key=req.model_key,
            seconds=time.monotonic() - started,
            est_cost=model.est_cost_usd,
        )


class HFEditProvider(EditProvider):
    """Instruction-based editing (image to image): the current image plus a short instruction."""

    def __init__(
        self,
        token: str,
        settings: Settings,
        *,
        client: Any = None,
        timeout: float = EDIT_TIMEOUT_SECONDS,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._settings = settings
        self._runner = HFRunner(token, client=client, timeout=timeout, sleep=sleep)

    async def edit(self, req: EditRequest) -> ImageResult:
        model = self._settings.models.edit_models[req.model_key]
        if not model.hf_model:
            raise ProviderError  # config error: the model has no hf_model
        started = time.monotonic()
        try:  # the current image may be a webp example; providers reliably take PNG
            source = await asyncio.to_thread(_to_png, Image.open(io.BytesIO(req.image)))
        except Exception as exc:
            logger.error(
                "hf edit %s: unusable source image (%s)", req.model_key, type(exc).__qualname__
            )
            raise ProviderError from None
        png = await self._runner.png(
            f"hf edit {req.model_key}",
            model.hf_provider,
            "image_to_image",
            source,
            prompt=req.instruction,
            model=model.hf_model,
            extra_body=safety_extra(model.hf_provider),
        )
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
