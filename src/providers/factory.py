"""Builds the provider set for the current settings."""

from __future__ import annotations

from dataclasses import dataclass

from src.config import Settings
from src.providers.base import EditProvider, ImageProvider, Moderator, TextProvider
from src.providers.fake import (
    FakeEditProvider,
    FakeImageProvider,
    FakeModerator,
    FakeTextProvider,
)


@dataclass(frozen=True)
class Providers:
    image: ImageProvider
    edit: EditProvider | None
    text: TextProvider
    moderator: Moderator


def build_providers(settings: Settings) -> Providers:
    if settings.development_mode:
        delay = settings.config.app.fake_delay_seconds
        return Providers(
            image=FakeImageProvider(delay=delay),
            edit=FakeEditProvider(delay=delay),
            text=FakeTextProvider(),
            moderator=FakeModerator(),
        )
    raise NotImplementedError("Real providers arrive in phase 3. Set DEVELOPMENT_MODE=true.")
