"""The "How it works" tab: a pipeline diagram that lights up one step at a time.

All steps are rendered once per language and stepped through in the browser, so a tap on Next is
instant. The server only hears about it to keep the visitor's session from going idle.
"""

from __future__ import annotations

import html
from typing import Any

import gradio as gr

from src.ui.components import ApiVisibility, Localizer

# (step key, kind). The kind picks the colour and the legend label.
STEPS: tuple[tuple[str, str], ...] = (
    ("prompt", "you"),
    ("translate", "language"),
    ("style", "code"),
    ("check", "safety"),
    ("limits", "code"),
    ("image", "image"),
    ("review", "safety"),
    ("result", "you"),
)
KINDS = ("you", "code", "language", "image", "safety")

_SET_STEP = """
  const root = document.getElementById('pipeline');
  if (!root) return args;
  const total = Number(root.dataset.steps);
  const current = Number(root.dataset.step);
  const step = %s;
  root.dataset.step = step;
  root.querySelectorAll('[data-i]').forEach((el) => {
    const i = Number(el.dataset.i);
    el.classList.toggle('active', i === step);
    el.classList.toggle('done', i > 0 && i < step);
  });
  return args;
"""


def _js(step: str) -> str:
    return "(...args) => {" + _SET_STEP % step + "}"


NEXT_JS = _js("(current + 1) % (total + 1)")  # after the last step it starts over
BACK_JS = _js("Math.max(0, current - 1)")
RESET_JS = _js("0")


def pipeline_html(loc: Localizer, lang: str) -> str:
    t = loc.t
    boxes: list[str] = []
    captions = [
        '<div class="pipe-caption pipe-you active" data-i="0">'
        f"<p>{html.escape(t(lang, 'how.start'))}</p></div>"
    ]
    for i, (key, kind) in enumerate(STEPS, 1):
        title = html.escape(t(lang, f"how.{key}.title"))
        text = html.escape(t(lang, f"how.{key}.text"))
        tag = html.escape(t(lang, f"how.kind.{kind}"))
        if i > 1:
            boxes.append('<span class="pipe-arrow" aria-hidden="true">&rsaquo;</span>')
        boxes.append(
            f'<div class="pipe-box pipe-{kind}" data-i="{i}">'
            f'<span class="pipe-num">{i}</span>{title}</div>'
        )
        captions.append(
            f'<div class="pipe-caption pipe-{kind}" data-i="{i}" role="status">'
            f'<h3>{i}. {title}</h3><p>{text}</p><span class="pipe-tag">{tag}</span></div>'
        )
    legend = "".join(
        f'<span class="pipe-key pipe-{kind}"><i></i>'
        f"{html.escape(t(lang, f'how.kind.{kind}'))}</span>"
        for kind in KINDS
    )
    return (
        f'<div id="pipeline" data-step="0" data-steps="{len(STEPS)}">'
        f'<div class="pipe-flow">{"".join(boxes)}</div>'
        f'<div class="pipe-captions">{"".join(captions)}</div>'
        f'<div class="pipe-legend">{legend}</div></div>'
    )


def build_how_tab(
    *, loc: Localizer, session: gr.State, api_visibility: ApiVisibility, touch: Any
) -> gr.Tab:
    quiet = {"queue": False, "show_progress": "hidden", "api_visibility": api_visibility}
    with loc.make(gr.Tab, lambda lang: {"label": loc.t(lang, "tab.how")}, id="how") as tab:
        loc.make(gr.Markdown, lambda lang: {"value": loc.t(lang, "how.intro")})
        loc.make(gr.HTML, lambda lang: {"value": pipeline_html(loc, lang)}, elem_id="pipeline-wrap")
        with gr.Row(elem_id="pipe-buttons"):
            back = loc.make(
                gr.Button,
                lambda lang: {"value": loc.t(lang, "how.back")},
                variant="secondary",
                elem_classes=["pipe-button"],
            )
            forward = loc.make(
                gr.Button,
                lambda lang: {"value": loc.t(lang, "how.next")},
                variant="primary",
                elem_classes=["pipe-button"],
            )
    back.click(touch, [session], [session], js=BACK_JS, **quiet)
    forward.click(touch, [session], [session], js=NEXT_JS, **quiet)
    tab.select(fn=None, js=RESET_JS)  # every visit starts at the beginning
    return tab
