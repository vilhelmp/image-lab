"""Prepare a visitor's photo for the edit model: validate, fix rotation, shrink, drop metadata.

The result is a plain PNG with no EXIF data (no location, camera or timestamps). Nothing here
touches the network and nothing is logged about the picture.
"""

from __future__ import annotations

import io
import logging
import threading
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from src.errors import BadImageError

logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 15 * 1024 * 1024
# A phone photo is 12 to 50 MP. Only JPEG can be decoded at a reduced size, so only JPEG gets the
# high cap; PNG and WebP decode in full and keep the low one.
MAX_PIXELS = 150_000_000
MAX_OTHER_PIXELS = 25_000_000
MAX_DECODED_PIXELS = 25_000_000  # what is really decoded, after the JPEG reduction
MAX_SIDE = 1024  # enough for a stylised result, and cheaper and faster to send
FORMATS = ("JPEG", "PNG", "WEBP")
_DECODING = threading.BoundedSemaphore(2)  # decoding runs before any spend or per-device limit


def _refuse(reason: str) -> BadImageError:
    logger.warning("photo refused reason=%s", reason)  # never the picture or its name
    return BadImageError()


def read_upload(path: str) -> bytes:
    """The bytes of an uploaded file (a path inside Gradio's cache), capped in size."""
    try:
        file = Path(path)
        if file.stat().st_size > MAX_UPLOAD_BYTES:
            raise _refuse("file_too_large")
        return file.read_bytes()
    except OSError:
        raise _refuse("file_unreadable") from None


def prepare_photo(raw: bytes) -> bytes:
    """A PNG of at most MAX_SIDE pixels on the long side, or BadImageError."""
    if not raw or len(raw) > MAX_UPLOAD_BYTES:
        raise _refuse("empty_or_too_large")
    try:
        with _DECODING, Image.open(io.BytesIO(raw), formats=FORMATS) as opened:
            width, height = opened.size
            cap = MAX_PIXELS if opened.format == "JPEG" else MAX_OTHER_PIXELS
            if width < 1 or height < 1 or width * height > cap:
                raise _refuse("too_many_pixels")
            opened.draft("RGB", (MAX_SIDE * 2, MAX_SIDE * 2))  # JPEG: decode at a reduced size
            if opened.size[0] * opened.size[1] > MAX_DECODED_PIXELS:
                raise _refuse("too_many_pixels_decoded")
            image = ImageOps.exif_transpose(opened)  # iPads store portrait photos rotated
            image = image.convert("RGB")
    except BadImageError:
        raise
    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise _refuse(f"decode_{type(exc).__name__}") from None
    image.thumbnail((MAX_SIDE, MAX_SIDE))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
