"""The paid-call pattern shared by Create and the edit chips: reserve, call, reconcile or release.

One place decides what a failure costs, so the rules cannot drift (spec section 10):
- the estimate is reserved before anything is sent to a paid provider, under the limit lock;
- a failure before the provider call releases it;
- a failure after the call keeps the estimate (a timeout, a drop or a 5xx may be billed), unless
  the error is known unbilled (`unbilled = True`);
- a 402 from the provider (credit used up) pauses generation until an admin resumes;
- a finished image stays counted at its actual estimate, even if the output check refuses it.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from src.errors import BudgetReachedError
from src.providers.base import ImageResult
from src.services.limits import LimitService

logger = logging.getLogger(__name__)


async def paid_call(
    limits: LimitService,
    *,
    est_cost: float,
    device: str | None,
    prepare: Callable[[], Awaitable[None]],
    call: Callable[[], Awaitable[ImageResult]],
) -> ImageResult:
    """`prepare` runs after the reservation (safety checks); `call` is the paid provider call."""
    reservation = limits.reserve(count=1, est_cost=est_cost, device=device)
    provider_called = False
    try:
        await prepare()
        async with limits.slot():
            provider_called = True
            result = await call()
    except BaseException as exc:
        if provider_called and not getattr(exc, "unbilled", False):
            limits.reconcile(reservation, est_cost)
        else:
            limits.release(reservation)
        if provider_called and isinstance(exc, BudgetReachedError):
            logger.error("Provider credit exhausted: pausing generation")
            limits.set_paused(True)
        raise
    limits.reconcile(reservation, result.est_cost)
    return result
