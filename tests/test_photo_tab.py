from collections.abc import Iterator
from pathlib import Path

import pytest
from gradio_client import Client, handle_file
from PIL import Image

from app import build_demo
from src.services.flags import RuntimeFlags


@pytest.fixture
def photo_file(tmp_path: Path) -> str:
    path = tmp_path / "me.jpg"
    Image.new("RGB", (800, 600), (200, 120, 60)).save(path)
    return str(path)


@pytest.fixture
def studio(dev_settings, fake_providers) -> Iterator[tuple[Client, RuntimeFlags]]:
    dev_settings.config.access.expose_api = True
    flags = RuntimeFlags(photo_studio=True)
    demo = build_demo(dev_settings, fake_providers, flags=flags)
    demo.launch(prevent_thread_lock=True, quiet=True)
    try:
        yield Client(demo.local_url, verbose=False), flags
    finally:
        demo.close()


def test_the_photo_tab_exists_but_starts_hidden(dev_settings, fake_providers):
    config = build_demo(dev_settings, fake_providers).get_config_file()
    tab = next(c for c in config["components"] if c["props"].get("id") == "photo")
    assert tab["props"]["visible"] is False


def test_a_photo_is_restyled(studio, photo_file):
    client, _ = studio
    _, status, result = client.predict(
        handle_file(photo_file), True, None, api_name="/on_photo_clay"
    )
    assert status["value"] == "Ändrad: Lera"
    assert result["value"].endswith(".png")


def test_without_the_tick_the_visitor_is_asked_for_it(studio, photo_file):
    client, _ = studio
    _, status, _ = client.predict(handle_file(photo_file), False, None, api_name="/on_photo_clay")
    assert "externa tjänster" in status["value"]


def test_without_a_photo_the_visitor_is_asked_for_one(studio):
    client, _ = studio
    _, status, _ = client.predict(None, True, None, api_name="/on_photo_clay")
    assert status["value"] == "Ta ett foto först."


def test_when_the_studio_is_closed_the_server_refuses_even_if_the_tab_is_open(studio, photo_file):
    client, flags = studio
    flags.set_photo_studio(False)
    _, status, _ = client.predict(handle_file(photo_file), True, None, api_name="/on_photo_clay")
    assert status["value"] == "Fotostudion är inte öppen just nu."
