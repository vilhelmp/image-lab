---
description: "Use when writing or changing Gradio UI code (tabs, components, theme, CSS) or visitor-facing strings in locales. Covers thin callbacks, locale key parity and iPad tap-target rules."
applyTo: "src/ui/**, locales/**"
---
# UI and locales

Layout and behaviour: [spec §3](../../ai_image_lab_project_spec_v2.md) and §14.

- Callbacks stay thin: build request, call a service in `src/services/`, render. No business rules, limit checks, moderation or provider calls in `src/ui/`.
- Every visible string comes from `locales/sv.json` and `locales/en.json` via `i18n.py`. No hard-coded text, including button labels, placeholders and error messages.
- Keys must be identical in both locale files. Add or remove a key in both in the same change; a unit test fails otherwise.
- Tap targets are at least 48 px, with large text and high contrast. Put sizing in the single small CSS file, not inline.
- Show at most one primary action at a time. Disable the triggering button and edit chips while generating.
- Show typed-error messages from `errors.py` only. Never show raw provider errors or moderation categories.
- Pass the selected language to every LLM helper call.
- Admin-only UI (`admin_tab.py`) is gated by `gr.Request.username`; do not rely on hiding it alone.
- No custom JS frameworks. Test layouts in landscape and portrait, light and dark.
