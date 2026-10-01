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
    previous: GeneratedImage | None = None  # the image before the last edit, for before/after
    history: list[GeneratedImage] = field(default_factory=list)
    undo_text: str | None = field(
        default=None, repr=False
    )  # the text before Help me or Surprise me
    epoch: int = 0  # bumped by reset(), so work started for the previous visitor is dropped

    def touch(self, now: float | None = None) -> None:
        self.last_interaction = time.monotonic() if now is None else now
        self.dirty = True

    def select_style(self, key: str) -> None:
        self.style = None if self.style == key else key

    def set_current(self, image: GeneratedImage, history_size: int) -> None:
        self.current = image
        self.previous = None
        self.history = [*self.history, image][-history_size:]

    def set_edited(self, image: GeneratedImage, history_size: int) -> None:
        before = self.current
        self.set_current(image, history_size)
        self.previous = before

    def swap(self) -> bool:
        """Show the other of the two latest images; False if there is only one."""
        if self.current is None or self.previous is None:
            return False
        self.current, self.previous = self.previous, self.current
        return True

    def is_idle(self, seconds: float, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        return self.dirty and now - self.last_interaction >= seconds

    def reset(self, lang: str, now: float | None = None) -> None:
        self.lang = lang
        self.style = None
        self.current = None
        self.previous = None
        self.history = []
        self.undo_text = None
        self.epoch += 1
        self.dirty = False
        self.last_interaction = time.monotonic() if now is None else now
