"""Buttons under the text box: ideas, Help me, Surprise me and Undo. Callbacks stay thin."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import gradio as gr

from src.errors import (
    AppError,
    EmptyInputError,
    PausedError,
    SafetyRefusalError,
    TooLongInputError,
    error_message_key,
)
from src.services.helpers import HelperService
from src.services.library import PromptLibrary
from src.services.limits import device_identity
from src.services.session import VisitorSession
from src.ui.components import ApiVisibility, Block, Localizer, Updates, build_heading
from src.ui.ideas import IdeasPanel, build_ideas

logger = logging.getLogger(__name__)
SHOWN_AS_IS = (EmptyInputError, TooLongInputError, PausedError, SafetyRefusalError)

Run = Callable[[str, str, str | None], Awaitable[str]]


@dataclass
class HelperRow:
    undo: gr.Button
    buttons: list[gr.Button]
    ideas: IdeasPanel | None = None

    @property
    def managed(self) -> list[Block]:
        return [self.undo, *self.buttons, *([self.ideas.overlay] if self.ideas else [])]

    def reset_props(self) -> Updates:
        return {
            self.undo: {"visible": False},
            **{button: {"interactive": True} for button in self.buttons},
            **({self.ideas.overlay: {"visible": False}} if self.ideas else {}),
        }


def build_helper_row(
    *,
    loc: Localizer,
    text: gr.Textbox,
    session: gr.State,
    api_visibility: ApiVisibility,
    library: PromptLibrary | None,
    help_me: bool,
    surprise_me: bool,
) -> HelperRow:
    t = loc.t

    def button(key: str, **props: Any) -> gr.Button:
        return loc.make(
            gr.Button,
            lambda lang: {"value": t(lang, key)},
            variant="secondary",
            elem_classes=["helper-button"],
            **props,
        )

    build_heading(loc, "helper.heading", "helper.hint")
    with gr.Row(elem_id="helper-row"):
        ideas = (
            build_ideas(
                library=library, loc=loc, text=text, session=session, api_visibility=api_visibility
            )
            if library and library.groups
            else None
        )
        buttons = [button("helper.help")] if help_me else []
        buttons += [button("helper.surprise")] if surprise_me else []
        undo = button("helper.undo", visible=False)
    return HelperRow(undo, buttons, ideas)


def wire_helpers(
    row: HelperRow,
    *,
    helpers: HelperService,
    loc: Localizer,
    session: gr.State,
    device: gr.BrowserState,
    text: gr.Textbox,
    status: gr.Markdown,
    rewrite_card: gr.Button,
    api_visibility: ApiVisibility,
    max_chars: int,
    help_me: bool,
    surprise_me: bool,
) -> None:
    t = loc.t
    quiet = {"queue": False, "show_progress": "hidden", "api_visibility": api_visibility}
    outputs = [session, device, *row.buttons, text, row.undo, status, rewrite_card]
    buttons = iter(row.buttons)

    def handler(name: str, run: Run):
        async def on_helper(idea: str, device_value: Any, current: VisitorSession):
            current.touch()
            lang = current.lang
            device_id, device_hash = device_identity(device_value)
            busy = [gr.update(interactive=False)] * len(row.buttons)
            ready = [gr.update(interactive=True)] * len(row.buttons)
            yield (
                current,
                device_id,
                *busy,
                gr.skip(),
                gr.skip(),
                gr.update(value=t(lang, "helper.working"), visible=True),
                gr.update(visible=False),
            )
            try:
                improved = await run(idea, lang, device_hash)
            except Exception as exc:  # the text box must stay as it was
                if not isinstance(exc, AppError):
                    logger.error("Helper callback failed: %s", type(exc).__qualname__)
                key = error_message_key(exc) if isinstance(exc, SHOWN_AS_IS) else "helper.failed"
                message = t(lang, key)
                suggestion = exc.rewrite if isinstance(exc, SafetyRefusalError) else None
                if suggestion:
                    message += "\n\n" + t(lang, "safety.rewrite_prompt")
                yield (
                    current,
                    device_id,
                    *ready,
                    gr.skip(),
                    gr.skip(),
                    gr.update(value=message, visible=True),
                    gr.update(value=suggestion, visible=True)
                    if suggestion
                    else gr.update(visible=False),
                )
                return
            current.undo_text = idea[:max_chars]
            yield (
                current,
                device_id,
                *ready,
                improved,
                gr.update(visible=True),
                gr.update(value="", visible=False),
                gr.update(visible=False),
            )

        on_helper.__name__ = name
        return on_helper

    if help_me:
        next(buttons).click(
            handler("on_help", lambda idea, lang, dev: helpers.improve(idea, lang, dev)),
            [text, device, session],
            outputs,
            api_visibility=api_visibility,
        )
    if surprise_me:
        next(buttons).click(
            handler("on_surprise", lambda idea, lang, dev: helpers.surprise(lang, dev)),
            [text, device, session],
            outputs,
            api_visibility=api_visibility,
        )

    def on_undo(current: VisitorSession):
        current.touch()
        previous, current.undo_text = current.undo_text or "", None
        return current, previous, gr.update(visible=False)

    row.undo.click(on_undo, [session], [session, text, row.undo], **quiet)

    def on_typing(current: VisitorSession):
        current.touch()
        had_undo, current.undo_text = current.undo_text is not None, None
        return current, gr.update(visible=False) if had_undo else gr.skip()

    text.input(on_typing, [session], [session, row.undo], trigger_mode="always_last", **quiet)

    def on_replaced(current: VisitorSession):
        # A picked idea or a suggested alternative replaces the text, so Undo no longer fits.
        current.undo_text = None
        return current, gr.update(visible=False)

    rewrite_card.click(on_replaced, [session], [session, row.undo], **quiet)
    for gallery in row.ideas.galleries if row.ideas else []:
        gallery.select(on_replaced, [session], [session, row.undo], **quiet)
