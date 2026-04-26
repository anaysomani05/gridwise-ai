# GridWise frontend

Static site: HTML, Tailwind (CDN), Chart.js, vanilla JS — no bundler.

## Files

| File | Purpose |
|------|---------|
| `index.html` | Landing page |
| `app.html` | Workspace: **Connect data** drawer, **Dashboard** / **Talk to agent** tabs (`?tab=`), optimizer + chart + explanations |
| `app.js` | Mock optimize when APIs are unset; else `POST /optimize`, `POST /explain`, `POST /equivalencies` (fun CO₂ lines), `POST /chat` (Talk to agent), optional audio |

## Run

```bash
cd frontend && python3 -m http.server 5500
```

Open `http://localhost:5500/app.html` (or `index.html` → **Connect data** → `app.html?settings=1` opens the drawer automatically). Use a local server so `fetch` to the backend/agent is not blocked as `file://`.

## Connect data

**Connect data** (header button) opens a side drawer: backend URL (`POST …/optimize`), agent URL (`POST …/explain`). Empty = built-in demo. **Save** / **Use demo data**. From marketing, links use `app.html?settings=1` so the drawer opens on first paint. **Dashboard** vs **Talk to agent** toggles layout on the same page (`?tab=dashboard` | `?tab=agent`). Settings persist in `localStorage`.

Earliest start and deadline use `datetime-local` inputs; the client sends ISO UTC (`…Z`) to the backend.

## UX (one glance)

**Dashboard:** Recommendation card (windows + KPIs) → chart (baseline vs optimized) → impact row → “Why this schedule?” (original/optimised times, Gemma text, two evidence cards, optional ElevenLabs link when the agent exposes audio).

**Talk to agent:** Chat UI with welcome (last metrics + an `optimize` digest in `localStorage` after each run), quick actions (including “What if 1h earlier?”), free-text **Send**. Each chat request sends **`last_optimize`** (digest of the last `/optimize` JSON) so the agent can negotiate trade-offs with precomputed shift scenarios. When a **backend** URL is set, chat uses **`POST {backend}/chat`** (proxied to the agent); **Optimize** uses **`POST {backend}/optimize`**. Open **Dashboard** for charts and the full job form (same underlying fields).
