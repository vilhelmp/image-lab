import asyncio
from concurrent.futures import ThreadPoolExecutor

import pytest

from src.errors import (
    AppError,
    BudgetReachedError,
    CooldownError,
    EmptyInputError,
    PausedError,
    ProviderError,
    ProviderTimeoutError,
    RateLimitedError,
    SafetyRefusalError,
)
from src.providers.factory import Providers
from src.providers.fake import FakeImageProvider, FakeModerator
from src.services import generation
from src.services.generation import CreateRequest, GenerationService
from src.services.limits import (
    LimitService,
    clean_device_id,
    device_identity,
    hash_device_id,
    new_device_id,
)


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def make_limits(dev_settings, clock):
    def build(**overrides) -> LimitService:
        base = {
            "max_images": 100,
            "max_cost_usd": 100,
            "max_concurrent_generations": 6,
            "max_generations_per_minute": 100,
            "device_cooldown_seconds": 0,
            "device_max_images_per_hour": None,
        }
        return LimitService(
            dev_settings.config.limits.model_copy(update={**base, **overrides}), clock
        )

    return build


def test_reserve_then_reconcile_keeps_the_actual_cost(make_limits):
    limits = make_limits()
    reservation = limits.reserve(count=1, est_cost=0.05, device="a")
    assert limits.snapshot().images_used == 1
    limits.reconcile(reservation, actual_cost=0.03)
    snap = limits.snapshot()
    assert snap.images_used == 1
    assert snap.spend_usd == pytest.approx(0.03)


def test_release_returns_the_reservation(make_limits):
    limits = make_limits()
    reservation = limits.reserve(count=2, est_cost=0.1, device="a")
    limits.release(reservation)
    limits.release(reservation)  # settling twice must not go negative
    snap = limits.snapshot()
    assert (snap.images_used, snap.spend_usd) == (0, 0)


def test_compare_reserves_two_images_atomically(make_limits):
    limits = make_limits(max_images=3)
    limits.reserve(count=2, est_cost=0, device="a")
    with pytest.raises(BudgetReachedError):
        limits.reserve(count=2, est_cost=0, device="b")
    assert limits.snapshot().images_used == 2  # the failed compare took nothing
    limits.reserve(count=1, est_cost=0, device="b")


def test_cost_ceiling_is_enforced(make_limits):
    limits = make_limits(max_cost_usd=0.1)
    limits.reserve(count=1, est_cost=0.08, device="a")
    with pytest.raises(BudgetReachedError):
        limits.reserve(count=1, est_cost=0.04, device="b")


def test_twenty_threads_stay_under_the_image_ceiling(make_limits):
    limits = make_limits(max_images=7, max_cost_usd=1)

    def attempt(i: int) -> bool:
        try:
            limits.reserve(count=1, est_cost=0.01, device=f"d{i}")
            return True
        except BudgetReachedError:
            return False

    with ThreadPoolExecutor(20) as pool:
        granted = sum(pool.map(attempt, range(20)))
    assert granted == 7
    assert limits.snapshot().images_used == 7


def test_cooldown_counts_from_the_previous_start_and_is_per_device(make_limits, clock):
    limits = make_limits(device_cooldown_seconds=5)
    limits.reserve(count=1, est_cost=0, device="a")
    clock.now += 3
    with pytest.raises(CooldownError):
        limits.reserve(count=1, est_cost=0, device="a")
    limits.reserve(count=1, est_cost=0, device="b")
    clock.now += 2.1  # 5.1 s after the first start; the refused try did not extend it
    limits.reserve(count=1, est_cost=0, device="a")


def test_refused_or_failed_attempt_still_starts_the_cooldown(make_limits, clock):
    limits = make_limits(device_cooldown_seconds=5)
    limits.release(limits.reserve(count=1, est_cost=0, device="a"))
    with pytest.raises(CooldownError):
        limits.reserve(count=1, est_cost=0, device="a")


def test_missing_device_shares_one_cooldown(make_limits):
    limits = make_limits(device_cooldown_seconds=5)
    limits.reserve(count=1, est_cost=0, device=None)
    with pytest.raises(CooldownError):
        limits.reserve(count=1, est_cost=0, device=None)


def test_hourly_cap_per_device(make_limits, clock):
    limits = make_limits(device_max_images_per_hour=2)
    limits.reserve(count=1, est_cost=0, device="a")
    limits.reserve(count=1, est_cost=0, device="a")
    with pytest.raises(RateLimitedError):
        limits.reserve(count=1, est_cost=0, device="a")
    limits.reserve(count=1, est_cost=0, device="b")
    clock.now += 3601
    limits.reserve(count=1, est_cost=0, device="a")


def test_global_per_minute_rate(make_limits, clock):
    limits = make_limits(max_generations_per_minute=3)
    for i in range(3):
        limits.reserve(count=1, est_cost=0, device=f"d{i}")
    with pytest.raises(RateLimitedError):
        limits.reserve(count=1, est_cost=0, device="late")
    clock.now += 61
    limits.reserve(count=1, est_cost=0, device="late")


def test_kill_switch_blocks_and_resumes(make_limits):
    limits = make_limits()
    limits.set_paused(True)
    with pytest.raises(PausedError):
        limits.reserve(count=1, est_cost=0, device="a")
    assert limits.snapshot().paused is True
    limits.set_paused(False)
    limits.reserve(count=1, est_cost=0, device="a")


def test_reset_counters_keeps_the_pause_flag(make_limits):
    limits = make_limits()
    limits.reserve(count=1, est_cost=0.01, device="a")
    limits.record("ok", "fast", 1.0)
    limits.set_paused(True)
    limits.reset_counters()
    snap = limits.snapshot()
    assert (snap.images_used, snap.spend_usd, snap.recent["ok"]) == (0, 0, 0)
    assert snap.paused is True


def test_snapshot_counts_recent_events_and_median_latency(make_limits, clock):
    limits = make_limits()
    limits.record("ok", "fast", 2.0)
    limits.record("ok", "fast", 4.0)
    limits.record("ok", "fast", 9.0)
    limits.record("refusal", "fast", 0.1)
    clock.now += 601
    limits.record("error", "fast", 0.2)
    snap = limits.snapshot()
    assert snap.recent == {"ok": 0, "error": 1, "refusal": 0, "limited": 0}
    assert snap.p50_seconds == {}


async def test_slots_cap_concurrent_generations(make_limits):
    limits = make_limits(max_concurrent_generations=2)
    running = peak = 0

    async def work() -> None:
        nonlocal running, peak
        async with limits.slot():
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0.02)
            running -= 1

    await asyncio.gather(*(work() for _ in range(10)))
    assert peak == 2
    assert limits.snapshot().in_flight == 0


def _service(dev_settings, limits, image=None, moderator=None, fake_providers=None):
    providers = Providers(
        image=image or FakeImageProvider(delay=0.02, cost=0.005),
        edit=None,
        text=fake_providers.text,
        moderator=moderator or FakeModerator(),
    )
    return GenerationService(dev_settings, providers, limits)


async def test_twenty_concurrent_creates_stay_under_the_ceiling(
    dev_settings, fake_providers, make_limits
):
    limits = make_limits(max_images=5)
    service = _service(dev_settings, limits, fake_providers=fake_providers)
    results = await asyncio.gather(
        *(service.create(CreateRequest(text="a cat", device_hash=f"d{i}")) for i in range(20)),
        return_exceptions=True,
    )
    assert sum(not isinstance(r, Exception) for r in results) == 5
    assert all(isinstance(r, BudgetReachedError) for r in results if isinstance(r, Exception))
    assert limits.snapshot().images_used == 5


async def test_failure_after_the_provider_call_keeps_the_estimate(
    dev_settings, fake_providers, make_limits
):
    """A timeout, a drop or a 5xx may already be billed, so it is counted (spec section 10)."""
    limits = make_limits()
    service = _service(
        dev_settings,
        limits,
        image=FakeImageProvider(error=ProviderError()),
        fake_providers=fake_providers,
    )
    with pytest.raises(AppError):
        await service.create(CreateRequest(text="a cat", device_hash="a"))
    snap = limits.snapshot()
    assert snap.images_used == 1 and snap.spend_usd > 0
    assert snap.recent["error"] == 1


async def test_a_call_the_provider_did_not_start_is_released(
    dev_settings, fake_providers, make_limits
):
    limits = make_limits()
    service = _service(
        dev_settings,
        limits,
        image=FakeImageProvider(error=RateLimitedError()),
        fake_providers=fake_providers,
    )
    with pytest.raises(RateLimitedError):
        await service.create(CreateRequest(text="a cat", device_hash="a"))
    snap = limits.snapshot()
    assert (snap.images_used, snap.spend_usd) == (0, 0)
    assert not snap.paused


async def test_exhausted_provider_credit_pauses_generation(
    dev_settings, fake_providers, make_limits
):
    limits = make_limits()
    service = _service(
        dev_settings,
        limits,
        image=FakeImageProvider(error=BudgetReachedError()),
        fake_providers=fake_providers,
    )
    with pytest.raises(BudgetReachedError):
        await service.create(CreateRequest(text="a cat", device_hash="a"))
    snap = limits.snapshot()
    assert (snap.images_used, snap.spend_usd) == (0, 0)
    assert snap.paused
    with pytest.raises(PausedError):
        await service.create(CreateRequest(text="a cat", device_hash="b"))
    limits.set_paused(False)  # an admin resumes after topping up


async def test_refusal_before_generation_releases_and_is_counted(
    dev_settings, fake_providers, make_limits
):
    limits = make_limits()
    service = _service(dev_settings, limits, fake_providers=fake_providers)
    with pytest.raises(SafetyRefusalError):
        await service.create(CreateRequest(text="a [blocked] idea", device_hash="a"))
    snap = limits.snapshot()
    assert snap.images_used == 0
    assert snap.recent["refusal"] == 1


async def test_bad_input_costs_nothing_and_is_not_a_fault(
    dev_settings, fake_providers, make_limits
):
    limits = make_limits(device_cooldown_seconds=5)
    service = _service(dev_settings, limits, fake_providers=fake_providers)
    with pytest.raises(EmptyInputError):
        await service.create(CreateRequest(text="  ", device_hash="a"))
    await service.create(CreateRequest(text="a cat", device_hash="a"))  # no cooldown was started
    assert sum(limits.snapshot().recent.values()) == 1


async def test_second_create_inside_the_cooldown_is_refused(
    dev_settings, fake_providers, make_limits
):
    limits = make_limits(device_cooldown_seconds=5)
    service = _service(dev_settings, limits, fake_providers=fake_providers)
    await service.create(CreateRequest(text="a cat", device_hash="a"))
    with pytest.raises(CooldownError):
        await service.create(CreateRequest(text="a dog", device_hash="a"))
    assert limits.snapshot().recent["limited"] == 1


async def test_flagged_output_is_still_paid_for(dev_settings, fake_providers, make_limits):
    limits = make_limits()
    service = _service(
        dev_settings,
        limits,
        moderator=FakeModerator(flag_images=True),
        fake_providers=fake_providers,
    )
    with pytest.raises(SafetyRefusalError):
        await service.create(CreateRequest(text="a cat", device_hash="a"))
    snap = limits.snapshot()
    assert snap.images_used == 1
    assert snap.spend_usd == pytest.approx(0.005)


async def test_timeout_during_the_provider_call_keeps_the_estimate(
    dev_settings, fake_providers, make_limits, monkeypatch
):
    monkeypatch.setattr(generation, "CREATE_TIMEOUT_SECONDS", 0.05)
    limits = make_limits()
    service = _service(
        dev_settings,
        limits,
        image=FakeImageProvider(delay=1.0, cost=0.005),
        fake_providers=fake_providers,
    )
    with pytest.raises(ProviderTimeoutError):
        await service.create(CreateRequest(text="a cat", device_hash="a"))
    snap = limits.snapshot()
    assert snap.images_used == 1
    assert snap.spend_usd == pytest.approx(0.005)
    assert snap.recent["error"] == 1


async def test_closed_tab_is_neither_ok_nor_an_error(dev_settings, fake_providers, make_limits):
    limits = make_limits()
    service = _service(
        dev_settings,
        limits,
        image=FakeImageProvider(delay=1.0, cost=0.005),
        fake_providers=fake_providers,
    )
    task = asyncio.create_task(service.create(CreateRequest(text="a cat", device_hash="a")))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    snap = limits.snapshot()
    assert sum(snap.recent.values()) == 0
    assert snap.images_used == 1


def test_reset_while_a_call_is_in_flight_does_not_corrupt_the_new_counters(make_limits):
    limits = make_limits()
    old = limits.reserve(count=1, est_cost=0.05, device="a")
    limits.reset_counters()
    fresh = limits.reserve(count=1, est_cost=0.02, device="b")
    limits.release(old)  # the old call finishes after the reset
    snap = limits.snapshot()
    assert (snap.images_used, snap.spend_usd) == (1, pytest.approx(0.02))
    limits.reconcile(fresh, 0.02)


def test_refused_requests_leave_no_per_device_state(make_limits):
    limits = make_limits(max_images=1)
    limits.reserve(count=1, est_cost=0, device="a")
    for i in range(50):
        with pytest.raises(BudgetReachedError):
            limits.reserve(count=1, est_cost=0, device=f"forged-{i}")
    assert set(limits._device_starts) == {"a"}


async def test_paused_create_never_reaches_the_provider(dev_settings, fake_providers, make_limits):
    limits = make_limits()
    limits.set_paused(True)
    service = _service(dev_settings, limits, fake_providers=fake_providers)
    with pytest.raises(PausedError):
        await service.create(CreateRequest(text="a cat", device_hash="a"))
    assert fake_providers.moderator.text_calls == 0


def test_device_ids_are_validated_and_hashed():
    issued = new_device_id()
    assert clean_device_id(issued) == issued
    for junk in (None, 5, "", "short", "x" * 65, "has spaces and !!! chars"):
        assert clean_device_id(junk) is None
    device_id, digest = device_identity(issued)
    assert device_id == issued and digest == hash_device_id(issued)
    assert issued not in digest
    assert device_identity("junk")[0] != "junk"
