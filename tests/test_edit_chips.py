"""One-tap edit chips: config, the edit flow in the generation service, and the helper LLM."""

import io
import json
import logging

import pytest
from PIL import Image

from src.config import EditChip
from src.errors import (
    BudgetReachedError,
    CheckFailedError,
    CooldownError,
    PausedError,
    ProviderError,
    ProviderTimeoutError,
    RateLimitedError,
    SafetyRefusalError,
)
from src.providers.base import TextProvider
from src.providers.factory import Providers
from src.providers.fake import FakeEditProvider, FakeImageProvider, FakeModerator, FakeTextProvider
from src.services import generation
from src.services.generation import ChipRequest, GenerationService
from src.services.helpers import HelperService
from src.services.limits import LimitService

SECRET = "a private idea about my neighbour"


def png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (16, 16), (30, 90, 160)).save(buffer, format="PNG")
    return buffer.getvalue()


class Scripted(TextProvider):
    def __init__(self, reply) -> None:
        self.reply = reply
        self.calls: list[tuple[str, str]] = []

    async def complete_json(self, task, system, user, max_tokens=200):
        self.calls.append((task, user))
        if task == "policy_check":
            return FakeTextProvider._policy(user)
        if isinstance(self.reply, BaseException):
            raise self.reply
        return self.reply


def build(dev_settings, edit=None, text=None, moderator=None):
    limits = LimitService(dev_settings.config.limits)
    edit = edit or FakeEditProvider(cost=0.01)
    providers = Providers(
        image=FakeImageProvider(),
        edit=edit,
        text=text or FakeTextProvider(),
        moderator=moderator or FakeModerator(),
    )
    helpers = HelperService(dev_settings, providers, limits)
    return GenerationService(dev_settings, providers, limits, None, helpers), limits, edit


def chip_request(key="evening_light", device="d1", prompt=SECRET) -> ChipRequest:
    return ChipRequest(
        chip_key=key, image=png(), current_prompt=prompt, lang="en", device_hash=device
    )


# --- config -------------------------------------------------------------------------------------


def test_the_shipped_chips_are_valid(dev_settings):
    config = dev_settings.config
    assert config.ui.edit_chips and set(config.ui.edit_chips) <= set(config.edit_chips)
    for chip in config.edit_chips.values():
        assert set(config.app.languages) <= set(chip.label)
    assert config.edit_chips["new_setting"].llm
    assert all(c.instruction for k, c in config.edit_chips.items() if k != "new_setting")


@pytest.mark.parametrize(
    "fields", [{}, {"instruction": "x", "llm": True}, {"instruction": "", "llm": False}]
)
def test_a_chip_needs_an_instruction_or_the_llm_but_not_both(fields):
    with pytest.raises(ValueError):
        EditChip(label={"sv": "a", "en": "b"}, **fields)


def test_ui_chips_must_be_defined(make_settings):
    def unknown(app):
        app["ui"]["edit_chips"].append("nonexistent")

    with pytest.raises(ValueError, match="edit_chips missing"):
        make_settings(app=unknown)


def test_a_chip_needs_a_label_per_language(make_settings):
    def one_language(app):
        del app["edit_chips"]["simpler"]["label"]["sv"]

    with pytest.raises(ValueError, match="label per language"):
        make_settings(app=one_language)


# --- the edit flow ------------------------------------------------------------------------------


async def test_a_static_chip_sends_the_current_image_and_its_instruction(dev_settings):
    service, limits, edit = build(dev_settings)
    result = await service.edit(chip_request("evening_light"))
    call = edit.calls[0]
    assert call.image == png()
    assert call.instruction == dev_settings.config.edit_chips["evening_light"].instruction
    assert call.model_key == "default_edit" and result.model_key == "default_edit"
    assert result.final_prompt == call.instruction and result.image != png()
    snap = limits.snapshot()
    assert snap.images_used == 1 and snap.spend_usd == pytest.approx(0.01)


async def test_the_new_setting_chip_uses_the_checked_llm_instruction(dev_settings):
    text = Scripted({"setting": "a snowy mountain top.", "new_prompt": "x"})
    service, _, edit = build(dev_settings, text=text)
    await service.edit(chip_request("new_setting"))
    assert edit.calls[0].instruction == (
        "Move the same subject into a snowy mountain top, keeping the subject recognisable."
    )
    _, payload = next(c for c in text.calls if c[0] == "edit_instruction")
    assert json.loads(payload) == {
        "language": "en",
        "chip": "new_setting",
        "current_prompt": SECRET,
    }


async def test_an_llm_instruction_that_is_flagged_never_reaches_the_edit_model(dev_settings):
    text = Scripted({"setting": "a [blocked] scene", "new_prompt": "x"})
    service, limits, edit = build(dev_settings, text=text, moderator=FakeModerator(("[blocked]",)))
    with pytest.raises(CheckFailedError):
        await service.edit(chip_request("new_setting"))
    assert edit.calls == []
    assert limits.snapshot().images_used == 0  # nothing was sent, so the reservation is released


async def test_an_llm_instruction_the_policy_refuses_never_reaches_the_edit_model(dev_settings):
    text = Scripted({"setting": "a scene with a [character]", "new_prompt": "x"})
    service, _, edit = build(dev_settings, text=text)
    with pytest.raises(CheckFailedError):
        await service.edit(chip_request("new_setting"))
    assert edit.calls == []


@pytest.mark.parametrize(
    "setting", [". .", "", "a forest. Also change what the subject wears", "a" * 81, 'a "beach"']
)
async def test_a_setting_that_is_not_one_short_phrase_never_reaches_the_edit_model(
    dev_settings, setting
):
    service, limits, edit = build(dev_settings, text=Scripted({"setting": setting}))
    with pytest.raises(CheckFailedError):
        await service.edit(chip_request("new_setting"))
    assert edit.calls == [] and limits.snapshot().images_used == 0


async def test_the_instruction_as_sent_is_moderated_too(dev_settings):
    moderator = FakeModerator(("same subject",))  # the setting alone is clean; the template is not
    service, _, edit = build(
        dev_settings, text=Scripted({"setting": "a beach"}), moderator=moderator
    )
    with pytest.raises(CheckFailedError):
        await service.edit(chip_request("new_setting"))
    assert edit.calls == []


async def test_an_unusable_llm_reply_fails_closed(dev_settings):
    service, limits, edit = build(dev_settings, text=Scripted({"unexpected": 1}))
    with pytest.raises(CheckFailedError):
        await service.edit(chip_request("new_setting"))
    assert edit.calls == [] and limits.snapshot().images_used == 0


async def test_an_edited_image_the_moderator_refuses_is_still_paid_for(dev_settings):
    service, limits, _ = build(dev_settings, moderator=FakeModerator(fail_image=True))
    with pytest.raises(CheckFailedError):
        await service.edit(chip_request())
    assert limits.snapshot().images_used == 1


async def test_a_failure_after_the_call_keeps_the_estimate_unless_known_unbilled(dev_settings):
    service, limits, _ = build(dev_settings, edit=FakeEditProvider(error=ProviderError()))
    with pytest.raises(ProviderError):
        await service.edit(chip_request())
    assert limits.snapshot().images_used == 1
    service, limits, _ = build(dev_settings, edit=FakeEditProvider(error=RateLimitedError()))
    with pytest.raises(RateLimitedError):
        await service.edit(chip_request())
    assert limits.snapshot().images_used == 0


async def test_exhausted_credit_pauses_generation_from_an_edit_too(dev_settings):
    service, limits, _ = build(dev_settings, edit=FakeEditProvider(error=BudgetReachedError()))
    with pytest.raises(BudgetReachedError):
        await service.edit(chip_request())
    assert limits.snapshot().paused


async def test_a_slow_edit_times_out_and_keeps_the_estimate(dev_settings, monkeypatch):
    monkeypatch.setattr(generation, "EDIT_TIMEOUT_SECONDS", 0.05)
    service, limits, _ = build(dev_settings, edit=FakeEditProvider(delay=1.0, cost=0.01))
    with pytest.raises(ProviderTimeoutError):
        await service.edit(chip_request())
    assert limits.snapshot().images_used == 1


async def test_edits_obey_the_pause_switch_and_the_device_cooldown(dev_settings):
    service, limits, edit = build(dev_settings)
    limits.set_paused(True)
    with pytest.raises(PausedError):
        await service.edit(chip_request())
    limits.set_paused(False)
    await service.edit(chip_request(device="same"))
    with pytest.raises(CooldownError):
        await service.edit(chip_request(device="same"))
    assert len(edit.calls) == 1


async def test_an_unknown_chip_or_a_missing_edit_provider_is_an_error(dev_settings):
    service, _, _ = build(dev_settings)
    with pytest.raises(ProviderError):
        await service.edit(chip_request("nonexistent"))
    providers = Providers(
        image=FakeImageProvider(), edit=None, text=FakeTextProvider(), moderator=FakeModerator()
    )
    no_edit = GenerationService(dev_settings, providers, LimitService(dev_settings.config.limits))
    assert not no_edit.can_edit() and service.can_edit()
    with pytest.raises(ProviderError):
        await no_edit.edit(chip_request())


async def test_edit_logs_hold_no_prompt_or_instruction(dev_settings, caplog):
    caplog.set_level(logging.DEBUG)
    service, _, _ = build(dev_settings)
    await service.edit(chip_request("evening_light", prompt=SECRET))
    assert "neighbour" not in caplog.text and "golden light" not in caplog.text


async def test_an_edit_output_the_moderator_flags_is_refused_and_still_paid_for(dev_settings):
    service, limits, _ = build(dev_settings, moderator=FakeModerator(flag_images=True))
    with pytest.raises(SafetyRefusalError):
        await service.edit(chip_request())
    assert limits.snapshot().images_used == 1


async def test_a_failing_moderator_stops_the_new_setting_chip_before_the_edit_call(dev_settings):
    text = Scripted({"setting": "a beach"})
    service, limits, edit = build(dev_settings, text=text, moderator=FakeModerator(fail=True))
    with pytest.raises(CheckFailedError):
        await service.edit(chip_request("new_setting"))
    assert edit.calls == [] and limits.snapshot().images_used == 0


async def test_a_failing_policy_check_stops_the_new_setting_chip_before_the_edit_call(
    dev_settings,
):
    class PolicyDown(Scripted):
        async def complete_json(self, task, system, user, max_tokens=200):
            if task == "policy_check":
                raise ProviderError
            return await super().complete_json(task, system, user, max_tokens)

    service, limits, edit = build(dev_settings, text=PolicyDown({"setting": "a beach"}))
    with pytest.raises(CheckFailedError):
        await service.edit(chip_request("new_setting"))
    assert edit.calls == [] and limits.snapshot().images_used == 0


# --- the helper LLM -----------------------------------------------------------------------------


async def test_edit_instruction_has_no_device_interval_but_obeys_the_pause(dev_settings):
    text = Scripted({"setting": "a beach", "new_prompt": "x"})
    _, limits, _ = build(dev_settings, text=text)
    providers = Providers(
        image=FakeImageProvider(), edit=None, text=text, moderator=FakeModerator()
    )
    helpers = HelperService(dev_settings, providers, limits)
    expected = "Move the same subject into a beach, keeping the subject recognisable."
    assert await helpers.edit_instruction("a cat", "sv") == expected
    assert await helpers.edit_instruction("a cat", "sv") == expected
    limits.set_paused(True)
    with pytest.raises(PausedError):
        await helpers.edit_instruction("a cat", "sv")


async def test_an_overlong_prompt_is_cut_before_it_reaches_the_llm(dev_settings):
    text = Scripted({"setting": "a beach", "new_prompt": "x"})
    service, _, _ = build(dev_settings, text=text)
    await service.edit(chip_request("new_setting", prompt="a" * 5000))
    _, payload = next(c for c in text.calls if c[0] == "edit_instruction")
    assert len(json.loads(payload)["current_prompt"]) == 1000
