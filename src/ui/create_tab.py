"""Create tab: text, style tiles, format, Create button, result. Callbacks stay thin."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import gradio as gr

from src.config import Settings
from src.errors import AppError, error_message_key
from src.services.generation import CreateRequest, GenerationService
from src.services.session import GeneratedImage, VisitorSession
from src.ui.components import Block, Localizer, Updates, to_pil

logger = logging.getLogger(__name__)

ASPECTS = ("square", "landscape", "portrait")
PLACEHOLDER_KEYS = ("create.placeholder.1", "create.placeholder.2", "create.placeholder.3")
PLACEHOLDER_ROTATE_SECONDS = 8

Handler = Callable[..., Any]


@dataclass
class CreateTab:
    text: gr.Textbox
    styles: dict[str, gr.Button]
    aspect: gr.Radio
    create_button: gr.Button
    status: gr.Markdown
    result: gr.Image

    @property
    def managed(self) -> list[Block]:
        return [
            self.text,
            *self.styles.values(),
            self.aspect,
            self.create_button,
            self.status,
            self.result,
        ]

    def reset_props(self) -> Updates:
        return {
            self.text: {"value": ""},
            self.aspect: {"value": ASPECTS[0]},
            self.create_button: {"interactive": True},
            self.status: {"value": "", "visible": False},
            self.result: {"value": None, "visible": False},
            **{button: {"variant": "secondary"} for button in self.styles.values()},
        }


def build_create_tab(
    *,
    settings: Settings,
    service: GenerationService,
    loc: Localizer,
    session: gr.State,
    touch: Handler,
) -> CreateTab:
    ui = settings.config.ui
    t = loc.t

    def placeholders(lang: str) -> list[str]:
        return [ui.challenge[lang], *(t(lang, key) for key in PLACEHOLDER_KEYS)]

    text = loc.make(
        gr.Textbox,
        lambda lang: {"label": t(lang, "create.label"), "placeholder": placeholders(lang)[0]},
        lines=2,
        max_length=settings.config.safety.max_input_chars,
        elem_id="idea-box",
    )

    with gr.Row(elem_id="style-row"):
        styles: dict[str, gr.Button] = {
            key: loc.make(
                gr.Button,
                lambda lang, key=key: {"value": t(lang, f"style.{key}")},
                variant="secondary",
                elem_classes=["style-tile"],
            )
            for key in ui.styles
        }

    aspect = loc.make(
        gr.Radio,
        lambda lang: {
            "label": t(lang, "format.label"),
            "choices": [(t(lang, f"format.{a}"), a) for a in ASPECTS],
        },
        value=ASPECTS[0],
        elem_classes=["format-radio"],
    )
    create_button = loc.make(
        gr.Button,
        lambda lang: {"value": t(lang, "create.button")},
        variant="primary",
        elem_classes=["primary-action"],
    )
    status = gr.Markdown(visible=False, elem_classes=["status-card"])
    result = loc.make(
        gr.Image,
        lambda lang: {"label": t(lang, "create.result_label")},
        visible=False,
        interactive=False,
        format="png",
        buttons=["download"],
        elem_id="result-image",
    )
    tab = CreateTab(text, styles, aspect, create_button, status, result)

    def style_handler(key: str) -> Handler:
        def on_style(current: VisitorSession) -> list[Any]:
            current.touch()
            current.select_style(key)
            return [
                current,
                *(
                    gr.update(variant="primary" if k == current.style else "secondary")
                    for k in styles
                ),
            ]

        return on_style

    for key, button in styles.items():
        button.click(
            style_handler(key),
            [session],
            [session, *styles.values()],
            queue=False,
            show_progress="hidden",
        )

    quiet = {"queue": False, "show_progress": "hidden", "trigger_mode": "always_last"}
    text.input(touch, [session], [session], **quiet)
    aspect.input(touch, [session], [session], **quiet)

    async def on_create(idea: str, chosen_aspect: str, current: VisitorSession):
        current.touch()
        lang = current.lang
        yield (
            current,
            gr.update(interactive=False),
            gr.update(value=t(lang, "create.working"), visible=True),
            gr.skip(),
        )
        try:
            made = await service.create(
                CreateRequest(text=idea, style=current.style, aspect=chosen_aspect)
            )
            picture = to_pil(made.image)
        except Exception as exc:  # any failure must re-enable the button
            if not isinstance(exc, AppError):
                logger.error("Create callback failed: %s", type(exc).__qualname__)
            yield (
                current,
                gr.update(interactive=True),
                gr.update(value=t(lang, error_message_key(exc)), visible=True),
                gr.skip(),
            )
            return
        current.set_current(
            GeneratedImage(made.image, made.final_prompt, made.model_key, made.seconds),
            ui.history_size,
        )
        yield (
            current,
            gr.update(interactive=True),
            gr.update(value="", visible=False),
            gr.update(value=picture, visible=True),
        )

    create_button.click(
        on_create,
        [text, aspect, session],
        [session, create_button, status, result],
    )

    def on_rotate(current: VisitorSession):
        options = placeholders(current.lang)
        return gr.update(
            placeholder=options[int(time.time() // PLACEHOLDER_ROTATE_SECONDS) % len(options)]
        )

    gr.Timer(PLACEHOLDER_ROTATE_SECONDS).tick(
        on_rotate, [session], [text], show_progress="hidden", queue=False
    )
    return tab
