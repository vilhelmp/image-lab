"""Create flow: validate, compose, moderate prompt, generate, moderate image (spec 8.1)."""

from __future__ import annotations

import asyncio
import logging
import time

from pydantic import BaseModel, Field

from src.config import Settings
from src.errors import (
    AppError,
    BudgetReachedError,
    CooldownError,
    EmptyInputError,
    PausedError,
    ProviderTimeoutError,
    RateLimitedError,
    SafetyRefusalError,
    TooLongInputError,
    error_code,
)
from src.providers.base import Aspect, ImageRequest
from src.providers.factory import Providers
from src.services.limits import Kind, LimitService
from src.services.prompts import compose_prompt, style_fragment
from src.services.safety import SafetyService, validate_input

logger = logging.getLogger(__name__)

CREATE_TIMEOUT_SECONDS = 45
INPUT_ERRORS = (EmptyInputError, TooLongInputError)
LIMIT_ERRORS = (PausedError, BudgetReachedError, CooldownError, RateLimitedError)


class CreateRequest(BaseModel):
    text: str = Field(repr=False)
    style: str | None = None
    aspect: Aspect = "square"
    lang: str = "sv"
    device_hash: str | None = None


class GenerationResult(BaseModel):
    image: bytes = Field(repr=False)
    final_prompt: str = Field(repr=False)
    model_key: str
    seconds: float
    est_cost: float


class GenerationService:
    """Only AppError escapes create(). Log lines hold no prompts, images or secrets."""

    def __init__(self, settings: Settings, providers: Providers, limits: LimitService) -> None:
        self._settings = settings
        self._providers = providers
        self._limits = limits
        self._safety = SafetyService(providers.moderator, providers.text, settings.config.safety)

    async def create(self, req: CreateRequest) -> GenerationResult:
        model_key = self._settings.models.defaults.create_model
        started = time.perf_counter()
        cost = 0.0
        outcome = "cancelled"
        kind: Kind | None = None
        try:
            async with asyncio.timeout(CREATE_TIMEOUT_SECONDS):
                result = await self._create(req, model_key)
            cost = result.est_cost
            outcome, kind = "ok", "ok"
            return result
        except TimeoutError as exc:
            outcome, kind = ProviderTimeoutError.code, "error"
            raise ProviderTimeoutError from exc
        except AppError as exc:
            outcome = error_code(exc)
            kind = _kind_of(exc)
            raise
        except Exception as exc:
            outcome, kind = AppError.code, "error"
            logger.error("Unexpected failure: %s.%s", type(exc).__module__, type(exc).__qualname__)
            raise AppError from exc
        finally:
            seconds = time.perf_counter() - started
            if kind:
                self._limits.record(kind, model_key, seconds)
            logger.info(
                "generation model=%s outcome=%s latency=%.2f cost=%.4f device=%s",
                model_key,
                outcome,
                seconds,
                cost,
                req.device_hash or "-",
            )

    async def _create(self, req: CreateRequest, model_key: str) -> GenerationResult:
        config = self._settings.config
        text = validate_input(req.text, config.safety.max_input_chars)
        est_cost = self._settings.models.image_models[model_key].est_cost_usd
        reservation = self._limits.reserve(count=1, est_cost=est_cost, device=req.device_hash)
        provider_called = False
        try:
            final_prompt = compose_prompt(text, style_fragment(config.style_fragments, req.style))

            await self._safety.check_prompt(final_prompt, req.lang)

            async with self._limits.slot():
                provider_called = True
                result = await self._providers.image.generate(
                    ImageRequest(prompt=final_prompt, model_key=model_key, aspect=req.aspect)
                )
        except asyncio.CancelledError:
            # A call cut short by the timeout or a closed tab may still be billed: keep the estimate
            if provider_called:
                self._limits.reconcile(reservation, est_cost)
            else:
                self._limits.release(reservation)
            raise
        except BaseException:
            self._limits.release(reservation)
            raise
        # The image exists and is paid for, even if the output check refuses it below.
        self._limits.reconcile(reservation, result.est_cost)

        await self._safety.check_image(result.image)

        return GenerationResult(
            image=result.image,
            final_prompt=final_prompt,
            model_key=model_key,
            seconds=result.seconds,
            est_cost=result.est_cost,
        )


def _kind_of(exc: AppError) -> Kind | None:
    """Admin-status category for a failed create. Bad input is not counted as a fault."""
    if isinstance(exc, INPUT_ERRORS):
        return None
    if isinstance(exc, LIMIT_ERRORS):
        return "limited"
    return "refusal" if isinstance(exc, SafetyRefusalError) else "error"
