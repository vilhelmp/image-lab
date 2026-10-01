"""Builds the provider set for the current settings."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from src.config import Settings
from src.providers.base import EditProvider, ImageProvider, Moderator, TextProvider
from src.providers.fake import (
    FakeEditProvider,
    FakeImageProvider,
    FakeModerator,
    FakeTextProvider,
)
from src.providers.hf_inference import HFEditProvider, HFImageProvider
from src.providers.openai_moderation import OpenAIModerator
from src.providers.openai_text import OpenAITextProvider


@dataclass(frozen=True)
class Providers:
    image: ImageProvider
    edit: EditProvider | None
    text: TextProvider
    moderator: Moderator


def build_moderator(settings: Settings, env: Mapping[str, str] | None = None) -> Moderator:
    env = os.environ if env is None else env
    return OpenAIModerator(env["OPENAI_API_KEY"], model=settings.models.moderation_model)


def build_text(settings: Settings, env: Mapping[str, str] | None = None) -> TextProvider:
    env = os.environ if env is None else env
    model = settings.models.text_models[settings.models.defaults.text_model]
    return OpenAITextProvider(
        env["OPENAI_API_KEY"], model=model.api_model, reasoning_effort=model.reasoning_effort
    )


def build_image(settings: Settings, env: Mapping[str, str] | None = None) -> ImageProvider:
    env = os.environ if env is None else env
    if settings.config.image_backend == "hf":
        return HFImageProvider(env["HF_TOKEN"], settings)
    raise NotImplementedError("The fal backend is not built yet. Use image_backend: hf.")


def build_edit(settings: Settings, env: Mapping[str, str] | None = None) -> EditProvider | None:
    """The edit provider, or None when no edit model is available (chips then use the fallback)."""
    env = os.environ if env is None else env
    if settings.active_edit_model() is None:
        return None
    if settings.config.image_backend == "hf":
        return HFEditProvider(env["HF_TOKEN"], settings)
    raise NotImplementedError("The fal backend is not built yet. Use image_backend: hf.")


def build_providers(settings: Settings, env: Mapping[str, str] | None = None) -> Providers:
    if settings.development_mode:
        delay = settings.config.app.fake_delay_seconds
        return Providers(
            image=FakeImageProvider(delay=delay),
            edit=FakeEditProvider(delay=delay),
            text=FakeTextProvider(),
            moderator=FakeModerator(),
        )
    return Providers(
        image=build_image(settings, env),
        edit=build_edit(settings, env),
        text=build_text(settings, env),
        moderator=build_moderator(settings, env),
    )
