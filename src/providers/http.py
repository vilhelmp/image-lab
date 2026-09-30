"""Shared HTTP call for provider adapters: retries, deadline and typed errors (spec section 7).

Retries only on 429, 500, 502, 503, 504 and network timeouts or drops: at most 2, with
exponential backoff and jitter, and never beyond the total time budget. Nothing from a response
body or a request (prompts, keys, image bytes) is logged or put into an exception.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from src.errors import ProviderError, ProviderTimeoutError, RateLimitedError

logger = logging.getLogger(__name__)

MAX_RETRIES = 2
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
BACKOFF_BASE_SECONDS = 0.5
BACKOFF_CAP_SECONDS = 4.0
JITTER_SECONDS = 0.25


def _backoff(attempt: int, retry_after: str | None, rand: Callable[[], float]) -> float:
    delay = min(BACKOFF_BASE_SECONDS * 2**attempt, BACKOFF_CAP_SECONDS) + rand() * JITTER_SECONDS
    if retry_after and retry_after.strip().isdigit():
        delay = max(delay, min(float(retry_after), BACKOFF_CAP_SECONDS))
    return delay


async def post_json(
    client: httpx.AsyncClient,
    url: str,
    *,
    headers: dict[str, str],
    payload: dict[str, Any],
    total_timeout: float,
    what: str,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    rand: Callable[[], float] = random.random,
) -> dict[str, Any]:
    """POST `payload` as JSON and return the parsed JSON object, or raise a typed error.

    `what` names the call in logs ("openai moderation"). `total_timeout` is the whole budget,
    retries and waits included; it is enforced as a hard cap, not only per request phase.
    """
    try:
        async with asyncio.timeout(total_timeout):
            return await _attempts(client, url, headers, payload, total_timeout, what, sleep, rand)
    except TimeoutError as exc:
        raise ProviderTimeoutError from exc


async def _attempts(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    total_timeout: float,
    what: str,
    sleep: Callable[[float], Awaitable[None]],
    rand: Callable[[], float],
) -> dict[str, Any]:
    deadline = time.monotonic() + total_timeout
    failure: Exception = ProviderError()
    for attempt in range(MAX_RETRIES + 1):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ProviderTimeoutError
        retry_after: str | None = None
        try:
            response = await client.post(url, headers=headers, json=payload, timeout=remaining)
        except httpx.TimeoutException:
            failure = ProviderTimeoutError()
            logger.warning("%s: timeout (attempt %d)", what, attempt + 1)
        except httpx.TransportError as exc:
            failure = ProviderError()
            logger.warning("%s: %s (attempt %d)", what, type(exc).__qualname__, attempt + 1)
        except httpx.HTTPError as exc:
            logger.error("%s: %s, not retried", what, type(exc).__qualname__)
            raise ProviderError from exc
        else:
            status = response.status_code
            if status < 400:
                return _json_object(response, what)
            if status not in RETRY_STATUSES:
                logger.error("%s: HTTP %d, not retried", what, status)
                raise ProviderError
            failure = RateLimitedError() if status == 429 else ProviderError()
            retry_after = response.headers.get("retry-after")
            logger.warning("%s: HTTP %d (attempt %d)", what, status, attempt + 1)
        if attempt == MAX_RETRIES:
            break
        delay = _backoff(attempt, retry_after, rand)
        if time.monotonic() + delay >= deadline:
            break
        await sleep(delay)
    raise failure


def _json_object(response: httpx.Response, what: str) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError as exc:
        logger.error("%s: the reply was not JSON", what)
        raise ProviderError from exc
    if not isinstance(data, dict):
        logger.error("%s: the reply was not a JSON object", what)
        raise ProviderError
    return data
