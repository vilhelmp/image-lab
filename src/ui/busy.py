"""A "working" overlay over the result area, driven by a CSS class on the result wrapper.

The overlay is rendered once per language (spinner and a text), hidden by CSS, and shown while the
wrapper `#result-wrap` has the `busy` class. A tap sets the class instantly in the browser; the
same script clears it when the Create button, which the server disables while it works, becomes
enabled again (so it ends on success and on failure alike). Two timers are the safety net: one
clears it if the server never disables the button, one if the connection drops mid-way. (The class
is on the wrapper, not on <body>, because Gradio scopes every CSS selector inside its container.)
"""

from __future__ import annotations

import html
from typing import Any, Literal

import gradio as gr

from src.ui.components import Localizer

Kind = Literal["create", "edit", "helper"]
# Create and edit cover the result image; the helper buttons cover the text box they fill.
TARGET_IDS: dict[str, str] = {"create": "result-wrap", "edit": "result-wrap", "helper": "idea-box"}
NEVER_DISABLED_MS = 3_000
FAILSAFE_MS = 75_000


def start_js(kind: Kind) -> str:
    """Browser hook for `click(js=...)`: runs before the server call and passes its inputs on."""
    return f"""(...args) => {{
  const wrap = document.getElementById('{TARGET_IDS[kind]}');
  const button = document.querySelector('.primary-action');
  if (!wrap || !button) return args;
  window.__busyObserver?.disconnect();
  clearTimeout(window.__busyTimer);
  clearTimeout(window.__busyGrace);
  const stop = () => {{
    window.__busyObserver?.disconnect();
    clearTimeout(window.__busyTimer);
    clearTimeout(window.__busyGrace);
    wrap.classList.remove('busy', 'busy-create', 'busy-edit', 'busy-helper');
  }};
  let seenDisabled = button.disabled;
  wrap.classList.remove('busy-create', 'busy-edit', 'busy-helper');
  wrap.classList.add('busy', 'busy-{kind}');
  window.__busyObserver = new MutationObserver(() => {{
    if (button.disabled) seenDisabled = true;
    else if (seenDisabled) stop();
  }});
  window.__busyObserver.observe(button, {{ attributes: true, attributeFilter: ['disabled'] }});
  window.__busyGrace = setTimeout(() => {{ if (!seenDisabled) stop(); }}, {NEVER_DISABLED_MS});
  window.__busyTimer = setTimeout(stop, {FAILSAFE_MS});
  return args;
}}"""


def build_busy_overlay(loc: Localizer) -> Any:
    """The overlay component; place it inside the `#result-wrap` column."""

    def props(lang: str) -> dict[str, str]:
        create, edit = (html.escape(loc.t(lang, key)) for key in ("create.working", "edit.working"))
        return {
            "value": (
                '<div class="busy-box" role="status"><div class="spinner"></div>'
                f'<div class="busy-create-text">{create}</div>'
                f'<div class="busy-edit-text">{edit}</div></div>'
            )
        }

    return loc.make(gr.HTML, props, elem_id="busy-overlay")
