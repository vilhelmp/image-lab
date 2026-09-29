"""Prompt composition (spec section 6.2). Pure functions, no I/O."""

from __future__ import annotations

from collections.abc import Mapping


def style_fragment(fragments: Mapping[str, str], style: str | None) -> str | None:
    return fragments.get(style) if style else None


def compose_prompt(
    user_text: str, style_fragment: str | None = None, translation: str | None = None
) -> str:
    """Join the visitor's text, style and optional translation. The visible text is untouched."""
    parts = (user_text, style_fragment or "", translation or "")
    return ", ".join(cleaned for part in parts if (cleaned := part.strip().rstrip(".,;")))
