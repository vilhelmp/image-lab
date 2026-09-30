"""Run tests/safety_cases.yaml against the real moderation and policy services.

    uv run python scripts/run_safety_cases.py

Needs the real secrets in the environment (OPENAI_API_KEY and the image backend's key), so run it
locally before the workshop, never in CI. It prints one line per case and exits 1 on any failure.
It only calls the prompt check (moderation API plus policy LLM); it generates no images.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import yaml

from src.config import load_settings
from src.errors import CheckFailedError, SafetyRefusalError
from src.providers.factory import build_providers
from src.services.safety import SafetyService

CASES_FILE = Path(__file__).resolve().parent.parent / "tests" / "safety_cases.yaml"
CONCURRENCY = 4


async def run_case(service: SafetyService, case: dict) -> tuple[bool, str]:
    """(passed, what happened). The outcome is described in codes only."""
    try:
        await service.check_prompt(case["prompt"], case["lang"])
    except SafetyRefusalError as refusal:
        outcome = "redirect" if refusal.rewrite else "block"
        return outcome == case["expect"], f"{outcome} ({refusal.code})"
    except CheckFailedError:
        return False, "check failed (fail closed)"
    return case["expect"] == "allow", "allow"


async def main() -> int:
    settings = load_settings()
    if settings.development_mode:
        print("Development mode uses fakes; unset DEVELOPMENT_MODE to test the real services.")
        return 2
    providers = build_providers(settings)
    service = SafetyService(providers.moderator, providers.text, settings.config.safety)
    cases = yaml.safe_load(CASES_FILE.read_text(encoding="utf-8"))["cases"]

    gate = asyncio.Semaphore(CONCURRENCY)

    async def guarded(case: dict) -> tuple[bool, str]:
        async with gate:
            return await run_case(service, case)

    results = await asyncio.gather(*(guarded(case) for case in cases))
    failures = 0
    for case, (passed, actual) in zip(cases, results, strict=True):
        failures += not passed
        mark = "PASS" if passed else "FAIL"
        print(f"{mark}  {case['id']:<28} want {case['expect']:<8} got {actual}")
    print(f"\n{len(cases) - failures}/{len(cases)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
