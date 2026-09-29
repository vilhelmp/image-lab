"""Locale catalogs loaded from locales/*.json (spec section 14)."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from pathlib import Path

logger = logging.getLogger(__name__)

LOCALES_DIR = Path(__file__).resolve().parent.parent / "locales"
NATIVE_NAME_KEY = "lang.name"


def load_catalogs(locales_dir: Path, languages: Iterable[str]) -> dict[str, dict[str, str]]:
    return {
        lang: json.loads((locales_dir / f"{lang}.json").read_text(encoding="utf-8"))
        for lang in languages
    }


def key_mismatches(catalogs: dict[str, dict[str, str]]) -> dict[str, set[str]]:
    """Per language, the keys that are missing or extra compared with the union of all keys."""
    all_keys = set().union(*(set(c) for c in catalogs.values())) if catalogs else set()
    return {
        lang: all_keys ^ set(catalog)
        for lang, catalog in catalogs.items()
        if set(catalog) != all_keys
    }


class I18n:
    def __init__(self, catalogs: dict[str, dict[str, str]], default_language: str) -> None:
        mismatches = key_mismatches(catalogs)
        if mismatches:
            raise ValueError(f"Locale keys differ between files: {mismatches}")
        if default_language not in catalogs:
            raise ValueError(f"No catalog for default language '{default_language}'")
        self._catalogs = catalogs
        self.default_language = default_language

    @classmethod
    def load(
        cls, languages: Iterable[str], default_language: str, locales_dir: Path = LOCALES_DIR
    ) -> I18n:
        return cls(load_catalogs(locales_dir, languages), default_language)

    def t(self, lang: str, key: str, **values: object) -> str:
        catalog = self._catalogs.get(lang) or self._catalogs[self.default_language]
        try:
            text = catalog[key]
        except KeyError:
            logger.error("Missing locale key: %s", key)
            return key
        return text.format(**values) if values else text

    def native_name(self, lang: str) -> str:
        return self._catalogs[lang][NATIVE_NAME_KEY]
