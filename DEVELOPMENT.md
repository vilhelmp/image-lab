# Development guide

How to implement things in AI Image Lab with Copilot. The spec is [ai_image_lab_project_spec_v2.md](ai_image_lab_project_spec_v2.md); rules for agents are in [AGENTS.md](AGENTS.md).

## Copilot customizations in this repo

| Type | File | When it applies |
|---|---|---|
| Always-on rules and routing | [AGENTS.md](AGENTS.md) | Every request |
| Provider rules | [providers.instructions.md](.github/instructions/providers.instructions.md) | Editing `src/providers/**` |
| UI and locale rules | [ui-locales.instructions.md](.github/instructions/ui-locales.instructions.md) | Editing `src/ui/**` or `locales/**` |
| Add model, provider, chip or language | [add-model-or-provider](.github/skills/add-model-or-provider/SKILL.md) | `/add-model-or-provider`, or ask in plain words |
| Safety review | [safety-reviewer](.github/agents/safety-reviewer.agent.md) | `@safety-reviewer`, or run as a subagent |

## Typical workflow

1. **Pick the phase.** Work in the order of spec §20. Do not add real API keys (phase 3) before access control and limits (phase 2) work.
2. **Read the spec section** for what you are building, for example §6 for the prompt pipeline or §10 for limits. Ask Copilot to read it first.
3. **Implement in small steps**, keeping to the layout in spec §4:
   - Services in `src/services/` hold the business rules.
   - Provider code stays in `src/providers/`.
   - UI in `src/ui/` only builds a request, calls a service and renders.
   - Visible text goes in `locales/sv.json` and `locales/en.json`.
   - Workshop-specific values go in `config/*.yaml`.
4. **Write the tests with the code**, using fakes only (spec §17). No test may need a secret.
5. **Run locally** with `development_mode: true` (fakes, no keys):
   ```bash
   uv run python app.py
   uv run pytest
   ```
6. **Review safety-relevant changes.** Run `@safety-reviewer` on the changed files if you touched generation, safety, prompts, limits, errors, providers or logging. Fix CRITICAL and HIGH findings before merging.
7. **Check the sync rules** before pushing (also enforced by CI, spec §18.3):
   - Regenerate `requirements.txt`, never edit it by hand:
     ```bash
     uv export --no-hashes --no-dev --no-emit-project --prune gradio > requirements.txt
     ```
   - The `gradio` pin in `pyproject.toml` equals `sdk_version` in the README frontmatter.
   - `.python-version` equals the README `python_version`.

## Examples

### Add a model from an existing provider

1. Run `/add-model-or-provider fal model for text in images`.
2. Give it the verified model IDs and price (spec values are `<verify>` placeholders).
3. Confirm the `models.yaml` entry has `api_model` and `hf_model`, labels in both languages, and no brand names.
4. Run `uv run pytest`.

### Add a new provider

1. Run `/add-model-or-provider new provider: <name>`.
2. Write the adapter in `src/providers/<name>.py` following the provider instructions: bytes only, typed errors, retries only on 429, 5xx and timeouts.
3. Add its fake in `fake.py`, adapter tests with mocked `httpx`, and the secret name in `.env.example`.
4. Run `@safety-reviewer review src/providers/<name>.py`.

### Add an edit chip

1. Run `/add-model-or-provider edit chip: black and white`.
2. Add the key to `ui.edit_chips`, choose a static or LLM-picked instruction, and add the label to both locale files.
3. Test the edit path and the fallback ("Ny version") when no edit model exists.

### Add a language

1. Run `/add-model-or-provider language: no`.
2. Create `locales/no.json` with the same keys as the others, add it to `app.languages`, and translate model labels and the challenge text.
3. Add safety cases for the language in `tests/safety_cases.yaml`.

### Change the safety pipeline or limits

1. Read spec §8 (safety) or §10 (limits) first.
2. Keep to the rules: moderate the final prompt and the output image, fail closed, reserve then reconcile or release under one lock type.
3. Update `tests/test_safety.py` or `tests/test_limits.py` in the same change.
4. Run `@safety-reviewer` on the changed files.

## Before the workshop

- Run `@safety-reviewer` on the whole flow before adding real API keys, and again before the freeze.
- Follow the checklist in spec §19.
