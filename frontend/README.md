# GridWise AI — Frontend

## What’s in this folder

Static, no-build site (HTML + Tailwind via CDN + Chart.js):

| File | Role |
|------|------|
| `index.html` | Marketing landing (hero, problem/solution, how it works) |
| `app.html` | Dashboard (form, recommendation, chart, KPIs, explanation, history) |
| `app.js` | Logic: mock “optimize” from inputs, optional live `POST /optimize` and `POST /explain` |

## Run locally

```bash
cd frontend
python3 -m http.server 5500
# open http://localhost:5500/index.html
```

For API calls from the page without file:// CORS issues, use any static server (port above is just an example).

## Connect to backend and agent

In `app.html`, open **Connect APIs** and set:

- **Backend base URL** → `POST {url}/optimize`
- **Agent base URL** → `POST {url}/explain`

Leave blank to use the built-in demo. Settings are stored in `localStorage`.

---

## Product / UX spec (reference)

**Goal:** make the scheduling decision obvious in a few seconds: which job, baseline vs optimized window, and kg CO₂ avoided.

**Principles:** chart-first, not chat-first; minimal text above the fold; strong “result” card; neutral, climate-tech look (teal = cleaner, orange/red = baseline / dirtier).

**Dashboard sections (conceptually):** header, job form + recommendation card, carbon timeline with baseline/optimized overlays, KPI row, AI explanation (Gemma) + optional ElevenLabs audio, history / “vs last run” if memory is wired.

**Integration:** prefer backend / agent numbers for emissions; the current static demo can compute a fallback when no backend is connected.

**Demo flow:** load demo → optimize → see chart + metrics → explain → (optional) second run to compare.
