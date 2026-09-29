"""Budget pacing, rate limits, device cooldown and the kill switch (spec section 10).

State is in memory and resets on restart. Provider prepaid credit is the hard cap; these
counters only pace. One threading.Lock guards all counters: every critical section is short and
never awaits, so it is safe from async generation code and from sync admin callbacks.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import secrets
import statistics
import threading
import time
from collections import defaultdict, deque
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Literal

from src.config import LimitsSection
from src.errors import BudgetReachedError, CooldownError, PausedError, RateLimitedError

logger = logging.getLogger(__name__)

MINUTE = 60.0
HOUR = 3600.0
STATS_WINDOW = 600.0
MAX_EVENTS = 5000
MAX_TRACKED_DEVICES = 5000
UNKNOWN_DEVICE = "-"

_DEVICE_ID = re.compile(r"[A-Za-z0-9_-]{16,64}")
_SALT = secrets.token_hex(8)

Kind = Literal["ok", "error", "refusal", "limited"]


def new_device_id() -> str:
    return secrets.token_urlsafe(16)


def clean_device_id(raw: object) -> str | None:
    """The stored id if it looks like one we issued. The browser controls it, so never trust it."""
    return raw if isinstance(raw, str) and _DEVICE_ID.fullmatch(raw) else None


def hash_device_id(raw: str) -> str:
    """Short salted hash for limits and logs. The salt changes on every restart."""
    return hashlib.sha256(f"{_SALT}:{raw}".encode()).hexdigest()[:12]


def device_identity(raw: object) -> tuple[str, str]:
    """(id to keep in the browser, hash to use for limits and logs)."""
    device_id = clean_device_id(raw) or new_device_id()
    return device_id, hash_device_id(device_id)


@dataclass
class Reservation:
    count: int
    cost: float
    epoch: int = 0
    settled: bool = False


@dataclass(frozen=True)
class Snapshot:
    images_used: int
    max_images: int
    spend_usd: float
    max_cost_usd: float
    in_flight: int
    paused: bool
    recent: dict[Kind, int]
    p50_seconds: dict[str, float]


class LimitService:
    def __init__(self, limits: LimitsSection, clock: Callable[[], float] = time.monotonic) -> None:
        self._limits = limits
        self._clock = clock
        self._lock = threading.Lock()
        self._slots = asyncio.Semaphore(limits.max_concurrent_generations)
        self._paused = False
        self._epoch = 0
        self._images = 0
        self._spend = 0.0
        self._in_flight = 0
        self._starts: deque[float] = deque()
        self._device_last: dict[str, float] = {}
        self._device_starts: dict[str, deque[float]] = {}
        self._events: deque[tuple[float, Kind, str, float]] = deque(maxlen=MAX_EVENTS)

    def reserve(self, *, count: int, est_cost: float, device: str | None) -> Reservation:
        """Claim budget for `count` images before calling a provider, or raise a typed error."""
        limits = self._limits
        key = device or UNKNOWN_DEVICE
        now = self._clock()
        with self._lock:
            if self._paused:
                raise PausedError
            last = self._device_last.get(key)
            if last is not None and now - last < limits.device_cooldown_seconds:
                raise CooldownError
            hour = self._device_starts.get(key) or deque()
            _drop_older(hour, now - HOUR)
            if limits.device_max_images_per_hour and (
                len(hour) + count > limits.device_max_images_per_hour
            ):
                raise RateLimitedError
            _drop_older(self._starts, now - MINUTE)
            if len(self._starts) + count > limits.max_generations_per_minute:
                raise RateLimitedError
            if (
                self._images + count > limits.max_images
                or self._spend + est_cost > limits.max_cost_usd
            ):
                raise BudgetReachedError

            self._device_last[key] = now
            self._device_starts[key] = hour
            hour.extend([now] * count)
            self._starts.extend([now] * count)
            self._images += count
            self._spend += est_cost
            self._forget_idle_devices(now)
            return Reservation(count=count, cost=est_cost, epoch=self._epoch)

    def reconcile(self, reservation: Reservation, actual_cost: float) -> None:
        with self._lock:
            if reservation.settled:
                return
            reservation.settled = True
            if reservation.epoch != self._epoch:
                return
            self._spend = max(0.0, self._spend + actual_cost - reservation.cost)

    def release(self, reservation: Reservation) -> None:
        """Return the budget of a call that produced nothing. The cooldown still counts."""
        with self._lock:
            if reservation.settled:
                return
            reservation.settled = True
            if reservation.epoch != self._epoch:
                return
            self._images = max(0, self._images - reservation.count)
            self._spend = max(0.0, self._spend - reservation.cost)

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        """Hold one of the global concurrent-generation slots."""
        async with self._slots:
            with self._lock:
                self._in_flight += 1
            try:
                yield
            finally:
                with self._lock:
                    self._in_flight -= 1

    def record(self, kind: Kind, model: str, seconds: float) -> None:
        with self._lock:
            self._events.append((self._clock(), kind, model, seconds))

    @property
    def paused(self) -> bool:
        with self._lock:
            return self._paused

    def set_paused(self, paused: bool) -> None:
        with self._lock:
            self._paused = paused
        logger.info("admin action: paused=%s", paused)

    def reset_counters(self) -> None:
        """Zero the counters. Reservations still in flight no longer count against the new ones."""
        with self._lock:
            self._epoch += 1
            self._images = 0
            self._spend = 0.0
            self._starts.clear()
            self._events.clear()
        logger.info("admin action: counters reset")

    def snapshot(self) -> Snapshot:
        now = self._clock()
        with self._lock:
            recent = [e for e in self._events if now - e[0] <= STATS_WINDOW]
            counts: dict[Kind, int] = {"ok": 0, "error": 0, "refusal": 0, "limited": 0}
            latencies: defaultdict[str, list[float]] = defaultdict(list)
            for _, kind, model, seconds in recent:
                counts[kind] += 1
                if kind == "ok":
                    latencies[model].append(seconds)
            return Snapshot(
                images_used=self._images,
                max_images=self._limits.max_images,
                spend_usd=self._spend,
                max_cost_usd=self._limits.max_cost_usd,
                in_flight=self._in_flight,
                paused=self._paused,
                recent=counts,
                p50_seconds={m: statistics.median(v) for m, v in latencies.items()},
            )

    def _forget_idle_devices(self, now: float) -> None:
        """Bound memory if many device ids are forged. Caller holds the lock."""
        if len(self._device_last) <= MAX_TRACKED_DEVICES:
            return
        stale = [k for k, t in self._device_last.items() if now - t > HOUR]
        for key in stale:
            self._device_last.pop(key, None)
        for key in [k for k, v in self._device_starts.items() if not v or now - v[-1] > HOUR]:
            del self._device_starts[key]


def _drop_older(stamps: deque[float], cutoff: float) -> None:
    while stamps and stamps[0] < cutoff:
        stamps.popleft()
