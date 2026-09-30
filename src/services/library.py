"""The ideas library: grouped example prompts and cached images (config/prompt_library.yaml).

A chosen prompt fills the text box. If the visitor then creates it unchanged, with no style, the
cached image is shown instantly and nothing is generated or billed. The text must equal a library
text exactly (after cleaning), so nothing else can reach the cache. Any change goes through the
normal Create pipeline and is moderated like anything a visitor types.

The images are made offline by `scripts/build_library.py`, reviewed and committed together with
`config/prompt_library.lock.json`, which ties each image to the texts it was moderated for. An
entry whose texts or image no longer match the lock file is hidden, never served.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping
from functools import cached_property
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.config import CONFIG_DIR, LocalizedText, Settings
from src.services.safety import clean_text, validate_input

logger = logging.getLogger(__name__)

LIBRARY_FILE = CONFIG_DIR / "prompt_library.yaml"
LOCK_FILE = CONFIG_DIR / "prompt_library.lock.json"
LIBRARY_DIR = Path(__file__).resolve().parent.parent.parent / "assets" / "library"
IMAGE_SUFFIX = ".webp"
IMAGE_LANGUAGE = "en"  # the language the example images were made from
ID_PATTERN = r"^[a-z0-9][a-z0-9-]*$"

Lock = dict[str, dict[str, str]]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LibraryPrompt(_Strict):
    id: str = Field(pattern=ID_PATTERN)
    text: LocalizedText

    def image_text(self) -> str:
        return self.text.get(IMAGE_LANGUAGE) or next(iter(self.text.values()))

    def text_digest(self) -> str:
        joined = "\n".join(f"{lang}={clean_text(t)}" for lang, t in sorted(self.text.items()))
        return hashlib.sha256(joined.encode("utf-8")).hexdigest()


class LibraryGroup(_Strict):
    id: str = Field(pattern=ID_PATTERN)
    label: LocalizedText
    prompts: list[LibraryPrompt]


class PromptLibrary(_Strict):
    groups: list[LibraryGroup]
    image_dir: Path = Field(default=LIBRARY_DIR, exclude=True)

    @model_validator(mode="after")
    def _ids_are_unique(self) -> PromptLibrary:
        group_ids = [g.id for g in self.groups]
        prompt_ids = [p.id for g in self.groups for p in g.prompts]
        if len(set(group_ids)) != len(group_ids) or len(set(prompt_ids)) != len(prompt_ids):
            raise ValueError("prompt library ids must be unique")
        if not all(g.prompts for g in self.groups):
            raise ValueError("every prompt library group needs at least one prompt")
        return self

    def prompts(self) -> list[LibraryPrompt]:
        return [p for g in self.groups for p in g.prompts]

    def image_path(self, prompt: LibraryPrompt) -> Path:
        return self.image_dir / f"{prompt.id}{IMAGE_SUFFIX}"

    @cached_property
    def _by_text(self) -> dict[str, LibraryPrompt]:
        return {clean_text(t): p for p in self.prompts() for t in p.text.values()}

    def find(self, text: str) -> LibraryPrompt | None:
        """The prompt whose text, in any language, equals `text` after cleaning, else None."""
        return self._by_text.get(clean_text(text))

    def check(self, settings: Settings) -> None:
        """Raise if a label or prompt is missing a language, would fail input validation or two
        texts collide once cleaned (the cache would answer with the wrong image)."""
        languages = set(settings.config.app.languages)
        limit = settings.config.safety.max_input_chars
        seen: set[str] = set()
        for group in self.groups:
            if not languages <= set(group.label):
                raise ValueError(f"library group '{group.id}' needs a label per language")
            for prompt in group.prompts:
                if not languages <= set(prompt.text):
                    raise ValueError(f"library prompt '{prompt.id}' needs text per language")
                for text in prompt.text.values():
                    cleaned = validate_input(text, limit)
                    if cleaned in seen:
                        raise ValueError(f"library prompt '{prompt.id}' repeats a text")
                    seen.add(cleaned)

    def build_lock(self) -> Lock:
        """Digests for every prompt that has an image, to be reviewed and committed."""
        return {
            p.id: {"text": p.text_digest(), "image": _file_digest(self.image_path(p))}
            for p in self.prompts()
            if self.image_path(p).is_file()
        }

    def with_images(self, lock: Mapping[str, Mapping[str, str]] | None = None) -> PromptLibrary:
        """Only the prompts whose image exists and, if a lock is given, still matches it."""
        groups = []
        for group in self.groups:
            have = []
            for prompt in group.prompts:
                path = self.image_path(prompt)
                entry = (lock or {}).get(prompt.id, {})
                if not path.is_file():
                    logger.warning("prompt library: no image for '%s', hidden", prompt.id)
                elif lock is not None and (
                    entry.get("text") != prompt.text_digest()
                    or entry.get("image") != _file_digest(path)
                ):
                    logger.warning(
                        "prompt library: '%s' does not match its lock, hidden", prompt.id
                    )
                else:
                    have.append(prompt)
            if have:
                groups.append(group.model_copy(update={"prompts": have}))
        return PromptLibrary(groups=groups, image_dir=self.image_dir)


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_library(
    settings: Settings, path: Path = LIBRARY_FILE, image_dir: Path = LIBRARY_DIR
) -> PromptLibrary:
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    library = PromptLibrary(groups=data["groups"], image_dir=image_dir)
    library.check(settings)
    return library


def load_lock(path: Path = LOCK_FILE) -> Lock:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def write_lock(lock: Lock, path: Path = LOCK_FILE) -> None:
    path.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8")
