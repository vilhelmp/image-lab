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


def test_the_photo_tab_is_always_there_and_only_tabs_sit_inside_the_tabs(
    dev_settings, fake_providers
):
    config = build_demo(dev_settings, fake_providers).get_config_file()
    components = {c["id"]: c for c in config["components"]}
    tab = next(c for c in components.values() if c["props"].get("id") == "photo")
    assert tab["props"].get("visible", True) is True  # a tab that comes and goes breaks Gradio

    def find_tabs(node):
        if components.get(node["id"], {}).get("type") == "tabs":
            return node
        return next((f for child in node.get("children", []) if (f := find_tabs(child))), None)

    tabs = find_tabs(config["layout"])
    # Anything between two tabs makes Gradio list the next tab twice (trailing items are fine).
    kinds = [components[c["id"]]["type"] for c in tabs["children"]]
    assert "tabitem" in kinds
    assert set(kinds[: len(kinds) - kinds[::-1].index("tabitem")]) == {"tabitem"}


def test_timers_never_update_visible_components(dev_settings, fake_providers):
    # A timer that updates the webcam, tabs or text box makes Gradio rebuild them in the browser
    # (the webcam restarts, tabs get duplicated). Timers may only write markers and admin text.
    config = build_demo(dev_settings, fake_providers).get_config_file()
    types = {c["id"]: c["type"] for c in config["components"]}
    for c in config["components"]:
        if c["props"].get("elem_id") == "photo-flag":
            types[c["id"]] = "marker"
    ticks = [d for d in config["dependencies"] if any(t[1] == "tick" for t in d["targets"])]
    assert ticks
    for dependency in ticks:
        allowed = {"state", "marker", "markdown", "checkbox"}
        assert {types[o] for o in dependency["outputs"]} <= allowed


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
