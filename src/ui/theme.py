"""Gradio theme and the small CSS file (spec section 14)."""

from __future__ import annotations

from pathlib import Path

import gradio as gr

CSS_PATH = Path(__file__).with_name("style.css")


def build_theme() -> gr.themes.Base:
    return gr.themes.Soft(primary_hue="indigo", text_size="lg", radius_size="lg")


def load_css() -> str:
    return CSS_PATH.read_text(encoding="utf-8")
