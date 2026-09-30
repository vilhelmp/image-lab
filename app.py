"""Builds the UI, wires services and launches the app."""

from __future__ import annotations

import logging
import os
from typing import Any

import gradio as gr

from src.config import Settings, load_env_file, load_settings
from src.i18n import I18n
from src.providers.factory import Providers, build_providers
from src.services.access import build_auth
from src.services.generation import GenerationService
from src.services.limits import LimitService
from src.services.session import VisitorSession
from src.ui.admin_tab import build_admin_tab
from src.ui.components import ApiVisibility, Localizer, merge, pack
from src.ui.create_tab import build_create_tab
from src.ui.theme import build_theme, load_css

logger = logging.getLogger(__name__)

try:
    import spaces  # only present on Hugging Face Spaces
except ImportError:
    spaces = None

if spaces is not None:

    @spaces.GPU
    def _zerogpu_marker() -> None:
        """Never called; ZeroGPU refuses to start a Space with no @spaces.GPU function."""


IDLE_CHECK_SECONDS = 5
DEFAULT_CONCURRENCY = 10
IMAGE_CACHE_CLEAN_EVERY_SECONDS = 60
IMAGE_CACHE_MAX_AGE_SECONDS = 600
TOGGLE_DARK_JS = "() => document.body.classList.toggle('dark')"
SCROLL_TOP_JS = "() => window.scrollTo(0, 0)"
DEVICE_STORAGE_KEY = "ai-image-lab-device"


def build_demo(
    settings: Settings,
    providers: Providers | None = None,
    limits: LimitService | None = None,
) -> gr.Blocks:
    cfg = settings.config
    default_lang = cfg.app.default_language
    i18n = I18n.load(cfg.app.languages, default_lang)
    limits = limits or LimitService(cfg.limits)
    service = GenerationService(settings, providers or build_providers(settings), limits)
    loc = Localizer(i18n)
    t = loc.t
    api_visibility: ApiVisibility = "undocumented" if cfg.access.expose_api else "private"
    visibility = {"api_visibility": api_visibility}

    def touch(current: VisitorSession) -> VisitorSession:
        current.touch()
        return current

    with gr.Blocks(
        title=cfg.app.name,
        delete_cache=(IMAGE_CACHE_CLEAN_EVERY_SECONDS, IMAGE_CACHE_MAX_AGE_SECONDS),
    ) as demo:
        session = gr.State(VisitorSession(lang=default_lang))
        device = gr.BrowserState(None, storage_key=DEVICE_STORAGE_KEY)

        with gr.Row(elem_id="header"):
            with gr.Column(scale=4):
                loc.make(
                    gr.Markdown,
                    lambda lang: {"value": f"# {t(lang, 'app.title')}\n{t(lang, 'app.subtitle')}"},
                )
            with gr.Column(scale=2):
                lang_toggle = gr.Radio(
                    choices=[(i18n.native_name(code), code) for code in cfg.app.languages],
                    value=default_lang,
                    show_label=False,
                    container=False,
                    elem_classes=["lang-toggle"],
                )
                theme_button = loc.make(
                    gr.Button,
                    lambda lang: {"value": t(lang, "theme.toggle")},
                    size="sm",
                )

        with gr.Tabs(selected="create") as tabs:
            with loc.make(gr.Tab, lambda lang: {"label": t(lang, "tab.create")}, id="create"):
                create = build_create_tab(
                    settings=settings,
                    service=service,
                    loc=loc,
                    session=session,
                    device=device,
                    touch=touch,
                    api_visibility=api_visibility,
                )
            build_admin_tab(
                demo=demo,
                limits=limits,
                loc=loc,
                session=session,
                api_visibility=api_visibility,
            )

        loc.make(
            gr.Markdown,
            lambda lang: {"value": t(lang, "footer.privacy")},
            elem_classes=["privacy-line"],
        )
        with loc.make(
            gr.Accordion, lambda lang: {"label": t(lang, "how.title")}, open=False
        ) as how:
            loc.make(
                gr.Markdown,
                lambda lang: {
                    "value": "\n".join(f"{i}. {t(lang, f'how.step{i}')}" for i in range(1, 5))
                },
            )
        new_visitor = loc.make(
            gr.Button,
            lambda lang: {"value": t(lang, "footer.new_visitor")},
            elem_classes=["new-visitor"],
        )

        managed = list(dict.fromkeys([*loc.components, *create.managed]))
        outputs = [session, lang_toggle, tabs, *managed]

        def reset(current: VisitorSession) -> list[Any]:
            lang = default_lang if cfg.ui.reset_language_on_new_visitor else current.lang
            current.reset(lang)
            merged = merge(loc.props(lang), create.reset_props())
            return [
                current,
                gr.update(value=lang),
                gr.update(selected="create"),
                *pack(managed, merged),
            ]

        def on_idle(current: VisitorSession) -> list[Any]:
            if current.is_idle(cfg.ui.idle_reset_seconds):
                return reset(current)
            return [gr.skip()] * len(outputs)

        def on_language(lang: str, current: VisitorSession) -> list[Any]:
            current.lang = lang
            current.touch()
            return [current, *pack(loc.components, loc.props(lang))]

        new_visitor.click(reset, [session], outputs, show_progress="hidden", **visibility).then(
            fn=None, js=SCROLL_TOP_JS
        )
        gr.Timer(IDLE_CHECK_SECONDS).tick(
            on_idle, [session], outputs, show_progress="hidden", **visibility
        )
        lang_toggle.input(
            on_language,
            [lang_toggle, session],
            [session, *loc.components],
            queue=False,
            show_progress="hidden",
            **visibility,
        )
        how.expand(touch, [session], [session], queue=False, show_progress="hidden", **visibility)
        theme_button.click(fn=None, js=TOGGLE_DARK_JS)

        if cfg.app.default_theme != "system":
            action = "add" if cfg.app.default_theme == "dark" else "remove"
            demo.load(fn=None, js=f"() => document.body.classList.{action}('dark')")

    demo.queue(default_concurrency_limit=DEFAULT_CONCURRENCY)
    return demo


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    loaded = load_env_file()
    if loaded:
        logger.info("Read %d variable(s) from the .env file: %s", len(loaded), ", ".join(loaded))
    settings = load_settings()
    problems = settings.startup_problems(os.environ)
    if problems:
        raise SystemExit("Startup blocked:\n- " + "\n- ".join(problems))
    for key in settings.hidden_image_models():
        logger.warning("Model '%s' hidden: no hf_model for image_backend=hf", key)

    demo = build_demo(settings)
    auth = build_auth(
        os.environ,
        enabled=settings.config.access.enabled,
        development_mode=settings.development_mode,
    )
    logger.info("Login required: %s", "yes" if auth else "no")
    logger.warning("Budget counters start at zero. Provider prepaid credit is the hard limit.")
    demo.launch(
        theme=build_theme(),
        css=load_css(),
        ssr_mode=False,
        auth=auth,
        footer_links=[],
        mcp_server=False,
    )


if __name__ == "__main__":
    main()
