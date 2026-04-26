# GridWise backend

FastAPI service that fetches hourly grid carbon intensity, runs a contiguous-window optimizer, and returns baseline vs optimized schedules plus metrics for the UI and agent.

## Layout

```text
backend/
  main.py              # FastAPI app, routes
  schemas.py           # Request/response models
  config.py            # Settings from env
  providers/           # Electricity Maps live client
  services/            # scheduler, regions, demo fallback, etc.
```

## Main routes

- `POST /optimize` — body: `region`, `duration_hours`, `power_kw` (or `instance_type`), `start_after`, `deadline` (ISO 8601 UTC), optional `job_name`.
- `POST /chat` — **proxy** to the agent layer’s `POST /chat` (scheduling assistant). Same JSON body/response as the agent service so the UI can use one base URL for both optimize and chat. Target URL defaults to `http://127.0.0.1:8001`; override with `AGENT_SERVICE_URL` in `.env` (see `config.py`).
- `POST /equivalencies` — **proxy** to the agent’s `POST /equivalencies` (body = `OptimizeResponse` → `{ equivalencies: […×3] }` for the dashboard “fun equivalencies” card).
- `GET /regions` — zones for the dashboard: a hand-picked catalog plus, when `ELECTRICITY_MAPS_API_TOKEN` is set, any extra zones returned by Electricity Maps `GET /v3/zones` (merged and cached ~1h).
- `GET /health` — liveness.

See `/docs` on a running server for full schemas (`GET /instance-types`, `POST /compare-regions`, …).

## Request / response (shape)

**Request**

```json
{
  "region": "US-CAL-CISO",
  "duration_hours": 4,
  "power_kw": 12,
  "start_after": "2026-04-25T18:00:00Z",
  "deadline": "2026-04-26T08:00:00Z"
}
```

**Response (conceptually)** — `baseline` / `optimized` windows and `emissions_kg`, `metrics` (`co2_saved_kg`, `percent_reduction`, `deadline_met`), hourly `timeseries`, `reasoning` (avg signals + hour lists), optional `data_quality` and `optimization_note`. Use `data_source`: `"live"` or `"demo"` to see if signal came from the provider or fallback.

The agent and dashboard should treat numbers and ISO timestamps from this payload as authoritative.

## Optimizer (short)

- Baseline: start at `start_after`, run `duration_hours` contiguous hours.  
- Optimized: among all feasible windows that end by `deadline`, pick minimum total emissions using the hourly signal (no imputation for missing hours in range).  
- Emissions: sum over hours of `(signal gCO₂/kWh × energy kWh) / 1000` → kg CO₂.

## Local run

```bash
cd backend
pip install -r requirements.txt
python app.py
```

Defaults to port **8000** (see `app.py` / env). Configure provider API keys in `.env` (see `config.py` for variable names). If the provider fails, the service can still respond using demo series when configured to do so.
