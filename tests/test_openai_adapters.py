import json
import logging

import httpx
import pytest

from src.errors import MalformedReplyError, ProviderError, SafetyRefusalError
from src.providers import http
from src.providers.base import ModerationResult
from src.providers.factory import build_moderator, build_text
from src.providers.openai_moderation import OpenAIModerator, parse_result
from src.providers.openai_text import TASK_SCHEMAS, OpenAITextProvider, parse_completion
from src.services.safety import SafetyService

CLEAN = {
    "flagged": False,
    "categories": {"sexual": False, "violence": False, "hate": False},
}


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch):
    monkeypatch.setattr(http, "BACKOFF_BASE_SECONDS", 0)
    monkeypatch.setattr(http, "JITTER_SECONDS", 0)


def _moderation(**overrides):
    return {"id": "modr-1", "results": [{**CLEAN, **overrides}]}


def _transport(handler):
    return httpx.MockTransport(handler)


# --- moderation --------------------------------------------------------------------------------


async def test_moderator_sends_text_as_a_string_with_the_configured_model():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=_moderation())

    moderator = OpenAIModerator(
        "sk-x", model="omni-moderation-latest", transport=_transport(handler)
    )
    assert await moderator.moderate_text("a cat") == ModerationResult(flagged=False)
    request = seen[0]
    assert str(request.url) == "https://api.openai.com/v1/moderations"
    assert request.headers["authorization"] == "Bearer sk-x"
    assert json.loads(request.content) == {"model": "omni-moderation-latest", "input": "a cat"}


@pytest.mark.parametrize(
    ("image", "mime"),
    [
        (b"\x89PNG\r\n\x1a\n....", "image/png"),
        (b"\xff\xd8\xff\xe0....", "image/jpeg"),
        (b"RIFF\x00\x00\x00\x00WEBPVP8 ", "image/webp"),
    ],
)
async def test_moderator_sends_images_as_data_urls(image, mime):
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=_moderation())

    await OpenAIModerator("sk-x", transport=_transport(handler)).moderate_image(image)
    [item] = seen[0]["input"]
    assert item["type"] == "image_url"
    assert item["image_url"]["url"].startswith(f"data:{mime};base64,")


@pytest.mark.parametrize(
    ("category", "code"),
    [
        ("sexual", "sexual"),
        ("sexual/minors", "minors"),
        ("violence", "violence"),
        ("violence/graphic", "violence"),
        ("hate", "hate"),
        ("hate/threatening", "hate"),
        ("harassment", "harassment"),
        ("harassment/threatening", "harassment"),
        ("self-harm", "self_harm"),
        ("self-harm/intent", "self_harm"),
        ("self-harm/instructions", "self_harm"),
        ("illicit", "illicit"),
        ("illicit/violent", "illicit"),
    ],
)
def test_every_openai_category_maps_to_the_fixed_code_set(category, code):
    body = _moderation(flagged=True, categories={category: True})
    assert parse_result(body) == ModerationResult(flagged=True, code=code)


def test_the_most_serious_category_names_the_flag():
    body = _moderation(flagged=True, categories={"violence": True, "sexual/minors": True})
    assert parse_result(body).code == "minors"


def test_a_flag_in_an_unknown_category_is_still_a_flag():
    body = _moderation(flagged=True, categories={"brand-new-category": True})
    assert parse_result(body) == ModerationResult(flagged=True, code="other")


def test_a_true_category_counts_even_if_flagged_says_false():
    body = _moderation(flagged=False, categories={"violence": True})
    assert parse_result(body) == ModerationResult(flagged=True, code="violence")


def test_unknown_categories_that_are_not_set_do_not_matter():
    body = _moderation(categories={"brand-new-category": False, "sexual": False})
    assert parse_result(body).flagged is False


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"results": []},
        {"results": "nope"},
        {"results": [CLEAN, CLEAN]},
        {"results": [{"flagged": True}]},
        {"results": [{"flagged": "yes", "categories": {}}]},
        {"results": [{"flagged": False, "categories": []}]},
        {"results": [None]},
    ],
)
def test_empty_or_malformed_moderation_replies_raise(body):
    with pytest.raises(ProviderError):
        parse_result(body)


async def test_moderator_retries_a_busy_reply():
    replies = [httpx.Response(429), httpx.Response(200, json=_moderation())]
    moderator = OpenAIModerator("sk-x", transport=_transport(lambda request: replies.pop(0)))
    assert (await moderator.moderate_text("a cat")).flagged is False


async def test_moderator_logs_hold_no_text_and_no_key(caplog):
    caplog.set_level(logging.DEBUG)
    moderator = OpenAIModerator(
        "sk-secret-key", transport=_transport(lambda r: httpx.Response(200, json=_moderation()))
    )
    await moderator.moderate_text("purple-elephant-unique-phrase")
    assert "purple-elephant-unique-phrase" not in caplog.text
    assert "sk-secret-key" not in caplog.text
    assert "flagged=False" in caplog.text


# --- text --------------------------------------------------------------------------------------


def _completion(content, **choice):
    message = {"role": "assistant", "content": content, "refusal": None}
    return {"choices": [{"index": 0, "finish_reason": "stop", "message": message, **choice}]}


async def test_text_provider_asks_for_strict_json_with_the_configured_model():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=_completion('{"prompt": "a whale"}'))

    provider = OpenAITextProvider("sk-x", model="gpt-6-luna", transport=_transport(handler))
    assert await provider.complete_json("surprise", "SYSTEM", "USER", 80) == {"prompt": "a whale"}
    assert str(seen[0].url) == "https://api.openai.com/v1/chat/completions"
    payload = json.loads(seen[0].content)
    assert payload["model"] == "gpt-6-luna"
    assert payload["messages"] == [
        {"role": "system", "content": "SYSTEM"},
        {"role": "user", "content": "USER"},
    ]
    assert payload["max_completion_tokens"] == 80
    assert payload["reasoning_effort"] == "none"
    assert payload["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "surprise", "strict": True, "schema": TASK_SCHEMAS["surprise"]},
    }


async def test_reasoning_effort_can_be_left_out_for_other_endpoints():
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=_completion('{"prompt": "x"}'))

    provider = OpenAITextProvider(
        "sk-x", model="m", reasoning_effort=None, transport=_transport(handler)
    )
    await provider.complete_json("improve", "s", "u")
    assert "reasoning_effort" not in seen[0]


def _strict_ok(schema):
    if schema.get("type") == "object":
        props = schema["properties"]
        assert schema["required"] == list(props) and schema["additionalProperties"] is False
        for sub in props.values():
            _strict_ok(sub)


@pytest.mark.parametrize("task", sorted(TASK_SCHEMAS))
def test_every_task_schema_fits_strict_structured_outputs(task):
    _strict_ok(TASK_SCHEMAS[task])


def test_the_policy_schema_matches_what_the_safety_service_reads():
    props = TASK_SCHEMAS["policy_check"]["properties"]
    assert set(props) == {"allowed", "category", "rewrite"}
    assert None in props["category"]["enum"] and "real_person" in props["category"]["enum"]


async def test_an_unknown_task_never_reaches_the_network():
    def handler(request):
        raise AssertionError("no request expected")

    with pytest.raises(ProviderError):
        await OpenAITextProvider("k", model="m", transport=_transport(handler)).complete_json(
            "made_up", "s", "u"
        )


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"choices": []},
        {"choices": [None]},
        _completion("not json"),
        _completion('["a", "list"]'),
        _completion(None),
        _completion('{"prompt": "cut off"}', finish_reason="length"),
        {"choices": [{"finish_reason": "stop", "message": {"content": None, "refusal": "No."}}]},
        {
            "choices": [
                {"finish_reason": "stop", "message": {"content": "{}", "refusal": "I cannot."}}
            ]
        },
    ],
)
def test_unusable_completions_raise(body):
    with pytest.raises(ProviderError):
        parse_completion(body)


def test_a_good_completion_parses():
    assert parse_completion(_completion('{"allowed": true}')) == {"allowed": True}


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"choices": []},
        _completion("not json"),
        _completion('["a", "list"]'),
        _completion(None),
        _completion('{"prompt": "cut off"}', finish_reason="length"),
    ],
)
def test_unusable_json_is_a_malformed_reply_that_may_be_retried(body):
    with pytest.raises(MalformedReplyError):
        parse_completion(body)


@pytest.mark.parametrize(
    "body",
    [
        _completion('{"prompt": "x"}', finish_reason="content_filter"),
        _completion('{"prompt": "x"}', finish_reason=None),
        {"choices": [{"finish_reason": "stop", "message": {"content": None, "refusal": "No."}}]},
    ],
)
def test_refusals_and_filtered_replies_are_plain_provider_errors(body):
    with pytest.raises(ProviderError) as info:
        parse_completion(body)
    assert not isinstance(info.value, MalformedReplyError)


# --- wiring ------------------------------------------------------------------------------------


def test_the_factory_builds_the_configured_adapters(dev_settings):
    moderator = build_moderator(dev_settings, {"OPENAI_API_KEY": "k"})
    text = build_text(dev_settings, {"OPENAI_API_KEY": "k"})
    assert isinstance(moderator, OpenAIModerator) and isinstance(text, OpenAITextProvider)
    assert text._model == dev_settings.models.text_models["helper"].api_model == "gpt-6-luna"
    assert moderator._model == "omni-moderation-latest"


async def test_the_safety_service_works_end_to_end_over_the_adapters(dev_settings):
    """A person's name is refused with a suggestion; a clean idea passes; wire formats line up."""
    policy_users = []

    def handler(request):
        if request.url.path.endswith("/moderations"):
            return httpx.Response(200, json=_moderation())
        body = json.loads(request.content)
        user = json.loads(body["messages"][1]["content"])
        policy_users.append(user)
        if "Emma" in user["text"]:
            verdict = {"allowed": False, "category": "real_person", "rewrite": "a friendly girl"}
        else:
            verdict = {"allowed": True, "category": None, "rewrite": None}
        return httpx.Response(200, json=_completion(json.dumps(verdict)))

    service = SafetyService(
        OpenAIModerator("k", transport=_transport(handler)),
        OpenAITextProvider("k", model="m", transport=_transport(handler)),
        dev_settings.config.safety,
    )
    await service.check_prompt("En katt på taket", "sv")
    with pytest.raises(SafetyRefusalError) as info:
        await service.check_prompt("Min klasskamrat Emma", "sv")
    assert info.value.code == "real_person" and info.value.rewrite == "a friendly girl"
    assert policy_users[0] == {"language": "sv", "text": "En katt på taket"}
