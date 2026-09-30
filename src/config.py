"""Pydantic settings loaded from config/*.yaml and validated at startup (spec section 16)."""

from __future__ import annotations

import os
from collections.abc import Mapping, MutableMapping
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.services.access import ADMIN_ENV, WORKSHOP_ENV, password_problems

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
# Kept outside the repository so a secret can never be committed by accident.
DEFAULT_ENV_FILE = CONFIG_DIR.parent.parent / ".env"

LocalizedText = dict[str, str]
PLACEHOLDER_MARK = "<verify"
REAL_SECRET_NAMES = ("FAL_KEY", "HF_TOKEN", "OPENAI_API_KEY")
# Only these are read from a .env file, so a shared file cannot leak other projects' secrets in.
ENV_FILE_KEYS = frozenset({*REAL_SECRET_NAMES, WORKSHOP_ENV, ADMIN_ENV, "DEVELOPMENT_MODE"})


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AppSection(_Strict):
    name: str
    default_language: str
    languages: list[str] = Field(min_length=1)
    default_theme: Literal["system", "light", "dark"] = "system"
    development_mode: bool = False
    fake_delay_seconds: float = Field(default=1.5, ge=0)

    @model_validator(mode="after")
    def _default_language_is_listed(self) -> AppSection:
        if self.default_language not in self.languages:
            raise ValueError("app.default_language must be one of app.languages")
        return self


class FeaturesSection(_Strict):
    compare_tab: bool = True
    help_me: bool = True
    surprise_me: bool = True
    edit_chips: bool = True
    qr_handoff: bool = False
    show_cost_to_visitors: bool = False
    allow_same_model_compare: bool = False


class UiSection(_Strict):
    idle_reset_seconds: int = Field(default=180, gt=0)
    history_size: int = Field(default=6, gt=0)
    styles: list[str]
    edit_chips: list[str]
    challenge: LocalizedText
    reset_language_on_new_visitor: bool = True


class AccessSection(_Strict):
    enabled: bool = True
    expose_api: bool = False  # true only while load testing: lets the Gradio client call events


class SafetySection(_Strict):
    mode: Literal["family"] = "family"
    characters: Literal["allow", "redirect", "block"] = "redirect"
    offer_safe_rewrite: bool = True
    fail_closed: Literal[True] = True
    max_input_chars: int = Field(default=400, gt=0)


class LimitsSection(_Strict):
    max_images: int = Field(gt=0)
    max_cost_usd: float = Field(gt=0)
    max_concurrent_generations: int = Field(gt=0)
    max_generations_per_minute: int = Field(gt=0)
    device_cooldown_seconds: float = Field(ge=0)
    device_max_images_per_hour: int | None = Field(default=None, gt=0)


class AppConfig(_Strict):
    image_backend: Literal["fal", "hf"]
    app: AppSection
    features: FeaturesSection
    ui: UiSection
    style_fragments: dict[str, str]
    access: AccessSection
    safety: SafetySection
    limits: LimitsSection

    @model_validator(mode="after")
    def _cross_checks(self) -> AppConfig:
        missing = [key for key in self.ui.styles if key not in self.style_fragments]
        if missing:
            raise ValueError(f"style_fragments missing for ui.styles: {missing}")
        if not set(self.app.languages) <= set(self.ui.challenge):
            raise ValueError("ui.challenge must have text for every language in app.languages")
        return self


class ImageModel(_Strict):
    label: LocalizedText
    description: LocalizedText
    provider: Literal["fal", "hf"]
    api_model: str
    hf_model: str | None = None
    est_cost_usd: float = Field(ge=0)
    translate_to_english: bool = False
    enabled: bool = True


class EditModel(_Strict):
    provider: Literal["fal", "hf"]
    api_model: str
    hf_model: str | None = None
    est_cost_usd: float = Field(ge=0)
    enabled: bool = True


class TextModel(_Strict):
    provider: Literal["openai"]
    api_model: str
    reasoning_effort: str | None = "none"  # sent as reasoning_effort; null omits it


class Defaults(_Strict):
    create_model: str
    edit_model: str
    compare_a: str
    compare_b: str
    text_model: str = "helper"


class ModelsConfig(_Strict):
    image_models: dict[str, ImageModel]
    edit_models: dict[str, EditModel]
    text_models: dict[str, TextModel]
    moderation_model: str = "omni-moderation-latest"
    defaults: Defaults


class Settings(_Strict):
    config: AppConfig
    models: ModelsConfig

    @model_validator(mode="after")
    def _cross_checks(self) -> Settings:
        languages = set(self.config.app.languages)
        for key, model in self.models.image_models.items():
            if not languages <= set(model.label) or not languages <= set(model.description):
                raise ValueError(f"image model '{key}' needs label and description per language")

        active = self.active_image_models()
        defaults = self.models.defaults
        for name in ("create_model", "compare_a", "compare_b"):
            key = getattr(defaults, name)
            if key not in active:
                raise ValueError(
                    f"defaults.{name} '{key}' is not an enabled, available image model"
                )
        if (
            defaults.compare_a == defaults.compare_b
            and not self.config.features.allow_same_model_compare
        ):
            raise ValueError("defaults.compare_a and compare_b must differ")
        if defaults.edit_model not in self.models.edit_models:
            raise ValueError(f"defaults.edit_model '{defaults.edit_model}' is not in edit_models")
        if defaults.text_model not in self.models.text_models:
            raise ValueError(f"defaults.text_model '{defaults.text_model}' is not in text_models")
        return self

    @property
    def development_mode(self) -> bool:
        return self.config.app.development_mode

    def _available(self, model: ImageModel | EditModel) -> bool:
        if not model.enabled:
            return False
        return self.config.image_backend == "fal" or model.hf_model is not None

    def active_image_models(self) -> dict[str, ImageModel]:
        return {k: m for k, m in self.models.image_models.items() if self._available(m)}

    def hidden_image_models(self) -> list[str]:
        return [
            k for k, m in self.models.image_models.items() if m.enabled and not self._available(m)
        ]

    def active_edit_model(self) -> tuple[str, EditModel] | None:
        key = self.models.defaults.edit_model
        model = self.models.edit_models[key]
        return (key, model) if self._available(model) else None

    def provider_for(self, model: ImageModel | EditModel) -> str:
        return "hf" if self.config.image_backend == "hf" else model.provider

    def model_id_for(self, model: ImageModel | EditModel) -> str:
        if self.config.image_backend == "hf" and model.hf_model:
            return model.hf_model
        return model.api_model

    def required_secrets(self) -> list[str]:
        if self.development_mode:
            return []
        names = ["FAL_KEY" if self.config.image_backend == "fal" else "HF_TOKEN"]
        names.append("OPENAI_API_KEY")
        if self.config.access.enabled:
            names += ["WORKSHOP_PASSWORD", "ADMIN_PASSWORD"]
        return names

    def startup_problems(self, env: Mapping[str, str]) -> list[str]:
        """Human-readable reasons startup must stop. Never includes secret values."""
        if self.development_mode:
            present = [name for name in REAL_SECRET_NAMES if env.get(name)]
            if env.get("SPACE_ID") and present:
                return [
                    "development_mode must not be enabled on a Hugging Face Space "
                    f"that has real secrets set: {', '.join(present)}"
                ]
            problems = password_problems(env)
            passwords_set = [bool(env.get(name)) for name in (WORKSHOP_ENV, ADMIN_ENV)]
            if self.config.access.enabled and any(passwords_set) and not all(passwords_set):
                problems.append(f"Set both {WORKSHOP_ENV} and {ADMIN_ENV}, or neither")
            return problems
        problems = [
            f"Missing secret: {name}" for name in self.required_secrets() if not env.get(name)
        ]
        if self.config.access.enabled:
            problems += password_problems(env)
        else:
            problems.append("access.enabled is false: refusing to run with real keys and no login")
        if self.config.access.expose_api:
            problems.append(
                "access.expose_api is only for load tests with fakes (development mode)"
            )
        model_ids = [
            (f"image model '{k}'", self.model_id_for(m))
            for k, m in self.active_image_models().items()
        ]
        if edit := self.active_edit_model():
            model_ids.append((f"edit model '{edit[0]}'", self.model_id_for(edit[1])))
        model_ids += [
            (f"text model '{k}'", m.api_model) for k, m in self.models.text_models.items()
        ]
        model_ids.append(("moderation model", self.models.moderation_model))
        problems += [
            f"{what} still has a placeholder model id"
            for what, mid in model_ids
            if PLACEHOLDER_MARK in mid
        ]
        return problems


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} must contain a YAML mapping")
    return data


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_file_path(env: Mapping[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    return Path(env.get("ENV_FILE") or DEFAULT_ENV_FILE)


def load_env_file(
    path: Path | None = None, env: MutableMapping[str, str] | None = None
) -> list[str]:
    """Copy the allowed KEY=VALUE lines of a .env file into the environment.

    Variables that are already set (and not empty) win, so Space secrets and shell values are never
    overridden. If a name appears twice in the file the last one wins. Unquoted values end at a
    " #" comment; quote a value that needs one. Returns the names set, never their values.
    """
    env = os.environ if env is None else env
    file = path or env_file_path(env)
    if not file.is_file():
        return []
    found: dict[str, str] = {}
    for line in file.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip().removeprefix("export ").strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        name, value = name.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        else:
            value = value.split(" #", 1)[0].strip()
        if name in ENV_FILE_KEYS:
            found[name] = value
    loaded: list[str] = []
    for name, value in found.items():
        if value and not env.get(name):
            env[name] = value
            loaded.append(name)
    return loaded


def load_settings(config_dir: Path = CONFIG_DIR, env: Mapping[str, str] | None = None) -> Settings:
    env = os.environ if env is None else env
    app_data = _read_yaml(config_dir / "app.yaml")
    if "DEVELOPMENT_MODE" in env:
        app_data.setdefault("app", {})["development_mode"] = _truthy(env["DEVELOPMENT_MODE"])
    if "EXPOSE_API" in env:
        app_data.setdefault("access", {})["expose_api"] = _truthy(env["EXPOSE_API"])
    return Settings(
        config=AppConfig.model_validate(app_data),
        models=ModelsConfig.model_validate(_read_yaml(config_dir / "models.yaml")),
    )
