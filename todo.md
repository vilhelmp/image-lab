# TODO

Progress tracker for AI Image Lab. Plan: [ai_image_lab_project_spec_v2.md](ai_image_lab_project_spec_v2.md) (change only when warranted). Current state: [STATUS.md](STATUS.md). Tick a box only when the work is done and its tests pass.

Phases follow spec §20. Phase 2 must be finished before real API keys are added in phase 3.

## Phase 0: Project setup

- [x] `pyproject.toml` with pinned `gradio==X.Y.Z`, dev group (pytest, pytest-asyncio, ruff)
- [x] `.python-version` (3.12), `uv.lock` committed
- [x] Repo layout from spec §4 (`src/`, `config/`, `locales/`, `assets/`, `tests/`)
- [x] `.env.example`, `.gitignore`, MIT `LICENSE`
- [x] README.md with HF Spaces frontmatter (`sdk_version` = gradio pin, `python_version` = `.python-version`)
- [x] `scripts/export_requirements.sh` fallback if `uv export --prune` is unavailable (not needed: `--prune` works in uv 0.8.12)
- [x] Generate `requirements.txt` (never edit by hand)
- [x] GitHub Actions: `uv sync --locked`, `pytest` with fakes, requirements diff check, version-pin check (spec §18.4). First green run: CI #1 on `vilhelmp/image-lab`, commit d8ebb7a
- [x] Confirm the pinned Gradio 6.28.0 and Python are supported on ZeroGPU (docs list Gradio 4+, Python 3.12.12 and 3.10.13). If HF does not accept `python_version: "3.12"`, pin `3.12.12` in `.python-version` and the README, and check the pin script still passes (spec §18.3)

## Phase 1: Skeleton (runs locally, no keys)

- [x] `src/config.py`: Pydantic settings, YAML loading, startup validation (spec §16)
- [x] `config/app.yaml` and `config/models.yaml` with placeholder `<verify>` models
- [x] `src/i18n.py`, `locales/sv.json`, `locales/en.json`
- [x] `src/errors.py`: typed errors mapped to localized messages (spec §15)
- [x] `src/providers/base.py`: `ImageProvider`, `EditProvider`, `TextProvider`, `Moderator`, request and result models
- [x] `src/providers/fake.py`: fakes for image, edit, text and moderation, with configurable delay
- [x] `src/services/prompts.py`: pure composer (style + optional translation), unit tested
- [x] `src/services/generation.py`: orchestration with fakes
- [x] `src/ui/theme.py` and small CSS file
- [x] `src/ui/components.py`: localizer and update helpers (style tiles, format control, status and image live in `create_tab.py`)
- [x] `src/ui/create_tab.py`: text box, style tiles, format, Create button, rotating placeholder with challenge
- [x] Footer with privacy line and "How does it work?" panel shell
- [x] "New visitor" button and idle auto-reset with `gr.Timer`
- [x] Language toggle and theme toggle
- [x] `app.py` wiring; `development_mode: true` (or env `DEVELOPMENT_MODE=true`) uses fakes and disables auth
- [x] Tests: `test_config.py`, `test_prompts.py`, locale key parity

## Phase 1b: Early hosting check on ZeroGPU (spec §18.1)

Deploy the fake-provider skeleton early, on the free account, before building further. Decision rule: if every check passes, stay on the free account; if anything is flaky, subscribe to PRO for the event month and switch the Space to CPU Basic.

- [x] Create the Gradio SDK Space and push the skeleton with `DEVELOPMENT_MODE=true` as a Space variable (no secrets set; startup allows this). Space is `magnusp/image-lab`; first build failed on a pydantic pin conflict, fixed by pinning `gradio[mcp,oauth]`; the Space now runs on `zero-a10g`
- [x] Check the Space starts on ZeroGPU with no `@spaces.GPU` function. It failed with "No @spaces.GPU function detected", so `app.py` now has a never-called no-op `@spaces.GPU` function. If startup fails with a missing-GPU-function error, add a never-called no-op `@spaces.GPU` function (needs the `spaces` package) and note it in STATUS
- [x] Pinned Gradio and Python versions build and run on ZeroGPU
- [ ] Measure wake-from-sleep time and note the sleep behaviour for the README
- [x] Load test with fakes: about 10 concurrent Creates for 10 minutes without errors or stalls (`scripts/load_test.py`: 459 creates, 0 failed, 0 stalls, median 3.1 s; Compare does not exist yet; repeat in Phase 5)
- [ ] Open the direct `.hf.space` URL on a real iPad and confirm the app is usable
- [x] Record the outcome (free ZeroGPU or PRO with CPU Basic) in STATUS.md
- [x] Do not enable the Storage Bucket option

## Phase 2: Access and limits

- [x] Auth for `workshop` and `admin` users from env vars; fail startup if missing (spec §11). Passwords must be 20+ characters and differ; in development mode, login turns on only when both are set
- [x] Hide API docs link (`footer_links=[]`); `ssr_mode=False`; every event uses `api_visibility="private"` so the Gradio client cannot call it (`access.expose_api` or env `EXPOSE_API` lifts this for load tests, development mode only)
- [x] `src/services/limits.py`: reservation (reserve, call, reconcile or release) under one lock type
- [x] Compare reserves 2 images atomically (`reserve(count=2)` tested; the Compare tab itself is Phase 5)
- [x] Global semaphore and per-minute rate limit
- [x] Device ID via `gr.BrowserState`; cooldown and optional hourly cap; pass the hashed ID as `device_hash` in `CreateRequest` for logs
- [x] Kill switch (Pause generation)
- [x] Startup warning that budget counters start at zero
- [x] `src/ui/admin_tab.py`: usage, spend, latency, errors and refusals (counts only), Pause, Reset counters with confirm
- [x] Tests: `test_limits.py` (20 concurrent tasks stay under ceiling, failure releases, compare reserves 2, cooldown, kill switch), `test_auth.py`
- [ ] ZeroGPU check on a real iPad: login works and survives normal use on the direct `.hf.space` URL (spec §18.1)

## Phase 3: Real providers and safety

- [ ] `src/providers/fal.py` image adapter
- [ ] `src/providers/hf_inference.py` image adapter (parity with fal)
- [ ] `image_backend: fal | hf` switch; hide models without `hf_model`; startup secret validation
- [ ] `src/providers/openai_text.py`: improve, surprise, policy check with structured JSON, one retry, graceful fallback. Done: the adapter (strict JSON schema per task, `gpt-6-luna`) and the policy check with one retry on malformed replies. Open: the Help me and Surprise me service wiring
- [x] `src/providers/openai_moderation.py`: text and image moderation
- [x] `src/services/safety.py`: final-prompt moderation and policy check in parallel (`asyncio.gather`), fail closed on errors and malformed output
- [ ] Moderate every LLM output (translation, rewrite, help-me, surprise) before composing or showing it, including `SafetyRefusalError.rewrite`. Done: `SafetyService.check_generated_text` and the moderated rewrite. Open: wire it into translation, Help me and Surprise me when they exist
- [x] Adapters map provider moderation categories to a fixed internal code set and raise on empty or unknown results
- [ ] Keep `FakeModerator` only with fake image providers (development mode on a Space with real secrets is already refused at startup). `build_providers` only builds fakes in development mode today; re-check when the real providers land
- [x] Output-image moderation before display
- [x] Character policy (`allow | redirect | block`) and safe-rewrite card
- [x] Retries only on 429, selected 5xx and timeouts, max 2, with jitter (`src/providers/http.py`, hard total deadline). Before reusing it for image POSTs: do not retry a request that may already have been billed
- [ ] Help me and Surprise me buttons with Undo
- [x] `tests/safety_cases.yaml` (about 40 SV and EN cases) and `test_safety.py`. The CI replay uses table-driven fakes, so it checks the pipeline logic, not any model's judgement
- [ ] Script to run safety cases against real services and print pass or fail. `scripts/run_safety_cases.py` is written; it needs the real adapters and keys to run
- [ ] Verify real model IDs, prices and latency; replace `<verify>` placeholders
- [ ] Logging check: no prompts, image bytes or secrets
- [ ] Run `@safety-reviewer` on the whole flow before adding real API keys

## Phase 4: Edit chips

- [ ] Edit adapter for fal, and HF where supported
- [ ] Chip config in `app.yaml`, static instructions, and LLM-picked "new setting"
- [ ] Chips send current image plus instruction to the edit model; previous image goes to history
- [ ] Fallback to rewrite and regenerate labelled "Ny version" when no edit model
- [ ] "Another version" button
- [ ] Recent images strip (last 6 per visitor)
- [ ] Post-generation layout: large image, collapsed inputs
- [ ] Tests for edit path, fallback, and moderation of chip output

## Phase 5: Compare

- [ ] `src/ui/compare_tab.py`: shared text box, styles, format
- [ ] Two model cards with friendly names and descriptions; block identical choice unless allowed
- [ ] Concurrent generation with isolated failures
- [ ] Side by side in landscape, stacked in portrait; model name and seconds
- [ ] "Why are they different?" expander
- [ ] Tests: one side fails or is refused while the other shows
- [ ] ZeroGPU check: 5 devices running Compare at once (about 10 concurrent outbound API calls) for 10 minutes without errors or stalls (spec §18.1)

## Phase 6: Polish

- [ ] Style thumbnails in `assets/style_thumbs/`
- [ ] iPad CSS: 48 px tap targets, landscape and portrait, light and dark
- [ ] "How does it work?" panel: four steps, prompt anatomy, "What did the model receive?"
- [ ] Status messages while generating; buttons disabled
- [ ] Latency tuning against spec §7 targets
- [ ] Test on a real iPad Safari with the pinned Gradio version, the direct `.hf.space` URL and the hardware used on the day

## Phase 7: Ship

- [ ] README: screenshot, Duplicate Space steps, 5-minute quick start, provider privacy note
- [ ] README states the hardware tested (ZeroGPU on a free account and/or CPU Basic on PRO) and the Space's sleep and wake behaviour (spec §18.5)
- [ ] Workshop checklist in README (spec §19)
- [ ] Optional QR handoff (`features.qr_handoff`), documented as an unauthenticated route
- [ ] Deploy to the HF Gradio SDK Space on the hardware chosen in Phase 1b; set secrets and turn off `DEVELOPMENT_MODE`; Storage Bucket stays off
- [ ] Full smoke test: Create and Compare with fakes in CI

## Workshop readiness (spec §19 and §21)

- [ ] Hosting decision from Phase 1b still holds (free ZeroGPU, or PRO with the Space switched to CPU Basic)
- [ ] Prepaid credits loaded, auto-recharge off
- [ ] Fal vs HF backend comparison on the same 20 prompts; backend chosen
- [ ] Swedish prompt quality tested per model; translation decided
- [ ] Five devices doing Compare for 10 minutes; admin tab watched
- [ ] Incognito browser blocked without password
- [ ] AirDrop tested (and QR if enabled)
- [ ] Repo and Space settings frozen
- [ ] Final `@safety-reviewer` pass
- [ ] All 15 acceptance criteria in spec §21 met

## Notes

Record decisions, blockers and open questions here.

- 2026-09-29: Restart on ZeroGPU with a fully cached build took a few seconds (all dependency layers CACHED). This is not a true wake from sleep; ZeroGPU sleep time is set automatically. Measure a real wake after the Space has been idle, and plan to open the Space about 15 minutes before the workshop.
- No iPad available yet. The iPad items stay open until a real device (or a borrowed one) is tested.
- 2026-09-29: Phase 2 safety review (`@safety-reviewer`): fixed a budget refund after a paid image, the cancelled-request outcome, per-device state leaks and startup guards. Accepted: a workshop-password holder can invent device ids to dodge the per-device cooldown (ids are unsigned); the global per-minute rate and the budget still apply. The kill switch is in memory, so a Space restart resumes generation. `max_generations_per_minute: 30` may be tight for 10+ iPads; tune it after the Phase 5 test.
- Load testing the Space now needs `EXPOSE_API=true` as a Space variable and `LOAD_TEST_PASSWORD` in the shell; remove `EXPOSE_API` afterwards.
- 2026-09-30: Phase 3 safety review (`@safety-reviewer`) found one HIGH (a contradictory policy verdict such as allowed with a category was accepted), now fixed with tests, plus request deadline, alternative policy check, error typing and `.env` loader fixes. Open risks: OpenAI image moderation only covers sexual, violence and self-harm, so hate imagery, minors-specific sexual content, harassment, real-person likeness and trademarked characters in OUTPUT images rely on the prompt checks and the image provider's own safety settings; consider lower `category_scores` thresholds after the first real safety-cases run. The parent-folder `.env` may be shared with other projects, so check the startup log line for which file and names were read.
- 2026-09-29: The first load test (10 visitors, pauses of 0-3 s, about 2.3 Creates/s from one IP) got 21% failures, all HTTP 429 from the `.hf.space` edge (image downloads and the event stream). The paced run (pauses of 0-20 s, about 0.8 Creates/s) had none. Unknown whether HF throttles per IP; venue iPads will likely share one IP, so watch for 429s in the Phase 5 test with several devices.
