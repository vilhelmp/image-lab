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

## Privacy

The app stores no prompts or images, and its logs hold only timestamps, model, outcome, latency, cost estimate, a refusal code and a hashed device id. With real keys, each description a visitor types (and each generated image) is sent to external providers: OpenAI for moderation and the text helpers, and Hugging Face Inference Providers (or fal) for image generation. Those providers process the requests under their own terms and retention policies. Tell participants before they start, and check the providers' terms if children take part.

The optional **Photo studio** tab sends a visitor's own photo (often their face) to OpenAI for the image safety check and, via Hugging Face, to the image provider for restyling. The photo is shrunk, stripped of metadata and kept in the app's cache for a few minutes only. The tab is off until an admin ticks "Photo studio is open to visitors" on the Status tab, and the visitor must tick a consent box that names the external services. Decide with the parents or the school whether to open it.
