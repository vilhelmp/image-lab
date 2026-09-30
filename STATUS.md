# Status

What exists right now. Plan: [ai_image_lab_project_spec_v2.md](ai_image_lab_project_spec_v2.md). Steps: [todo.md](todo.md).

## Current phase

Phase 1 (skeleton) and Phase 2 (access and limits) are done in code and tests with fakes. Phase 0 is done, including a green CI run on GitHub (`vilhelmp/image-lab`). Phase 1b is nearly done: the Space `magnusp/image-lab` runs on free ZeroGPU (`zero-a10g`), and a 10-minute load test with 10 paced visitors ran clean (before Phase 2 existed). Still open: a real wake-from-sleep measurement, the iPad checks (Phase 1b and the Phase 2 login check; no device yet) and setting the two password secrets on the Space to try login there. Next: Phase 3, real providers and safety. The safety core is built and tested with fakes; the real adapters, Help me and Surprise me are not. No real API key goes in before the Phase 3 safety review.

## Run it

```powershell
$env:DEVELOPMENT_MODE = "true"   # fakes, no keys, no login
uv run python app.py
uv run pytest
```

To try login and the admin tab with fakes, also set `WORKSHOP_PASSWORD` and `ADMIN_PASSWORD` (20+ characters, different). Log in as `workshop` or `admin`; only `admin` sees the Status tab.

## What works

The Create tab runs end to end with fakes: text box with rotating placeholder (the challenge plus three examples), six style tiles (tap again to deselect), format choice, Create button, result image with download. Also working: Swedish/English toggle, light/dark toggle, "Så funkar det" panel (static steps), "Ny besökare" reset, and idle auto-reset (default 180 s, counted from the last tap or keystroke). Errors show friendly localized messages.
- Project setup: `pyproject.toml` (Gradio 6.28.0 pinned), `.python-version` 3.12, `uv.lock`, generated `requirements.txt`, `.env.example`, `.gitignore`, `.gitattributes`, MIT `LICENSE`, `README.md` with HF Spaces frontmatter.
- Empty package layout under `src/`, plus `config/`, `locales/`, `assets/style_thumbs/`.
- `scripts/check_versions.py` (also run as a test) fails if the Gradio pin or Python version drifts from the README frontmatter.
- GitHub Actions workflow `.github/workflows/ci.yml`.
- Copilot customizations: [AGENTS.md](AGENTS.md), provider and UI/locale instructions, `add-model-or-provider` skill, `safety-reviewer` agent, [DEVELOPMENT.md](DEVELOPMENT.md).
- [todo.md](todo.md) created.
- Phase 1 code: `src/config.py` (validated YAML settings), `src/i18n.py` with `locales/sv.json` and `en.json`, `src/errors.py` (typed errors), provider contracts and fakes in `src/providers/`, `src/services/` (`prompts.py` composer, `safety.py` input validation, `session.py` visitor state, `generation.py` pipeline: validate, compose, moderate prompt, generate, moderate image, fail closed), UI in `src/ui/`, and `app.py`.
- 99 tests with fakes only. Safety reviewed with `@safety-reviewer`; findings fixed or added to [todo.md](todo.md).
- Phase 3 safety core (fakes only): `SafetyService` in `src/services/safety.py` runs the moderation API and the workshop policy check in parallel on the final prompt, checks the output image, and can vet LLM text. Everything fails closed: an error, timeout, malformed reply (retried once) or missing verdict stops the create. A moderation flag wins over a policy failure, and a policy refusal stands even if moderation failed. The policy reply is a `{allowed, category, rewrite}` JSON; unknown categories count as `other`; the character setting (`allow | redirect | block`) and `offer_safe_rewrite` have the last word over the LLM; sexual, minors, violence, hate and self-harm never get an alternative. A suggested alternative is cleaned, length-limited and moderated before it is shown as a tappable card. Moderation results use a fixed internal code set (`ModerationCode`). `tests/safety_cases.yaml` holds 40 SV and EN cases, replayed in CI with table-driven fakes; `scripts/run_safety_cases.py` runs them against the real services once the adapters exist. In development mode the fake policy check reacts to the markers `[real person]`, `[character]`, `[minors]` and `[malformed]`. 
- Phase 3 OpenAI adapters (mocked HTTP in tests): `src/providers/http.py` (shared POST with retries on 429, 500, 502, 503, 504 and timeouts, max 2, jitter, hard total deadline, typed errors, nothing sensitive logged), `openai_moderation.py` (`omni-moderation-latest`, categories mapped to the fixed code set, any true category counts as flagged, malformed replies raise) and `openai_text.py` (`gpt-6-luna` through chat completions with a strict JSON schema per task, `reasoning_effort: none`). One `OPENAI_API_KEY` covers both. The safety service now also runs the policy check on its suggested alternative, treats a contradictory verdict as unusable, and retries a malformed reply once. `scripts/run_safety_cases.py` builds only the moderator and text provider, so it needs just `OPENAI_API_KEY`. `build_providers` still raises outside development mode until the image adapters exist. 269 tests.170 tests.
- Phase 2: `src/services/access.py` (login users, password rules, admin check), `src/services/limits.py` (reserve, reconcile or release under one `threading.Lock`; per-device cooldown counted from the previous start; hourly cap; global per-minute rate; concurrent-generation slots; kill switch; stats), `src/ui/admin_tab.py` (admin-only Status tab: usage, spend, last 10 minutes, median time per model, Pause, Reset with confirm), a `CooldownError` with SV and EN messages, and a per-browser device id in `gr.BrowserState`, stored hashed in logs. The generation pipeline reserves before moderation and the provider call and releases on failure; an image that was generated stays counted even if the output check refuses it. Checked in a real browser: login, Create, Pause and the admin tab. Safety reviewed; findings fixed.

## Not done

Everything from Phase 3 on: no real providers or moderation (fakes only), no Help me, Surprise me, edit chips, Compare tab, style thumbnails, or "What did the model receive?". Login has not been tried on the Space or on an iPad yet. See [todo.md](todo.md).

## Decisions and deviations from the spec

- `requirements.txt` is pinned to LF line endings in `.gitattributes` so the CI diff check matches on Windows and Linux.
- No `scripts/export_requirements.sh` fallback: `uv export --prune gradio` works with the installed uv.
- `development_mode` is `false` in `config/app.yaml` (fail safe). The env var `DEVELOPMENT_MODE=true` overrides it, and startup refuses it on a Hugging Face Space (`SPACE_ID` set) only when real secrets are also set, so the fake-only skeleton can be deployed for the ZeroGPU check (spec §18.1).
- Extra config keys not in spec §16: `style_fragments` (English prompt text per style), `ui.reset_language_on_new_visitor`, `safety.max_input_chars`, `app.fake_delay_seconds`. `safety.fail_closed` cannot be set to false.
- Added `src/services/session.py` (per-visitor state in `gr.State`), not in the spec §4 layout.
- `TextProvider` has one generic `complete_json(task, system, user)` method; helper prompts will live in `prompts.py`, not in adapters.
- Language names come from each locale file (`lang.name`), so adding a language needs only one new JSON file.
- Generated images are removed from Gradio's temp cache after 10 minutes (`delete_cache`).
- Gradio events use `api_visibility="private"`, so the Gradio client cannot call them and the API docs link is gone (`footer_links=[]`). `access.expose_api` (env `EXPOSE_API`) lifts this for `scripts/load_test.py`; startup refuses it outside development mode. Startup also refuses to run with real keys and `access.enabled: false`.
- In development mode login is off unless both passwords are set, so login can be tried with fakes. Passwords are no longer in the list of real secrets that block development mode on a Space.
- Device ids are stored in the browser and are unsigned, so someone with the workshop password could invent ids to dodge the per-device cooldown. The global per-minute rate and the budget still apply. The kill switch and counters are in memory and reset on a Space restart.
- `device_cooldown_seconds` is 5 and counts from the start of the previous Create, so a normal visitor never waits.
- ZeroGPU refuses to start a Space with no `@spaces.GPU` function, so `app.py` defines a never-called no-op one when the `spaces` package is present (only on the Space). The app itself never uses a GPU.
- The Space installs `gradio[oauth,mcp]`, whose `mcp` extra caps pydantic at 2.12.5. `pyproject.toml` therefore pins `gradio[mcp,oauth]==6.28.0` so `requirements.txt` matches, and CI dry-runs the Space's install (`scripts/check_space_install.py`).
- The local `.venv` lives in the project again. OneDrive locks files inside it and corrupted it once, so keep OneDrive paused or exclude `.venv` from syncing; otherwise set `UV_PROJECT_ENVIRONMENT` to a folder under `%LOCALAPPDATA%`.
