"""Shared HTTP call for provider adapters: retries, deadline and typed errors (spec section 7).

Retries only on 429, 500, 502, 503, 504 and network timeouts or drops: at most 2, with
exponential backoff and jitter, and never beyond the total time budget. Nothing from a response
body or a request (prompts, keys, image bytes) is logged or put into an exception.
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
import time
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import httpx

from src.errors import ProviderError, ProviderTimeoutError, RateLimitedError

logger = logging.getLogger(__name__)

T = TypeVar("T")
MAX_RETRIES = 2
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
UNBILLED_RETRY_STATUSES = frozenset({429, 503})  # the provider has not started the work
BACKOFF_BASE_SECONDS = 0.5
BACKOFF_CAP_SECONDS = 4.0
JITTER_SECONDS = 0.25
_CODE_SHAPE = re.compile(r"[a-z0-9_.-]{1,60}")


def _backoff(attempt: int, retry_after: str | None, rand: Callable[[], float]) -> float:
    delay = min(BACKOFF_BASE_SECONDS * 2**attempt, BACKOFF_CAP_SECONDS) + rand() * JITTER_SECONDS
    if retry_after and retry_after.strip().isdigit():
        delay = max(delay, min(float(retry_after), BACKOFF_CAP_SECONDS))
    return delay


class Retry(Exception):
    """Raised by one attempt to ask `run_with_retries` for another try."""

    def __init__(self, failure: Exception, retry_after: str | None = None) -> None:
        super().__init__()
        self.failure = failure  # what to raise if the retries run out
        self.retry_after = retry_after


async def run_with_retries(
    attempt: Callable[[float], Awaitable[T]],
    *,
    total_timeout: float,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    rand: Callable[[], float] = random.random,
) -> T:
    """Call `attempt(seconds_left)` until it returns, raises a typed error, or the retries or the
    total budget run out. An attempt asks for a retry by raising `Retry`.

    At most MAX_RETRIES retries, exponential backoff with jitter, and never beyond the budget,
    which is enforced as a hard cap.
    """
    try:
        async with asyncio.timeout(total_timeout):
            deadline = time.monotonic() + total_timeout
            failure: Exception = ProviderError()
            for tried in range(MAX_RETRIES + 1):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ProviderTimeoutError
                try:
                    return await attempt(remaining)
                except Retry as retry:
                    failure = retry.failure
                    if tried == MAX_RETRIES:
                        break
                    delay = _backoff(tried, retry.retry_after, rand)
                    if time.monotonic() + delay >= deadline:
                        break
                    await sleep(delay)
            raise failure
    except TimeoutError as exc:
        raise ProviderTimeoutError from exc


async def post_json(
    client: httpx.AsyncClient,
    url: str,
    *,
    headers: dict[str, str],
    payload: dict[str, Any],
    total_timeout: float,
    what: str,
    idempotent: bool = True,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    rand: Callable[[], float] = random.random,
) -> dict[str, Any]:
    """POST `payload` as JSON and return the parsed JSON object, or raise a typed error.

    `what` names the call in logs ("openai moderation"). `total_timeout` is the whole budget,
    retries and waits included. Set `idempotent=False` for a call that costs money: then only 429
    and 503 are retried (the provider did not start the work), never timeouts or dropped
    connections, so a request that may already be billed is not sent twice.
    """
    retry_statuses = RETRY_STATUSES if idempotent else UNBILLED_RETRY_STATUSES
    tries = 0

    async def attempt(remaining: float) -> dict[str, Any]:
        nonlocal tries
        tries += 1
        try:
            response = await client.post(url, headers=headers, json=payload, timeout=remaining)
        except httpx.TimeoutException:
            logger.warning("%s: timeout (attempt %d)", what, tries)
            raise (
                Retry(ProviderTimeoutError()) if idempotent else ProviderTimeoutError()
            ) from None
        except httpx.TransportError as exc:
            logger.warning("%s: %s (attempt %d)", what, type(exc).__qualname__, tries)
            raise (Retry(ProviderError()) if idempotent else ProviderError()) from exc
        except httpx.HTTPError as exc:
            logger.error("%s: %s, not retried", what, type(exc).__qualname__)
            raise ProviderError from exc
        status = response.status_code
        if status < 400:
            return _json_object(response, what)
        if status not in retry_statuses:
            logger.error("%s: HTTP %d (%s), not retried", what, status, _error_code(response))
            raise ProviderError
        logger.warning("%s: HTTP %d (%s) (attempt %d)", what, status, _error_code(response), tries)
        raise Retry(
            RateLimitedError() if status == 429 else ProviderError(),
            response.headers.get("retry-after"),
        )

    return await run_with_retries(attempt, total_timeout=total_timeout, sleep=sleep, rand=rand)


def _error_code(response: httpx.Response) -> str:
    """The provider's short machine code for an error (for example "invalid_api_key"), or "-".

    Only a code-shaped token is returned, never the message, which could echo request content.
    """
    try:
        error = response.json().get("error")
    except (ValueError, AttributeError):
        return "-"
    if isinstance(error, dict):
        for key in ("code", "type"):
            value = error.get(key)
            if isinstance(value, str) and _CODE_SHAPE.fullmatch(value):
                return value
    return "-"


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
