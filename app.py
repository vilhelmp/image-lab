"""Builds the UI, wires services and launches the app."""

from __future__ import annotations

import html
import logging
import os
import time
from typing import Any

import gradio as gr

from src.config import Settings, env_file_path, load_env_file, load_settings
from src.i18n import I18n
from src.logging_setup import configure_logging
from src.providers.factory import Providers, build_providers
from src.services.access import build_auth
from src.services.flags import RuntimeFlags
from src.services.generation import GenerationService
from src.services.helpers import HelperService
from src.services.library import PromptLibrary, load_library, load_lock
from src.services.limits import LimitService
from src.services.session import VisitorSession
from src.ui.admin_tab import build_admin_tab
from src.ui.components import ApiVisibility, Localizer, merge, pack
from src.ui.create_tab import build_create_tab
from src.ui.how_tab import build_how_tab
from src.ui.photo_tab import build_photo_tab
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
# Tap the result to zoom it to the full screen; any tap or Escape closes it again.
ZOOM_JS = """() => {
  if (window.__zoomReady) return;
  window.__zoomReady = true;
  const open = () => document.querySelector('#result-image.zoomed, #photo-result.zoomed');
  document.addEventListener('click', (e) => {
    const zoomed = open();
    if (zoomed) {
      zoomed.classList.remove('zoomed');
      e.preventDefault();
      e.stopPropagation();
      return;
    }
    const box = e.target.closest('#result-image, #photo-result');
    if (box && e.target.closest('img')) box.classList.add('zoomed');
  }, true);
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') open()?.classList.remove('zoomed');
  });
}"""
SCROLL_TOP_JS = "() => window.scrollTo(0, 0)"
# Enter in the idea box creates the picture; Shift+Enter adds a new line.
ENTER_JS = """() => {
  if (window.__enterReady) return;
  window.__enterReady = true;
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter' || e.shiftKey || e.isComposing) return;
    if (!e.target.matches('#idea-box textarea')) return;
    e.preventDefault();
    document.querySelector('.primary-action')?.click();
  });
}"""


def _open_class_js(element_id: str, action: str) -> str:
    return f"document.getElementById('{element_id}')?.classList.{action}('open')"


TOGGLE_LANG_JS = "() => " + _open_class_js("lang-toggle", "toggle")
CLOSE_LANG_JS = "(...args) => { " + _open_class_js("lang-toggle", "remove") + "; return args; }"
TOGGLE_CONFIRM_JS = "() => " + _open_class_js("new-visitor-confirm", "toggle")
CLOSE_CONFIRM_JS = (
    "(...args) => { " + _open_class_js("new-visitor-confirm", "remove") + "; return args; }"
)
DEVICE_STORAGE_KEY = "ai-image-lab-device"


def login_message(i18n: I18n, languages: list[str]) -> str:
    """The text on Gradio's login page, which has no language switch, so every language shows."""
    parts = [f"<strong>{html.escape(i18n.t(languages[0], 'app.title'))}</strong>"]
    parts += [f"<span>{html.escape(i18n.t(code, 'login.message'))}</span>" for code in languages]
    return '<div class="login-intro">' + "".join(parts) + "</div>"


def build_demo(
    settings: Settings,
    providers: Providers | None = None,
    limits: LimitService | None = None,
    library: PromptLibrary | None = None,
    flags: RuntimeFlags | None = None,
) -> gr.Blocks:
    cfg = settings.config
    default_lang = cfg.app.default_language
    i18n = I18n.load(cfg.app.languages, default_lang)
    limits = limits or LimitService(cfg.limits)
    flags = flags or RuntimeFlags()
    library = library or load_library(settings).with_images(load_lock())
    providers = providers or build_providers(settings)
    helpers = HelperService(settings, providers, limits, library)
    service = GenerationService(settings, providers, limits, library, helpers, flags)
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
        idle_marker = gr.State(0.0)
        device = gr.BrowserState(None, storage_key=DEVICE_STORAGE_KEY)

        with gr.Row(elem_id="header"):
            with gr.Column(scale=4):
                loc.make(
                    gr.Markdown,
                    lambda lang: {"value": f"# {t(lang, 'app.title')}\n{t(lang, 'app.subtitle')}"},
                )
            with gr.Column(scale=1, min_width=160):
                with gr.Row(elem_id="header-tools"):
                    lang_button = loc.make(
                        gr.Button,
                        lambda lang: {"value": lang.upper()},
                        size="sm",
                        elem_id="lang-button",
                    )
                    lang_toggle = gr.Radio(
                        choices=[(i18n.native_name(code), code) for code in cfg.app.languages],
                        value=default_lang,
                        label="Språk / Language",
                        show_label=False,
                        container=False,
                        elem_id="lang-toggle",
                    )
                    theme_button = loc.make(
                        gr.Button,
                        lambda lang: {"value": t(lang, "theme.toggle")},
                        size="sm",
                        elem_id="theme-button",
                    )

        with gr.Tabs(selected="create") as tabs:
            with loc.make(gr.Tab, lambda lang: {"label": t(lang, "tab.create")}, id="create"):
                create = build_create_tab(
                    settings=settings,
                    service=service,
                    helpers=helpers,
                    loc=loc,
                    session=session,
                    device=device,
                    api_visibility=api_visibility,
                    library=library,
                )
            photo = (
                build_photo_tab(
                    demo=demo,
                    settings=settings,
                    service=service,
                    flags=flags,
                    loc=loc,
                    session=session,
                    device=device,
                    api_visibility=api_visibility,
                )
                if cfg.features.photo_studio and cfg.ui.photo_styles and service.can_edit()
                else None
            )
            build_how_tab(loc=loc, session=session, api_visibility=api_visibility, touch=touch)
            build_admin_tab(
                demo=demo,
                limits=limits,
                flags=flags,
                photo_studio=photo is not None,
                high_quality=bool(settings.models.defaults.high_quality_model),
                loc=loc,
                session=session,
                api_visibility=api_visibility,
            )

        if photo:
            photo.wire_switch()
        loc.make(
            gr.Markdown,
            lambda lang: {"value": t(lang, "footer.privacy")},
            elem_classes=["privacy-line"],
        )
        new_visitor = loc.make(
            gr.Button,
            lambda lang: {"value": t(lang, "footer.new_visitor")},
            elem_classes=["new-visitor"],
        )
        with gr.Row(elem_id="new-visitor-confirm"):  # shown by the button above, so no accidents
            confirm_yes = loc.make(
                gr.Button,
                lambda lang: {"value": t(lang, "footer.new_visitor_yes")},
                variant="stop",
                elem_classes=["new-visitor"],
            )
            confirm_no = loc.make(
                gr.Button,
                lambda lang: {"value": t(lang, "footer.cancel")},
                elem_classes=["new-visitor"],
            )

        managed = list(
            dict.fromkeys([*loc.components, *create.managed, *(photo.managed if photo else [])])
        )
        outputs = [session, lang_toggle, tabs, *managed]

        def reset(current: VisitorSession) -> list[Any]:
            lang = default_lang if cfg.ui.reset_language_on_new_visitor else current.lang
            current.reset(lang)
            merged = merge(
                loc.props(lang),
                create.reset_props(),
                photo.reset_props() if photo else {},
            )
            return [
                current,
                gr.update(value=lang),
                gr.update(selected="create"),
                *pack(managed, merged),
            ]

        def on_idle(current: VisitorSession) -> Any:
            # A timer must not send updates to visible components: Gradio rebuilds them (the
            # webcam restarts, tabs get duplicated). It writes a marker; the reset follows from it.
            return time.monotonic() if current.is_idle(cfg.ui.idle_reset_seconds) else gr.skip()

        def on_idle_reset(current: VisitorSession) -> list[Any]:
            if current.is_idle(cfg.ui.idle_reset_seconds):
                return reset(current)
            return [gr.skip()] * len(outputs)

        def on_language(lang: str, current: VisitorSession) -> list[Any]:
            current.lang = lang
            current.touch()
            return [current, *pack(loc.components, loc.props(lang))]

        new_visitor.click(fn=None, js=TOGGLE_CONFIRM_JS)
        confirm_no.click(fn=None, js=CLOSE_CONFIRM_JS)
        confirm_yes.click(
            reset, [session], outputs, js=CLOSE_CONFIRM_JS, show_progress="hidden", **visibility
        ).then(fn=None, js=SCROLL_TOP_JS)
        gr.Timer(IDLE_CHECK_SECONDS).tick(
            on_idle, [session], [idle_marker], show_progress="hidden", **visibility
        )
        idle_marker.change(on_idle_reset, [session], outputs, show_progress="hidden", **visibility)
        lang_button.click(fn=None, js=TOGGLE_LANG_JS)
        lang_toggle.input(
            on_language,
            [lang_toggle, session],
            [session, *loc.components],
            js=CLOSE_LANG_JS,
            queue=False,
            show_progress="hidden",
            **visibility,
        )
        theme_button.click(fn=None, js=TOGGLE_DARK_JS)
        demo.load(fn=None, js=ZOOM_JS)
        demo.load(fn=None, js=ENTER_JS)

        if cfg.app.default_theme != "system":
            action = "add" if cfg.app.default_theme == "dark" else "remove"
            demo.load(fn=None, js=f"() => document.body.classList.{action}('dark')")

    demo.queue(default_concurrency_limit=DEFAULT_CONCURRENCY)
    return demo


def main() -> None:
    configure_logging()

    loaded = load_env_file()
    if loaded:
        logger.info(
            "Read %d variable(s) from %s: %s", len(loaded), env_file_path(), ", ".join(loaded)
        )
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
    i18n = I18n.load(settings.config.app.languages, settings.config.app.default_language)
    demo.launch(
        theme=build_theme(),
        css=load_css(),
        ssr_mode=False,
        auth=auth,
        auth_message=login_message(i18n, settings.config.app.languages),
        max_file_size="15mb",  # a photo upload is cut off here, before it reaches the app
        footer_links=[],
        mcp_server=False,
        enable_monitoring=False,  # no usage analytics page for logged-in visitors
    )


if __name__ == "__main__":
    main()
