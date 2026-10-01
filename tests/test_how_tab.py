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


def test_the_edit_chips_start_disabled_and_the_old_accordion_is_gone(dev_settings, fake_providers):
    config = build_demo(dev_settings, fake_providers).get_config_file()
    components = config["components"]
    chip_labels = {chip.label["sv"] for chip in dev_settings.config.edit_chips.values()}
    chips = [
        c for c in components if c["type"] == "button" and c["props"].get("value") in chip_labels
    ]
    assert chips and all(c["props"]["interactive"] is False for c in chips)
    assert not any(c["type"] == "accordion" for c in components)
