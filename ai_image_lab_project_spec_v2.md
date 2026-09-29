# AI Image Lab – Project Specification v2 (for GitHub Copilot)

> **Revision note.** v2 is written for a one-off, supervised 2–3 hour workshop on 4–5 shared iPads, and is also meant to be a clean, reusable open-source repo that others can duplicate. Compared with v1 it trades breadth for speed and simplicity: fewer tabs, fewer buttons, one aggregator for image models, image *editing* instead of prompt re-writing for iteration, and budget/security mechanisms that work with how Hugging Face Spaces and iPad Safari actually behave.
>
> When this spec is ambiguous, optimise in this order: **(1) visitor speed and ease, (2) safety, (3) predictable cost, (4) workshop reliability, (5) reusability, (6) code elegance.**

---

## 1. Summary

A Gradio web app, hosted on a CPU-only Hugging Face Space, where workshop visitors describe an image in Swedish or English, optionally get AI help with the description, generate an image, tweak it with one-tap edits, and compare how two models interpret the same idea.

All generation happens through external APIs. The Space itself does no inference.

### What changed from v1 (and why)

| v1 | v2 | Reason |
|---|---|---|
| Separate BFL + OpenAI image adapters | One aggregator adapter (fal.ai default, HF Inference Providers alternative) | One key, one bill, many models, faster Compare setup |
| Post-image actions rewrite the prompt and regenerate | Post-image actions call an image **edit** model on the current image | Regenerating changes the whole picture; visitors read that as "it didn't listen" |
| 3–4 tabs (Create, Compare, Learn, Challenge) | 2 tabs (Create, Compare) + "How does it work?" panel + rotating challenge placeholder | Drop-in visitors stay 3–5 minutes and never reach tab 3 |
| 4 AI help buttons + 8 styles + model dropdown on Create | 1 "Help me" button, 1 "Surprise me", 6 style tiles, no model picker on Create | 10-second comprehension target |
| Per-session limits keyed on a Gradio session | Per-**device** limits via `gr.BrowserState`, plus global rate limit | Sessions reset on reload and all iPads share one login |
| SQLite budget counter "survives restarts" | In-memory counter for pacing; **prepaid provider credits are the hard cap** | Free Space disk is ephemeral; counter resets exactly when things go wrong |
| QR link to a Gradio-served file | Save via long-press/AirDrop by default; QR is an optional flag with an explicitly unauthenticated route | Visitors' phones aren't logged in, so Gradio file URLs fail |
| Moderate user input only | Moderate the **final composed prompt** and the **output image** | LLM rewrites, styles and translation change what reaches the model |
| No handling of visitor turnover | "New visitor" button + idle auto-reset | Next visitor otherwise sees previous visitor's images and prompts |

---

## 2. Non-goals

User accounts, persistent galleries, databases, payment, model training, GPU inference, advanced generation controls (CFG, steps, seed, sampler, LoRA, scheduler), voting/leaderboards, a custom admin portal, long-term storage of prompts or images.

---

## 3. Visitor experience

### 3.1 Principles

- A first-time visitor (child, elderly, never used AI) generates their first image **without instruction within ~30 seconds**.
- At most **one primary action** visible at a time. Everything else is secondary or hidden.
- Large tap targets (≥ 48 px), large text, high contrast, no jargon.
- Images dominate the screen once they exist.
- If a feature can't be explained in one short sentence, it doesn't belong in the default UI.

### 3.2 Layout

Header: app name, one-line subtitle, language toggle (SV/EN), theme toggle. Nothing else.

Two tabs:

1. **Skapa / Create** (default)
2. **Jämför / Compare**

Footer: privacy line, "How does it work? / Så funkar det" expandable panel, **"Ny besökare / New visitor"** button.

### 3.3 Create tab – before generating

1. **Text box**, label "Vad vill du skapa? / What would you like to create?". Placeholder rotates between example ideas. One of the rotating placeholders is the current *workshop challenge* (e.g. "En svensk stad år 2100"), configured in YAML. This replaces v1's Challenge tab.
2. **Two secondary buttons** under the text box:
   - **"Hjälp mig / Help me"** – improves the description (see §6.1). Shows the improved text *in the text box* with a small "Ångra / Undo" link. Never generates automatically.
   - **"Överraska mig / Surprise me"** – fills the box with a complete, family-friendly idea.
3. **Style tiles** – a single row (wraps on portrait) of 6 large tiles with a small example thumbnail each: Foto, Illustration, Målning, 3D, Serie, Retro. One tile is selectable; tapping the selected tile deselects it (= no style).
4. **Format** – a compact segmented control: Kvadrat (default) / Liggande / Stående.
5. **Primary button** – "Skapa bild / Create image". Large, full width.

There is **no model picker** on Create. Create always uses the configured default model, chosen for speed. Model choice lives in Compare, where it is the point.

### 3.4 Create tab – after generating

- Image shown large, replacing the input area's visual weight (inputs stay available above or collapse into a "Ändra beskrivningen / Edit description" row).
- **One-tap edit chips** under the image (configurable list, default 5):
  - "Kvällsljus / Evening light"
  - "Mer lekfull / More playful"
  - "Byt miljö / New setting" (LLM picks a new setting, shown to the user)
  - "Som målning / As a painting"
  - "Enklare / Simpler"
- Each chip sends the **current image** plus a short instruction to the configured **edit model** (§5.2), so the subject stays recognisable. The resulting image replaces the current one; the previous one goes to history.
- If the default model/provider doesn't support editing, chips fall back to prompt rewrite + regenerate, and the UI says "Ny version / New version" instead of implying an edit.
- **"Ny version / Another version"** – regenerates the same prompt.
- **"Ta med bilden / Take it with you"** – see §9.
- **Recent images strip** – the last 6 images of the *current visitor*. Tapping one makes it current again.

### 3.5 Compare tab

- Shared text box (+ "Hjälp mig"), shared style tiles, shared format.
- **Two model pickers** rendered as large tappable cards (not tiny dropdowns), each with a friendly name and a one-sentence description. Identical choice prevented unless `allow_same_model_compare: true`.
- "Jämför / Compare" button runs both requests **concurrently**.
- Results side by side in landscape, stacked in portrait. Under each: model name and generation time in seconds. Cost only if `show_cost_to_visitors: true`.
- Failures isolated: if one side fails or is refused, show a friendly card on that side and the successful image on the other.
- Expandable "Varför blir bilderna olika? / Why are they different?" – three short sentences.
- A compare counts as **two** images for all limits.

### 3.6 "How does it work?" panel (replaces v1 Learn tab)

Collapsible panel, available on both tabs. Contains:

- Four short steps: you described → the app added your style choice → the model interpreted the words → it made a new image from patterns learned in training (it does not search the web or copy an image).
- **Prompt anatomy** mini-explainer: subject, setting, style, light, perspective, mood – with one example sentence where each part is colour-highlighted. Not interactive in the MVP.
- "Vad fick modellen? / What did the model receive?" – shows the final composed prompt for the current image (including any style text and translation). This is the most educational element and costs nothing to build.

### 3.7 Visitor turnover

- **"Ny besökare / New visitor"** button: clears text box, current image, history and edit state; returns to Create; scrolls to top. Does not reset device-level counters.
- **Idle auto-reset**: after `idle_reset_seconds` (default 180) without interaction, the same reset runs. Implement with `gr.Timer` and a last-interaction timestamp in state.
- Language resets to default on New visitor (configurable).

### 3.8 While generating

- Disable the triggering button and the edit chips; show "AI skapar din bild… / Creating your image…".
- Show real status transitions only if the provider exposes them ("Skickar… / Skapar… / Klar!"). No fake percentages.
- Target times (see §7).

---

## 4. Architecture

Keep it small. Abstractions exist only where they serve provider swap, testability or safety.

```text
ai-image-lab/
├── app.py                     # builds UI, wires services, launches with auth
├── README.md                  # includes HF Spaces frontmatter + Duplicate button
├── LICENSE                    # MIT
├── pyproject.toml             # source of truth for dependencies
├── uv.lock                    # committed lockfile
├── .python-version            # e.g. 3.12; must match README python_version
├── requirements.txt           # GENERATED by uv export for HF Spaces; do not edit
├── .env.example
├── config/
│   ├── app.yaml               # features, limits, safety, UI
│   └── models.yaml            # image/edit/LLM models
├── locales/
│   ├── sv.json
│   └── en.json
├── assets/
│   └── style_thumbs/          # small example images for style tiles
├── src/
│   ├── config.py              # Pydantic settings + YAML loading + validation
│   ├── i18n.py
│   ├── ui/
│   │   ├── create_tab.py
│   │   ├── compare_tab.py
│   │   ├── components.py      # style tiles, model cards, chips, status
│   │   ├── admin_tab.py
│   │   └── theme.py           # Gradio theme + small CSS file
│   ├── providers/
│   │   ├── base.py            # ImageProvider, EditProvider, TextProvider, Moderator
│   │   ├── fal.py             # default image + edit provider
│   │   ├── hf_inference.py    # alternative image provider
│   │   ├── openai_text.py     # prompt help + policy check
│   │   ├── openai_moderation.py
│   │   └── fake.py            # all fakes, for dev/tests/CI
│   ├── services/
│   │   ├── generation.py      # orchestrates: limits → moderation → provider → output check
│   │   ├── prompts.py         # composer + LLM helper calls
│   │   ├── safety.py          # pipeline + policy
│   │   ├── limits.py          # budget reservation, rate limit, device limits, kill switch
│   │   └── handoff.py         # optional QR route
│   └── errors.py              # typed errors → localized messages
└── tests/
    ├── test_config.py
    ├── test_limits.py
    ├── test_safety.py
    ├── test_prompts.py
    ├── test_generation_flow.py
    ├── test_auth.py
    └── safety_cases.yaml      # SV + EN prompts with expected allow/block
```

Rules:

- Gradio callbacks stay thin: build request → call service → render.
- No provider-specific logic outside `providers/`.
- No business rules in UI code.
- All visible strings from `locales/`.
- Python 3.11+, type hints, Pydantic for structured data, `httpx` (async) for HTTP unless an official SDK clearly simplifies things.

---

## 5. Providers and models

### 5.1 Interfaces

```python
class ImageRequest(BaseModel):
    prompt: str  # final composed prompt
    model_key: str  # key in models.yaml
    aspect: Literal["square", "landscape", "portrait"]


class EditRequest(BaseModel):
    image: bytes
    instruction: str  # short natural-language edit instruction
    model_key: str


class ImageResult(BaseModel):
    image: bytes  # always bytes; adapters download URLs immediately
    model_key: str
    seconds: float
    est_cost: float


class ImageProvider(ABC):
    async def generate(self, req: ImageRequest) -> ImageResult: ...


class EditProvider(ABC):
    async def edit(self, req: EditRequest) -> ImageResult: ...
```

Adapters own: auth, endpoint calls, aspect → dimensions mapping, polling, retries, error translation to typed errors, downloading result bytes (provider URLs are often short-lived signed URLs), and provider safety parameters (always set to the strictest available).

### 5.2 Service choices

| Need | Default | Alternative | Notes |
|---|---|---|---|
| Image generation | **fal.ai** (one key, many models, fast endpoints) | **HF Inference Providers** via `huggingface_hub.InferenceClient` (one HF token, billed at provider rates) | Both are aggregators; one adapter each covers many models |
| Image editing | fal.ai edit-capable model | Any provider whose model supports image-to-image editing | Fallback to rewrite + regenerate if none configured |
| Prompt help + policy check | OpenAI, small fast model, structured JSON output | Any OpenAI-compatible endpoint (HF, OpenRouter) via `base_url` | Keep `max_tokens` low for latency |
| Moderation (text + image) | OpenAI moderation endpoint | – | Free; accepts images; requires the OpenAI key anyway |

Secrets (env vars / Space Secrets only): `FAL_KEY` and/or `HF_TOKEN` (only the selected `image_backend`'s key is required), `OPENAI_API_KEY`, `WORKSHOP_PASSWORD`, `ADMIN_PASSWORD`.

**Provider parity requirement.** fal.ai is the default for speed and model breadth, but the app must run with **HF Inference Providers only** (just `HF_TOKEN`, no `FAL_KEY`) by changing config alone:

- Both adapters (`fal.py`, `hf_inference.py`) are first-class and built in the same phase.
- Each model entry names its provider; a global override switches all image models to HF:

```yaml
image_backend: fal        # fal | hf  — hf remaps every model to its hf_model value
```

- Every model in `models.yaml` has both `api_model` (fal) and `hf_model` (HF Hub model ID). A model without an `hf_model` is hidden when `image_backend: hf`, and startup logs which ones were hidden.
- Editing via HF is used only where the chosen HF model/provider supports image-to-image editing; otherwise the edit-chip fallback (§3.4) applies automatically.
- Startup validation fails clearly if the selected backend's secret is missing.
- Note: fal is itself one of the providers behind HF Inference Providers, so many fal models are also reachable with an HF token. Going direct to fal is justified only if it's measurably faster, exposes models or parameters HF doesn't, or bills more clearly. The pre-event comparison in §19 decides this.

**Before the event, verify** the current model catalogue, per-image prices, typical latency and Swedish-prompt quality for each configured model. Model names and prices in this spec are placeholders.

### 5.3 models.yaml

```yaml
image_models:
  fast:
    label: { sv: "Snabb", en: "Fast" }
    description: { sv: "Blixtsnabb och bra till det mesta.", en: "Very fast and good for most ideas." }
    provider: fal
    api_model: "<verify: fast text-to-image model>"
    hf_model: "<verify: HF Hub ID of same or equivalent model>"
    est_cost_usd: 0.005
    translate_to_english: false
    enabled: true

  quality:
    label: { sv: "Hög kvalitet", en: "High quality" }
    description: { sv: "Långsammare men mer detaljerad.", en: "Slower but more detailed." }
    provider: fal
    api_model: "<verify: high-quality model>"
    hf_model: "<verify>"
    est_cost_usd: 0.04
    enabled: true

  text_expert:
    label: { sv: "Bra på text i bilder", en: "Good at text in images" }
    description: { sv: "Klarar skyltar och bokstäver bättre.", en: "Handles signs and lettering better." }
    provider: fal
    api_model: "<verify>"
    hf_model: "<verify>"
    est_cost_usd: 0.03
    enabled: true

edit_models:
  default_edit:
    provider: fal
    api_model: "<verify: instruction-based image edit model>"
    hf_model: "<verify, or omit if no HF edit route>"
    est_cost_usd: 0.04
    enabled: true

text_models:
  helper:
    provider: openai
    api_model: "<verify: small fast model>"

defaults:
  create_model: fast
  edit_model: default_edit
  compare_a: fast
  compare_b: quality
```

Model labels describe **what visitors will notice** (fast, detailed, good at text), not brand names. Brand names can appear in the model card's small print and in the "What did the model receive?" panel.

Adding a model from an existing provider = config only. Adding a provider = one adapter file + config.

---

## 6. Prompt pipeline

### 6.1 LLM helpers

All calls return JSON validated with Pydantic; on malformed output, retry once, then fall back to a friendly "Try again" without changing the text box.

- **improve(text, lang)** → `{ "prompt": str }`. Preserve subject and intent; add at most 2–3 concrete visual details (setting, light, perspective, medium); max ~40 words; no "8k, ultra-detailed, cinematic" filler; answer in `lang`; family-friendly.
- **surprise(lang)** → `{ "prompt": str }`. Whimsical, family-friendly, visually concrete, ideally with a Swedish touch. Avoid real people, trademarked characters, politics, violence.
- **edit_instruction(chip_key, current_prompt, lang)** → `{ "instruction": str, "new_prompt": str }`. Used for chips like "New setting" where the LLM must pick specifics. Simple chips (e.g. "Evening light") use static instructions from config and skip the LLM entirely.
- **policy_check(text)** → see §8.

### 6.2 Composer

Pure function, no I/O, fully unit-tested:

```text
final_prompt = user_text
             + style_fragment(style)           # provider-neutral, from config
             + (english translation if model.translate_to_english)
```

The visible text box is never overwritten by style or translation. `final_prompt` is stored per image and shown in "What did the model receive?".

Translation is **off by default** because it adds an LLM round-trip. Turn it on per model only if pre-event testing shows Swedish prompts perform poorly.

---

## 7. Speed

Speed is a feature. Targets, measured click-to-image on workshop Wi-Fi:

| Flow | Target p50 | Hard timeout |
|---|---|---|
| Create with default model | ≤ 6 s | 45 s |
| Edit chip | ≤ 12 s | 60 s |
| Compare (both images) | ≤ slower model + 2 s | 60 s |
| "Help me" / "Surprise me" | ≤ 3 s | 15 s |

Techniques:

- Default Create model is chosen for latency, not maximum quality.
- Run text moderation and the policy check **in parallel** (`asyncio.gather`).
- Output-image moderation runs right after generation; it's the only check on the image path, so keep it.
- Reuse one `httpx.AsyncClient` per provider (connection pooling).
- Download result bytes immediately; don't pass provider URLs to the browser.
- Static edit instructions skip the LLM.
- No translation by default.
- Retries: only on 429 / selected 5xx / network timeouts, max 2, exponential backoff with jitter, and never beyond the hard timeout.
- Gradio queue: `default_concurrency_limit` sized for 5 devices × Compare (≈ 10), plus a global generation semaphore (§10).

---

## 8. Safety

### 8.1 Pipeline

```text
visitor text
  → input validation (length, empty, control chars)
  → compose final prompt (style, translation, LLM rewrite already applied)
  → [parallel] moderation API on final prompt  +  workshop policy check on final prompt
  → provider call with strictest provider safety setting
  → moderation API on output image
  → display
```

Moderate the **final composed prompt**, not just the visitor's raw text. LLM outputs from "Help me" and "Surprise me" also pass through moderation before being shown.

If moderation or the policy check fails to run (timeout, error), **fail closed**: show the "try again" message, don't generate.

### 8.2 Workshop policy (`family` mode)

Block, with a friendly message, anything involving:

- sexual content or sexualised nudity; any sexual content involving minors (no rewrite offered);
- graphic gore or extreme violence;
- hateful or demeaning imagery;
- self-harm imagery;
- **real, identifiable people** – public figures and private individuals (e.g. "my classmate Emma", a named politician). Rewrite suggestion: a fictional character with similar general traits.
- **Trademarked/copyrighted characters** – configurable:

```yaml
safety:
  mode: family
  characters: redirect     # allow | redirect | block
  offer_safe_rewrite: true
```

`redirect` (default) offers "a character inspired by…" instead of the named character. This keeps Compare consistent when one provider would refuse and another wouldn't.

The policy check is a small LLM call with a fixed system prompt returning `{ "allowed": bool, "category": str | null, "rewrite": str | null }`. It complements the moderation API, it doesn't replace it.

### 8.3 Messages

Never show categories, raw provider errors or moderation taxonomy.

- SV: "Den idén passar inte för den här workshopen. Prova gärna en annan!"
- EN: "That idea isn't suitable for this workshop. Try another one!"

If a rewrite exists: "Vill du prova det här istället? / Want to try this instead?" with the rewrite in a tappable card.

### 8.4 Safety test set

`tests/safety_cases.yaml` holds ~40 Swedish and English prompts with expected outcomes: obvious allow, obvious block, tricky benign ("en sjöjungfru", "a bloody Mary cocktail", "barn som badar vid sjön"), real-person, and character cases. A script runs them against the real moderation stack before the event and prints a pass/fail table. The CI version runs against fakes.

---

## 9. Getting images off the iPad

Default (no code beyond a download button):

1. **Long-press the image → Share → AirDrop** to the visitor's iPhone. Staff can help.
2. **Download button** (Gradio's built-in).

Staff clear the iPad Photos/Downloads between sessions if anything was saved locally (checklist item).

Optional, `features.qr_handoff: true`:

- `gr.mount_gradio_app` onto a FastAPI app; add **one unauthenticated route** `/i/{token}` that serves a single image.
- Token: 128-bit random (`secrets.token_urlsafe(16)`); in-memory store; TTL 30 minutes; purge on expiry and on New visitor; no listing endpoint; simple per-IP rate limit.
- QR shown in a modal with "Skanna med din mobil / Scan with your phone".
- This route is a **deliberate hole in the access model**. Document that in the README.
- Images are lost on Space restart. That's acceptable.

---

## 10. Limits and budget

### 10.1 Layers

| Layer | Mechanism | Purpose |
|---|---|---|
| Hard cap | **Prepaid credits** on each provider, loaded with the workshop budget; auto-recharge **off** | The only limit that survives restarts, bugs and leaked passwords |
| Pacing | In-memory global counters with reservation (§10.2) | Stop cleanly with a friendly message before credits run out |
| Burst | Global semaphore (max concurrent generations) + global per-minute rate | Protect stability and credit burn |
| Per device | Device ID in `gr.BrowserState` (localStorage) with cooldown and optional hourly cap | Stop one iPad hogging; survives page reload |
| Kill switch | Admin toggle "Pause generation" | Stop everything instantly during the event |

### 10.2 Reservation

```text
reserve(cost, count) under lock → deny if over max_images or max_cost
call provider
success → reconcile to actual/estimated cost
failure → release reservation
```

Use an `asyncio.Lock` if all generation code paths are async; otherwise a `threading.Lock`. Pick one and make all paths consistent. A compare reserves two images atomically.

Counters reset on restart. Log a clear warning at startup: "Budget counters start at zero. Provider prepaid credit is the hard limit."

### 10.3 Config

```yaml
limits:
  max_images: 1000
  max_cost_usd: 40
  max_concurrent_generations: 6
  max_generations_per_minute: 30
  device_cooldown_seconds: 3
  device_max_images_per_hour: 120    # null = off
```

Budget reached → "Dagens bildbudget är slut. Tack för att du testade AI Image Lab! / Today's image budget has been reached. Thanks for trying AI Image Lab!"

---

## 11. Access control

### 11.1 Mechanism

Gradio built-in auth with two users:

```python
def build_auth(settings) -> list[tuple[str, str]] | None:
    if not settings.access.enabled:
        return None
    workshop = os.environ.get("WORKSHOP_PASSWORD")
    admin = os.environ.get("ADMIN_PASSWORD")
    if not workshop or not admin:
        raise RuntimeError("Access enabled but WORKSHOP_PASSWORD/ADMIN_PASSWORD missing.")
    return [("workshop", workshop), ("admin", admin)]


demo.launch(
    auth=build_auth(settings), ssr_mode=False
)  # hide API docs link per the pinned Gradio version's option
```

- The **admin** user sees an extra "Status" tab (§12), detected via `gr.Request.username`.
- Passwords: long and random (≥ 20 characters). Gradio auth has no brute-force protection.
- Hide the "Use via API" link and API docs (option name depends on the pinned Gradio version).
- Space stays **public**; the URL is treated as non-secret. A private Space would require every visitor to have a Hugging Face login.

### 11.2 iPad Safari requirements

- **Always open the direct URL** `https://<owner>-<space>.hf.space`, never `huggingface.co/spaces/<owner>/<space>`. Gradio auth inside the Hugging Face iframe relies on third-party cookies, which Safari blocks by default; the login then loops.
- Login sessions live in server memory. **Any Space restart logs out every iPad.** Restarts happen on crash, on `git push`, and on changing secrets or variables. So: freeze the repo and settings on the day, and keep the workshop password available to staff (not taped to the iPad).
- Test the login flow on a real iPad in the pinned Gradio version before the event.

### 11.3 Kiosk

- Add the direct URL to the iPad home screen or keep one Safari tab.
- Use **Guided Access** (Settings → Accessibility) so visitors can't leave Safari.
- Disable auto-lock during the event.

---

## 12. Admin status tab

Visible only to the `admin` user. Read-mostly, one screen:

- images used / max, estimated spend / max;
- generations in the last 10 minutes; current in-flight count;
- errors and refusals in the last 10 minutes (counts only, no prompts);
- p50 latency per model;
- **Pause generation** toggle (kill switch);
- **Reset counters** button (with confirm).

No prompts, no images, no per-visitor data.

---

## 13. Privacy

- No login for visitors, no names, no email, no persistent prompts or images.
- Server logs: timestamps, model, outcome, latency, cost estimate, refusal category code, device ID hash. **Never** full prompts, image bytes or secrets.
- Footer: "Bilder och beskrivningar sparas inte av appen. / Images and descriptions are not stored by the app."
- README notes that external providers process requests under their own terms.
- New visitor + idle reset prevent the next visitor from seeing the previous one's work.

---

## 14. Localisation and theme

- `locales/sv.json`, `locales/en.json`; a unit test fails if keys differ between files.
- The selected language is passed to all LLM helper calls.
- Light / dark via Gradio theme; one small CSS file for tap targets, tile layout and image sizing. No custom JS frameworks.
- Adding a language = one JSON file + one line in `app.yaml`.

---

## 15. Error handling

Typed errors in `errors.py` map to localized messages:

| Error | SV message |
|---|---|
| Timeout | "Bildtjänsten svarade inte i tid. Försök gärna igen." |
| Rate limited / busy | "Många skapar bilder just nu. Försök igen om en liten stund." |
| Budget reached | "Dagens bildbudget är slut. Tack för att du testade AI Image Lab!" |
| Paused by admin | "Bildskapandet är pausat en liten stund." |
| Safety | see §8.3 |
| Anything else | "Något gick fel. Försök igen." |

Full exceptions are logged server-side only.

---

## 16. Configuration (app.yaml)

```yaml
app:
  name: "AI Image Lab"
  default_language: sv
  languages: [sv, en]
  default_theme: system
  development_mode: false        # true = fake providers, no keys needed

features:
  compare_tab: true
  help_me: true
  surprise_me: true
  edit_chips: true
  qr_handoff: false
  show_cost_to_visitors: false
  allow_same_model_compare: false

ui:
  idle_reset_seconds: 180
  history_size: 6
  styles: [photo, illustration, painting, 3d, comic, retro]
  edit_chips: [evening_light, more_playful, new_setting, as_painting, simpler]
  challenge: { sv: "En svensk stad år 2100", en: "A Swedish city in the year 2100" }

access:
  enabled: true

safety:
  mode: family
  characters: redirect
  offer_safe_rewrite: true
  fail_closed: true

limits: { ... see §10.3 }
```

Config is validated at startup with Pydantic; invalid default models, missing enabled providers or missing secrets stop startup with a clear message.

---

## 17. Fakes and tests

Fake providers (`providers/fake.py`) for image, edit, text and moderation. Fake image = coloured placeholder with the prompt text, returned after a configurable delay to exercise loading states. `development_mode: true` uses fakes and disables auth.

Minimum tests:

- **Config**: loads; invalid default model rejected; locale keys match; `image_backend: hf` hides models without `hf_model` and requires only `HF_TOKEN`.
- **Composer**: style and translation don't alter visible text; deterministic output.
- **Limits**: reservation under 20 concurrent tasks never exceeds the ceiling; failure releases; compare reserves 2; device cooldown; kill switch blocks.
- **Safety**: blocked prompt never reaches the image provider; moderation failure fails closed; flagged output image isn't displayed; LLM helper output is moderated.
- **Prompts**: malformed LLM JSON → one retry → graceful fallback.
- **Auth**: disabled in dev returns `None`; missing password fails startup; secrets absent from config serialisation and logs.
- **Smoke**: app builds and completes one Create and one Compare with fakes.

GitHub Actions runs tests on push with fakes only (no secrets).

---
## 18. Deployment

### 18.1 Hosting

- Hugging Face **Gradio SDK Space**. Docker Spaces require PRO and are not used; if the optional QR route (§9) can't be built in the Gradio SDK Space, drop QR rather than switching to Docker.
- **Hardware:**
  - **Free account:** Gradio Spaces run on **ZeroGPU**; CPU Basic is not available. The app never requests a GPU (no `@spaces.GPU` functions), so it runs on the CPU side and uses no GPU quota.
  - **PRO account:** CPU Basic is available and is the preferred hardware for the event.
  - Decision rule: deploy the fake-provider skeleton (phase 1) on ZeroGPU early and run the ZeroGPU checks below. If all pass, stay on the free account. If anything is flaky, subscribe to PRO for the event month and switch the Space to CPU Basic.
- **ZeroGPU checks** (on a real iPad, direct `.hf.space` URL):
  - the pinned Gradio and Python versions build and run on ZeroGPU;
  - login works and survives normal use;
  - 5 devices running Compare simultaneously (≈ 10 concurrent outbound API calls) for 10 minutes without errors or stalls;
  - wake-from-sleep time is acceptable, and sleep behaviour is noted in the README.
- Do not enable the Storage Bucket option. Budget counters are in-memory by design; prepaid provider credits are the hard cap (§10).
- Secrets set in Space settings.
- Spaces sleep after a period of inactivity: open the app about an hour before the event to wake it.
- Test on iPad Safari with exactly the pinned Gradio version and the hardware used on the day.

### 18.2 Environment and dependency management

Use **uv** for local development. No conda (no heavy compiled scientific dependencies) and no Docker for local dev (keeps forking simple).

- `pyproject.toml` is the single source of truth; `uv.lock` is committed.
- `.python-version` pins Python (e.g. 3.12). Dev tools (pytest, pytest-asyncio, ruff) go in a `dev` dependency group.
- Local quick start:

```bash
uv sync
cp .env.example .env        # or set development_mode: true and skip keys
uv run python app.py
uv run pytest
```

### 18.3 Keeping HF Spaces in sync with uv

HF Gradio SDK Spaces install from `requirements.txt`, not `uv.lock`, and install Gradio from the README `sdk_version`. Three rules prevent version drift:

1. **Generate `requirements.txt`, never edit it:**

```bash
   uv export --no-hashes --no-dev --no-emit-project \
     --prune gradio > requirements.txt
```

   `--prune gradio` keeps Gradio out of the file so it doesn't conflict with `sdk_version`. Check that the uv version used supports `--prune`; if not, filter the top-level `gradio` line out in a small script (`scripts/export_requirements.sh`). Verify the Space builds either way.

2. **One Gradio version everywhere:** the version pinned in `pyproject.toml` (`gradio==X.Y.Z`) must equal `sdk_version` in the README frontmatter, and must be a version supported on ZeroGPU.

3. **One Python version everywhere:** `python_version` in the README frontmatter must equal `.python-version`, and must be a version supported on ZeroGPU.

README frontmatter:

```yaml
  ---
  title: AI Image Lab
  sdk: gradio
  sdk_version: "X.Y.Z"        # == gradio pin in pyproject.toml; ZeroGPU-compatible
  python_version: "3.12"      # == .python-version; ZeroGPU-compatible
  app_file: app.py
  pinned: false
  license: mit
  ---
```

### 18.4 CI checks (GitHub Actions)

On every push:

- `uv sync --locked` (fails if `uv.lock` is out of date with `pyproject.toml`);
- `uv run pytest` with fakes, no secrets;
- regenerate `requirements.txt` and fail if `git diff --exit-code requirements.txt` shows changes;
- a small script asserts the Gradio pin equals `sdk_version` and `.python-version` equals `python_version`.

### 18.5 Reusability

- MIT license; README with screenshot, "Duplicate this Space" instructions (secrets are not copied), and a 5-minute quick start.
- README states which hardware has been tested: **ZeroGPU (free account)** and/or **CPU Basic (PRO)**, so people who fork it on a free account know what to expect.
- Everything workshop-specific (challenge text, limits, models, styles, chips, languages) lives in YAML/JSON.
- `development_mode` lets anyone run it locally with zero API keys.
---

## 19. Workshop checklist (in README)

**Week before**

- Verify model catalogue, prices and latency; update `models.yaml`.
- Run the same 20 prompts through `image_backend: fal` and `image_backend: hf`; compare latency, image quality, edit support and how clearly each bill shows the spend. Pick the backend for the day.
- Load prepaid credits = workshop budget; auto-recharge off.
- Run the safety test set against real services; review failures.
- Test Swedish prompts on each enabled model; decide on translation per model.
- Full run-through on a real iPad (landscape + portrait, light + dark).

**Day before**

- Freeze repo and Space settings (no pushes, no secret changes after this).
- Five simultaneous devices doing Compare for 10 minutes; watch the admin tab.
- Incognito browser cannot reach the app without a password.
- Test AirDrop (and QR, if enabled) with a staff phone.

**One hour before**

- Open the direct `.hf.space` URL to wake the Space.
- Log in on every iPad; enable Guided Access; disable auto-lock.
- Admin: reset counters; generate one real image.
- Staff know the workshop password and where the Pause switch is.

**Between visitors (staff habit)**

- Tap "Ny besökare"; clear anything saved to Photos/Downloads.

**After**

- Pause the Space; check spend on provider dashboards; rotate both passwords; remove leftover credits if desired.

---

## 20. Implementation phases

1. **Skeleton** – config, i18n, fakes, Create tab end-to-end with fakes, New visitor + idle reset. *Runs locally without keys.*
2. **Access + limits** – auth with two users, reservation, semaphore, device ID, kill switch, admin tab.
3. **Real providers** – fal **and** HF Inference Providers image adapters (parity per §5.2), OpenAI text + moderation, output-image check, safety pipeline.
4. **Edit chips** – edit adapter, fallback path.
5. **Compare** – model cards, concurrent calls, isolated failures.
6. **Polish** – style thumbnails, iPad CSS, "How does it work?" panel, latency tuning against §7 targets.
7. **Ship** – README, safety test script, GitHub Actions, optional QR.

Access control and limits (phase 2) must work **before** real API keys are added in phase 3.

---

## 21. Acceptance criteria

1. A first-time visitor creates an image without instruction on an iPad.
2. Default Create p50 ≤ 6 s on workshop Wi-Fi.
3. Edit chips keep the subject recognisable (edit model path).
4. Compare shows two models concurrently with isolated failures.
5. Swedish and English UI and LLM help both work.
6. Final prompts and output images are moderated; failures fail closed; real people and characters follow policy.
7. Concurrent requests can't exceed the pacing ceiling; prepaid credit is documented as the hard cap.
8. Device limits survive a page reload.
9. New visitor and idle reset clear all visitor-visible state.
10. Login works on iPad Safari via the direct URL; incognito is blocked.
11. Admin tab shows usage and can pause generation.
12. No prompts, images or secrets in logs or storage.
13. Adding a model from an existing provider is config-only, and switching between fal and HF-only (`image_backend`) is config-only.
14. Runs locally and in CI with fakes and no keys.
15. Someone else can duplicate the Space and run their own workshop using only the README.
