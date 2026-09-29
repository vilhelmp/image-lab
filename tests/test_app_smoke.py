import time
from collections.abc import Iterator

import gradio as gr
import pytest
from gradio_client import Client

from app import build_demo
from src.config import Settings

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


def test_app_builds_with_fakes(dev_settings: Settings, fake_providers):
    demo = build_demo(dev_settings, fake_providers)
    assert isinstance(demo, gr.Blocks)
    labels = {c.get("props", {}).get("value") for c in demo.get_config_file()["components"]}
    assert "Skapa bild" in labels


def test_create_completes_with_fakes(client: Client):
    device, status, image = client.predict("A cat", "landscape", None, api_name="/on_create")
    assert device
    assert status["visible"] is False
    assert image["visible"] is True
    assert image["value"].endswith(".png")


def test_empty_idea_shows_friendly_message(client: Client):
    _, status, _ = client.predict("   ", "square", None, api_name="/on_create")
    assert status["value"] == "Skriv först vad du vill skapa."


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
