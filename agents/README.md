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
  prompts/
    explain_schedule.md
```

## Endpoints

| Method | Path | Notes |
|--------|------|--------|
| `POST` | `/explain` | Body = same JSON as backend `OptimizeResponse`. Returns `explanation_text`, `audio_available`. |
| `POST` | `/explain/audio` | Same body; needs `ELEVENLABS_API_KEY`. Returns text + `audio_b64` (MP3). |
| `GET` | `/health` | Liveness. |

## Environment

- **`GEMINI_API_KEY`** — required for `/explain`.  
- **`GEMMA_MODEL`** — optional override (default in code).  
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
