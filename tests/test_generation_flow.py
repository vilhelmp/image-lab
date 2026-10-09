import io
import logging

import pytest
from PIL import Image

from src.errors import (
    AppError,
    CheckFailedError,
    EmptyInputError,
    ProviderError,
    ProviderTimeoutError,
    SafetyRefusalError,
)
from src.providers.factory import Providers
from src.providers.fake import FakeImageProvider, FakeModerator
from src.services import generation
from src.services.flags import RuntimeFlags
from src.services.generation import CreateRequest, GenerationService
from src.services.limits import LimitService


def _service(settings, providers: Providers) -> GenerationService:
    return GenerationService(settings, providers, LimitService(settings.config.limits))


async def test_create_returns_png_and_composed_prompt(dev_settings, fake_providers):
    result = await _service(dev_settings, fake_providers).create(
        CreateRequest(text="A cat", style="retro", aspect="landscape")
    )
    assert Image.open(io.BytesIO(result.image)).size == (640, 384)
    assert result.model_key == dev_settings.models.defaults.create_model
    assert result.final_prompt.startswith("A cat, retro 1970s poster")
    assert fake_providers.moderator.text_calls == 1
    assert fake_providers.moderator.image_calls == 1


async def test_the_admin_switch_makes_create_use_the_high_quality_model(
    dev_settings, fake_providers
):
    flags = RuntimeFlags()
    limits = LimitService(dev_settings.config.limits)
    service = GenerationService(dev_settings, fake_providers, limits, flags=flags)
    defaults = dev_settings.models.defaults
    assert defaults.high_quality_model and defaults.high_quality_model != defaults.create_model
    first = await service.create(CreateRequest(text="A cat", device_hash="a"))
    assert first.model_key == defaults.create_model
    flags.set_high_quality(True)
    result = await service.create(CreateRequest(text="A dog", device_hash="b"))
    assert result.model_key == defaults.high_quality_model
    assert fake_providers.moderator.text_calls == 2 and fake_providers.moderator.image_calls == 2
    flags.set_high_quality(False)
    last = await service.create(CreateRequest(text="A fox", device_hash="c"))
    assert last.model_key == defaults.create_model


async def test_the_high_quality_model_reserves_its_own_higher_cost(dev_settings, fake_providers):
    providers = Providers(
        image=FakeImageProvider(error=ProviderError()),  # a billed failure keeps the estimate
        edit=None,
        text=fake_providers.text,
        moderator=fake_providers.moderator,
    )
    limits = LimitService(dev_settings.config.limits)
    service = GenerationService(
        dev_settings, providers, limits, flags=RuntimeFlags(high_quality=True)
    )
    with pytest.raises(ProviderError):
        await service.create(CreateRequest(text="A cat"))
    quality = dev_settings.models.image_models[dev_settings.models.defaults.high_quality_model]
    assert limits.snapshot().spend_usd == pytest.approx(quality.est_cost_usd)


async def test_a_blocked_prompt_is_refused_with_the_high_quality_model_too(
    dev_settings, fake_providers
):
    service = GenerationService(
        dev_settings,
        fake_providers,
        LimitService(dev_settings.config.limits),
        flags=RuntimeFlags(high_quality=True),
    )
    with pytest.raises(SafetyRefusalError):
        await service.create(CreateRequest(text="a [blocked] idea"))
    assert fake_providers.image.calls == []


async def test_blocked_prompt_never_reaches_the_image_provider(dev_settings, fake_providers):
    with pytest.raises(SafetyRefusalError):
        await _service(dev_settings, fake_providers).create(CreateRequest(text="a [blocked] idea"))
    assert fake_providers.image.calls == []


async def test_moderation_failure_fails_closed(dev_settings, fake_providers):
    providers = Providers(
        image=fake_providers.image,
        edit=None,
        text=fake_providers.text,
        moderator=FakeModerator(fail=True),
    )
    with pytest.raises(CheckFailedError):
        await _service(dev_settings, providers).create(CreateRequest(text="a cat"))
    assert providers.image.calls == []


async def test_output_check_failure_fails_closed(dev_settings, fake_providers):
    providers = Providers(
        image=fake_providers.image,
        edit=None,
        text=fake_providers.text,
        moderator=FakeModerator(fail_image=True),
    )
    with pytest.raises(CheckFailedError):
        await _service(dev_settings, providers).create(CreateRequest(text="a cat"))
    assert len(providers.image.calls) == 1


async def test_malformed_moderation_verdict_fails_closed(dev_settings, fake_providers):
    class NoVerdict(FakeModerator):
        async def moderate_text(self, text):
            return None

    providers = Providers(
        image=fake_providers.image,
        edit=None,
        text=fake_providers.text,
        moderator=NoVerdict(),
    )
    with pytest.raises(CheckFailedError):
        await _service(dev_settings, providers).create(CreateRequest(text="a cat"))
    assert providers.image.calls == []


async def test_flagged_output_image_is_not_returned(dev_settings, fake_providers):
    providers = Providers(
        image=fake_providers.image,
        edit=None,
        text=fake_providers.text,
        moderator=FakeModerator(flag_images=True),
    )
    with pytest.raises(SafetyRefusalError):
        await _service(dev_settings, providers).create(CreateRequest(text="a cat"))
    assert len(providers.image.calls) == 1


async def test_empty_text_is_rejected_before_any_call(dev_settings, fake_providers):
    with pytest.raises(EmptyInputError):
        await _service(dev_settings, fake_providers).create(CreateRequest(text="   "))
    assert fake_providers.moderator.text_calls == 0
    assert fake_providers.image.calls == []


async def test_slow_provider_times_out_with_typed_error(dev_settings, fake_providers, monkeypatch):
    monkeypatch.setattr(generation, "CREATE_TIMEOUT_SECONDS", 0.05)
    providers = Providers(
        image=FakeImageProvider(delay=1.0),
        edit=None,
        text=fake_providers.text,
        moderator=fake_providers.moderator,
    )
    with pytest.raises(ProviderTimeoutError):
        await _service(dev_settings, providers).create(CreateRequest(text="a cat"))


async def test_unexpected_provider_error_becomes_generic_app_error(dev_settings, fake_providers):
    providers = Providers(
        image=FakeImageProvider(error=ValueError("boom with details")),
        edit=None,
        text=fake_providers.text,
        moderator=fake_providers.moderator,
    )
    with pytest.raises(AppError) as info:
        await _service(dev_settings, providers).create(CreateRequest(text="a cat"))
    assert type(info.value) is AppError
    assert info.value.message_key == "error.generic"


async def test_logs_hold_no_prompt_text(dev_settings, fake_providers, caplog):
    caplog.set_level(logging.DEBUG)
    phrase = "purple-elephant-unique-phrase"
    await _service(dev_settings, fake_providers).create(CreateRequest(text=phrase))
    providers = Providers(
        image=FakeImageProvider(error=ValueError(phrase)),
        edit=None,
        text=fake_providers.text,
        moderator=fake_providers.moderator,
    )
    with pytest.raises(AppError):
        await _service(dev_settings, providers).create(CreateRequest(text=phrase))
    assert phrase not in caplog.text
    assert "outcome=ok" in caplog.text
