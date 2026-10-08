# AI Image Lab

Gradio app on a Hugging Face Gradio SDK Space (ZeroGPU on a free account, CPU Basic on PRO; the app never requests a GPU) for a supervised workshop on shared iPads. All inference is via external APIs. The full spec is [ai_image_lab_project_spec_v2.md](ai_image_lab_project_spec_v2.md); read the relevant section before implementing. The repo is spec-only so far, so the layout in spec §4 is the target structure.

## Priorities when the spec is ambiguous

Visitor speed and ease > safety > predictable cost > workshop reliability > reusability > code elegance.

## Commands (target, spec §18.2)

```bash
uv sync
uv run python app.py      # development_mode: true uses fakes, no keys needed
uv run pytest
uv export --no-hashes --no-dev --no-emit-project --prune gradio > requirements.txt
```

## Conventions

- Python 3.11+, type hints, Pydantic models, async `httpx` (one reused client per provider).
- Gradio callbacks stay thin: build request, call a service, render. No business rules in `src/ui/`, and no provider-specific logic outside `src/providers/`.
- All visible strings come from `locales/sv.json` and `locales/en.json`. Keys must match in both files.
- Everything workshop-specific (models, limits, styles, chips, challenge text) lives in `config/*.yaml`. Adding a model from an existing provider must be config-only.
- Model labels describe what visitors notice (fast, detailed), not brand names.
- Providers return image bytes; download provider URLs immediately and never pass them to the browser.
- Every provider needs a fake in `providers/fake.py`. Tests and CI use fakes only and need no secrets.

## Safety and limits (non-negotiable)

- Moderate the final composed prompt and the output image, not just raw user text. Fail closed if a check errors.
- Never show raw provider errors or moderation categories to visitors. Use the typed errors in `errors.py`.
- Never log full prompts, image bytes, or secrets. Logs hold only timestamps, model, outcome, latency, cost estimate, refusal code and hashed device ID.
- Budget uses reserve, call, then reconcile or release under a single lock type. A Compare reserves 2 images atomically. Prepaid provider credit is the hard cap; in-memory counters only pace.
- Implement access control and limits (phase 2) before adding real API keys (phase 3).

## Pitfalls

- HF Spaces installs from a generated `requirements.txt`; never edit it by hand.
- The Space also installs `gradio[oauth,mcp]`, `spaces` and `torch`, so `pyproject.toml` pins `gradio[mcp,oauth]==X` and `scripts/check_space_install.py` dry-runs the Space's resolution. Run it after changing dependencies.
- The `gradio` pin in `pyproject.toml` must equal `sdk_version` in the README frontmatter. `.python-version` must equal the README `python_version`. Both must be versions supported on ZeroGPU (Gradio 4+, Python 3.12.12 or 3.10.13).
- No Docker Space and no Storage Bucket. If the optional QR route does not fit the Gradio SDK Space, drop QR.
- HF rejects pushes with plain binary files. Binaries such as `assets/library/*.webp` must be tracked by Git LFS (`.gitattributes`); add new binary types the same way before committing them. `git lfs checkout` restores real bytes after a clone or rewrite.
- Gradio rebuilds components that a timer tick updates (webcam restarts, tabs get duplicated), and it lists the next tab twice if anything but a `gr.Tab` sits between tabs inside `gr.Tabs`. Timers write only a hidden marker (`gr.State` or the `#photo-flag` textbox) or run JS; show and hide by a body class, not by `visible`, and create timers outside the `Tabs` block. `tests/test_photo_tab.py` guards both.
- Free Space disk is ephemeral and counters reset on restart, so do not rely on SQLite or files for state.
- Per-visitor limits use `gr.BrowserState` device IDs, not Gradio sessions.
- iPad Safari must use the direct `.hf.space` URL because auth breaks inside the Hugging Face iframe.
- Both fal and HF backends must work; `image_backend: hf` needs only `HF_TOKEN`.
- Model names and prices in the spec are placeholders marked `<verify>`.

## Project files

- [ai_image_lab_project_spec_v2.md](ai_image_lab_project_spec_v2.md) is the plan. Change it only when a change is warranted, and say why.
- [todo.md](todo.md) tracks the steps. Tick a box only when the work is done and its tests pass.
- [STATUS.md](STATUS.md) describes what exists now. Update it when a step is finished.
- `README.md` is for visitors and forkers and holds the HF Spaces frontmatter; do not use it for progress.

## Routing

- Before editing `src/providers/**`, `src/ui/**` or `locales/**`, read the matching file in [.github/instructions/](.github/instructions/).
- To add a model, provider, edit chip or language, use the [add-model-or-provider](.github/skills/add-model-or-provider/SKILL.md) skill instead of improvising.
- After changing any safety-relevant code, run the `safety-reviewer` subagent on the changed files and fix CRITICAL/HIGH findings before finishing. Safety-relevant means `src/services/generation.py`, `safety.py`, `prompts.py`, `limits.py`, `src/errors.py`, `src/providers/**`, or any logging.
- Run the `safety-reviewer` on the whole flow before adding real API keys (phase 3) and before the workshop freeze.
