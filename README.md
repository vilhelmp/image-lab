---
title: AI Image Lab
sdk: gradio
sdk_version: "6.28.0"
python_version: "3.12"
emoji: 🌍
colorFrom: green
colorTo: red
app_file: app.py
pinned: false
license: mit
---

# AI Image Lab

A Gradio app for a supervised workshop where visitors describe an image in Swedish or English, generate it, tweak it with one-tap edits and compare two models. All inference goes through external APIs.

The app is under construction. See [STATUS.md](STATUS.md) for what exists and [todo.md](todo.md) for the plan.

## Quick start

```bash
uv sync
uv run pytest
DEVELOPMENT_MODE=true uv run python app.py   # fakes, no API keys needed
```

On Windows PowerShell, set `$env:DEVELOPMENT_MODE = "true"` before `uv run python app.py`.

To try the login and the admin tab with fakes, also set `WORKSHOP_PASSWORD` and `ADMIN_PASSWORD` (10 or more characters, different from each other). Log in as `workshop` or `admin`; only `admin` sees the Status tab.

Everything workshop-specific is in `config/*.yaml` (models, limits, styles, edit chips, challenge text) and `locales/*.json` (all visible text, Swedish and English). Adding a model from an existing provider is a config change only; see [DEVELOPMENT.md](DEVELOPMENT.md).

## Run it for real

The app calls external APIs, so it needs these secrets in a `.env` file or as Space secrets:

| Secret | What for |
| --- | --- |
| `HF_TOKEN` | Image generation and edits through Hugging Face Inference Providers (`image_backend: hf`) |
| `OPENAI_API_KEY` | Text safety check, image safety check and the text helpers |
| `WORKSHOP_PASSWORD` | The shared login for visitors' iPads (user `workshop`) |
| `ADMIN_PASSWORD` | The supervisor's login (user `admin`) |

Prepaid provider credit is the hard spending cap: the app's own budget counters live in memory and start at zero on every restart. Set billing limits at both providers before the workshop and top up beforehand.

## Deploy to a Hugging Face Space

1. Create a Gradio SDK Space and push this repository to it (`git push space main`). Binary files such as `assets/library/*.webp` are tracked with Git LFS.
2. Add the four secrets above in the Space settings. Delete the `DEVELOPMENT_MODE` and `EXPOSE_API` variables if they exist.
3. The app never uses a GPU, so the cheapest CPU hardware is enough (CPU Basic on a PRO account). It was tested on CPU Basic and, earlier, on ZeroGPU on a free account.
4. If you change dependencies, regenerate `requirements.txt` with `uv export --no-hashes --no-dev --no-emit-project --prune gradio > requirements.txt` and run `uv run python scripts/check_space_install.py`. The `gradio` pin in `pyproject.toml` must equal `sdk_version` above, and `.python-version` must equal `python_version`.
5. Give the iPads the direct `https://<owner>-<space>.hf.space` URL. Login does not work inside the Hugging Face page frame in iPad Safari.

### Sleep and wake

- Free hardware goes to sleep after 48 hours without visitors. Waking a sleeping or restarted Space took about one minute to reach the login page when measured.
- Open the direct URL about 15 minutes before the workshop and make one real image and one edit, so the Space is awake and the connections are warm.
- Every restart logs everyone out and resets the budget counters. Restarts happen on a crash, on `git push` and when secrets or variables change, so freeze the repository and settings before the day.
- Setting a CPU upgrade for the day avoids sleep during the workshop.

## Model choice

`config/models.yaml` lists the models. `defaults.create_model` picks the one visitors get for Create. The default is `fast` (FLUX.1-schnell, Apache-2.0, about $0.003 per image). A more detailed model, `quality` (FLUX.1-dev, about $0.04 per image and a non-commercial licence), is configured as `defaults.high_quality_model`. The admin account switches it on for new images with the "High-quality model" tick on the Status tab; it starts off and a restart turns it off again. To make it the default instead, set `create_model: quality`.

## Privacy

The app stores no prompts or images, and its logs hold only timestamps, model, outcome, latency, cost estimate, a refusal code and a hashed device id. With real keys, each description a visitor types (and each generated image) is sent to external providers: OpenAI for moderation and the text helpers, and Hugging Face Inference Providers (or fal) for image generation. Those providers process the requests under their own terms and retention policies. Tell participants before they start, and check the providers' terms if children take part.

The optional **Photo studio** tab sends a visitor's own photo (often their face) to OpenAI for the image safety check and, via Hugging Face, to the image provider for restyling. The photo is shrunk, stripped of metadata and kept in the app's cache for a few minutes only. The tab is off until an admin ticks "Photo studio is open to visitors" on the Status tab, and the visitor must tick a consent box that names the external services. Decide with the parents or the school whether to open it.
