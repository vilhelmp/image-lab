"""Helpers that keep every visible string in the locale files and switchable at runtime."""

from __future__ import annotations

import io
from collections.abc import Callable, Iterable
from typing import Any, Literal

import gradio as gr
from PIL import Image

from src.i18n import I18n

Block = gr.blocks.Block
Updates = dict[Block, dict[str, Any]]
Props = Callable[[str], dict[str, Any]]
ApiVisibility = Literal["private", "undocumented"]


class Localizer:
    """Creates components from locale-driven props and re-renders them for another language."""

    def __init__(self, i18n: I18n) -> None:
        self.i18n = i18n
        self.default_language = i18n.default_language
        self._bindings: list[tuple[Block, Props]] = []

    def t(self, lang: str, key: str, **values: object) -> str:
        return self.i18n.t(lang, key, **values)

    def make(self, cls: type[Block], props: Props, **static: Any) -> Any:
        """Build `cls` with props for the default language and remember how to re-localize it."""
        component = cls(**props(self.default_language), **static)
        self._bindings.append((component, props))
        return component

    @property
    def components(self) -> list[Block]:
        return [component for component, _ in self._bindings]

    def props(self, lang: str) -> Updates:
        return {component: props(lang) for component, props in self._bindings}


def build_heading(loc: Localizer, title_key: str, hint_key: str) -> Any:
    """A bold section title with a one-line explanation under it."""
    return loc.make(
        gr.Markdown,
        lambda lang: {"value": f"**{loc.t(lang, title_key)}**  \n{loc.t(lang, hint_key)}"},
        elem_classes=["section-heading"],
    )


def merge(*parts: Updates) -> Updates:
    merged: Updates = {}
    for part in parts:
        for component, props in part.items():
            merged[component] = {**merged.get(component, {}), **props}
    return merged


def pack(order: Iterable[Block], updates: Updates) -> list[Any]:
    """Turn updates into an output list aligned with `order`; untouched components get no-ops."""
    return [gr.update(**updates[c]) if c in updates else gr.skip() for c in order]


def to_pil(image: bytes) -> Image.Image:
    return Image.open(io.BytesIO(image))
