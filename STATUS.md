# Status

What exists right now. Plan: [ai_image_lab_project_spec_v2.md](ai_image_lab_project_spec_v2.md). Steps: [todo.md](todo.md).

## Current phase

Phase 1 (skeleton) is done. Phase 0 has one open item: the first CI run on GitHub. Next: Phase 1b (early ZeroGPU hosting check), then Phase 2, access and limits.

## Run it

```powershell
$env:DEVELOPMENT_MODE = "true"   # fakes, no keys, no auth
uv run python app.py
uv run pytest
```

## What works

The Create tab runs end to end with fakes: text box with rotating placeholder (the challenge plus three examples), six style tiles (tap again to deselect), format choice, Create button, result image with download. Also working: Swedish/English toggle, light/dark toggle, "Så funkar det" panel (static steps), "Ny besökare" reset, and idle auto-reset (default 180 s, counted from the last tap or keystroke). Errors show friendly localized messages.
- Project setup: `pyproject.toml` (Gradio 6.28.0 pinned), `.python-version` 3.12, `uv.lock`, generated `requirements.txt`, `.env.example`, `.gitignore`, `.gitattributes`, MIT `LICENSE`, `README.md` with HF Spaces frontmatter.
- Empty package layout under `src/`, plus `config/`, `locales/`, `assets/style_thumbs/`.
- `scripts/check_versions.py` (also run as a test) fails if the Gradio pin or Python version drifts from the README frontmatter.
- GitHub Actions workflow `.github/workflows/ci.yml`.
- Copilot customizations: [AGENTS.md](AGENTS.md), provider and UI/locale instructions, `add-model-or-provider` skill, `safety-reviewer` agent, [DEVELOPMENT.md](DEVELOPMENT.md).
- [todo.md](todo.md) created.
- Phase 1 code: `src/config.py` (validated YAML settings), `src/i18n.py` with `locales/sv.json` and `en.json`, `src/errors.py` (typed errors), provider contracts and fakes in `src/providers/`, `src/services/` (`prompts.py` composer, `safety.py` input validation, `session.py` visitor state, `generation.py` pipeline: validate, compose, moderate prompt, generate, moderate image, fail closed), UI in `src/ui/`, and `app.py`.
- 58 tests with fakes only. Safety reviewed with `@safety-reviewer`; findings fixed or added to [todo.md](todo.md).

## Not done

Everything from Phase 2 on: no auth, budget or device limits, no real providers or moderation (fakes only), no Help me, Surprise me, edit chips, Compare tab, admin tab, style thumbnails, or "What did the model receive?". See [todo.md](todo.md).

## Decisions and deviations from the spec

- `requirements.txt` is pinned to LF line endings in `.gitattributes` so the CI diff check matches on Windows and Linux.
- No `scripts/export_requirements.sh` fallback: `uv export --prune gradio` works with the installed uv.
- `development_mode` is `false` in `config/app.yaml` (fail safe). The env var `DEVELOPMENT_MODE=true` overrides it, and startup refuses it on a Hugging Face Space (`SPACE_ID` set) only when real secrets are also set, so the fake-only skeleton can be deployed for the ZeroGPU check (spec §18.1).
- Extra config keys not in spec §16: `style_fragments` (English prompt text per style), `ui.reset_language_on_new_visitor`, `safety.max_input_chars`, `app.fake_delay_seconds`. `safety.fail_closed` cannot be set to false.
- Added `src/services/session.py` (per-visitor state in `gr.State`), not in the spec §4 layout.
- `TextProvider` has one generic `complete_json(task, system, user)` method; helper prompts will live in `prompts.py`, not in adapters.
- Language names come from each locale file (`lang.name`), so adding a language needs only one new JSON file.
- Generated images are removed from Gradio's temp cache after 10 minutes (`delete_cache`).
- Known: the Gradio footer and internal API endpoints are still visible; Phase 2 hides them.
- The Space installs `gradio[oauth,mcp]`, whose `mcp` extra caps pydantic at 2.12.5. `pyproject.toml` therefore pins `gradio[mcp,oauth]==6.28.0` so `requirements.txt` matches, and CI dry-runs the Space's install (`scripts/check_space_install.py`).
- The local `.venv` must live outside OneDrive (OneDrive locks files and corrupts it). Set `UV_PROJECT_ENVIRONMENT` to a folder under `%LOCALAPPDATA%`.
