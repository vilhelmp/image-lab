"""Prepare a visitor's photo for the edit model: validate, fix rotation, shrink, drop metadata.

The result is a plain PNG with no EXIF data (no location, camera or timestamps). Nothing here
touches the network and nothing is logged about the picture.
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from src.errors import BadImageError

MAX_UPLOAD_BYTES = 15 * 1024 * 1024
MAX_PIXELS = 25_000_000  # refuse absurd sizes before decoding them (a phone photo is ~12 MP)
MAX_SIDE = 1024  # enough for a stylised result, and cheaper and faster to send


def read_upload(path: str) -> bytes:
    """The bytes of an uploaded file (a path inside Gradio's cache), capped in size."""
    try:
        file = Path(path)
        if file.stat().st_size > MAX_UPLOAD_BYTES:
            raise BadImageError
        return file.read_bytes()
    except OSError:
        raise BadImageError from None


def prepare_photo(raw: bytes) -> bytes:
    """A PNG of at most MAX_SIDE pixels on the long side, or BadImageError."""
    if not raw or len(raw) > MAX_UPLOAD_BYTES:
        raise BadImageError
    try:
        with Image.open(io.BytesIO(raw)) as opened:
            width, height = opened.size
            if width < 1 or height < 1 or width * height > MAX_PIXELS:
                raise BadImageError
            image = ImageOps.exif_transpose(opened)  # iPads store portrait photos rotated
            image = image.convert("RGB")
    except BadImageError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise BadImageError from None
    image.thumbnail((MAX_SIDE, MAX_SIDE))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
