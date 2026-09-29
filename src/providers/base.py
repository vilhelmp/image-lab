"""Provider contracts (spec section 5.1). Adapters return bytes and raise typed errors only."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Literal

from pydantic import BaseModel, Field

Aspect = Literal["square", "landscape", "portrait"]


class ImageRequest(BaseModel):
    prompt: str = Field(repr=False)
    model_key: str
    aspect: Aspect


class EditRequest(BaseModel):
    image: bytes = Field(repr=False)
    instruction: str = Field(repr=False)
    model_key: str


class ImageResult(BaseModel):
    image: bytes = Field(repr=False)
    model_key: str
    seconds: float
    est_cost: float


class ModerationResult(BaseModel):
    flagged: bool
    code: str | None = None


class ImageProvider(ABC):
    @abstractmethod
    async def generate(self, req: ImageRequest) -> ImageResult: ...


class EditProvider(ABC):
    @abstractmethod
    async def edit(self, req: EditRequest) -> ImageResult: ...


class TextProvider(ABC):
    @abstractmethod
    async def complete_json(
        self, task: str, system: str, user: str, max_tokens: int = 200
    ) -> dict[str, Any]:
        """Return one parsed JSON object. `task` names the helper (improve, surprise, ...)."""


class Moderator(ABC):
    @abstractmethod
    async def moderate_text(self, text: str) -> ModerationResult: ...

    @abstractmethod
    async def moderate_image(self, image: bytes) -> ModerationResult: ...
