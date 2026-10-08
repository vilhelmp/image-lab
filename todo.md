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
- [x] GitHub Actions: `uv sync --locked`, `pytest` with fakes, requirements diff check, version-pin check (spec §18.4). First green run: CI #1 on `vilhelmp/image-lab`, commit d8ebb7a. CI failed from the LFS commit on because checkout did not fetch LFS files; `lfs: true` added 2026-10-01, so confirm the next run is green
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
- [x] `src/ui/create_tab.py`: text box, style tiles, Create button, rotating placeholder with challenge (the format picker was dropped: images are always square)
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
- [x] Measure wake-from-sleep time and note the sleep behaviour for the README. 2026-10-01: a paused Space, restarted by hand, took about 1 min 5 s to reach the login page. Plan: open the Space about 15 minutes before the workshop and make one real generation to warm it; the README still needs the sleep note
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

- [ ] `src/providers/fal.py` image adapter (raw REST at `https://fal.run/<id>`, `Authorization: Key`, `post_json(idempotent=False)` plus an image download)
- [x] `src/providers/hf_inference.py` image adapter (`AsyncInferenceClient`, `hf_model` and `hf_provider` from config, PNG bytes, billing-safe retries, 402 maps to `BudgetReachedError`). First live image 2026-10-01: FLUX.1-schnell via fal-ai, 5.0 s. `scripts/try_image.py` generates one image and prints latency and estimated cost
- [x] `image_backend: fal | hf` switch in config and the factory (`build_image`); models without `hf_model` are hidden; startup secret validation. Default is now `hf`; the fal branch of the factory is not built yet
- [x] `src/providers/openai_text.py`: improve, surprise, policy check with structured JSON, one retry, graceful fallback (Help me and Surprise me are wired through `HelperService`)
- [x] `src/providers/openai_moderation.py`: text and image moderation
- [x] `src/services/safety.py`: final-prompt moderation and policy check in parallel (`asyncio.gather`), fail closed on errors and malformed output
- [x] Moderate every LLM output (Help me, Surprise me, rewrite) before showing it, including `SafetyRefusalError.rewrite`. `check_generated_text` now runs moderation and the policy check. Translation does not exist yet; wire it in if it is added
- [x] Adapters map provider moderation categories to a fixed internal code set and raise on empty or unknown results
- [ ] Keep `FakeModerator` only with fake image providers (development mode on a Space with real secrets is already refused at startup). `build_providers` only builds fakes in development mode today; re-check when the real providers land
- [x] Output-image moderation before display
- [x] Character policy (`allow | redirect | block`) and safe-rewrite card
- [x] Retries only on 429, selected 5xx and timeouts, max 2, with jitter (`src/providers/http.py`, hard total deadline). Before reusing it for image POSTs: do not retry a request that may already have been billed
- [x] Help me and Surprise me buttons with Undo (`src/services/helpers.py`, `src/ui/helper_row.py`). Every reply passes moderation and the policy check; a refused idea gets the usual refusal; a failed Surprise falls back to a library prompt; per-device 2 s interval and the pause switch apply
- [x] `tests/safety_cases.yaml` (about 40 SV and EN cases) and `test_safety.py`. The CI replay uses table-driven fakes, so it checks the pipeline logic, not any model's judgement
- [x] Script to run safety cases against real services and print pass or fail. First real run 2026-09-30 with OpenAI moderation and `gpt-6-luna`: 40 of 41 passed, 0 failed, 1 known issue (see Notes)
- [ ] Verify real model IDs, prices and latency; replace `<verify>` placeholders. Done: text, moderation and image model ids (from the HF provider mapping); schnell latency 5.0 s and 9.5 s (target p50 6 s, so measure more runs) Open: latency of `detailed` and `artistic`, the actual prices of those two (fal bills per megapixel, rounded up, so schnell is $0.003 per image: measured $0.13 for 44 requests, and `est_cost_usd` for `fast` is now 0.003; dev and Qwen-Image are probably about $0.025 and $0.02, still estimated higher), the edit model (Phase 4)
- [ ] Logging check: no prompts, image bytes or secrets. Done: adapter log lines carry only model key, status code and exception class; `src/logging_setup.py` keeps httpx, httpcore and huggingface_hub at WARNING. Open: a full pass over the running app's logs
- [ ] Image adapter follow-ups from the safety review: the SDK's blocking image download in its worker thread has no explicit timeout (a hung thread would linger); `hf_provider: null` routes to "auto", so require `hf_provider` in config or accept the cost drift; the adapter's 45 s budget starts after moderation while the outer Create timeout is also 45 s
- [x] Real-keys check before the Space: `scripts/check_real_flow.py` passed 2026-09-30 (startup validation, a real image in 8 to 9 s, a cached example, three refusals, Help me, Surprise me, 40 log lines and 0 leaks). Helpers take 2.6 to 5.6 s (target 3 s); the first refusal of a named politician took 11 to 14 s twice, so watch policy-check latency against its 15 s timeout
- [x] `@safety-reviewer` on the whole flow: no CRITICAL or HIGH code findings; the items below are the operational gate
- [ ] Before the Space gets keys: set `WORKSHOP_PASSWORD` and `ADMIN_PASSWORD` in `../.env` first (20+ characters, different; the check found them too short), then on the Space add all secrets and delete the `DEVELOPMENT_MODE` and `EXPOSE_API` variables in the same change
- [ ] Before the Space gets keys: confirm HF billing has a spending limit or prepaid credit only, prepay OpenAI with auto-recharge off, keep `limits.max_cost_usd` at or below what is prepaid, use fine-grained tokens (HF: inference calls only)
- [ ] Confirm live that `enable_safety_checker` reaches fal through the HF router; run one flagged image through `check_image` live
- [ ] Optional hardening: treat OpenAI `insufficient_quota` like the HF 402 (pause); `queue(max_size=...)`; `analytics_enabled=False`; a test that raw API calls are refused when `expose_api` is false
- [ ] Run `@safety-reviewer` on the whole flow before adding real API keys (done 2026-09-30; repeat before the workshop freeze)

## Phase 4: Edit chips

- [x] Edit adapter over HF `image_to_image`: `HFEditProvider` (shares `HFRunner` with the image adapter), `EditModel.hf_provider`, `build_edit` in the factory (None until an edit model has `hf_model`). `scripts/bakeoff.py` compares models (t2i or edit) with latency and a contact sheet
- [x] Choose the edit model from the bake-off and set it in `config/models.yaml`. Decision: klein-4B on fal-ai (`fal-ai/flux-2/klein/4b/distilled/edit`, Apache-2.0). Bake-off 2026-10-01 on one cached example, three chips: klein-4B 3.9 to 5.2 s, klein-9B 4.1 to 5.8 s, Kontext-dev 8.6 to 9.4 s, Qwen-Image-Edit-2511 13.9 to 14.8 s. By eye klein-4B is among the best; Qwen is better only on "as a painting", which a more specific chip instruction may fix. Licences (HF model cards, 2026-10-01): Apache-2.0 are FLUX.1-schnell, Z-Image-Turbo, Qwen-Image, Qwen-Image-Edit(-2511) and FLUX.2-klein-4B; non-commercial are FLUX.1-dev, FLUX.1-Kontext-dev, FLUX.2-klein-9B and Ideogram 4; Krea-2-Turbo has its own community licence
- [x] Chip config in `app.yaml` (`edit_chips`: label per language, static `instruction` or `llm: true`), static instructions, and LLM-picked "new setting" (`HelperService.edit_instruction`, moderated and policy-checked)
- [x] Chips send current image plus instruction to the edit model (`GenerationService.edit`, `src/ui/chips.py`); previous image goes to history. Create and edit share `spend.paid_call`; output goes through `check_image`; a result that arrives after "New visitor" is dropped (session epoch). Edit model: FLUX.2-klein-4B on fal-ai
- [ ] Fallback to rewrite and regenerate labelled "Ny version" when no edit model (chips are hidden when there is no edit provider, so the fallback is not built yet)
- [ ] "Another version" button
- [ ] Recent images strip (last 6 per visitor)
- [x] Post-generation layout: replaced by a two-column Create tab (controls left, image and edit panel right, fixed slots so nothing jumps); the edit panel appears after the first image
- [x] Before/after switch for the last edit (`VisitorSession.previous`, `Switch before / after`)
- [x] Tests for the edit path and moderation of chip output (`tests/test_edit_chips.py`, smoke tests). Open: an edit case in `tests/safety_cases.yaml`; check the klein edit cost on the billing page (estimate 0.01); the second "new setting" tap describes the original scene because an edited image keeps the original prompt

## Phase 4b: Photo studio (extra, not in the spec)

- [x] Photo studio (2026-10-08): a tab with webcam or upload, five styles (felt puppet, rag doll, clay, animated movie, comic book; `photo_styles` in `app.yaml`, brand-free instructions), restyled by the edit model. Off at start; the admin Status tab switches it on (`RuntimeFlags`). Consent tick naming the external services, enforced by the server; the photo is moderated before it is sent (OpenAI), shrunk and stripped of EXIF; `max_file_size` 15 MB. Safety review done. Open: try it on a real iPad (camera permission, front or back camera, the direct `.hf.space` URL), judge the quality on real faces and tune the instructions (a bake-off with a real photo), decide whether the style names should stay brand-free

## Phase 5: Compare

- [ ] `src/ui/compare_tab.py`: shared text box, styles
- [ ] Two model cards with friendly names and descriptions; block identical choice unless allowed
- [ ] Concurrent generation with isolated failures
- [ ] Side by side in landscape, stacked in portrait; model name and seconds
- [ ] "Why are they different?" expander
- [ ] Tests: one side fails or is refused while the other shows
- [ ] ZeroGPU check: 5 devices running Compare at once (about 10 concurrent outbound API calls) for 10 minutes without errors or stalls (spec §18.1)

## Phase 6: Polish

- [x] Ideas popup: 7 themed groups of example prompts (`config/prompt_library.yaml`), tap to fill the text box; an unchanged prompt with no style shows its cached image instantly and free (`assets/library/*.webp`, tied to the texts by `config/prompt_library.lock.json`). Built with `scripts/build_library.py`
- [ ] Ideas popup: check the popup on a real iPad in landscape and portrait. The contact sheet of the 37 images was reviewed and committed; on small screens the categories are now wrapping buttons and each example has its text under the picture (2026-10-08)
- [ ] Ideas popup, later: optional per-prompt model (for example `detailed`) for the photo examples; record cached hits in the admin counts; Help me and Surprise me could draw from the library

- [ ] Style thumbnails in `assets/style_thumbs/`
- [ ] iPad CSS: tap targets are now at least 44 px (Apple's minimum), light and dark, a lighter design with smaller text and pill buttons, a restyled login page; checked in a desktop browser only. Open: landscape and portrait on a real iPad
- [x] How it works tab (replaces the accordion): a pipeline of eight steps lit one at a time with Next and Back, colour-coded by who does the work (you, plain code, language model, image model, safety check)
- [ ] "What did the model receive?": show the visitor's final English prompt (and the translation) in the How it works tab or under the image. The final prompt is already stored per image
- [x] Status messages while generating; buttons disabled (a busy overlay on the result for Create, edits and photos, and on the text box for Help me and Give me an idea)
- [x] Tap the image to zoom; Enter in the text box creates; New visitor asks for confirmation; language and light/dark are two small header buttons
- [x] Clearer labels and section headings (examples, improve my text, give me an idea, style, edit panel)
- [ ] Latency tuning against spec §7 targets
- [ ] Test on a real iPad Safari with the pinned Gradio version, the direct `.hf.space` URL and the hardware used on the day

## Phase 7: Ship

- [ ] README: screenshot, Duplicate Space steps, 5-minute quick start, provider privacy note
- [ ] README states the hardware tested (ZeroGPU on a free account and/or CPU Basic on PRO) and the Space's sleep and wake behaviour (spec §18.5)
- [ ] Workshop checklist in README (spec §19)
- [ ] Optional QR handoff (`features.qr_handoff`), documented as an unauthenticated route
- [ ] Deploy to the HF Gradio SDK Space on the hardware chosen in Phase 1b; set secrets and turn off `DEVELOPMENT_MODE`; Storage Bucket stays off. Done 2026-09-30: secrets set, real image generated on `magnusp-image-lab.hf.space`. Open: admin tab and Space logs check, iPad test, wake time, billing limits confirmed
- [ ] Full smoke test: Create and Compare with fakes in CI

## Workshop readiness (spec §19 and §21)

- [ ] Hosting decision from Phase 1b still holds. 2026-10-08: the account is now PRO, so switch the Space to CPU Basic (the app never uses a GPU), then run one Create and one edit. Free hardware sleeps after 48 h: open the Space about 15 minutes before, or use CPU upgrade ($0.03/hour) for the day
- [ ] Prepaid credits loaded, auto-recharge off
- [ ] Fal vs HF backend comparison on the same 20 prompts; backend chosen. Decision so far: `image_backend: hf` (fal-ai through Hugging Face); `fal.py` is not built and is optional
- [x] Image model: keep `fast` (FLUX.1-schnell, Apache-2.0). 2026-10-08 bake-off against `quality` (FLUX.1-dev): 5.0 to 5.3 s against 5.8 to 6.4 s, about 13 times the price ($0.04 against $0.003), a modest visual gain, and a non-commercial licence. The `quality` model stays configured and unused
- [x] Swedish prompt quality: translation to English is on for all image models (a Swedish fox prompt gave no fox); re-check on the Space after deploy
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
- 2026-09-30: First real safety-cases run (`python -m scripts.run_safety_cases`): every injection, real-person and character case behaved, and each redirect returned a usable alternative after the policy prompt was changed to forbid naming the original. Known issue: OpenAI moderation flags the Swedish "Skjuta iväg en raket till månen" as violence ("skjuta" = shoot), so visitors typing it get the friendly refusal. Accepted for now; watch for more Swedish false positives in the workshop rehearsal. Also note: a restricted OpenAI key needs Chat completions and Moderations both set to Request; a key lacking Chat completions gave `missing_scope`.
- 2026-09-30: Phase 3 safety review (`@safety-reviewer`) found one HIGH (a contradictory policy verdict such as allowed with a category was accepted), now fixed with tests, plus request deadline, alternative policy check, error typing and `.env` loader fixes. Open risks: OpenAI image moderation only covers sexual, violence and self-harm, so hate imagery, minors-specific sexual content, harassment, real-person likeness and trademarked characters in OUTPUT images rely on the prompt checks and the image provider's own safety settings; consider lower `category_scores` thresholds after the first real safety-cases run. The parent-folder `.env` may be shared with other projects, so check the startup log line for which file and names were read.
- 2026-09-29: The first load test (10 visitors, pauses of 0-3 s, about 2.3 Creates/s from one IP) got 21% failures, all HTTP 429 from the `.hf.space` edge (image downloads and the event stream). The paced run (pauses of 0-20 s, about 0.8 Creates/s) had none. Unknown whether HF throttles per IP; venue iPads will likely share one IP, so watch for 429s in the Phase 5 test with several devices.
- 2026-10-08: A colleague on Edge lost the typed prompt after a Create, and one Swedish prompt was refused once and passed the second time. Neither could be reproduced locally. The prompt is now sent back to the text box when Create finishes, and the logs say which check refused (`refusal stage=policy`, `text_moderation` or `image_moderation`, with a code only). If it happens again, read the Space log line next to that request. Idea if it is the image check: one automatic retry with a new image instead of showing the refusal (costs one more image).
- 2026-10-08: The Compare tab (Phase 5) needs two models worth comparing. With `fast` kept and FLUX.1-dev not cleared for visitors, a Compare would have to use an Apache-2.0 alternative such as Qwen-Image (`text_expert`) or Z-Image-Turbo. Decide whether Compare is worth building before the workshop; the rest of the app does not depend on it.
- 2026-10-08: Photo studio safety review: the consent text must name every external service (OpenAI moderation, Hugging Face, the image provider), and the tick belongs to one photo (it resets when the photo changes). Gradio's own upload preprocessing rejects a non-image before our code runs, so a visitor may see Gradio's generic error for that.
