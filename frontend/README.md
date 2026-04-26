# GridWise frontend

Static site: HTML, Tailwind (CDN), Chart.js, vanilla JS — no bundler.

## Files

| File | Purpose |
|------|---------|
| `index.html` | Landing page |
| `app.html` | Dashboard |
| `app.js` | Mock optimize when APIs are unset; else `POST /optimize`, `POST /explain`, optional audio |

## Run

```bash
cd frontend && python3 -m http.server 5500
```

Open `http://localhost:5500/app.html` (or `index.html`). Use a local server so `fetch` to the backend/agent is not blocked as `file://`.

## Connect APIs

In **Connect APIs**: set backend URL (`POST …/optimize`) and agent URL (`POST …/explain`). Empty = built-in demo. Settings persist in `localStorage`.

Earliest start and deadline use `datetime-local` inputs; the client sends ISO UTC (`…Z`) to the backend.

## UX (one glance)

Recommendation card (windows + KPIs) → chart (baseline vs optimized) → impact row → “Why this schedule?” (original/optimised times, Gemma text, two evidence cards, optional ElevenLabs link when the agent exposes audio).
