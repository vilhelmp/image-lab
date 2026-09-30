"""Fakes for dev, tests and CI. No network, no keys."""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import textwrap
import time
from typing import Any

from PIL import Image, ImageDraw

from src.providers.base import (
    Aspect,
    EditProvider,
    EditRequest,
    ImageProvider,
    ImageRequest,
    ImageResult,
    ModerationResult,
    Moderator,
    TextProvider,
)

SIZES: dict[Aspect, tuple[int, int]] = {
    "square": (512, 512),
    "landscape": (640, 384),
    "portrait": (384, 640),
}


def _color_for(text: str) -> tuple[int, int, int]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return (60 + digest[0] % 140, 60 + digest[1] % 140, 60 + digest[2] % 140)


def _draw_caption(image: Image.Image, caption: str) -> None:
    draw = ImageDraw.Draw(image)
    lines = textwrap.wrap(caption, width=max(12, image.width // 8)) or [""]
    draw.multiline_text((16, 16), "\n".join(lines[:12]), fill=(255, 255, 255))


def _to_png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class FakeImageProvider(ImageProvider):
    def __init__(
        self, delay: float = 0.0, cost: float = 0.0, error: Exception | None = None
    ) -> None:
        self.delay = delay
        self.cost = cost
        self.error = error
        self.calls: list[ImageRequest] = []

    async def generate(self, req: ImageRequest) -> ImageResult:
        self.calls.append(req)
        started = time.perf_counter()
        await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        image = Image.new("RGB", SIZES[req.aspect], _color_for(req.prompt))
        _draw_caption(image, req.prompt)
        return ImageResult(
            image=_to_png(image),
            model_key=req.model_key,
            seconds=time.perf_counter() - started,
            est_cost=self.cost,
        )


class FakeEditProvider(EditProvider):
    def __init__(self, delay: float = 0.0, cost: float = 0.0) -> None:
        self.delay = delay
        self.cost = cost
        self.calls: list[EditRequest] = []

    async def edit(self, req: EditRequest) -> ImageResult:
        self.calls.append(req)
        started = time.perf_counter()
        await asyncio.sleep(self.delay)
        image = Image.open(io.BytesIO(req.image)).convert("RGB")
        tint = Image.new("RGB", image.size, _color_for(req.instruction))
        image = Image.blend(image, tint, 0.35)
        _draw_caption(image, req.instruction)
        return ImageResult(
            image=_to_png(image),
            model_key=req.model_key,
            seconds=time.perf_counter() - started,
            est_cost=self.cost,
        )


class FakeTextProvider(TextProvider):
    """Canned JSON per task. The policy check reacts to markers so dev mode can show each outcome:
    [real person], [character], [minors] and [malformed] (an unusable reply)."""

    def __init__(self, responses: dict[str, dict[str, Any]] | None = None) -> None:
        self.responses = responses or {
            "improve": {"prompt": "A friendly scene with soft evening light"},
            "surprise": {"prompt": "A whale reading a book on a Swedish island"},
            "edit_instruction": {"instruction": "Change the setting", "new_prompt": "A new scene"},
        }
        self.calls: list[str] = []

    async def complete_json(
        self, task: str, system: str, user: str, max_tokens: int = 200
    ) -> dict[str, Any]:
        self.calls.append(task)
        if task == "policy_check" and task not in self.responses:
            return self._policy(user)
        return dict(self.responses[task])

    @staticmethod
    def _policy(user: str) -> dict[str, Any]:
        text = json.loads(user).get("text", "").lower()
        if "[malformed]" in text:
            return {"unexpected": True}
        if "[real person]" in text:
            return {
                "allowed": False,
                "category": "real_person",
                "rewrite": "a fictional explorer with a warm smile",
            }
        if "[character]" in text:
            return {
                "allowed": False,
                "category": "character",
                "rewrite": "a friendly mouse inspired by classic cartoons",
            }
        if "[minors]" in text:
            return {"allowed": False, "category": "minors", "rewrite": "a harmless scene"}
        return {"allowed": True, "category": None, "rewrite": None}


class FakeModerator(Moderator):
    """Flags text containing a blocked word. `fail` breaks every check, `fail_image` only images."""

    def __init__(
        self,
        blocked_words: tuple[str, ...] = ("[blocked]",),
        flag_images: bool = False,
        fail: bool = False,
        fail_image: bool = False,
    ) -> None:
        self.blocked_words = tuple(w.lower() for w in blocked_words)
        self.flag_images = flag_images
        self.fail = fail
        self.fail_image = fail_image
        self.text_calls = 0
        self.image_calls = 0

    async def moderate_text(self, text: str) -> ModerationResult:
        self.text_calls += 1
        if self.fail:
            raise RuntimeError("fake moderation failure")
        flagged = any(word in text.lower() for word in self.blocked_words)
        return ModerationResult(flagged=flagged, code="other" if flagged else None)

    async def moderate_image(self, image: bytes) -> ModerationResult:
        self.image_calls += 1
        if self.fail or self.fail_image:
            raise RuntimeError("fake moderation failure")
        return ModerationResult(
            flagged=self.flag_images, code="other" if self.flag_images else None
        )
