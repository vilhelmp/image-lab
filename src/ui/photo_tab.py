"""Photo studio tab: take or upload a photo, restyle it with the edit model. Callbacks stay thin.

The tab is hidden until an admin switches it on (see `RuntimeFlags`). The photo goes to an
external service, so the tab says so in plain words and asks for a tick before anything is sent.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import gradio as gr

from src.config import Settings
from src.errors import AppError, SafetyRefusalError, error_message_key
from src.services.flags import RuntimeFlags
from src.services.generation import GenerationService, PhotoRequest
from src.services.limits import device_identity
from src.services.photo import read_upload
from src.services.session import VisitorSession
from src.ui.busy import build_busy_overlay, start_js
from src.ui.components import ApiVisibility, Block, Localizer, Updates, build_heading, to_pil

logger = logging.getLogger(__name__)
FLAGS_REFRESH_SECONDS = 5
OPEN_JS = "(flag) => document.body.classList.toggle('photo-open', flag === '1')"


@dataclass
class PhotoTab:
    tab: gr.Tab
    photo: gr.Image
    consent: gr.Checkbox
    styles: dict[str, gr.Button]
    result: gr.Image
    status: gr.Markdown
    # Follows the admin's on/off switch. Call it once, outside the Tabs block.
    wire_switch: Callable[[], None]

    @property
    def managed(self) -> list[Block]:
        return [self.photo, self.consent, *self.styles.values(), self.result, self.status]

    def reset_props(self) -> Updates:
        return {
            self.photo: {"value": None},
            self.consent: {"value": False},
            self.result: {"value": None},
            self.status: {"value": "", "visible": False},
            **{button: {"interactive": True} for button in self.styles.values()},
        }


def build_photo_tab(
    *,
    demo: gr.Blocks,
    settings: Settings,
    service: GenerationService,
    flags: RuntimeFlags,
    loc: Localizer,
    session: gr.State,
    device: gr.BrowserState,
    api_visibility: ApiVisibility,
) -> PhotoTab:
    t = loc.t
    config = settings.config
    visibility = {"api_visibility": api_visibility, "show_progress": "hidden", "queue": False}
    active = settings.active_edit_model()
    provider = (active[1].hf_provider or active[1].provider) if active else ""

    with loc.make(gr.Tab, lambda lang: {"label": t(lang, "tab.photo")}, id="photo") as tab:
        # The tab itself is never shown or hidden: Gradio's tab list breaks when tabs come and go.
        # Shown or hidden by a class on <body> (see OPEN_JS and style.css), not by server updates:
        # Gradio drops visibility updates for components in a tab that is not yet on screen.
        with gr.Column(elem_id="photo-closed"):
            loc.make(
                gr.Markdown,
                lambda lang: {"value": t(lang, "photo.off")},
                elem_classes=["status-card"],
            )
        with gr.Row(elem_id="photo-layout", equal_height=False):
            with gr.Column(scale=1, min_width=340, elem_classes=["card-col"]):
                loc.make(
                    gr.Markdown,
                    lambda lang: {"value": t(lang, "photo.notice", provider=provider)},
                    elem_classes=["photo-notice"],
                )
                photo = loc.make(
                    gr.Image,
                    lambda lang: {"label": t(lang, "photo.label")},
                    sources=["webcam", "upload"],
                    type="filepath",
                    format="png",
                    height=340,
                    webcam_options=gr.WebcamOptions(mirror=True),
                    elem_id="photo-input",
                )
                consent = loc.make(
                    gr.Checkbox,
                    lambda lang: {"label": t(lang, "photo.consent")},
                    elem_id="photo-consent",
                )
                build_heading(loc, "photo.styles", "photo.styles_hint")
                with gr.Row(elem_id="photo-styles"):
                    styles = {
                        key: loc.make(
                            gr.Button,
                            lambda lang, key=key: {"value": config.photo_styles[key].label[lang]},
                            variant="secondary",
                            elem_classes=["photo-style"],
                        )
                        for key in config.ui.photo_styles
                    }
            with gr.Column(scale=1, min_width=340, elem_classes=["card-col"]):
                with gr.Column(elem_id="photo-result-wrap", elem_classes=["result-wrap"]):
                    result = loc.make(
                        gr.Image,
                        lambda lang: {"label": t(lang, "photo.result_label")},
                        interactive=False,
                        format="png",
                        buttons=["download"],
                        height=340,
                        elem_id="photo-result",
                    )
                    build_busy_overlay(loc, elem_id="photo-busy-overlay")
                status = gr.Markdown(visible=False, elem_classes=["status-card"])

    outputs = [session, device, *styles.values(), status, result]
    count = len(styles)

    def handler(key: str):
        label = config.photo_styles[key].label

        async def on_photo(
            photo_path: str | None, agreed: bool, device_value: Any, current: VisitorSession
        ):
            current.touch()
            lang = current.lang
            device_id, device_hash = device_identity(device_value)
            if not photo_path:
                # Busy then ready, so the browser's working overlay ends at once.
                yield (
                    current,
                    device_id,
                    *[gr.update(interactive=False)] * count,
                    gr.update(value=t(lang, "photo.need_photo"), visible=True),
                    gr.skip(),
                )
                yield (
                    current,
                    device_id,
                    *[gr.update(interactive=True)] * count,
                    gr.update(value=t(lang, "photo.need_photo"), visible=True),
                    gr.skip(),
                )
                return
            epoch = current.epoch
            busy = gr.update(interactive=False)
            yield (
                current,
                device_id,
                *[busy] * count,
                gr.update(value=t(lang, "edit.working"), visible=True),
                gr.skip(),
            )
            ready = gr.update(interactive=True)
            try:
                raw = await asyncio.to_thread(read_upload, photo_path)
                made = await service.photo(
                    PhotoRequest(
                        style_key=key,
                        photo=raw,
                        consent=agreed is True,
                        lang=lang,
                        device_hash=device_hash,
                    )
                )
                picture = to_pil(made.image)
            except Exception as exc:  # any failure must re-enable the buttons
                if current.epoch != epoch:  # "New visitor" was tapped meanwhile
                    yield (
                        current,
                        device_id,
                        *[ready] * count,
                        gr.update(value="", visible=False),
                        gr.skip(),
                    )
                    return
                if not isinstance(exc, AppError):
                    logger.error("Photo callback failed: %s", type(exc).__qualname__)
                refused = isinstance(exc, SafetyRefusalError)
                message = t(lang, "photo.refused" if refused else error_message_key(exc))
                yield (
                    current,
                    device_id,
                    *[ready] * count,
                    gr.update(value=message, visible=True),
                    gr.skip(),
                )
                return
            if current.epoch != epoch:
                yield (
                    current,
                    device_id,
                    *[ready] * count,
                    gr.update(value="", visible=False),
                    gr.skip(),
                )
                return
            yield (
                current,
                device_id,
                *[ready] * count,
                gr.update(value=t(lang, "edit.done", chip=label[lang]), visible=True),
                gr.update(value=picture, visible=True),
            )

        on_photo.__name__ = f"on_photo_{key}"
        return on_photo

    for key, button in styles.items():
        button.click(
            handler(key),
            [photo, consent, device, session],
            outputs,
            js=start_js("photo"),
            api_visibility=api_visibility,
        )

    # A timer must never send updates to visible components: Gradio then rebuilds them (the
    # webcam restarts, tabs get duplicated). It only writes a hidden marker; the marker's change
    # event flips a class on <body> in the browser. The marker and the timer must be created
    # outside the Tabs (see `wire_switch`): anything but a Tab directly inside the Tabs makes
    # Gradio list the tab that follows twice.
    def on_flag() -> str:
        return "1" if flags.photo_studio else "0"

    def wire_switch() -> None:
        marker = gr.Textbox(elem_id="photo-flag", container=False, interactive=False)
        timer = gr.Timer(FLAGS_REFRESH_SECONDS)
        demo.load(on_flag, None, [marker], **visibility)
        marker.change(fn=None, inputs=[marker], js=OPEN_JS)
        timer.tick(on_flag, None, [marker], **visibility)

    photo.change(lambda: gr.update(value=False), None, [consent], **visibility)
    return PhotoTab(tab, photo, consent, styles, result, status, wire_switch)
