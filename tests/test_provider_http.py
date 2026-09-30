import asyncio
import logging
import time

import httpx
import pytest

from src.errors import ProviderError, ProviderTimeoutError, RateLimitedError
from src.providers import http
from src.providers.http import post_json

URL = "https://provider.test/v1/thing"
HEADERS = {"Authorization": "Bearer sk-test-key"}


class Recorder:
    """Scripted MockTransport: one entry per request, each a Response or an Exception to raise."""

    def __init__(self, *script):
        self.script = list(script)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        step = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(step, Exception):
            raise step
        return step


def _ok(body=None):
    return httpx.Response(200, json=body if body is not None else {"ok": True})


async def _call(recorder, *, total_timeout=30.0, sleeps=None, **kwargs):
    slept = [] if sleeps is None else sleeps

    async def fake_sleep(seconds):
        slept.append(seconds)

    async with httpx.AsyncClient(transport=httpx.MockTransport(recorder)) as client:
        return await post_json(
            client,
            URL,
            headers=HEADERS,
            payload={"a": 1},
            total_timeout=total_timeout,
            what="test call",
            sleep=fake_sleep,
            rand=lambda: 0.0,
            **kwargs,
        )


async def test_success_returns_the_parsed_object_and_sends_auth_and_payload():
    recorder = Recorder(_ok({"hello": "world"}))
    assert await _call(recorder) == {"hello": "world"}
    request = recorder.requests[0]
    assert request.headers["authorization"] == "Bearer sk-test-key"
    assert request.content == b'{"a":1}'


async def test_a_server_error_is_retried_then_succeeds():
    recorder = Recorder(httpx.Response(503), _ok())
    sleeps: list[float] = []
    assert await _call(recorder, sleeps=sleeps) == {"ok": True}
    assert len(recorder.requests) == 2 and sleeps == [http.BACKOFF_BASE_SECONDS]


async def test_backoff_grows_and_stops_after_two_retries():
    recorder = Recorder(httpx.Response(502))
    sleeps: list[float] = []
    with pytest.raises(ProviderError):
        await _call(recorder, sleeps=sleeps)
    assert len(recorder.requests) == 1 + http.MAX_RETRIES
    assert sleeps == [0.5, 1.0]


async def test_rate_limit_is_retried_then_raised_as_busy():
    recorder = Recorder(httpx.Response(429))
    with pytest.raises(RateLimitedError):
        await _call(recorder)
    assert len(recorder.requests) == 3


async def test_retry_after_is_honoured_but_capped():
    sleeps: list[float] = []
    await _call(Recorder(httpx.Response(429, headers={"retry-after": "3"}), _ok()), sleeps=sleeps)
    assert sleeps == [3.0]
    sleeps.clear()
    await _call(Recorder(httpx.Response(429, headers={"retry-after": "600"}), _ok()), sleeps=sleeps)
    assert sleeps == [http.BACKOFF_CAP_SECONDS]


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
async def test_client_errors_are_not_retried(status):
    recorder = Recorder(httpx.Response(status))
    with pytest.raises(ProviderError):
        await _call(recorder)
    assert len(recorder.requests) == 1


async def test_timeouts_are_retried_then_raised_as_timeout():
    recorder = Recorder(httpx.ReadTimeout("slow"))
    with pytest.raises(ProviderTimeoutError):
        await _call(recorder)
    assert len(recorder.requests) == 3


async def test_network_errors_are_retried_then_raised_as_provider_error():
    recorder = Recorder(httpx.ConnectError("no route"))
    with pytest.raises(ProviderError):
        await _call(recorder)
    assert len(recorder.requests) == 3


async def test_the_total_budget_is_never_exceeded():
    recorder = Recorder(httpx.Response(503))
    with pytest.raises(ProviderError):
        await _call(recorder, total_timeout=0.3)  # the first backoff (0.5 s) would not fit
    assert len(recorder.requests) == 1
    with pytest.raises(ProviderTimeoutError):
        await _call(Recorder(_ok()), total_timeout=0)


async def test_the_total_budget_is_a_hard_cap_even_for_a_slow_reply():
    class Stalls(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            await asyncio.sleep(5)
            return httpx.Response(200, json={})

    started = time.monotonic()
    async with httpx.AsyncClient(transport=Stalls()) as client:
        with pytest.raises(ProviderTimeoutError):
            await post_json(
                client, URL, headers=HEADERS, payload={}, total_timeout=0.2, what="stalled call"
            )
    assert time.monotonic() - started < 1.5


async def test_other_httpx_errors_become_provider_errors_without_a_retry():
    recorder = Recorder(httpx.TooManyRedirects("loop"))
    with pytest.raises(ProviderError):
        await _call(recorder)
    assert len(recorder.requests) == 1


@pytest.mark.parametrize(
    "response",
    [httpx.Response(200, text="not json"), httpx.Response(200, json=["a", "list"])],
)
async def test_an_unusable_reply_is_a_provider_error(response):
    with pytest.raises(ProviderError):
        await _call(Recorder(response))


async def test_logs_and_errors_never_hold_bodies_or_keys(caplog):
    caplog.set_level(logging.DEBUG)
    recorder = Recorder(httpx.Response(503, text="SECRET-BODY-CONTENT"), _ok())
    await _call(recorder)
    with pytest.raises(ProviderError) as info:
        await _call(Recorder(httpx.Response(400, text="SECRET-BODY-CONTENT")))
    assert "SECRET-BODY-CONTENT" not in caplog.text + str(info.value)
    assert "sk-test-key" not in caplog.text + str(info.value)
