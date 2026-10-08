"""Create tab: text, style tiles, Create button, result. Callbacks stay thin."""

from __future__ import annotations

import html
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import gradio as gr

from src.config import Settings
from src.errors import AppError, SafetyRefusalError, error_message_key
from src.services.generation import CreateRequest, GenerationService
from src.services.helpers import HelperService
from src.services.library import PromptLibrary
from src.services.limits import device_identity
from src.services.session import GeneratedImage, VisitorSession
from src.ui.busy import build_busy_overlay, start_js
from src.ui.chips import ChipRow, build_chip_row, wire_chips
from src.ui.components import ApiVisibility, Block, Localizer, Updates, build_heading, to_pil
from src.ui.helper_row import HelperRow, build_helper_row, wire_helpers

logger = logging.getLogger(__name__)

PLACEHOLDER_KEYS = ("create.placeholder.1", "create.placeholder.2", "create.placeholder.3")
PLACEHOLDER_ROTATE_SECONDS = 8

Handler = Callable[..., Any]


@dataclass
class CreateTab:
    text: gr.Textbox
    styles: dict[str, gr.Button]
    create_button: gr.Button
    status: gr.Markdown
    result: gr.Image
    rewrite_card: gr.Button
    helper_row: HelperRow
    chips: ChipRow | None = None

    @property
    def managed(self) -> list[Block]:
        return [
            self.text,
            *self.styles.values(),
            self.create_button,
            self.status,
            self.result,
            self.rewrite_card,
            *self.helper_row.managed,
            *(self.chips.managed if self.chips else []),
        ]

    def reset_props(self) -> Updates:
        return {
            self.text: {"value": ""},
            self.create_button: {"interactive": True},
            self.status: {"value": "", "visible": False},
            self.result: {"value": None},
            self.rewrite_card: {"value": "", "visible": False},
            **self.helper_row.reset_props(),
            **(self.chips.reset_props() if self.chips else {}),
            **{button: {"variant": "secondary"} for button in self.styles.values()},
        }


def build_create_tab(
    *,
    settings: Settings,
    service: GenerationService,
    helpers: HelperService,
    loc: Localizer,
    session: gr.State,
    device: gr.BrowserState,
    api_visibility: ApiVisibility,
    library: PromptLibrary | None = None,
) -> CreateTab:
    ui = settings.config.ui
    features = settings.config.features
    t = loc.t
    visibility = {"api_visibility": api_visibility}

    def placeholders(lang: str) -> list[str]:
        return [ui.challenge[lang], *(t(lang, key) for key in PLACEHOLDER_KEYS)]

    with gr.Row(elem_id="create-layout", equal_height=False):
        with gr.Column(scale=1, min_width=340, elem_id="controls-col"):
            text = loc.make(
                gr.Textbox,
                lambda lang: {
                    "label": t(lang, "create.label"),
                    "placeholder": placeholders(lang)[0],
                },
                lines=3,
                max_length=settings.config.safety.max_input_chars,
                elem_id="idea-box",
            )
            create_button = loc.make(
                gr.Button,
                lambda lang: {"value": t(lang, "create.button")},
                variant="primary",
                elem_classes=["primary-action"],
            )
            helper_row = build_helper_row(
                loc=loc,
                text=text,
                session=session,
                api_visibility=api_visibility,
                library=library,
                help_me=features.help_me,
                surprise_me=features.surprise_me,
            )
            build_heading(loc, "style.heading", "style.hint")
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
        with gr.Column(scale=1, min_width=340, elem_id="result-col"):
            with gr.Column(elem_id="result-wrap"):
                result = loc.make(
                    gr.Image,
                    lambda lang: {"label": t(lang, "create.result_label")},
                    interactive=False,
                    format="png",
                    buttons=["download"],
                    elem_id="result-image",
                )
                build_busy_overlay(loc)
                loc.make(
                    gr.HTML,
                    lambda lang: {
                        "value": f'<div class="result-hint">'
                        f"{html.escape(t(lang, 'create.result_empty'))}</div>"
                    },
                    elem_id="result-hint",
                )
            with gr.Column(elem_id="status-slot"):  # reserved, so a message moves nothing
                status = gr.Markdown(visible=False, elem_classes=["status-card"])
                rewrite_card = gr.Button(
                    visible=False, variant="secondary", elem_classes=["rewrite-card"]
                )
            chips = (
                build_chip_row(settings=settings, loc=loc)
                if features.edit_chips and service.can_edit()
                else None
            )
    tab = CreateTab(text, styles, create_button, status, result, rewrite_card, helper_row, chips)
    if chips:
        wire_chips(
            chips,
            settings=settings,
            service=service,
            loc=loc,
            session=session,
            device=device,
            create_button=create_button,
            status=status,
            result=result,
            api_visibility=api_visibility,
        )
    wire_helpers(
        helper_row,
        helpers=helpers,
        loc=loc,
        session=session,
        device=device,
        text=text,
        status=status,
        rewrite_card=rewrite_card,
        api_visibility=api_visibility,
        max_chars=settings.config.safety.max_input_chars,
        help_me=features.help_me,
        surprise_me=features.surprise_me,
    )

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
            **visibility,
        )

    async def on_create(idea: str, device_value: Any, current: VisitorSession):
        current.touch()
        lang = current.lang
        device_id, device_hash = device_identity(device_value)
        epoch = current.epoch
        dropped = (  # "New visitor" was tapped meanwhile: the result is not for the next visitor
            current,
            device_id,
            gr.update(interactive=True),
            gr.update(value="", visible=False),
            gr.skip(),
            gr.update(visible=False),
            gr.skip(),
        )
        yield (
            current,
            device_id,
            gr.update(interactive=False),
            gr.update(value=t(lang, "create.working"), visible=True),
            gr.skip(),
            gr.update(visible=False),
            gr.skip(),
        )
        try:
            made = await service.create(
                CreateRequest(
                    text=idea,
                    style=current.style,
                    lang=lang,
                    device_hash=device_hash,
                )
            )
            picture = to_pil(made.image)
        except Exception as exc:  # any failure must re-enable the button
            if current.epoch != epoch:
                yield dropped
                return
            if not isinstance(exc, AppError):
                logger.error("Create callback failed: %s", type(exc).__qualname__)
            message = t(lang, error_message_key(exc))
            rewrite = exc.rewrite if isinstance(exc, SafetyRefusalError) else None
            if rewrite:
                message += "\n\n" + t(lang, "safety.rewrite_prompt")
            yield (
                current,
                device_id,
                gr.update(interactive=True),
                gr.update(value=message, visible=True),
                gr.skip(),
                gr.update(value=rewrite, visible=True) if rewrite else gr.update(visible=False),
                gr.update(value=idea),
            )
            return
        if current.epoch != epoch:
            yield dropped
            return
        current.set_current(
            GeneratedImage(made.image, made.final_prompt, made.model_key, made.seconds),
            ui.history_size,
        )
        yield (
            current,
            device_id,
            gr.update(interactive=True),
            gr.update(value=t(lang, "ideas.example_note"), visible=True)
            if made.cached
            else gr.update(value="", visible=False),
            gr.update(value=picture, visible=True),
            gr.update(visible=False),
            gr.update(value=idea),  # the prompt stays in the box, whatever the browser does
        )

    created = create_button.click(
        on_create,
        [text, device, session],
        [session, device, create_button, status, result, rewrite_card, text],
        js=start_js("create"),
        **visibility,
    )
    if chips:

        def show_chips(current: VisitorSession):
            return (
                gr.update(visible=current.current is not None),
                gr.update(visible=current.previous is not None),
            )

        created.then(
            show_chips,
            [session],
            [chips.panel, chips.swap],
            queue=False,
            show_progress="hidden",
            **visibility,
        )

    def on_use_rewrite(suggestion: str, current: VisitorSession):
        current.touch()
        limit = settings.config.safety.max_input_chars
        shown = (suggestion or "")[:limit]
        return current, shown, gr.update(visible=False), gr.update(visible=False)

    rewrite_card.click(
        on_use_rewrite,
        [rewrite_card, session],
        [session, text, rewrite_card, status],
        queue=False,
        show_progress="hidden",
        **visibility,
    )

    def on_rotate(current: VisitorSession):
        options = placeholders(current.lang)
        return gr.update(
            placeholder=options[int(time.time() // PLACEHOLDER_ROTATE_SECONDS) % len(options)]
        )

    gr.Timer(PLACEHOLDER_ROTATE_SECONDS).tick(
        on_rotate, [session], [text], show_progress="hidden", queue=False, **visibility
    )
    return tab
