# GridWise agents

Small FastAPI service: turns the **full** `POST /optimize` JSON into plain language (Gemma via Google Gemini API) and optionally speech (ElevenLabs). It does not re-optimize or change numbers — the backend remains the source of truth.

## Layout

```text
agents/
  main.py
  requirements.txt
  services/
    gemma_service.py
    elevenlabs_service.py
    chat_service.py
    chat_scenarios.py
    equivalency_service.py
  prompts/
    explain_schedule.md
```

## Endpoints

| Method | Path | Notes |
|--------|------|--------|
| `POST` | `/explain` | Body = same JSON as backend `OptimizeResponse`. Returns `explanation_text`, `audio_available`. |
| `POST` | `/explain/audio` | Same body; needs `ELEVENLABS_API_KEY`. Returns text + `audio_b64` (MP3). |
| `POST` | `/equivalencies` | Body = full `OptimizeResponse`. Returns `{ "equivalencies": [s1, s2, s3] }` — three short relatable CO₂ lines (Gemma); deterministic fallbacks if the model or key is unavailable. |
| `POST` | `/chat` | Talk-to-agent: `{ messages, last_run?, last_optimize?, form_state }` → `{ assistant_message, patch, suggest_optimize }`. `last_optimize` is a digest of the last `POST /optimize` response; the service precomputes hourly **what-if** shift scenarios from `timeseries` so the model can answer “one hour earlier?” with real deltas. Frontend merges `patch` and may call `POST /optimize` when `suggest_optimize` is true. |
| `GET` | `/health` | Liveness. |

## Environment

- **`GEMINI_API_KEY`** — required for `/explain`, `/chat`, and AI-written `/equivalencies` (ballpark lines still work without it).
- **`CHAT_MAX_OUTPUT_TOKENS`** — optional (default **4096**). Raise if long chat replies are still truncated at the model.  
- **`GEMMA_MODEL`** — optional override (default in code).  
- **`EXPLAIN_MAX_OUTPUT_TOKENS`** — optional (default **2048**). The `/explain` route needs enough headroom for several sentences; too low truncates mid-word at the model.  
- **`ELEVENLABS_API_KEY`** (and voice/model ids if you use audio) — optional.

Copy `.env` from your secrets manager; do not commit real keys.

## Local run

```bash
cd agents
pip install -r requirements.txt
python main.py
```

Default port **8001** (see `main.py` / `AGENT_PORT`). CORS allows common local static-server origins for the dashboard.

## Prompting

Gemma is instructed to use only fields from the JSON (intensities, savings, regional context with hedged language). The dashboard shows original vs optimised times explicitly; the model should not duplicate those windows in prose.
