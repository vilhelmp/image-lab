import copy
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from src.config import CONFIG_DIR, AppConfig, ModelsConfig, Settings, load_settings
from src.providers.factory import Providers
from src.providers.fake import FakeEditProvider, FakeImageProvider, FakeModerator, FakeTextProvider

Mutator = Callable[[dict[str, Any]], None]


def _yaml(name: str) -> dict[str, Any]:
    return yaml.safe_load((Path(CONFIG_DIR) / name).read_text(encoding="utf-8"))


@pytest.fixture
def make_settings() -> Callable[..., Settings]:
    """Build Settings from the real YAML, optionally mutated by the given callbacks."""

    def build(app: Mutator | None = None, models: Mutator | None = None) -> Settings:
        app_data, models_data = (
            copy.deepcopy(_yaml("app.yaml")),
            copy.deepcopy(_yaml("models.yaml")),
        )
        if app:
            app(app_data)
        if models:
            models(models_data)
        return Settings(
            config=AppConfig.model_validate(app_data),
            models=ModelsConfig.model_validate(models_data),
        )

    return build


@pytest.fixture
def dev_settings() -> Settings:
    return load_settings(env={"DEVELOPMENT_MODE": "true"})


@pytest.fixture
def fake_providers() -> Providers:
    return Providers(
        image=FakeImageProvider(),
        edit=FakeEditProvider(),
        text=FakeTextProvider(),
        moderator=FakeModerator(),
    )
