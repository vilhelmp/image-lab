"""Create flow: validate, compose, moderate prompt, generate, moderate image (spec 8.1)."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable

from pydantic import BaseModel, Field

from src.config import Settings
from src.errors import (
    AppError,
    CheckFailedError,
    ProviderTimeoutError,
    SafetyRefusalError,
    error_code,
)
from src.providers.base import Aspect, ImageRequest, ModerationResult
from src.providers.factory import Providers
from src.services.prompts import compose_prompt, style_fragment
from src.services.safety import validate_input

logger = logging.getLogger(__name__)

CREATE_TIMEOUT_SECONDS = 45


class CreateRequest(BaseModel):
    text: str = Field(repr=False)
    style: str | None = None
    aspect: Aspect = "square"
    device_hash: str | None = None


class GenerationResult(BaseModel):
    image: bytes = Field(repr=False)
    final_prompt: str = Field(repr=False)
    model_key: str
    seconds: float
    est_cost: float


class GenerationService:
    """Only AppError escapes create(). Log lines hold no prompts, images or secrets."""

    def __init__(self, settings: Settings, providers: Providers) -> None:
        self._settings = settings
        self._providers = providers

    async def create(self, req: CreateRequest) -> GenerationResult:
        model_key = self._settings.models.defaults.create_model
        started = time.perf_counter()
        cost = 0.0
        outcome = "ok"
        try:
            async with asyncio.timeout(CREATE_TIMEOUT_SECONDS):
                result = await self._create(req, model_key)
            cost = result.est_cost
            return result
        except TimeoutError as exc:
            outcome = ProviderTimeoutError.code
            raise ProviderTimeoutError from exc
        except AppError as exc:
            outcome = error_code(exc)
            raise
        except Exception as exc:
            outcome = AppError.code
            logger.error("Unexpected failure: %s.%s", type(exc).__module__, type(exc).__qualname__)
            raise AppError from exc
        finally:
            logger.info(
                "generation model=%s outcome=%s latency=%.2f cost=%.4f device=%s",
                model_key,
                outcome,
                time.perf_counter() - started,
                cost,
                req.device_hash or "-",
            )

    async def _create(self, req: CreateRequest, model_key: str) -> GenerationResult:
        config = self._settings.config
        text = validate_input(req.text, config.safety.max_input_chars)
        final_prompt = compose_prompt(text, style_fragment(config.style_fragments, req.style))

        await self._require_clean(self._providers.moderator.moderate_text(final_prompt))

        result = await self._providers.image.generate(
            ImageRequest(prompt=final_prompt, model_key=model_key, aspect=req.aspect)
        )

        await self._require_clean(self._providers.moderator.moderate_image(result.image))

        return GenerationResult(
            image=result.image,
            final_prompt=final_prompt,
            model_key=model_key,
            seconds=result.seconds,
            est_cost=result.est_cost,
        )

    async def _require_clean(self, check: Awaitable[ModerationResult]) -> None:
        """Raise unless the check ran and passed. A failed check counts as a refusal."""
        try:
            verdict = await check
            if not isinstance(verdict, ModerationResult):
                raise TypeError("moderator returned no verdict")
        except Exception as exc:
            logger.error("Safety check failed: %s.%s", type(exc).__module__, type(exc).__qualname__)
            raise CheckFailedError from exc
        if verdict.flagged:
            raise SafetyRefusalError(code=verdict.code or "flagged")
