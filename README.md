# GridWise AI

Carbon-aware scheduling for flexible compute: given region, duration, power, earliest start, and deadline, GridWise picks the lowest-emission contiguous window before the deadline and compares it to “run as soon as possible.”

## Repo layout

| Path | Role |
|------|------|
| `backend/` | Optimizer API — grid signal, baseline vs optimized windows, metrics (`POST /optimize`). |
| `frontend/` | Static dashboard + marketing page — form, chart, KPIs, Gemma explanation (optional audio). |
| `agents/` | FastAPI layer — `POST /explain` and optional `POST /explain/audio` (Gemma + ElevenLabs). |

Each folder has its own README with setup and API notes.

## Quick start

```bash
# Terminal 1 — optimizer (port 8000)
cd backend && pip install -r requirements.txt && python app.py

# Terminal 2 — explanations (port 8001)
cd agents && pip install -r requirements.txt && python main.py

# Terminal 3 — UI
cd frontend && python3 -m http.server 5500
# Open http://localhost:5500/app.html — use “Connect APIs” if not on defaults.
```

**Env:** backend needs Electricity Maps (and/or WattTime) keys in `backend/.env`; agents need `GEMINI_API_KEY` for explanations. See each service README.

## What ships today

- Hourly carbon signal → contiguous-window optimization vs ASAP baseline  
- Dashboard: timeline, savings KPIs, “why this schedule?” (structured times + Gemma prose; optional TTS)  
- No persisted run history — each optimize/explain is stateless aside from browser `localStorage` for API URLs
