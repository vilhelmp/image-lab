"""The ideas popup: grouped example prompts. Tapping one fills the text box (spec section 3.3)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import gradio as gr

from src.services.library import LibraryGroup, PromptLibrary
from src.services.session import VisitorSession
from src.ui.components import ApiVisibility, Localizer

GALLERY_COLUMNS = 3


@dataclass
class IdeasPanel:
    button: gr.Button
    overlay: gr.Column
    galleries: list[gr.Gallery]


def build_ideas(
    *,
    library: PromptLibrary,
    loc: Localizer,
    text: gr.Textbox,
    session: gr.State,
    api_visibility: ApiVisibility,
) -> IdeasPanel:
    t = loc.t
    quiet = {"queue": False, "show_progress": "hidden", "api_visibility": api_visibility}
    gr.set_static_paths([library.image_dir])  # serve the cached images without copying them

    button = loc.make(
        gr.Button,
        lambda lang: {"value": t(lang, "ideas.button")},
        variant="secondary",
        elem_classes=["ideas-button"],
    )
    galleries: list[gr.Gallery] = []
    with gr.Column(visible=False, elem_id="ideas-overlay") as overlay:
        with gr.Column(elem_id="ideas-panel"):
            with gr.Row(elem_id="ideas-header"):
                loc.make(gr.Markdown, lambda lang: {"value": f"## {t(lang, 'ideas.title')}"})
                close = loc.make(
                    gr.Button,
                    lambda lang: {"value": t(lang, "ideas.close")},
                    variant="secondary",
                    elem_classes=["ideas-close"],
                )
            loc.make(gr.Markdown, lambda lang: {"value": t(lang, "ideas.hint")})
            # Pills that wrap, not Gradio tabs: tabs fold into a "..." menu on a small screen.
            first = library.groups[0].id
            category = loc.make(
                gr.Radio,
                lambda lang: {"choices": [(g.label[lang], g.id) for g in library.groups]},
                value=first,
                show_label=False,
                container=False,
                elem_id="ideas-categories",
            )
            columns: list[gr.Column] = []
            for group in library.groups:
                with gr.Column(visible=group.id == first, elem_classes=["ideas-group"]) as column:
                    gallery = loc.make(
                        gr.Gallery,
                        lambda lang, g=group: {"value": _items(library, g, lang)},
                        columns=GALLERY_COLUMNS,
                        height="auto",
                        object_fit="cover",
                        allow_preview=False,
                        interactive=False,
                        show_label=False,
                        buttons=[],
                        elem_classes=["ideas-gallery"],
                    )
                    galleries.append(gallery)
                    gallery.select(_pick(group), [session], [session, text, overlay], **quiet)
                columns.append(column)

            def show_category(chosen: str):
                return [gr.update(visible=g.id == chosen) for g in library.groups]

            category.input(show_category, [category], columns, **quiet)

    def open_panel(current: VisitorSession):
        current.touch()
        return current, gr.update(visible=True)

    def close_panel(current: VisitorSession):
        current.touch()
        return current, gr.update(visible=False)

    button.click(open_panel, [session], [session, overlay], **quiet)
    close.click(close_panel, [session], [session, overlay], **quiet)
    return IdeasPanel(button, overlay, galleries)


def _items(library: PromptLibrary, group: LibraryGroup, lang: str) -> list[tuple[str, str]]:
    return [(str(library.image_path(p)), p.text[lang]) for p in group.prompts]


def _pick(group: LibraryGroup):
    def on_pick(current: VisitorSession, evt: gr.SelectData) -> tuple[Any, ...]:
        current.touch()
        prompt = group.prompts[int(evt.index)]
        return current, prompt.text[current.lang], gr.update(visible=False)

    return on_pick
