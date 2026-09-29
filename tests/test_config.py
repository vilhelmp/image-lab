import json

import pytest
from pydantic import ValidationError

from src.config import Settings, load_settings
from src.i18n import LOCALES_DIR, I18n, key_mismatches, load_catalogs


def test_real_config_loads():
    settings = load_settings(env={})
    assert settings.config.app.default_language in settings.config.app.languages
    assert settings.development_mode is False


def test_development_mode_env_override():
    assert load_settings(env={"DEVELOPMENT_MODE": "true"}).development_mode is True
    assert load_settings(env={"DEVELOPMENT_MODE": "0"}).development_mode is False


def test_dev_mode_disables_auth_and_needs_no_secrets():
    settings = load_settings(env={"DEVELOPMENT_MODE": "true"})
    assert settings.auth_enabled is False
    assert settings.startup_problems({}) == []


def test_dev_mode_is_refused_on_a_space_with_real_secrets():
    settings = load_settings(env={"DEVELOPMENT_MODE": "true"})
    problems = settings.startup_problems({"SPACE_ID": "me/space", "OPENAI_API_KEY": "secret-x"})
    assert problems and "OPENAI_API_KEY" in problems[0]
    assert "secret-x" not in problems[0]


def test_dev_mode_is_allowed_on_a_space_without_secrets():
    settings = load_settings(env={"DEVELOPMENT_MODE": "true"})
    assert settings.startup_problems({"SPACE_ID": "me/space"}) == []


def test_invalid_default_model_rejected(make_settings):
    def bad_default(models):
        models["defaults"]["create_model"] = "does_not_exist"

    with pytest.raises(ValidationError, match="create_model"):
        make_settings(models=bad_default)


def test_disabled_default_model_rejected(make_settings):
    def disable(models):
        models["image_models"]["fast"]["enabled"] = False

    with pytest.raises(ValidationError, match="create_model"):
        make_settings(models=disable)


def test_same_compare_models_rejected_unless_allowed(make_settings):
    def same(models):
        models["defaults"]["compare_b"] = models["defaults"]["compare_a"]

    with pytest.raises(ValidationError, match="differ"):
        make_settings(models=same)

    def allow(app):
        app["features"]["allow_same_model_compare"] = True

    assert make_settings(app=allow, models=same)


def test_fail_closed_cannot_be_disabled(make_settings):
    def off(app):
        app["safety"]["fail_closed"] = False

    with pytest.raises(ValidationError):
        make_settings(app=off)


def test_style_without_fragment_rejected(make_settings):
    def drop(app):
        del app["style_fragments"]["retro"]

    with pytest.raises(ValidationError, match="style_fragments"):
        make_settings(app=drop)


def test_model_label_must_cover_every_language(make_settings):
    def drop(models):
        del models["image_models"]["fast"]["label"]["en"]

    with pytest.raises(ValidationError, match="label and description"):
        make_settings(models=drop)


def test_hf_backend_hides_models_without_hf_model(make_settings):
    def hf(app):
        app["image_backend"] = "hf"

    def strip_one(models):
        del models["image_models"]["text_expert"]["hf_model"]

    settings = make_settings(app=hf, models=strip_one)
    assert "text_expert" not in settings.active_image_models()
    assert settings.hidden_image_models() == ["text_expert"]
    assert settings.active_edit_model() is None  # placeholder edit model has no hf_model


def test_hf_backend_rejects_default_without_hf_model(make_settings):
    def hf(app):
        app["image_backend"] = "hf"

    def strip_default(models):
        del models["image_models"]["fast"]["hf_model"]

    with pytest.raises(ValidationError, match="create_model"):
        make_settings(app=hf, models=strip_default)


def test_hf_backend_requires_only_hf_token(make_settings):
    def hf(app):
        app["image_backend"] = "hf"
        app["access"]["enabled"] = False

    settings = make_settings(app=hf)
    assert "HF_TOKEN" in settings.required_secrets()
    assert "FAL_KEY" not in settings.required_secrets()


def test_fal_backend_requires_fal_key(make_settings):
    settings = make_settings()
    assert "FAL_KEY" in settings.required_secrets()
    assert "HF_TOKEN" not in settings.required_secrets()


def test_missing_secrets_stop_startup_without_leaking_values(make_settings):
    settings = make_settings()
    problems = settings.startup_problems({"FAL_KEY": "super-secret-value"})
    assert any("OPENAI_API_KEY" in p for p in problems)
    assert not any("FAL_KEY" in p for p in problems)
    assert "super-secret-value" not in " ".join(problems)


def test_placeholder_model_ids_stop_startup(make_settings):
    env = dict.fromkeys(make_settings().required_secrets(), "x")
    problems = make_settings().startup_problems(env)
    assert any("placeholder" in p for p in problems)


def test_secrets_are_not_part_of_serialised_settings(make_settings):
    dumped = make_settings().model_dump_json()
    assert "OPENAI_API_KEY" not in dumped and "PASSWORD" not in dumped


def test_locale_keys_match_across_all_files():
    files = sorted(LOCALES_DIR.glob("*.json"))
    assert len(files) >= 2
    catalogs = {f.stem: json.loads(f.read_text(encoding="utf-8")) for f in files}
    assert key_mismatches(catalogs) == {}


def test_i18n_rejects_mismatched_catalogs():
    with pytest.raises(ValueError, match="differ"):
        I18n({"sv": {"a": "1"}, "en": {"a": "1", "b": "2"}}, "sv")


def test_i18n_returns_key_for_unknown_key():
    assert I18n({"sv": {"a": "1"}}, "sv").t("sv", "missing") == "missing"


def test_config_texts_have_locale_entries(dev_settings: Settings):
    config = dev_settings.config
    catalogs = load_catalogs(LOCALES_DIR, config.app.languages)
    for lang, catalog in catalogs.items():
        for style in config.ui.styles:
            assert f"style.{style}" in catalog, (lang, style)
        assert "lang.name" in catalog
    assert set(config.app.languages) <= set(config.ui.challenge)
