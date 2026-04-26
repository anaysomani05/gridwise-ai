# GridWise AI

Carbon-aware scheduling for flexible compute: given region, duration, power, earliest start, and deadline, GridWise picks the lowest-emission contiguous window before the deadline and compares it to “run as soon as possible.”

## Repo layout

| Path | Role |
|------|------|
| `backend/` | Optimizer API — `POST /optimize`; `POST /chat` and `POST /equivalencies` proxy to the agent so the UI can use one base URL. |
| `frontend/` | Static dashboard + marketing page — form, chart, KPIs, Gemma explanation (optional audio). |
| `agents/` | FastAPI layer — `POST /explain`, optional `POST /explain/audio`, `POST /equivalencies` (fun CO₂ lines), `POST /chat` (Gemma + optional ElevenLabs). |

Each folder has its own README with setup and API notes.

## Quick start

```bash
# Terminal 1 — optimizer (port 8000)
cd backend && pip install -r requirements.txt && python app.py

# Terminal 2 — explanations (port 8001)
cd agents && pip install -r requirements.txt && python main.py

# Terminal 3 — UI
cd frontend && python3 -m http.server 5500
# Open http://localhost:5500/app.html — use “Connect data” (drawer) if not on defaults; switch Dashboard / Talk to agent in the header.
```

**Env:** backend needs an Electricity Maps token in `backend/.env` for live carbon data; agents need `GEMINI_API_KEY` for explanations. See each service README.

## What ships today

- Hourly carbon signal → contiguous-window optimization vs ASAP baseline  
- Single workspace (`app.html`): Dashboard vs Talk to agent tabs, **Connect data** side drawer for API URLs, timeline, KPIs, “why this schedule?” (Gemma; optional TTS)  
- No persisted run history — each optimize/explain is stateless aside from browser `localStorage` for API URLs
