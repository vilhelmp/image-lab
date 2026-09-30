"""Per-visitor state held in gr.State: language, style, current image, history, idle tracking."""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class GeneratedImage:
    image: bytes = field(repr=False)
    prompt: str = field(repr=False)
    model_key: str
    seconds: float


@dataclass
class VisitorSession:
    lang: str
    last_interaction: float = field(default_factory=time.monotonic)
    dirty: bool = False
    style: str | None = None
    current: GeneratedImage | None = None
    history: list[GeneratedImage] = field(default_factory=list)
    undo_text: str | None = field(
        default=None, repr=False
    )  # the text before Help me or Surprise me

    def touch(self, now: float | None = None) -> None:
        self.last_interaction = time.monotonic() if now is None else now
        self.dirty = True

    def select_style(self, key: str) -> None:
        self.style = None if self.style == key else key

    def set_current(self, image: GeneratedImage, history_size: int) -> None:
        self.current = image
        self.history = [*self.history, image][-history_size:]

    def is_idle(self, seconds: float, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        return self.dirty and now - self.last_interaction >= seconds

    def reset(self, lang: str, now: float | None = None) -> None:
        self.lang = lang
        self.style = None
        self.current = None
        self.history = []
        self.undo_text = None
        self.dirty = False
        self.last_interaction = time.monotonic() if now is None else now
