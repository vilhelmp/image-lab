"""Safety pipeline pieces (spec section 8). Phase 1 holds input validation only."""

from __future__ import annotations

import unicodedata

from src.errors import EmptyInputError, TooLongInputError


def validate_input(text: str | None, max_chars: int) -> str:
    """Return cleaned visitor text or raise a typed error."""
    raw = text or ""
    if len(raw) > max_chars * 4:
        raise TooLongInputError
    cleaned = "".join(
        " " if ch in "\n\r\t" else ch
        for ch in unicodedata.normalize("NFKC", raw)
        if ch in "\n\r\t" or not unicodedata.category(ch).startswith("C")
    )
    cleaned = " ".join(cleaned.split())
    if not cleaned:
        raise EmptyInputError
    if len(cleaned) > max_chars:
        raise TooLongInputError
    return cleaned
