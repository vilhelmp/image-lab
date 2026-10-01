"""The Hugging Face image adapter, against a stand-in client (no network, no token)."""

import asyncio
import io
import logging
import time

import httpx
import pytest
from huggingface_hub.errors import HfHubHTTPError, InferenceTimeoutError
from PIL import Image

from src.errors import (
    AppError,
    BudgetReachedError,
    ProviderError,
    ProviderTimeoutError,
    RateLimitedError,
)
from src.providers.base import ImageRequest
from src.providers.factory import build_image, build_providers
from src.providers.hf_inference import SIZES, HFEditProvider, HFImageProvider

SECRET_PROMPT = "a very private prompt about my neighbour"


def http_error(status: int, headers: dict[str, str] | None = None) -> HfHubHTTPError:
    request = httpx.Request("POST", "https://router.huggingface.co/x")
    response = httpx.Response(
        status, headers=headers, content=SECRET_PROMPT.encode(), request=request
    )
    return HfHubHTTPError(f"boom {SECRET_PROMPT}", response=response)


class StandInClient:
    """Plays back a script: an exception is raised, an image is returned."""

    def __init__(self, *script: object) -> None:
        self.script = list(script)
        self.calls: list[dict] = []

    def text_to_image(self, prompt: str, **kwargs):
        self.calls.append({"prompt": prompt, **kwargs})
        step = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(step, BaseException):
            raise step
        return step


async def no_sleep(_: float) -> None:
    return None


def picture(mode: str = "RGB") -> Image.Image:
    return Image.new(mode, (8, 8), (200, 30, 30) if mode == "RGB" else (200, 30, 30, 128))


def make(settings, client, **kwargs) -> HFImageProvider:
    return HFImageProvider("hf_token", settings, client=client, sleep=no_sleep, **kwargs)


def request(model_key: str = "fast", aspect="square") -> ImageRequest:
    return ImageRequest(prompt=SECRET_PROMPT, model_key=model_key, aspect=aspect)


async def test_generate_returns_png_bytes_and_the_configured_cost(dev_settings):
    client = StandInClient(picture())
    result = await make(dev_settings, client).generate(request())
    assert Image.open(io.BytesIO(result.image)).format == "PNG"
    model = dev_settings.models.image_models["fast"]
    assert result.est_cost == model.est_cost_usd and result.model_key == "fast"
    assert result.seconds >= 0


async def test_the_model_provider_and_size_come_from_config(dev_settings):
    client = StandInClient(picture())
    await make(dev_settings, client).generate(request("fast", "landscape"))
    call = client.calls[0]
    model = dev_settings.models.image_models["fast"]
    assert call["model"] == model.hf_model
    assert (call["width"], call["height"]) == SIZES["landscape"]
    assert call["extra_body"] == {"enable_safety_checker": True}


async def test_the_fal_safety_checker_is_only_sent_to_fal(dev_settings):
    dev_settings.models.image_models["fast"].hf_provider = "together"
    client = StandInClient(picture())
    await make(dev_settings, client).generate(request())
    assert client.calls[0]["extra_body"] is None


async def test_an_image_with_alpha_is_flattened_to_rgb_png(dev_settings):
    result = await make(dev_settings, StandInClient(picture("RGBA"))).generate(request())
    assert Image.open(io.BytesIO(result.image)).mode == "RGB"


async def test_a_model_without_hf_model_is_a_provider_error(dev_settings):
    dev_settings.models.image_models["fast"].hf_model = None
    with pytest.raises(ProviderError):
        await make(dev_settings, StandInClient(picture())).generate(request())


@pytest.mark.parametrize("status", [429, 503])
async def test_a_request_the_provider_did_not_start_is_retried(dev_settings, status):
    client = StandInClient(http_error(status), picture())
    result = await make(dev_settings, client).generate(request())
    assert result.image and len(client.calls) == 2


async def test_rate_limits_that_never_clear_end_as_rate_limited(dev_settings):
    client = StandInClient(http_error(429))
    with pytest.raises(RateLimitedError):
        await make(dev_settings, client).generate(request())
    assert len(client.calls) == 3  # one try and two retries


@pytest.mark.parametrize("status", [500, 502, 504])
async def test_server_errors_may_already_be_billed_so_are_not_retried(dev_settings, status):
    client = StandInClient(http_error(status), picture())
    with pytest.raises(ProviderError):
        await make(dev_settings, client).generate(request())
    assert len(client.calls) == 1


async def test_used_up_credit_is_the_budget_error_and_is_not_retried(dev_settings):
    client = StandInClient(http_error(402), picture())
    with pytest.raises(BudgetReachedError):
        await make(dev_settings, client).generate(request())
    assert len(client.calls) == 1


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
async def test_client_errors_are_provider_errors_without_retry(dev_settings, status):
    client = StandInClient(http_error(status), picture())
    with pytest.raises(ProviderError) as info:
        await make(dev_settings, client).generate(request())
    assert not isinstance(info.value, (BudgetReachedError, RateLimitedError))
    assert len(client.calls) == 1


@pytest.mark.parametrize(
    "failure", [InferenceTimeoutError("slow"), httpx.ReadTimeout("slow"), TimeoutError()]
)
async def test_timeouts_are_typed_and_never_retried(dev_settings, failure):
    client = StandInClient(failure, picture())
    with pytest.raises(ProviderTimeoutError):
        await make(dev_settings, client).generate(request())
    assert len(client.calls) == 1


async def test_a_call_that_hangs_hits_the_hard_timeout(dev_settings):
    class Hanging:
        def text_to_image(self, *args, **kwargs):
            time.sleep(0.5)

    with pytest.raises(ProviderTimeoutError):
        await make(dev_settings, Hanging(), timeout=0.05).generate(request())


async def test_a_blocking_download_does_not_freeze_the_event_loop(dev_settings):
    class Blocking:
        def text_to_image(self, *args, **kwargs):
            time.sleep(0.3)
            return picture()

    ticks = 0

    async def heartbeat():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.02)
            ticks += 1

    beat = asyncio.create_task(heartbeat())
    await make(dev_settings, Blocking()).generate(request())
    beat.cancel()
    assert ticks >= 5


async def test_a_cancelled_call_stops_waiting_at_once(dev_settings):
    class Blocking:
        def text_to_image(self, *args, **kwargs):
            time.sleep(0.3)

    task = asyncio.create_task(make(dev_settings, Blocking()).generate(request()))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.parametrize("failure", [ConnectionError("x"), RuntimeError("x"), ValueError("x")])
async def test_other_failures_are_plain_provider_errors(dev_settings, failure):
    client = StandInClient(failure, picture())
    with pytest.raises(ProviderError):
        await make(dev_settings, client).generate(request())
    assert len(client.calls) == 1


async def test_an_unusable_image_is_a_provider_error(dev_settings):
    with pytest.raises(ProviderError):
        await make(dev_settings, StandInClient(object())).generate(request())


async def test_cancellation_is_not_swallowed(dev_settings):
    class Cancelling:
        def text_to_image(self, *args, **kwargs):
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await make(dev_settings, Cancelling()).generate(request())


async def test_no_prompt_or_error_text_reaches_the_logs_or_the_exception(dev_settings, caplog):
    caplog.set_level(logging.DEBUG)
    for failure in (http_error(500), http_error(429), http_error(402), InferenceTimeoutError("x")):
        with pytest.raises(AppError) as info:
            await make(dev_settings, StandInClient(failure)).generate(request())
        assert SECRET_PROMPT not in str(info.value)
    with pytest.raises(AppError):
        await make(dev_settings, StandInClient(object())).generate(request())
    assert SECRET_PROMPT not in caplog.text and "neighbour" not in caplog.text
    assert "hf_token" not in caplog.text


# --- wiring ------------------------------------------------------------------------------------


def test_the_factory_builds_the_hf_image_provider_for_the_hf_backend(dev_settings):
    assert dev_settings.config.image_backend == "hf"
    provider = build_image(dev_settings, {"HF_TOKEN": "hf_x"})
    assert isinstance(provider, HFImageProvider)


def test_build_providers_wires_real_adapters_outside_development(make_settings):
    def real(app):
        app["app"]["development_mode"] = False

    settings = make_settings(app=real)
    providers = build_providers(settings, {"HF_TOKEN": "hf_x", "OPENAI_API_KEY": "sk-x"})
    assert isinstance(providers.image, HFImageProvider)
    assert isinstance(providers.edit, HFEditProvider)
