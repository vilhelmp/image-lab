---
name: add-model-or-provider
description: 'Extend AI Image Lab config-driven content: add an image, edit or text model, a new provider, an edit chip, or a new language. Use when asked to add a model, enable a fal or Hugging Face model, register a provider, update models.yaml with api_model and hf_model, add a one-tap edit chip, or add a language such as Norwegian or German.'
argument-hint: 'What to add, e.g. "fal model for text in images", "edit chip: black and white", "language: no"'
---

# Extend models, providers, chips and languages

Spec: [§5 Providers and models](../../../ai_image_lab_project_spec_v2.md), §3.4 (chips), §14 (localisation). Keep each change config-only where possible.

## Pick the case

| Request | Section |
|---|---|
| New model, existing provider | A (config only) |
| New provider | A and B; also follow [providers.instructions.md](../../instructions/providers.instructions.md) |
| New edit chip | C |
| New language | D |

Finish every case with "Done when" at the end.

## A. Add a model (config only)

1. **Verify facts first.** Model names and prices in the spec are placeholders marked `<verify>`. Confirm the current model ID, per-image price and whether it supports editing. Do not invent IDs; ask the user if unverifiable.
2. **Add the entry to `config/models.yaml`** under `image_models`, `edit_models` or `text_models`:
   - `label` and `description` in every configured language, describing what visitors notice (fast, detailed, good at text), never brand names.
   - `provider`, `api_model` (fal) and `hf_model` (HF Hub ID). Without `hf_model` the model is hidden when `image_backend: hf`; omit it only if no HF route exists.
   - `est_cost_usd`, `enabled`, and `translate_to_english` only if Swedish prompts perform poorly.
   - Change `defaults` only if the user wants it as a default.
3. Update `tests/test_config.py` if the entry adds a new case (for example a model without `hf_model`).

## B. Add a provider

1. Add `src/providers/<name>.py` implementing `ImageProvider` / `EditProvider` from `src/providers/base.py`. Register it in config validation and require its secret at startup only when selected. Add the secret name to `.env.example`.
2. Add or extend the fake in `src/providers/fake.py` so `development_mode: true` works with no keys.
3. Add adapter tests with mocked `httpx`: bytes returned, typed errors, retries only on 429/5xx/timeouts. Add a smoke path in `tests/test_generation_flow.py`.

## C. Add an edit chip

1. Add the chip key to `ui.edit_chips` in `config/app.yaml`.
2. Choose the instruction type:
   - **Static** (default): a fixed short instruction in config, sent to the edit model; skips the LLM.
   - **LLM-picked** (like "new setting"): uses `edit_instruction(chip_key, current_prompt, lang)` in `src/services/prompts.py`; the chosen specifics are shown to the visitor.
3. Add the chip label to `locales/sv.json` and `locales/en.json` with identical keys.
4. Keep the chip subject-preserving: it sends the current image plus the instruction to the edit model. The fallback (rewrite and regenerate, labelled "Ny version") must still work when no edit model is available.
5. Add or extend a test in `tests/test_prompts.py` or `tests/test_generation_flow.py`. The chip's resulting prompt or instruction is moderated like any other.

## D. Add a language

1. Create `locales/<code>.json` by copying `locales/en.json` and translating every value. Keys must match exactly.
2. Add the code to `app.languages` in `config/app.yaml`.
3. Add translations wherever labels are keyed by language: `config/models.yaml` (`label`, `description`), `ui.challenge` in `config/app.yaml`, and style, chip and error strings.
4. LLM helpers receive the selected language; confirm `improve`, `surprise` and `edit_instruction` handle it. Add allow and block cases for the language to `tests/safety_cases.yaml`.
5. Ensure the locale key-parity test in `tests/test_config.py` covers the new file.

## Done when

- `uv run pytest` passes with fakes and no secrets.
- Models work under both `image_backend: fal` and `hf`, or are deliberately hidden in `hf`.
- Locale files have identical keys, and no visible string is hard-coded in `src/ui/`.
- No brand names in visitor-facing labels, and no hard-coded model IDs in code.
