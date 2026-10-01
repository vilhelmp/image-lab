"""Gradio theme and the small CSS file (spec section 14)."""

from __future__ import annotations

from pathlib import Path

import gradio as gr

CSS_PATH = Path(__file__).with_name("style.css")
# System fonts only: no request to a font server from a visitor's iPad.
SYSTEM_FONTS = ("ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif")


def build_theme() -> gr.themes.Base:
    return gr.themes.Soft(
        primary_hue="indigo",
        neutral_hue="slate",
        text_size="md",
        spacing_size="md",
        radius_size="lg",
        font=SYSTEM_FONTS,
    ).set(
        button_secondary_background_fill="white",
        button_secondary_background_fill_dark="*neutral_800",
        button_secondary_background_fill_hover="*neutral_100",
        button_secondary_background_fill_hover_dark="*neutral_700",
        button_secondary_border_color="*neutral_200",
        button_secondary_border_color_dark="*neutral_700",
        button_secondary_text_color="*neutral_800",
        button_secondary_text_color_dark="*neutral_100",
    )


def load_css() -> str:
    return CSS_PATH.read_text(encoding="utf-8")
