import io

import pytest
from PIL import Image

from src.errors import (
    BadImageError,
    CheckFailedError,
    ConsentRequiredError,
    FeatureOffError,
    ProviderError,
    SafetyRefusalError,
)
from src.providers.factory import Providers
from src.providers.fake import FakeModerator
from src.services import photo
from src.services.flags import RuntimeFlags
from src.services.generation import GenerationService, PhotoRequest
from src.services.limits import LimitService
from src.services.photo import prepare_photo, read_upload


def jpeg(size=(1600, 1200), orientation: int | None = None) -> bytes:
    image = Image.new("RGB", size, (200, 120, 60))
    buffer = io.BytesIO()
    exif = Image.Exif()
    if orientation:
        exif[0x0112] = orientation
    image.save(buffer, format="JPEG", exif=exif)
    return buffer.getvalue()


def _service(settings, providers: Providers, *, open_studio: bool = True):
    limits = LimitService(settings.config.limits)
    flags = RuntimeFlags(photo_studio=open_studio)
    return GenerationService(settings, providers, limits, flags=flags), limits


def request(style="clay", raw: bytes | None = None, consent=True) -> PhotoRequest:
    return PhotoRequest(
        style_key=style, photo=raw or jpeg(), consent=consent, lang="sv", device_hash="d1"
    )


# --- prepare_photo --------------------------------------------------------------------------------


def test_a_large_photo_is_shrunk_to_a_png():
    result = Image.open(io.BytesIO(prepare_photo(jpeg((3000, 2000)))))
    assert result.format == "PNG" and max(result.size) == photo.MAX_SIDE


def test_a_small_photo_keeps_its_size():
    assert Image.open(io.BytesIO(prepare_photo(jpeg((400, 300))))).size == (400, 300)


def test_a_phone_photo_of_48_megapixels_is_accepted():
    result = Image.open(io.BytesIO(prepare_photo(jpeg((8000, 6000), orientation=6))))
    assert max(result.size) <= photo.MAX_SIDE and result.size[0] < result.size[1]  # turned upright


def test_a_huge_png_is_refused_because_it_cannot_be_decoded_cheaply():
    buffer = io.BytesIO()
    Image.new("L", (6000, 5000)).save(buffer, format="PNG")  # 30 MP, tiny file
    with pytest.raises(BadImageError):
        prepare_photo(buffer.getvalue())


def test_a_panorama_jpeg_is_refused_even_when_it_decodes_reduced():
    with pytest.raises(BadImageError):
        prepare_photo(jpeg((30000, 3000)))  # 90 MP, short side too small to reduce


def test_a_refused_photo_is_logged_by_reason_only(caplog, tmp_path):
    secret_name = tmp_path / "my-face-secret.jpg"
    secret_name.write_bytes(b"not a picture")
    with caplog.at_level("WARNING"), pytest.raises(BadImageError):
        prepare_photo(secret_name.read_bytes())
    assert "reason=decode_UnidentifiedImageError" in caplog.text
    assert "secret" not in caplog.text and "not a picture" not in caplog.text


def test_an_ipad_portrait_photo_is_turned_upright_and_loses_its_metadata():
    prepared = Image.open(io.BytesIO(prepare_photo(jpeg((200, 100), orientation=6))))
    assert prepared.size == (100, 200)
    assert not prepared.getexif()


@pytest.mark.parametrize("raw", [b"", b"not an image", b"\x89PNG\r\n\x1a\n" + b"x" * 50])
def test_something_that_is_not_an_image_is_refused(raw):
    with pytest.raises(BadImageError):
        prepare_photo(raw)


def test_an_oversized_upload_is_refused(monkeypatch):
    monkeypatch.setattr(photo, "MAX_UPLOAD_BYTES", 100)
    with pytest.raises(BadImageError):
        prepare_photo(jpeg())


def test_an_absurd_pixel_count_is_refused_before_decoding(monkeypatch):
    monkeypatch.setattr(photo, "MAX_PIXELS", 1000)
    with pytest.raises(BadImageError):
        prepare_photo(jpeg((100, 100)))


def test_read_upload_reads_a_file_and_refuses_a_missing_or_big_one(tmp_path, monkeypatch):
    path = tmp_path / "p.jpg"
    path.write_bytes(jpeg((50, 50)))
    assert read_upload(str(path)) == path.read_bytes()
    with pytest.raises(BadImageError):
        read_upload(str(tmp_path / "missing.jpg"))
    monkeypatch.setattr(photo, "MAX_UPLOAD_BYTES", 10)
    with pytest.raises(BadImageError):
        read_upload(str(path))


# --- the photo flow in the service ----------------------------------------------------------------


async def test_a_photo_is_checked_restyled_and_checked_again(dev_settings, fake_providers):
    service, limits = _service(dev_settings, fake_providers)
    result = await service.photo(request("clay", jpeg((3000, 2000))))
    call = fake_providers.edit.calls[0]
    assert call.instruction == dev_settings.config.photo_styles["clay"].instruction
    assert max(Image.open(io.BytesIO(call.image)).size) == photo.MAX_SIDE  # shrunk before sending
    assert fake_providers.moderator.image_calls == 2  # the photo in, the picture out
    assert result.model_key == "default_edit"
    assert limits.snapshot().images_used == 1


async def test_the_studio_is_off_until_an_admin_opens_it(dev_settings, fake_providers):
    service, limits = _service(dev_settings, fake_providers, open_studio=False)
    with pytest.raises(FeatureOffError):
        await service.photo(request())
    assert fake_providers.edit.calls == [] and limits.snapshot().images_used == 0


async def test_without_the_tick_nothing_is_sent(dev_settings, fake_providers):
    service, _ = _service(dev_settings, fake_providers)
    with pytest.raises(ConsentRequiredError):
        await service.photo(request(consent=False))
    assert fake_providers.edit.calls == [] and fake_providers.moderator.image_calls == 0


async def test_a_flagged_photo_never_leaves_the_app(dev_settings, fake_providers):
    providers = Providers(
        image=fake_providers.image,
        edit=fake_providers.edit,
        text=fake_providers.text,
        moderator=FakeModerator(flag_images=True),
    )
    service, limits = _service(dev_settings, providers)
    with pytest.raises(SafetyRefusalError):
        await service.photo(request())
    assert providers.edit.calls == []
    assert limits.snapshot().images_used == 0  # the reservation was released


async def test_a_flagged_result_is_not_returned(dev_settings, fake_providers):
    class FlagsTheSecondImage(FakeModerator):
        async def moderate_image(self, image):
            self.flag_images = self.image_calls >= 1  # the photo passes, the result is flagged
            return await super().moderate_image(image)

    providers = Providers(
        image=fake_providers.image,
        edit=fake_providers.edit,
        text=fake_providers.text,
        moderator=FlagsTheSecondImage(),
    )
    service, limits = _service(dev_settings, providers)
    with pytest.raises(SafetyRefusalError):
        await service.photo(request())
    assert len(providers.edit.calls) == 1  # it was sent, so its estimate stays counted
    assert limits.snapshot().images_used == 1


def test_consent_must_be_a_real_boolean():
    with pytest.raises(ValueError):
        PhotoRequest(style_key="clay", photo=b"x", consent="false")


async def test_a_failing_image_check_fails_closed_before_sending(dev_settings, fake_providers):
    providers = Providers(
        image=fake_providers.image,
        edit=fake_providers.edit,
        text=fake_providers.text,
        moderator=FakeModerator(fail_image=True),
    )
    service, _ = _service(dev_settings, providers)
    with pytest.raises(CheckFailedError):
        await service.photo(request())
    assert providers.edit.calls == []


async def test_a_bad_file_is_refused_without_a_reservation(dev_settings, fake_providers):
    service, limits = _service(dev_settings, fake_providers)
    with pytest.raises(BadImageError):
        await service.photo(request(raw=b"not an image"))
    assert fake_providers.edit.calls == [] and limits.snapshot().images_used == 0


async def test_an_unknown_style_is_an_error(dev_settings, fake_providers):
    service, _ = _service(dev_settings, fake_providers)
    with pytest.raises(ProviderError):
        await service.photo(request("nonexistent"))


async def test_the_photo_bytes_are_never_logged(dev_settings, fake_providers, caplog):
    service, _ = _service(dev_settings, fake_providers)
    caplog.set_level("DEBUG")
    await service.photo(request("comic", jpeg((64, 64))))
    assert all("PNG" not in record.getMessage() for record in caplog.records)


# --- config ---------------------------------------------------------------------------------------


def test_the_shipped_photo_styles_are_valid_and_brand_free(dev_settings):
    config = dev_settings.config
    assert config.ui.photo_styles and set(config.ui.photo_styles) <= set(config.photo_styles)
    for style in config.photo_styles.values():
        assert set(config.app.languages) <= set(style.label)
        assert style.instruction and not style.llm
        text = style.instruction.lower()
        assert not any(name in text for name in ("muppet", "pixar", "wallace", "gromit", "disney"))


def test_ui_photo_styles_must_be_defined(make_settings):
    def app(data):
        data["ui"]["photo_styles"].append("nonexistent")

    with pytest.raises(ValueError, match="photo_styles missing"):
        make_settings(app=app)


def test_a_photo_style_needs_a_label_per_language(make_settings):
    def app(data):
        del data["photo_styles"]["clay"]["label"]["sv"]

    with pytest.raises(ValueError, match="needs a label per language"):
        make_settings(app=app)
