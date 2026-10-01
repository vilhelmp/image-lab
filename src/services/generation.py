"""Create and edit flows: validate, check, generate or edit, check the image (spec 8.1).

Both go through `paid_call`, so budget accounting is identical. Only AppError escapes. Log lines
hold no prompts, images or secrets.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

from pydantic import BaseModel, Field

from src.config import EditChip, Settings
from src.errors import (
    AppError,
    BudgetReachedError,
    CooldownError,
    EmptyInputError,
    PausedError,
    ProviderError,
    ProviderTimeoutError,
    RateLimitedError,
    SafetyRefusalError,
    TooLongInputError,
    error_code,
)
from src.providers.base import Aspect, EditRequest, ImageRequest
from src.providers.factory import Providers
from src.services.helpers import HelperService
from src.services.library import PromptLibrary
from src.services.limits import Kind, LimitService
from src.services.prompts import compose_prompt, style_fragment
from src.services.safety import SafetyService, validate_input
from src.services.spend import paid_call
from src.services.translate import Translator

logger = logging.getLogger(__name__)

CREATE_TIMEOUT_SECONDS = 45
EDIT_TIMEOUT_SECONDS = 60
LIBRARY_MODEL_KEY = "library"
INPUT_ERRORS = (EmptyInputError, TooLongInputError)
LIMIT_ERRORS = (PausedError, BudgetReachedError, CooldownError, RateLimitedError)


class CreateRequest(BaseModel):
    text: str = Field(repr=False)
    style: str | None = None
    aspect: Aspect = "square"
    lang: str = "sv"
    device_hash: str | None = None


class ChipRequest(BaseModel):
    chip_key: str
    image: bytes = Field(repr=False)  # the visitor's current image
    current_prompt: str = Field(repr=False)
    lang: str = "sv"
    device_hash: str | None = None


class GenerationResult(BaseModel):
    image: bytes = Field(repr=False)
    final_prompt: str = Field(repr=False)
    model_key: str
    seconds: float
    est_cost: float
    cached: bool = False  # a library example, not generated for this visitor


class GenerationService:
    """Only AppError escapes create() and edit()."""

    def __init__(
        self,
        settings: Settings,
        providers: Providers,
        limits: LimitService,
        library: PromptLibrary | None = None,
        helpers: HelperService | None = None,
    ) -> None:
        self._settings = settings
        self._providers = providers
        self._limits = limits
        self._library = library
        self._helpers = helpers
        self._safety = SafetyService(providers.moderator, providers.text, settings.config.safety)
        self._translator = Translator(providers.text, settings.config.safety.max_input_chars)

    def can_edit(self) -> bool:
        return self._providers.edit is not None and self._settings.active_edit_model() is not None

    async def _library_example(self, req: CreateRequest) -> GenerationResult | None:
        """The cached image for an unchanged library prompt with no style, else None."""
        if self._library is None or req.style:
            return None
        if len(req.text) > self._settings.config.safety.max_input_chars * 4:
            return None  # the normal path rejects it
        prompt = self._library.find(req.text)
        if prompt is None:
            return None
        try:
            image = await asyncio.to_thread(self._library.image_path(prompt).read_bytes)
        except OSError:
            logger.warning("prompt library: cannot read the image for '%s'", prompt.id)
            return None  # no cached image: fall back to a real generation
        logger.info(
            "generation model=%s outcome=cached device=%s",
            LIBRARY_MODEL_KEY,
            req.device_hash or "-",
        )
        return GenerationResult(
            image=image,
            final_prompt=compose_prompt(prompt.image_text()),
            model_key=LIBRARY_MODEL_KEY,
            seconds=0.0,
            est_cost=0.0,
            cached=True,
        )

    async def create(self, req: CreateRequest) -> GenerationResult:
        if example := await self._library_example(req):
            return example
        model_key = self._settings.models.defaults.create_model
        return await self._observed(
            model_key,
            req.device_hash,
            CREATE_TIMEOUT_SECONDS,
            lambda: self._create(req, model_key),
        )

    async def edit(self, req: ChipRequest) -> GenerationResult:
        """Apply a one-tap chip to the visitor's current image with the configured edit model."""
        chip = self._settings.config.edit_chips.get(req.chip_key)
        active = self._settings.active_edit_model()
        if chip is None or active is None or self._providers.edit is None:
            raise ProviderError  # an unknown chip or no edit model: the UI never offers this
        model_key, model = active
        return await self._observed(
            model_key,
            req.device_hash,
            EDIT_TIMEOUT_SECONDS,
            lambda: self._edit(req, chip, model_key, model.est_cost_usd),
        )

    async def _observed(
        self,
        model_key: str,
        device: str | None,
        timeout: float,
        run: Callable[[], Awaitable[GenerationResult]],
    ) -> GenerationResult:
        started = time.perf_counter()
        cost = 0.0
        outcome = "cancelled"
        kind: Kind | None = None
        try:
            async with asyncio.timeout(timeout):
                result = await run()
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
                device or "-",
            )

    async def _create(self, req: CreateRequest, model_key: str) -> GenerationResult:
        config = self._settings.config
        text = validate_input(req.text, config.safety.max_input_chars)
        model = self._settings.models.image_models[model_key]
        fragment = style_fragment(config.style_fragments, req.style)
        final_prompt = compose_prompt(text, fragment)

        async def prepare() -> None:
            nonlocal final_prompt
            if model.translate_to_english:
                final_prompt = compose_prompt(await self._translator.to_english(text), fragment)
            await self._safety.check_prompt(final_prompt, req.lang)

        result = await paid_call(
            self._limits,
            est_cost=model.est_cost_usd,
            device=req.device_hash,
            prepare=prepare,
            call=lambda: self._providers.image.generate(
                ImageRequest(prompt=final_prompt, model_key=model_key, aspect=req.aspect)
            ),
        )
        # The image exists and is paid for, even if the output check refuses it here.
        await self._safety.check_image(result.image)
        return GenerationResult(
            image=result.image,
            final_prompt=final_prompt,
            model_key=model_key,
            seconds=result.seconds,
            est_cost=result.est_cost,
        )

    async def _edit(
        self, req: ChipRequest, chip: EditChip, model_key: str, est_cost: float
    ) -> GenerationResult:
        edit_provider = self._providers.edit
        assert edit_provider is not None  # checked in edit()
        instruction = chip.instruction or ""

        async def prepare() -> None:
            nonlocal instruction
            if chip.llm:
                if self._helpers is None:
                    raise ProviderError
                # The LLM's wording is checked inside before it can reach the edit model.
                instruction = await self._helpers.edit_instruction(req.current_prompt, req.lang)

        result = await paid_call(
            self._limits,
            est_cost=est_cost,
            device=req.device_hash,
            prepare=prepare,
            call=lambda: edit_provider.edit(
                EditRequest(image=req.image, instruction=instruction, model_key=model_key)
            ),
        )
        await self._safety.check_image(result.image)
        return GenerationResult(
            image=result.image,
            final_prompt=instruction,
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
