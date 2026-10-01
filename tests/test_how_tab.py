import pytest

from app import build_demo
from src.i18n import I18n
from src.ui.components import Localizer
from src.ui.how_tab import KINDS, STEPS, pipeline_html


@pytest.mark.parametrize("lang", ["sv", "en"])
def test_the_pipeline_has_a_box_and_a_caption_for_every_step(lang):
    html = pipeline_html(Localizer(I18n.load(["sv", "en"], "sv")), lang)
    assert html.count('class="pipe-box ') == len(STEPS)
    assert html.count('class="pipe-caption ') == len(STEPS) + 1  # plus the "tap Next" start text
    assert all(kind in KINDS for _, kind in STEPS)


def test_the_edit_chips_start_hidden_and_the_old_accordion_is_gone(dev_settings, fake_providers):
    config = build_demo(dev_settings, fake_providers).get_config_file()
    components = config["components"]
    panel = next(c for c in components if c["props"].get("elem_id") == "chip-panel")
    assert panel["props"]["visible"] is False
    assert not any(c["type"] == "accordion" for c in components)
