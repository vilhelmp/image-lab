"""One-tap edit chips under the image (spec section 3.4). Callbacks stay thin."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import gradio as gr

from src.config import Settings
from src.errors import AppError, SafetyRefusalError, error_message_key
from src.services.generation import ChipRequest, GenerationService
from src.services.limits import device_identity
from src.services.session import GeneratedImage, VisitorSession
from src.ui.busy import start_js
from src.ui.components import ApiVisibility, Block, Localizer, Updates, build_heading, to_pil

logger = logging.getLogger(__name__)

HOW_JS = "() => document.querySelectorAll('[role=\"tab\"]')[1]?.click()"


@dataclass
class ChipRow:
    panel: gr.Column
    buttons: dict[str, gr.Button]
    swap: gr.Button

    @property
    def managed(self) -> list[Block]:
        return [self.panel, self.swap, *self.buttons.values()]

    def reset_props(self) -> Updates:
        return {
            self.panel: {"visible": False},
            self.swap: {"visible": False, "interactive": True},
            **{button: {"interactive": True} for button in self.buttons.values()},
        }


def build_chip_row(*, settings: Settings, loc: Localizer) -> ChipRow:
    chips = settings.config.edit_chips
    t = loc.t
    with gr.Column(visible=False, elem_id="chip-panel") as panel:
        with gr.Row(elem_id="image-actions"):
            swap = loc.make(
                gr.Button,
                lambda lang: {"value": t(lang, "chips.swap")},
                variant="secondary",
                elem_classes=["swap-button"],
                visible=False,
            )
        build_heading(loc, "chips.heading", "chips.hint")
        with gr.Row(elem_id="chip-row"):
            buttons = {
                key: loc.make(
                    gr.Button,
                    lambda lang, key=key: {"value": chips[key].label[lang]},
                    variant="secondary",
                    elem_classes=["chip-button"],
                )
                for key in settings.config.ui.edit_chips
            }
        how = loc.make(
            gr.Button,
            lambda lang: {"value": t(lang, "chips.how")},
            variant="secondary",
            elem_classes=["swap-button"],
        )
    how.click(fn=None, js=HOW_JS)
    return ChipRow(panel, buttons, swap)


def wire_chips(
    chips: ChipRow,
    *,
    settings: Settings,
    service: GenerationService,
    loc: Localizer,
    session: gr.State,
    device: gr.BrowserState,
    create_button: gr.Button,
    status: gr.Markdown,
    result: gr.Image,
    api_visibility: ApiVisibility,
) -> None:
    t = loc.t
    history_size = settings.config.ui.history_size
    outputs = [session, device, create_button, *chips.buttons.values(), chips.swap, status, result]
    count = len(chips.buttons)

    def handler(key: str):
        chip_label = settings.config.edit_chips[key].label

        async def on_chip(device_value: Any, current: VisitorSession):
            current.touch()
            lang = current.lang
            device_id, device_hash = device_identity(device_value)
            source = current.current
            epoch = current.epoch
            if source is None:
                yield (current, device_id, *[gr.skip()] * (count + 4))
                return
            busy = gr.update(interactive=False)
            yield (
                current,
                device_id,
                busy,
                *[busy] * count,
                busy,
                gr.update(value=t(lang, "edit.working"), visible=True),
                gr.skip(),
            )
            ready = gr.update(interactive=True)
            made = None
            picture = None
            error: Exception | None = None
            try:
                made = await service.edit(
                    ChipRequest(
                        chip_key=key,
                        image=source.image,
                        current_prompt=source.prompt,
                        lang=lang,
                        device_hash=device_hash,
                    )
                )
                picture = to_pil(made.image)
            except Exception as exc:  # any failure must re-enable the buttons
                error = exc
            if current.epoch != epoch:
                # "New visitor" was tapped meanwhile: the result belongs to the previous visitor.
                yield (
                    current,
                    device_id,
                    ready,
                    *[ready] * count,
                    gr.update(visible=False, interactive=True),
                    gr.update(value="", visible=False),
                    gr.skip(),
                )
                return
            if error is not None or made is None or picture is None:
                if not isinstance(error, AppError):
                    logger.error("Edit callback failed: %s", type(error).__qualname__)
                # A refusal of the output must not suggest rewriting a text the visitor never wrote.
                refused = isinstance(error, SafetyRefusalError)
                message = t(lang, "edit.refused" if refused else error_message_key(error))
                yield (
                    current,
                    device_id,
                    ready,
                    *[ready] * count,
                    gr.update(visible=current.previous is not None, interactive=True),
                    gr.update(value=message, visible=True),
                    gr.skip(),
                )
                return
            current.set_edited(
                GeneratedImage(made.image, source.prompt, made.model_key, made.seconds),
                history_size,
            )
            yield (
                current,
                device_id,
                ready,
                *[ready] * count,
                gr.update(visible=True, interactive=True),
                gr.update(value=t(lang, "edit.done", chip=chip_label[lang]), visible=True),
                gr.update(value=picture, visible=True),
            )

        on_chip.__name__ = f"on_chip_{key}"
        return on_chip

    for key, button in chips.buttons.items():
        button.click(
            handler(key),
            [device, session],
            outputs,
            js=start_js("edit"),
            api_visibility=api_visibility,
        )

    def on_swap(current: VisitorSession):
        current.touch()
        if not current.swap():
            return current, gr.skip(), gr.skip()
        assert current.current is not None
        return (
            current,
            gr.update(value=to_pil(current.current.image), visible=True),
            gr.update(value="", visible=False),
        )

    chips.swap.click(
        on_swap,
        [session],
        [session, result, status],
        queue=False,
        show_progress="hidden",
        api_visibility=api_visibility,
    )
