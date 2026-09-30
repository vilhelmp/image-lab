"""Generate one real image and print the latency and the estimated cost.

    uv run python -m scripts.try_image
    uv run python -m scripts.try_image --model detailed --aspect landscape --moderate
    uv run python -m scripts.try_image "a cat wearing a space helmet"

Needs the image backend's key (HF_TOKEN for `image_backend: hf`) in the environment or in the
.env file one folder above the repo. Costs real money (a few cents); run it locally, never in CI.
The image goes to a temporary PNG file, and the path is printed. The prompt is not moderated here:
use a harmless one. `--moderate` also sends the image to the OpenAI image moderation.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import tempfile
from pathlib import Path

from src.config import load_env_file, load_settings
from src.errors import AppError
from src.logging_setup import configure_logging
from src.providers.base import ImageRequest
from src.providers.factory import build_image, build_moderator

DEFAULT_PROMPT = "a friendly robot painting a rainbow, colourful children's book illustration"


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("prompt", nargs="?", default=DEFAULT_PROMPT)
    parser.add_argument("--model", help="image model key from config/models.yaml")
    parser.add_argument("--aspect", choices=["square", "landscape", "portrait"], default="square")
    parser.add_argument("--moderate", action="store_true", help="also moderate the image")
    args = parser.parse_args()

    sys.stdout.reconfigure(encoding="utf-8")
    load_env_file()
    settings = load_settings()
    if settings.development_mode:
        print("Development mode uses fakes; unset DEVELOPMENT_MODE to try the real service.")
        return 2
    key_name = "FAL_KEY" if settings.config.image_backend == "fal" else "HF_TOKEN"
    needed = [key_name] + (["OPENAI_API_KEY"] if args.moderate else [])
    missing = [name for name in needed if not os.environ.get(name)]
    if missing:
        print(f"Missing: {', '.join(missing)} (set it in the shell or the .env file).")
        return 2
    model_key = args.model or settings.models.defaults.create_model
    active = settings.active_image_models()
    if model_key not in active:
        print(f"Unknown or inactive model '{model_key}'. Active: {list(active)}")
        return 2
    model = settings.models.image_models[model_key]
    print(f"Backend {settings.config.image_backend}, model {settings.model_id_for(model)}")

    try:
        result = await build_image(settings).generate(
            ImageRequest(prompt=args.prompt, model_key=model_key, aspect=args.aspect)
        )
    except AppError as error:
        print(f"Failed: {type(error).__name__} (see the log line above)")
        return 1
    with tempfile.NamedTemporaryFile(prefix="ai_image_lab_", suffix=".png", delete=False) as file:
        file.write(result.image)
    print(f"Latency {result.seconds:.1f} s, estimated cost ${result.est_cost:.3f}")
    print(f"Image: {len(result.image) / 1024:.0f} KiB -> {Path(file.name)}")

    if args.moderate:
        try:
            verdict = await build_moderator(settings).moderate_image(result.image)
        except AppError as error:
            print(f"Image moderation failed: {type(error).__name__}")
            return 1
        print(f"Image moderation: {'FLAGGED ' + str(verdict.code) if verdict.flagged else 'clean'}")
    return 0


if __name__ == "__main__":
    configure_logging()
    raise SystemExit(asyncio.run(main()))
