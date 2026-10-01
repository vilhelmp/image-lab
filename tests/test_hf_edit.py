"""The Hugging Face edit adapter, against a stand-in client (no network, no token)."""

import io
import logging

import httpx
import pytest
from huggingface_hub.errors import HfHubHTTPError
from PIL import Image

from src.errors import BudgetReachedError, ProviderError, ProviderTimeoutError, RateLimitedError
from src.providers.base import EditRequest
from src.providers.factory import build_edit, build_providers
from src.providers.hf_inference import HFEditProvider

INSTRUCTION = "make it an evening scene for my private neighbour"


def png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), (10, 20, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


def http_error(status: int) -> HfHubHTTPError:
    request = httpx.Request("POST", "https://router.huggingface.co/x")
    response = httpx.Response(status, content=INSTRUCTION.encode(), request=request)
    return HfHubHTTPError(f"boom {INSTRUCTION}", response=response)


class StandInClient:
    def __init__(self, *script) -> None:
        self.script = list(script)
        self.calls: list[tuple] = []

    def image_to_image(self, image, prompt=None, **kwargs):
        self.calls.append((image, prompt, kwargs))
        step = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(step, BaseException):
            raise step
        return step


async def no_sleep(_: float) -> None:
    return None


@pytest.fixture
def edit_settings(make_settings):
    return make_settings()  # default_edit is klein-4B on fal-ai


@pytest.fixture
def no_hf_edit_model(make_settings):
    def strip(models):
        del models["edit_models"]["default_edit"]["hf_model"]

    return make_settings(models=strip)


def make(settings, client) -> HFEditProvider:
    return HFEditProvider("hf_token", settings, client=client, sleep=no_sleep)


def request() -> EditRequest:
    return EditRequest(image=png(), instruction=INSTRUCTION, model_key="default_edit")


async def test_edit_sends_the_image_and_instruction_and_returns_png(edit_settings):
    client = StandInClient(Image.new("RGBA", (8, 8), (200, 0, 0, 128)))
    result = await make(edit_settings, client).edit(request())
    image, prompt, kwargs = client.calls[0]
    assert image == request().image and prompt == INSTRUCTION
    assert kwargs["model"] == "black-forest-labs/FLUX.2-klein-4B"
    assert kwargs["extra_body"] == {"enable_safety_checker": True}
    assert Image.open(io.BytesIO(result.image)).format == "PNG"
    assert result.est_cost == edit_settings.models.edit_models["default_edit"].est_cost_usd


async def test_a_model_without_hf_model_is_a_provider_error(no_hf_edit_model):
    with pytest.raises(ProviderError):
        await make(no_hf_edit_model, StandInClient(Image.new("RGB", (8, 8)))).edit(request())


async def test_rate_limits_are_retried_and_credit_exhaustion_is_the_budget_error(edit_settings):
    client = StandInClient(http_error(429), Image.new("RGB", (8, 8)))
    assert (await make(edit_settings, client).edit(request())).image
    assert len(client.calls) == 2
    with pytest.raises(BudgetReachedError):
        await make(edit_settings, StandInClient(http_error(402))).edit(request())
    with pytest.raises(RateLimitedError):
        await make(edit_settings, StandInClient(http_error(429))).edit(request())


async def test_server_errors_and_timeouts_are_not_retried(edit_settings):
    for failure, error in (
        (http_error(500), ProviderError),
        (TimeoutError(), ProviderTimeoutError),
    ):
        client = StandInClient(failure, Image.new("RGB", (8, 8)))
        with pytest.raises(error):
            await make(edit_settings, client).edit(request())
        assert len(client.calls) == 1


async def test_the_instruction_is_never_logged(edit_settings, caplog):
    caplog.set_level(logging.DEBUG)
    for failure in (http_error(500), http_error(402), http_error(429)):
        with pytest.raises(Exception):  # noqa: B017 - any typed error
            await make(edit_settings, StandInClient(failure)).edit(request())
    assert "neighbour" not in caplog.text and "hf_token" not in caplog.text


def test_no_edit_provider_without_an_available_edit_model(no_hf_edit_model):
    assert build_edit(no_hf_edit_model, {"HF_TOKEN": "hf_x"}) is None


def test_the_factory_builds_the_edit_provider_when_a_model_is_configured(edit_settings):
    assert isinstance(build_edit(edit_settings, {"HF_TOKEN": "hf_x"}), HFEditProvider)

    providers = build_providers(edit_settings, {"HF_TOKEN": "hf_x", "OPENAI_API_KEY": "sk-x"})
    assert isinstance(providers.edit, HFEditProvider)
