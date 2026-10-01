import pytest

from src.errors import ProviderError, SafetyRefusalError
from src.providers.factory import Providers
from src.providers.fake import FakeTextProvider
from src.services.generation import CreateRequest, GenerationService
from src.services.limits import LimitService
from src.services.translate import Translator

SECRET = "en räv i skogen"


def _service(settings, providers: Providers) -> GenerationService:
    return GenerationService(settings, providers, LimitService(settings.config.limits))


def _providers(base: Providers, text: FakeTextProvider) -> Providers:
    return Providers(image=base.image, edit=None, text=text, moderator=base.moderator)


class FailingText(FakeTextProvider):
    async def complete_json(self, task, system, user, max_tokens=200):
        if task == "translate":
            raise ProviderError
        return await super().complete_json(task, system, user, max_tokens)


async def test_the_image_model_gets_the_english_text_with_the_style(dev_settings, fake_providers):
    text = FakeTextProvider({"translate": {"text": "a fox in the forest."}})
    providers = _providers(fake_providers, text)
    result = await _service(dev_settings, providers).create(
        CreateRequest(text=SECRET, style="retro")
    )
    assert result.final_prompt.startswith("a fox in the forest, retro 1970s poster")
    assert SECRET not in result.final_prompt
    assert providers.image.calls[0].prompt == result.final_prompt


async def test_the_translated_prompt_is_the_one_that_is_checked(dev_settings, fake_providers):
    text = FakeTextProvider({"translate": {"text": "a [blocked] fox"}})
    providers = _providers(fake_providers, text)
    with pytest.raises(SafetyRefusalError):
        await _service(dev_settings, providers).create(CreateRequest(text=SECRET))
    assert providers.image.calls == []


async def test_a_failed_translation_falls_back_to_the_original_text(dev_settings, fake_providers):
    providers = _providers(fake_providers, FailingText())
    result = await _service(dev_settings, providers).create(CreateRequest(text=SECRET))
    assert result.final_prompt == SECRET


async def test_a_failed_translation_still_goes_through_the_checks(dev_settings, fake_providers):
    providers = _providers(fake_providers, FailingText())
    with pytest.raises(SafetyRefusalError):
        await _service(dev_settings, providers).create(CreateRequest(text="a [blocked] räv"))
    assert providers.image.calls == []


async def test_a_model_without_translation_gets_the_original_text(make_settings, fake_providers):
    def models(data):
        data["image_models"]["fast"]["translate_to_english"] = False

    settings = make_settings(models=models)
    result = await _service(settings, fake_providers).create(CreateRequest(text=SECRET))
    assert result.final_prompt == SECRET
    assert "translate" not in fake_providers.text.calls


@pytest.mark.parametrize("reply", [{}, {"text": ""}, {"text": 5}, {"text": "x" * 5000}])
async def test_an_unusable_translation_is_ignored(reply):
    translator = Translator(FakeTextProvider({"translate": reply}), max_chars=200)
    assert await translator.to_english(SECRET) == SECRET


async def test_the_translator_sends_the_text_as_data():
    text = FakeTextProvider()
    assert await Translator(text, max_chars=200).to_english(SECRET) == SECRET
    assert text.calls == ["translate"]
