"""The ideas library: config, cached images and the instant example on Create."""

import io

import pytest
from PIL import Image

from src.errors import PausedError
from src.providers.factory import Providers
from src.providers.fake import FakeEditProvider, FakeImageProvider, FakeModerator, FakeTextProvider
from src.services.generation import CreateRequest, GenerationService
from src.services.library import (
    IMAGE_SUFFIX,
    LibraryPrompt,
    PromptLibrary,
    load_library,
    load_lock,
    write_lock,
)
from src.services.limits import LimitService

LIBRARY = {
    "groups": [
        {
            "id": "animals",
            "label": {"sv": "Djur", "en": "Animals"},
            "prompts": [
                {"id": "fox", "text": {"sv": "En räv i snö", "en": "A fox in the snow"}},
                {"id": "owl", "text": {"sv": "En uggla", "en": "An owl"}},
            ],
        }
    ]
}


def picture() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), (10, 200, 30)).save(buffer, format="WEBP")
    return buffer.getvalue()


@pytest.fixture
def library(tmp_path) -> PromptLibrary:
    (tmp_path / f"fox{IMAGE_SUFFIX}").write_bytes(picture())
    return PromptLibrary(groups=LIBRARY["groups"], image_dir=tmp_path)


def service(
    dev_settings, library, image=None, limits=None
) -> tuple[GenerationService, LimitService]:
    limits = limits or LimitService(dev_settings.config.limits)
    providers = Providers(
        image=image or FakeImageProvider(cost=0.005),
        edit=FakeEditProvider(),
        text=FakeTextProvider(),
        moderator=FakeModerator(),
    )
    return GenerationService(dev_settings, providers, limits, library), limits


# --- the real library ------------------------------------------------------------------------


def test_the_real_library_is_valid_and_every_prompt_has_its_cached_image(dev_settings):
    library = load_library(dev_settings)
    missing = [p.id for p in library.prompts() if not library.image_path(p).is_file()]
    assert library.prompts() and not missing, f"run scripts/build_library.py: {missing}"


def test_the_committed_lock_matches_every_text_and_image(dev_settings):
    library = load_library(dev_settings)
    shown = library.with_images(load_lock())
    hidden = {p.id for p in library.prompts()} - {p.id for p in shown.prompts()}
    assert not hidden, f"run scripts/build_library.py and review the images: {sorted(hidden)}"
    assert load_lock() == library.build_lock()


# --- the library model ------------------------------------------------------------------------


def test_find_matches_either_language_ignoring_whitespace(library):
    assert library.find("A fox in the snow").id == "fox"
    assert library.find("  En  räv\ti snö\n").id == "fox"
    assert library.find("A fox in the snow.") is None
    assert library.find("a fox in the snow") is None
    assert library.find("") is None


def test_ids_must_be_unique():
    dup = {"id": "fox", "text": {"sv": "a", "en": "b"}}
    with pytest.raises(ValueError):
        PromptLibrary(groups=[{"id": "g", "label": {"sv": "g", "en": "g"}, "prompts": [dup, dup]}])


def test_every_prompt_needs_every_language(dev_settings):
    broken = PromptLibrary(
        groups=[
            {
                "id": "g",
                "label": {"sv": "g", "en": "g"},
                "prompts": [{"id": "x", "text": {"sv": "bara svenska"}}],
            }
        ]
    )
    with pytest.raises(ValueError, match="text per language"):
        broken.check(dev_settings)


def test_overlong_prompts_are_rejected(dev_settings):
    long = "x" * (dev_settings.config.safety.max_input_chars + 1)
    broken = PromptLibrary(
        groups=[
            {
                "id": "g",
                "label": {"sv": "g", "en": "g"},
                "prompts": [{"id": "x", "text": {"sv": long, "en": long}}],
            }
        ]
    )
    with pytest.raises(Exception):  # noqa: B017 - TooLongInputError is an AppError
        broken.check(dev_settings)


def test_prompts_without_an_image_are_hidden(library):
    shown = library.with_images()
    assert [p.id for p in shown.prompts()] == ["fox"]


def test_a_matching_lock_shows_the_prompt(library):
    assert [p.id for p in library.with_images(library.build_lock()).prompts()] == ["fox"]


def test_an_empty_or_missing_lock_hides_everything(library):
    assert library.with_images({}).prompts() == []


def test_an_edited_text_hides_the_prompt_until_it_is_rebuilt(library):
    lock = library.build_lock()
    edited = PromptLibrary(
        groups=[
            {
                **LIBRARY["groups"][0],
                "prompts": [
                    {"id": "fox", "text": {"sv": "En räv i snö", "en": "A fox in the rain"}}
                ],
            }
        ],
        image_dir=library.image_dir,
    )
    assert edited.with_images(lock).prompts() == []


def test_a_replaced_image_hides_the_prompt(library):
    lock = library.build_lock()
    (library.image_dir / f"fox{IMAGE_SUFFIX}").write_bytes(b"something else")
    assert library.with_images(lock).prompts() == []


def test_the_lock_round_trips_through_its_file(library, tmp_path):
    path = tmp_path / "lock.json"
    write_lock(library.build_lock(), path)
    assert load_lock(path) == library.build_lock()
    assert load_lock(tmp_path / "missing.json") == {}


@pytest.mark.parametrize("bad_id", ["../x", "a/b", "A", "", "x.webp", "-x"])
def test_ids_cannot_escape_the_image_folder(bad_id):
    with pytest.raises(ValueError):
        LibraryPrompt(id=bad_id, text={"sv": "a", "en": "b"})


def test_texts_that_collide_once_cleaned_are_rejected(dev_settings):
    twins = PromptLibrary(
        groups=[
            {
                "id": "g",
                "label": {"sv": "g", "en": "g"},
                "prompts": [
                    {"id": "a", "text": {"sv": "En räv", "en": "A fox"}},
                    {"id": "b", "text": {"sv": "Ett träd", "en": "A  fox"}},
                ],
            }
        ]
    )
    with pytest.raises(ValueError, match="repeats"):
        twins.check(dev_settings)


# --- the instant example on Create -----------------------------------------------------------


async def test_an_unchanged_library_prompt_returns_the_cached_image_for_free(dev_settings, library):
    fake = FakeImageProvider(cost=0.005)
    create, limits = service(dev_settings, library, image=fake)
    result = await create.create(CreateRequest(text="A fox in the snow", device_hash="a"))
    assert result.cached and result.est_cost == 0 and result.image == picture()
    assert fake.calls == []
    snap = limits.snapshot()
    assert (snap.images_used, snap.spend_usd) == (0, 0)


async def test_the_swedish_text_also_hits_the_cache(dev_settings, library):
    create, _ = service(dev_settings, library)
    result = await create.create(CreateRequest(text="En räv i snö", lang="sv"))
    assert result.cached


async def test_a_style_or_an_edit_makes_a_real_generation(dev_settings, library):
    fake = FakeImageProvider(cost=0.005)
    create, limits = service(dev_settings, library, image=fake)
    styled = await create.create(CreateRequest(text="A fox in the snow", style="comic"))
    edited = await create.create(CreateRequest(text="A fox in the snow!", device_hash="b"))
    assert not styled.cached and not edited.cached
    assert len(fake.calls) == 2 and limits.snapshot().images_used == 2


async def test_a_changed_prompt_is_still_moderated(dev_settings, library):
    from src.errors import SafetyRefusalError

    create, _ = service(dev_settings, library)
    with pytest.raises(SafetyRefusalError):
        await create.create(CreateRequest(text="A fox in the snow [blocked]"))


async def test_a_prompt_without_its_image_falls_back_to_generation(dev_settings, library):
    fake = FakeImageProvider(cost=0.005)
    create, _ = service(dev_settings, library, image=fake)
    result = await create.create(CreateRequest(text="An owl"))  # owl has no image file
    assert not result.cached and len(fake.calls) == 1


async def test_cached_examples_still_work_while_generation_is_paused(dev_settings, library):
    create, limits = service(dev_settings, library)
    limits.set_paused(True)
    assert (await create.create(CreateRequest(text="A fox in the snow"))).cached
    with pytest.raises(PausedError):
        await create.create(CreateRequest(text="A brand new idea"))


async def test_oversized_input_is_left_to_the_normal_path(dev_settings, library):
    from src.errors import TooLongInputError

    create, _ = service(dev_settings, library)
    huge = "A fox in the snow" + " " * (dev_settings.config.safety.max_input_chars * 5)
    with pytest.raises(TooLongInputError):
        await create.create(CreateRequest(text=huge))


async def test_no_library_means_no_cache(dev_settings):
    fake = FakeImageProvider(cost=0.005)
    create, _ = service(dev_settings, None, image=fake)
    assert not (await create.create(CreateRequest(text="A fox in the snow"))).cached
