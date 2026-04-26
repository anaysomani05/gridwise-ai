## GridWise AI — Frontend

Static, no-build, startup-style site (Tailwind via CDN + Chart.js).

### Files

- `index.html` — landing page (hero + features + how it works + CTA)
- `app.html` — dashboard (form + recommendation + chart + KPIs + AI explanation + history)
- `app.js` — dashboard logic (mock-first; live API toggle in the “Connect APIs” drawer)

### Run locally

Just open the files in a browser. For best results (so `fetch` to APIs works without CORS issues), serve them with a tiny static server:

```bash
cd frontend
python3 -m http.server 5173
# open http://localhost:5173/index.html
```

### Connect to backend & agent later

In `app.html`, click **Connect APIs** (top right) and paste:

- Backend base URL → calls `POST {url}/optimize`
- Agent base URL → calls `POST {url}/explain`

Leave blank to use demo data. Settings persist in `localStorage`.
