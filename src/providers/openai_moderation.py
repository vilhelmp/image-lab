"""OpenAI moderation adapter (text and image), mapped to the fixed internal code set (spec 8)."""

from __future__ import annotations

import base64
import logging
import time
from typing import Any

import httpx

from src.errors import ProviderError
from src.providers.base import ModerationCode, ModerationResult, Moderator
from src.providers.http import post_json

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.openai.com/v1"
MODERATION_TIMEOUT_SECONDS = 10.0

# OpenAI category -> internal code. Listed most serious first: the first hit names the refusal.
CATEGORY_CODES: tuple[tuple[str, ModerationCode], ...] = (
    ("sexual/minors", "minors"),
    ("sexual", "sexual"),
    ("self-harm/intent", "self_harm"),
    ("self-harm/instructions", "self_harm"),
    ("self-harm", "self_harm"),
    ("violence/graphic", "violence"),
    ("violence", "violence"),
    ("hate/threatening", "hate"),
    ("hate", "hate"),
    ("harassment/threatening", "harassment"),
    ("harassment", "harassment"),
    ("illicit/violent", "illicit"),
    ("illicit", "illicit"),
)


def _image_data_url(image: bytes) -> str:
    if image.startswith(b"\xff\xd8"):
        mime = "image/jpeg"
    elif image[:4] == b"RIFF" and image[8:12] == b"WEBP":
        mime = "image/webp"
    else:
        mime = "image/png"
    return f"data:{mime};base64,{base64.b64encode(image).decode('ascii')}"


def parse_result(body: dict[str, Any]) -> ModerationResult:
    """Turn a moderation reply into our result, or raise if it is empty or malformed.

    Any category set to true counts as flagged even if `flagged` says otherwise (fail closed).
    A flag in a category we do not know maps to "other".
    """
    results = body.get("results")
    if not isinstance(results, list) or len(results) != 1 or not isinstance(results[0], dict):
        raise ProviderError
    result = results[0]
    categories = result.get("categories")
    if not isinstance(result.get("flagged"), bool) or not isinstance(categories, dict):
        raise ProviderError
    raised = {name for name, value in categories.items() if value is True}
    if not result["flagged"] and not raised:
        return ModerationResult(flagged=False)
    code: ModerationCode = next((code for name, code in CATEGORY_CODES if name in raised), "other")
    return ModerationResult(flagged=True, code=code)


class OpenAIModerator(Moderator):
    def __init__(
        self,
        api_key: str,
        *,
        model: str = "omni-moderation-latest",
        base_url: str = DEFAULT_BASE_URL,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._model = model
        self._url = f"{base_url.rstrip('/')}/moderations"
        self._transport = transport
        self._client: httpx.AsyncClient | None = None

    async def moderate_text(self, text: str) -> ModerationResult:
        return await self._moderate(text, "text")

    async def moderate_image(self, image: bytes) -> ModerationResult:
        url = _image_data_url(image)
        return await self._moderate([{"type": "image_url", "image_url": {"url": url}}], "image")

    async def _moderate(self, content: str | list[dict[str, Any]], kind: str) -> ModerationResult:
        started = time.perf_counter()
        body = await post_json(
            self._get_client(),
            self._url,
            headers=self._headers,
            payload={"model": self._model, "input": content},
            total_timeout=MODERATION_TIMEOUT_SECONDS,
            what=f"openai moderation ({kind})",
        )
        result = parse_result(body)
        logger.info(
            "moderation kind=%s model=%s flagged=%s code=%s latency=%.2f",
            kind,
            self._model,
            result.flagged,
            result.code or "-",
            time.perf_counter() - started,
        )
        return result

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(transport=self._transport)
        return self._client
