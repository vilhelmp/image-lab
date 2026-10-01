"""OpenAI text adapter: policy check and prompt helpers as strict-JSON chat completions (spec 6).

Uses /chat/completions so any OpenAI-compatible endpoint works through `base_url`.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import httpx

from src.errors import MalformedReplyError, ProviderError
from src.providers.base import TextProvider
from src.providers.http import post_json

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.openai.com/v1"
TEXT_TIMEOUT_SECONDS = 15.0

_POLICY_CATEGORIES = [
    "sexual",
    "minors",
    "violence",
    "hate",
    "self_harm",
    "real_person",
    "character",
    "other",
    None,
]
_STRING = {"type": "string"}
_NULLABLE_STRING = {"type": ["string", "null"]}


def _object(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


# Strict structured outputs need every field required and no extras.
TASK_SCHEMAS: dict[str, dict[str, Any]] = {
    "policy_check": _object(
        {
            "allowed": {"type": "boolean"},
            "category": {"type": ["string", "null"], "enum": _POLICY_CATEGORIES},
            "rewrite": _NULLABLE_STRING,
        }
    ),
    "improve": _object({"prompt": _STRING}),
    "surprise": _object({"prompt": _STRING}),
    "edit_instruction": _object({"instruction": _STRING}),
}


def parse_completion(body: dict[str, Any]) -> dict[str, Any]:
    """The JSON object in a chat completion, or a typed error if there is none to trust.

    A refusal or a filtered reply is a plain ProviderError; unusable JSON is a
    MalformedReplyError, which callers may retry once.
    """
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise MalformedReplyError
    choice = choices[0]
    message = choice.get("message")
    if not isinstance(message, dict):
        raise MalformedReplyError
    if message.get("refusal") or choice.get("finish_reason") not in ("stop", "length"):
        raise ProviderError
    if choice.get("finish_reason") == "length":
        raise MalformedReplyError
    content = message.get("content")
    if not isinstance(content, str):
        raise MalformedReplyError
    try:
        parsed = json.loads(content)
    except ValueError as exc:
        raise MalformedReplyError from exc
    if not isinstance(parsed, dict):
        raise MalformedReplyError
    return parsed


class OpenAITextProvider(TextProvider):
    def __init__(
        self,
        api_key: str,
        *,
        model: str,
        base_url: str = DEFAULT_BASE_URL,
        reasoning_effort: str | None = "none",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._model = model
        self._url = f"{base_url.rstrip('/')}/chat/completions"
        self._reasoning_effort = reasoning_effort
        self._transport = transport
        self._client: httpx.AsyncClient | None = None

    async def complete_json(
        self, task: str, system: str, user: str, max_tokens: int = 200
    ) -> dict[str, Any]:
        schema = TASK_SCHEMAS.get(task)
        if schema is None:
            raise ProviderError
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": task, "strict": True, "schema": schema},
            },
            "max_completion_tokens": max_tokens,
        }
        if self._reasoning_effort:
            payload["reasoning_effort"] = self._reasoning_effort
        started = time.perf_counter()
        body = await post_json(
            self._get_client(),
            self._url,
            headers=self._headers,
            payload=payload,
            total_timeout=TEXT_TIMEOUT_SECONDS,
            what=f"openai text ({task})",
        )
        parsed = parse_completion(body)
        logger.info(
            "text task=%s model=%s latency=%.2f", task, self._model, time.perf_counter() - started
        )
        return parsed

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(transport=self._transport)
        return self._client
