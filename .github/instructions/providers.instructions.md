---
description: "Use when writing or changing image, edit, text or moderation provider adapters (fal, HF Inference, OpenAI, fakes). Covers the adapter contract, typed errors, safety flags and retry rules."
applyTo: "src/providers/**"
---
# Provider adapters

Contract and rationale: [spec §5](../../ai_image_lab_project_spec_v2.md) and §7 (retries).

- Return `bytes` in `ImageResult.image`. Download provider URLs immediately; never return or log a URL.
- Translate every provider failure to a typed error from `src/errors.py`. Never let raw provider exceptions or messages escape the adapter.
- Set the strictest provider-side safety parameters available, and do not expose them as options.
- Retry only on 429, selected 5xx and network timeouts. Max 2 retries, exponential backoff with jitter, and never beyond the hard timeout (Create 45 s, Edit/Compare 60 s, text 15 s).
- Do not retry 4xx client errors or safety refusals; map them to the matching typed error.
- One reused `httpx.AsyncClient` per provider.
- Adapters own auth, aspect-to-dimension mapping, polling and error translation. Model names come from `config/models.yaml`, never hard-coded.
- Never log prompts, image bytes or secrets. Log model, outcome, latency and cost estimate only.
- Every new provider needs a matching fake in `fake.py`, and fal and HF adapters must stay at parity (`image_backend` is config-only).
