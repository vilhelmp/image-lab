"""Exercise the real flow with real keys, locally, before the Space gets them.

    uv run python -m scripts.check_real_flow

Needs HF_TOKEN (or FAL_KEY) and OPENAI_API_KEY in the environment or the .env file one folder
above the repo. Costs about one image. It checks that startup validation passes with the real
environment, then drives Create (a new image, a cached library example, refused ideas), Help me
and Surprise me through the services, and checks that every step ended as expected. Finally it
scans every log line for the visitor texts, the composed prompts, the LLM replies, the suggested
alternatives and the secret values. Exits 1 on any unexpected outcome or leak. Run it locally,
never in CI.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time

from src.config import ENV_FILE_KEYS, load_env_file, load_settings
from src.errors import AppError, SafetyRefusalError
from src.logging_setup import configure_logging
from src.providers.factory import build_providers
from src.services.generation import CreateRequest, GenerationService
from src.services.helpers import HelperService
from src.services.library import load_library, load_lock
from src.services.limits import LimitService
from src.services.prompts import compose_prompt

NEW_IDEA = "a friendly robot painting a rainbow on a brick wall"
SWEDISH_IDEA = "en katt som åker skateboard"
REFUSED_IDEAS = {
    "real person": "a photo of Donald Trump eating a burger",
    "character": "Mickey Mouse driving a car",
    "violence": "a gory murder scene with lots of blood",
}
MIN_LENGTH_TO_SCAN = 12


class Collector(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(self.format(record))


class Run:
    """Runs one step, prints what happened and remembers every text the logs must not hold."""

    def __init__(self) -> None:
        self.sensitive: list[str] = []
        self.unexpected: list[str] = []

    async def step(self, name: str, coro, expect: str) -> None:
        started = time.perf_counter()
        outcome, detail = "ok", ""
        try:
            result = await coro
            if isinstance(result, str):
                self.sensitive.append(result)
                detail = f"\n    -> {result}"
            elif getattr(result, "cached", False):
                detail = "cached"
        except SafetyRefusalError as refusal:
            outcome = "refused"
            detail = refusal.code + (" (with an alternative)" if refusal.rewrite else "")
            if refusal.rewrite:
                self.sensitive.append(refusal.rewrite)
        except AppError as error:
            outcome, detail = "error", type(error).__name__
        seconds = time.perf_counter() - started
        verdict = "" if outcome == expect else f"   UNEXPECTED, wanted {expect}"
        print(f"{name:32} {outcome:8} {seconds:5.1f} s  {detail}{verdict}")
        if outcome != expect:
            self.unexpected.append(name)


async def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    configure_logging()
    collector = Collector()
    logging.getLogger().addHandler(collector)
    load_env_file()
    settings = load_settings()
    if settings.development_mode:
        print("Development mode uses fakes; unset DEVELOPMENT_MODE to test with real keys.")
        return 2
    problems = settings.startup_problems(os.environ)
    # Login is not part of this flow, so missing passwords only warn (the Space still needs them).
    login = [p for p in problems if "PASSWORD" in p]
    if blocking := [p for p in problems if p not in login]:
        print("Startup would stop:")
        for problem in blocking:
            print(f"  - {problem}")
        return 2
    for problem in login:
        print(f"WARNING, the app would not start yet: {problem}")
    print(f"Startup checks pass apart from login. Image backend {settings.config.image_backend}.")

    providers = build_providers(settings)
    limits = LimitService(settings.config.limits)
    library = load_library(settings).with_images(load_lock())
    service = GenerationService(settings, providers, limits, library)
    helpers = HelperService(settings, providers, limits, library)
    example = library.prompts()[0].text["en"]

    run = Run()
    run.sensitive += [NEW_IDEA, SWEDISH_IDEA, *REFUSED_IDEAS.values()]
    run.sensitive += [compose_prompt(idea) for idea in (NEW_IDEA, *REFUSED_IDEAS.values())]

    def create(idea: str, device: str):
        return service.create(CreateRequest(text=idea, lang="en", device_hash=device))

    print("\nCreate")
    await run.step("new image", create(NEW_IDEA, "d1"), "ok")
    await run.step("library example, unchanged", create(example, "d2"), "ok")
    for label, idea in REFUSED_IDEAS.items():
        await run.step(f"refused: {label}", create(idea, f"r-{label}"), "refused")

    print("\nHelpers")
    await run.step("help me (sv)", helpers.improve(SWEDISH_IDEA, "sv", "h1"), "ok")
    refused = REFUSED_IDEAS["real person"]
    await run.step("help me, refused idea", helpers.improve(refused, "en", "h2"), "refused")
    await run.step("surprise me (sv)", helpers.surprise("sv", "h3"), "ok")
    await run.step("surprise me (en)", helpers.surprise("en", "h4"), "ok")

    snapshot = limits.snapshot()
    print(f"\nCounters: {snapshot.images_used} images, ${snapshot.spend_usd:.3f} estimated")

    print("\nLogs")
    log_text = "\n".join(collector.lines)
    secrets = [
        os.environ[name]
        for name in ENV_FILE_KEYS - {"DEVELOPMENT_MODE"}
        if len(os.environ.get(name, "")) >= 8
    ]
    leaks = [t for t in run.sensitive if len(t) >= MIN_LENGTH_TO_SCAN and t in log_text]
    leaked_secrets = sum(value in log_text for value in secrets)
    print(f"{len(collector.lines)} log lines, {len(leaks)} texts and {leaked_secrets} keys leaked")
    for leak in leaks:
        print(f"  LEAK: {leak[:40]}")
    if not collector.lines:
        print("  No log lines were captured, so the scan proves nothing.")
    if run.unexpected:
        print(f"Unexpected outcomes: {', '.join(run.unexpected)}")
    ok = collector.lines and not leaks and not leaked_secrets and not run.unexpected
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
