"""Make the cached example images for the ideas library (config/prompt_library.yaml).

    uv run python -m scripts.build_library --dry-run     # what would be made, and the cost
    uv run python -m scripts.build_library               # make the missing images
    uv run python -m scripts.build_library --only fox-snow --force

Uses the real image provider, so it needs the image backend's key (HF_TOKEN) and OPENAI_API_KEY in
the environment or the .env file, and costs about one image per missing prompt. Each prompt (in
every language) and each image goes through the same safety checks as a visitor's Create. Images
are square, made with the default Create model and no style, saved as webp in assets/library/.
The run ends by writing config/prompt_library.lock.json, which ties each image to the texts it was
made for; the app hides any prompt that no longer matches it. Look at the contact sheet it prints,
delete any image you dislike and run again (a new one is made), then commit the images and the
lock file. Running it with nothing missing only refreshes the lock file and the sheet.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import os
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

from src.config import Settings, load_env_file, load_settings
from src.errors import AppError, SafetyRefusalError
from src.logging_setup import configure_logging
from src.providers.base import ImageRequest
from src.providers.factory import build_image, build_moderator, build_text
from src.services.library import (
    LOCK_FILE,
    LibraryPrompt,
    PromptLibrary,
    load_library,
    write_lock,
)
from src.services.prompts import compose_prompt
from src.services.safety import SafetyService

CONCURRENCY = 3
WEBP_QUALITY = 85
SHEET_COLUMNS = 6
SHEET_CELL = 256


def to_webp(png: bytes) -> bytes:
    buffer = io.BytesIO()
    Image.open(io.BytesIO(png)).convert("RGB").save(buffer, format="WEBP", quality=WEBP_QUALITY)
    return buffer.getvalue()


def contact_sheet(library: PromptLibrary) -> Path | None:
    prompts = [p for p in library.prompts() if library.image_path(p).is_file()]
    if not prompts:
        return None
    rows = -(-len(prompts) // SHEET_COLUMNS)
    sheet = Image.new("RGB", (SHEET_COLUMNS * SHEET_CELL, rows * SHEET_CELL), "white")
    draw = ImageDraw.Draw(sheet)
    for index, prompt in enumerate(prompts):
        with Image.open(library.image_path(prompt)) as image:
            cell = image.convert("RGB").resize((SHEET_CELL, SHEET_CELL))
        x, y = (index % SHEET_COLUMNS) * SHEET_CELL, (index // SHEET_COLUMNS) * SHEET_CELL
        sheet.paste(cell, (x, y))
        draw.rectangle((x, y, x + SHEET_CELL, y + 14), fill="black")
        draw.text((x + 3, y + 1), prompt.id, fill="white")
    with tempfile.NamedTemporaryFile(prefix="library_sheet_", suffix=".png", delete=False) as file:
        sheet.save(file, format="PNG")
    return Path(file.name)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true", help="remake images that already exist")
    parser.add_argument("--only", action="append", default=[], help="a prompt id (repeatable)")
    args = parser.parse_args()

    sys.stdout.reconfigure(encoding="utf-8")
    configure_logging()
    load_env_file()
    settings = load_settings()
    library = load_library(settings)
    if unknown := set(args.only) - {p.id for p in library.prompts()}:
        print(f"Unknown prompt id: {', '.join(sorted(unknown))}")
        return 2
    todo = [
        p
        for p in library.prompts()
        if (not args.only or p.id in args.only)
        and (args.force or not library.image_path(p).is_file())
    ]
    model_key = settings.models.defaults.create_model
    cost = settings.models.image_models[model_key].est_cost_usd
    total = len(library.prompts())
    print(
        f"{len(todo)} of {total} images to make with '{model_key}', about ${len(todo) * cost:.2f}"
    )
    if args.dry_run:
        return 0
    bad = 0
    if todo:
        if settings.development_mode:
            print("Development mode uses fakes; unset DEVELOPMENT_MODE to make real images.")
            return 2
        key = "HF_TOKEN" if settings.config.image_backend == "hf" else "FAL_KEY"
        if missing := [n for n in (key, "OPENAI_API_KEY") if not os.environ.get(n)]:
            print(f"Missing: {', '.join(missing)} (set it in the shell or the .env file).")
            return 2
        results = await make_images(settings, library, todo, model_key)
        for prompt_id, outcome in results:
            print(f"{prompt_id:22} {outcome}")
        bad = sum(not outcome.startswith("ok") for _, outcome in results)
        print(f"{len(results) - bad} made, {bad} not made")

    write_lock(library.build_lock())
    print(f"Wrote {LOCK_FILE.name}: commit it with the images once you have reviewed them.")
    if sheet := contact_sheet(library):
        print(f"Contact sheet for review: {sheet}")
    return 1 if bad else 0


async def make_images(
    settings: Settings, library: PromptLibrary, todo: list[LibraryPrompt], model_key: str
) -> list[tuple[str, str]]:
    image_provider = build_image(settings)
    safety = SafetyService(build_moderator(settings), build_text(settings), settings.config.safety)
    library.image_dir.mkdir(parents=True, exist_ok=True)
    gate = asyncio.Semaphore(CONCURRENCY)

    async def make(prompt: LibraryPrompt) -> tuple[str, str]:
        async with gate:
            try:
                # Every language the visitor can see is checked, not only the one the image uses.
                for lang, text in prompt.text.items():
                    await safety.check_prompt(compose_prompt(text), lang)
                result = await image_provider.generate(
                    ImageRequest(
                        prompt=compose_prompt(prompt.image_text()),
                        model_key=model_key,
                        aspect="square",
                    )
                )
                await safety.check_image(result.image)
                target = library.image_path(prompt)
                partial = target.with_suffix(".tmp")
                partial.write_bytes(to_webp(result.image))
                os.replace(partial, target)
            except SafetyRefusalError as refusal:
                return prompt.id, f"REFUSED ({refusal.code}): reword this prompt"
            except AppError as error:
                return prompt.id, f"FAILED ({type(error).__name__}): run again"
            except Exception as error:
                return prompt.id, f"FAILED ({type(error).__name__}): run again"
            return prompt.id, f"ok, {result.seconds:.1f} s"

    return await asyncio.gather(*(make(p) for p in todo))


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
