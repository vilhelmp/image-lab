"""Compare image models side by side on a few fixed prompts, with latency and a contact sheet.

    uv run python -m scripts.bakeoff t2i black-forest-labs/FLUX.1-schnell Tongyi-MAI/Z-Image-Turbo
    uv run python -m scripts.bakeoff edit black-forest-labs/FLUX.2-klein-4B@fal-ai --source fox-snow

Each model is `huggingface-id@provider` (leave out `@provider` to let HF choose). Needs HF_TOKEN in
the environment or the .env file one folder above the repo, and costs real money (cents per run).
The prompts are fixed and harmless and bypass the app's safety checks, so this is a private
evaluation tool, never part of the app. Models with a non-commercial licence may be tried here for
evaluation only; do not enable them for visitors without permission. Images and the contact
sheet go to a temporary folder; compare actual cost on the Hugging Face billing page afterwards.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import os
import sys
import tempfile
import time
from pathlib import Path

from PIL import Image, ImageDraw

from src.config import load_env_file
from src.errors import AppError
from src.logging_setup import configure_logging
from src.providers.hf_inference import SIZES, HFRunner, safety_extra
from src.services.library import LIBRARY_DIR

TIMEOUT_SECONDS = 90.0
CELL = 320
LABEL_WIDTH = 230
HEADER_HEIGHT = 40

T2I_PROMPTS = {
    "photo": "A candid photo of a home kitchen in the morning, steam rising from a coffee mug, "
    "crumbs on the counter, soft window light",
    "illustration": "A friendly dragon flipping pancakes in a small cottage kitchen, "
    "colorful illustration",
    "text": 'A wooden shop sign that reads "FIKA" above a cosy cafe door, rainy evening, photo',
}
EDIT_INSTRUCTIONS = {
    "evening": "Make it a warm evening scene with golden light. Keep the subject the same.",
    "playful": "Make it more playful and colorful. Keep the subject the same.",
    "painting": "Turn it into an oil painting. Keep the subject and composition the same.",
}

Cell = tuple[float, bytes | None, str]  # seconds, PNG bytes, error name


def parse(spec: str) -> tuple[str, str | None]:
    model, _, provider = spec.partition("@")
    return model, provider or None


async def run_cell(runner: HFRunner, spec: str, method: str, *args, **kwargs) -> Cell:
    model, provider = parse(spec)
    started = time.perf_counter()
    try:
        png = await runner.png(
            f"bakeoff {model}",
            provider,
            method,
            *args,
            model=model,
            extra_body=safety_extra(provider),
            **kwargs,
        )
    except AppError as error:
        return time.perf_counter() - started, None, type(error).__name__
    return time.perf_counter() - started, png, ""


def load_source(name: str) -> bytes:
    path = LIBRARY_DIR / f"{name}.webp"
    if not path.is_file():
        raise SystemExit(
            f"No library image '{name}' (run `git lfs checkout` if the files are pointers)"
        )
    buffer = io.BytesIO()
    Image.open(path).convert("RGB").save(buffer, format="PNG")
    return buffer.getvalue()


def sheet(
    rows: list[str], columns: list[str], cells: dict[tuple[str, str], Cell], source: bytes | None
) -> Image.Image:
    offset = 1 if source else 0
    width = LABEL_WIDTH + (len(columns) + offset) * CELL
    image = Image.new("RGB", (width, HEADER_HEIGHT + len(rows) * CELL), "white")
    draw = ImageDraw.Draw(image)
    if source:
        draw.text((LABEL_WIDTH + 6, 12), "source", fill="black")
    for index, column in enumerate(columns):
        draw.text((LABEL_WIDTH + (index + offset) * CELL + 6, 12), column, fill="black")
    for row_index, row in enumerate(rows):
        top = HEADER_HEIGHT + row_index * CELL
        draw.text((6, top + 6), row, fill="black")
        if source:
            with Image.open(io.BytesIO(source)) as original:
                image.paste(original.convert("RGB").resize((CELL, CELL)), (LABEL_WIDTH, top))
        for index, column in enumerate(columns):
            seconds, png, error = cells[(row, column)]
            left = LABEL_WIDTH + (index + offset) * CELL
            if png:
                with Image.open(io.BytesIO(png)) as result:
                    image.paste(result.convert("RGB").resize((CELL, CELL)), (left, top))
                draw.text((left + 4, top + 4), f"{seconds:.1f} s", fill="yellow")
            else:
                draw.text((left + 4, top + 4), f"failed: {error}", fill="red")
    return image


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("mode", choices=["t2i", "edit"])
    parser.add_argument("models", nargs="+", help="huggingface-id@provider")
    parser.add_argument("--source", default="fox-snow", help="library image to edit (edit mode)")
    parser.add_argument(
        "--instruction",
        action="append",
        default=[],
        help="edit instruction to try instead of the defaults (repeatable)",
    )
    args = parser.parse_args()

    sys.stdout.reconfigure(encoding="utf-8")
    configure_logging()
    load_env_file()
    token = os.environ.get("HF_TOKEN")
    if not token:
        print("Missing HF_TOKEN (set it in the shell or the .env file).")
        return 2
    runner = HFRunner(token, timeout=TIMEOUT_SECONDS)

    source = load_source(args.source) if args.mode == "edit" else None
    instructions = (
        {f"#{n}": text for n, text in enumerate(args.instruction, 1)}
        if args.instruction
        else EDIT_INSTRUCTIONS
    )
    for label, text in instructions.items() if args.instruction else []:
        print(f"{label}: {text}")
    columns = list(instructions if source else T2I_PROMPTS)
    cells: dict[tuple[str, str], Cell] = {}
    for spec in args.models:
        for column in columns:
            if source:
                cell = await run_cell(
                    runner, spec, "image_to_image", source, prompt=instructions[column]
                )
            else:
                width, height = SIZES["square"]
                cell = await run_cell(
                    runner,
                    spec,
                    "text_to_image",
                    T2I_PROMPTS[column],
                    width=width,
                    height=height,
                )
            cells[(spec, column)] = cell
            seconds, _, error = cell
            print(f"{spec:55} {column:13} {seconds:5.1f} s  {error or 'ok'}")

    folder = Path(tempfile.mkdtemp(prefix="bakeoff_"))
    for (spec, column), (_, png, _) in cells.items():
        if png:
            safe = spec.replace("/", "_").replace("@", "_at_")
            (folder / f"{safe}__{column}.png").write_bytes(png)
    sheet(args.models, columns, cells, source).save(folder / "sheet.png")
    ok = [seconds for seconds, png, _ in cells.values() if png]
    if ok:
        print(f"\nMedian latency {sorted(ok)[len(ok) // 2]:.1f} s over {len(ok)} images")
    print(f"Images and sheet.png: {folder}")
    return 0 if all(png for _, png, _ in cells.values()) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
