"""Admin status tab (spec section 12). Callbacks re-check the username; hiding is not enough."""

from __future__ import annotations

import gradio as gr

from src.services.access import is_admin
from src.services.limits import LimitService
from src.services.session import VisitorSession
from src.ui.components import ApiVisibility, Localizer

REFRESH_SECONDS = 5


def build_admin_tab(
    *,
    demo: gr.Blocks,
    limits: LimitService,
    loc: Localizer,
    session: gr.State,
    api_visibility: ApiVisibility,
) -> gr.Tab:
    t = loc.t
    visibility = {"api_visibility": api_visibility, "show_progress": "hidden"}

    with loc.make(
        gr.Tab, lambda lang: {"label": t(lang, "tab.admin")}, id="admin", visible=False
    ) as tab:
        summary = gr.Markdown()
        paused = loc.make(gr.Checkbox, lambda lang: {"label": t(lang, "admin.pause")})
        ask_reset = loc.make(gr.Button, lambda lang: {"value": t(lang, "admin.reset")})
        with gr.Column(visible=False) as confirm:
            loc.make(gr.Markdown, lambda lang: {"value": t(lang, "admin.reset_confirm")})
            with gr.Row():
                yes = loc.make(
                    gr.Button, lambda lang: {"value": t(lang, "admin.reset_yes")}, variant="stop"
                )
                no = loc.make(gr.Button, lambda lang: {"value": t(lang, "admin.reset_cancel")})
    timer = gr.Timer(REFRESH_SECONDS, active=False)

    def render(lang: str) -> str:
        snap = limits.snapshot()
        latency = ", ".join(f"{m} {s:.1f} s" for m, s in sorted(snap.p50_seconds.items()))
        return "\n\n".join(
            [
                t(lang, "admin.paused" if snap.paused else "admin.running"),
                t(
                    lang,
                    "admin.usage",
                    used=snap.images_used,
                    max_images=snap.max_images,
                    spend=f"{snap.spend_usd:.2f}",
                    max_cost=f"{snap.max_cost_usd:.2f}",
                ),
                t(lang, "admin.activity", in_flight=snap.in_flight, **snap.recent),
                t(lang, "admin.latency", details=latency or t(lang, "admin.latency_none")),
            ]
        )

    def on_load(current: VisitorSession, request: gr.Request):
        if not is_admin(request.username):
            return [gr.skip()] * 4
        return (
            gr.update(visible=True),
            gr.Timer(active=True),
            render(current.lang),
            limits.paused,
        )

    def on_refresh(current: VisitorSession, request: gr.Request):
        if not is_admin(request.username):
            return gr.skip(), gr.skip()
        return render(current.lang), limits.paused

    def on_pause(value: bool, current: VisitorSession, request: gr.Request):
        if not is_admin(request.username):
            return gr.skip()
        limits.set_paused(bool(value))
        return render(current.lang)

    def on_confirm_reset(current: VisitorSession, request: gr.Request):
        if is_admin(request.username):
            limits.reset_counters()
            return gr.update(visible=False), render(current.lang)
        return gr.skip(), gr.skip()

    demo.load(on_load, [session], [tab, timer, summary, paused], **visibility)
    timer.tick(on_refresh, [session], [summary, paused], **visibility)
    paused.input(on_pause, [paused, session], [summary], **visibility)
    ask_reset.click(lambda: gr.update(visible=True), None, [confirm], **visibility)
    no.click(lambda: gr.update(visible=False), None, [confirm], **visibility)
    yes.click(on_confirm_reset, [session], [confirm, summary], **visibility)
    return tab
