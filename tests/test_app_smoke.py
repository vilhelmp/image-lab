import time
from collections.abc import Iterator
from dataclasses import replace

import gradio as gr
import pytest
from gradio_client import Client

from app import build_demo
from src.config import Settings
from src.providers.fake import FakeModerator

NOOP = {"__type__": "update"}


@pytest.fixture
def client(dev_settings: Settings, fake_providers) -> Iterator[Client]:
    dev_settings.config.ui.idle_reset_seconds = 1
    dev_settings.config.access.expose_api = True
    demo = build_demo(dev_settings, fake_providers)
    demo.launch(prevent_thread_lock=True, quiet=True)
    try:
        yield Client(demo.local_url, verbose=False)
    finally:
        demo.close()


class FlagsImagesAfterTheFirst(FakeModerator):
    """Clean for the first image (Create), then flags every image (the edit output)."""

    def __init__(self) -> None:
        super().__init__()
        self.images = 0

    async def moderate_image(self, image: bytes):
        self.images += 1
        self.flag_images = self.images > 1
        return await super().moderate_image(image)


@pytest.fixture
def refusing_client(dev_settings: Settings, fake_providers) -> Iterator[Client]:
    dev_settings.config.access.expose_api = True
    providers = replace(fake_providers, moderator=FlagsImagesAfterTheFirst())
    demo = build_demo(dev_settings, providers)
    demo.launch(prevent_thread_lock=True, quiet=True)
    try:
        yield Client(demo.local_url, verbose=False)
    finally:
        demo.close()


def test_app_builds_with_fakes(dev_settings: Settings, fake_providers):
    demo = build_demo(dev_settings, fake_providers)
    assert isinstance(demo, gr.Blocks)
    labels = {
        value
        for c in demo.get_config_file()["components"]
        if isinstance(value := c.get("props", {}).get("value"), str)
    }
    assert "Skapa bild" in labels
    assert "Se exempel" in labels


def test_create_completes_with_fakes(client: Client):
    device, status, image, prompt = client.predict("A cat", None, api_name="/on_create")
    assert device
    assert status["visible"] is False
    assert image["visible"] is True
    assert image["value"].endswith(".png")
    assert prompt["value"] == "A cat"  # the prompt stays in the box


def test_a_library_prompt_shows_its_cached_example_with_a_note(client: Client):
    _, status, image, _ = client.predict(
        "A fox in a snowy forest, caught mid-step, soft winter light", None, api_name="/on_create"
    )
    assert image["value"].endswith(".webp") or image["value"].endswith(".png")
    assert status["visible"] is True and "exempelbild" in status["value"]


def test_help_me_fills_the_box_and_undo_restores_it(client: Client):
    device, improved, status = client.predict("a cat", None, api_name="/on_help")
    assert improved == "A friendly scene with soft evening light"
    assert status["visible"] is False
    assert client.predict(api_name="/on_undo") == "a cat"


def test_surprise_me_fills_the_box_and_undo_clears_an_empty_box(client: Client):
    device, surprise, status = client.predict("", None, api_name="/on_surprise")
    assert surprise == "A whale reading a book on a Swedish island"
    assert client.predict(api_name="/on_undo") == ""


def test_help_me_with_an_empty_box_shows_the_friendly_message(client: Client):
    _, text, status = client.predict("  ", None, api_name="/on_help")
    assert status["value"] == "Skriv först vad du vill skapa."


def test_typing_after_help_me_drops_the_undo(client: Client):
    client.predict("a cat", None, api_name="/on_help")
    client.predict(api_name="/on_typing")
    assert client.predict(api_name="/on_undo") == ""  # nothing left to restore


def test_an_unknown_language_is_rejected_by_the_framework(client: Client):
    with pytest.raises(Exception, match="not in the list of choices"):
        client.predict("xx", api_name="/on_language")


def test_a_chip_edits_the_current_image(client: Client):
    _, _, created, _ = client.predict("A cat", None, api_name="/on_create")
    device, status, edited = client.predict(None, api_name="/on_chip_evening_light")
    assert status["visible"] is True and status["value"] == "Ändrad: Kvällsljus"
    assert edited["value"] and edited["value"] != created["value"]


def test_a_refused_edit_keeps_the_image_and_shows_a_friendly_message(refusing_client: Client):
    refusing_client.predict("A cat", None, api_name="/on_create")
    _, status, edited = refusing_client.predict(None, api_name="/on_chip_evening_light")
    assert status["value"] == "Den ändringen blev inte bra. Prova en annan!"
    assert not edited.get("value")  # the image area is untouched


def test_a_chip_without_an_image_does_nothing(client: Client):
    result = client.predict(None, api_name="/on_chip_as_painting")
    assert all(not (isinstance(part, dict) and part.get("value")) for part in result)


def test_empty_idea_shows_friendly_message(client: Client):
    _, status, _, prompt = client.predict("   ", None, api_name="/on_create")
    assert status["value"] == "Skriv först vad du vill skapa."
    assert prompt["value"] == "   "


def test_new_visitor_resets_language_and_text(client: Client):
    client.predict(api_name="/touch")
    client.predict("en", api_name="/on_language")
    reset = client.predict(api_name="/reset")
    assert reset[0]["value"] == "sv"
    assert reset[2]["value"] == ""


def test_idle_reset_only_fires_after_interaction_and_idle_time(client: Client):
    assert client.predict(api_name="/on_idle")[2] == NOOP
    client.predict(api_name="/touch")
    time.sleep(1.2)
    assert client.predict(api_name="/on_idle")[2]["value"] == ""
    assert client.predict(api_name="/on_idle")[2] == NOOP


def test_swap_toggles_between_the_image_before_and_after_a_chip(client: Client):
    client.predict("A cat", None, api_name="/on_create")
    _, _, edited = client.predict(None, api_name="/on_chip_evening_light")
    original, status = client.predict(api_name="/on_swap")
    assert original["value"] != edited["value"]
    assert status["visible"] is False  # "Changed: ..." no longer describes what is shown
    assert client.predict(api_name="/on_swap")[0]["value"] != original["value"]


def test_swap_without_an_edit_does_nothing(client: Client):
    client.predict("A cat", None, api_name="/on_create")
    assert client.predict(api_name="/on_swap") == (NOOP, NOOP)
