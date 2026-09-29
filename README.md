---
title: AI Image Lab
sdk: gradio
sdk_version: "6.28.0"
python_version: "3.12"
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
