# Backend README

This directory owns the **core scheduling engine** for GridWise. The backend is the real product: it fetches grid-emissions data, models a workload, compares a baseline schedule to an optimized schedule, and returns the metrics the frontend and AI layer display.[web:65][web:74]

## What this part does

The backend should answer one question: given a flexible AI/data-center job with a duration, power draw, start time, and deadline, what is the cleanest feasible time window to run it in? Electricity Maps and WattTime both expose real-time, historical, and forecasted grid-emissions signals that make this kind of load-shifting optimization possible.[web:55][web:65][web:74][web:86] It should also compute the baseline “run as soon as possible” schedule and report the difference in emissions between the baseline and optimized options, because carbon-aware scheduling is useful only if the impact is quantified.[web:117][web:149]

## Key concepts

- **Carbon intensity** means grams of CO2 per kWh of electricity at a particular time and region, which can vary significantly across hours because the grid mix changes.[web:68][web:85][web:92]
- **Marginal emissions** estimate the emissions impact of one extra unit of electricity demand, which is especially relevant for incremental loads like compute jobs.[web:74][web:117]
- **Load shifting** means moving the same job to a different time, not reducing the amount of compute, and modern grid-data APIs explicitly support using forecast signals to find lower-carbon windows.[web:55][web:66][web:74]

## Recommended stack

- Python
- FastAPI
- Pydantic
- httpx or requests
- Optional: pandas for convenience

FastAPI is a strong fit for parallel frontend/backend work because schema-first and contract-first API development works well with OpenAPI-style flows and reduces integration friction.[web:170][web:171][web:191]

## Directory structure

```text
backend/
  README.md
  main.py
  schemas.py
  config.py
  providers/
    electricity_maps.py
    watttime.py
  services/
    scheduler.py
    metrics.py
    demo_data.py
```

## Core endpoint contract

### POST /optimize

Request body example:

```json
{
  "region": "US-CAL-CISO",
  "job_name": "nightly-training",
  "duration_hours": 4,
  "power_kw": 12,
  "start_after": "2026-04-25T18:00:00Z",
  "deadline": "2026-04-26T08:00:00Z",
  "optimization_mode": "carbon"
}
```

Response body example:

```json
{
  "request": {
    "region": "US-CAL-CISO",
    "duration_hours": 4,
    "power_kw": 12,
    "deadline": "2026-04-26T08:00:00Z"
  },
  "provider": "electricity_maps",
  "signal_type": "carbon_intensity",
  "baseline": {
    "start": "2026-04-25T18:00:00Z",
    "end": "2026-04-25T22:00:00Z",
    "emissions_kg": 14.8
  },
  "optimized": {
    "start": "2026-04-26T01:00:00Z",
    "end": "2026-04-26T05:00:00Z",
    "emissions_kg": 10.9
  },
  "metrics": {
    "co2_saved_kg": 3.9,
    "percent_reduction": 26.35,
    "deadline_met": true
  },
  "timeseries": [
    {"timestamp": "2026-04-25T18:00:00Z", "signal": 410},
    {"timestamp": "2026-04-25T19:00:00Z", "signal": 430}
  ],
  "reasoning": {
    "baseline_avg_signal": 402,
    "optimized_avg_signal": 281,
    "dirtiest_hours_avoided": ["18:00", "19:00", "20:00"],
    "cleaner_hours_used": ["01:00", "02:00", "03:00", "04:00"]
  }
}
```

The frontend and AI layer should both build against this response shape first using mock data, because contract-first development reduces merge conflicts and speeds up parallel work.[web:171][web:191]

## Data provider plan

### Option 1: Electricity Maps

Electricity Maps provides real-time, historical, and forecasted grid carbon signals and is a strong default choice for the MVP.[web:55][web:65][web:67] Its forecasted carbon-intensity endpoint uses 1-hour granularity by default and returns 25 hours of forecasts by default, and the platform also supports broader forecast-based load-optimization use cases including 72-hour forecasts.[web:65][web:86] Electricity Maps also publishes methodology notes explaining how it computes carbon intensity by combining flow-traced electricity mix with technology-specific emission factors.[web:68][web:85]

### Option 2: WattTime

WattTime provides marginal CO2 signals and forecasting support, which is especially strong for incremental-load scheduling use cases like compute jobs.[web:55][web:74][web:117] WattTime’s MOER signal represents the emissions rate of the generators responding to changes in local load, which makes it a very good fit for deciding when an additional AI workload should run.[web:74][web:117] WattTime has also expanded its hourly marginal emissions coverage globally and continues to improve forecast quality and regional models.[web:70][web:72]

### Recommended implementation order

1. Implement Electricity Maps first because its forecasted carbon-intensity endpoint is straightforward and well-suited for the MVP.[web:65][web:86]
2. Add fallback demo data so the app still works if the live API fails.
3. Add WattTime only if the MVP is stable, especially if you want a stronger marginal-emissions story.[web:74][web:117]

## Scheduling logic

Use a simple contiguous sliding-window optimizer.

### Assumptions

- The job must run continuously.
- The power draw is fixed during the run.
- The schedule uses hourly slots.
- The job must finish before the deadline.

### Baseline

Use **ASAP scheduling** as the baseline: the job starts at `start_after` and runs for the required duration. This is the most natural default because it mimics what many users or cron-based systems would do without carbon-awareness.[web:149]

### Optimized schedule

1. Fetch signal values from `start_after` until `deadline` using either Electricity Maps or WattTime.[web:55][web:65][web:74]
2. Enumerate all feasible contiguous windows of length `duration_hours`.
3. For each window, compute total emissions using the hourly signal values.
4. Select the window with the lowest emissions.[web:117][web:149]

### Emissions formula

If the signal is in gCO2/kWh and the job uses fixed power each hour, emissions in kilograms are:

\[
\text{emissions\_kg} = \sum_t \frac{\text{signal}_t \times \text{energy\_kWh}_t}{1000}
\]

This is the main measurable impact calculation for the project, and API-based carbon accounting is a recognized way to estimate electricity-related software emissions by location and time.[web:55][web:117]

## Build order

### Step 1: Set up the app

- Create FastAPI app in `main.py`
- Add `GET /health`
- Add Pydantic schemas in `schemas.py`
- Add environment variable loading in `config.py`

FastAPI is well suited to this because its schema tooling naturally supports clean REST API design and contract-driven iteration.[web:170][web:171]

### Step 2: Implement provider client

- Add API key support
- Implement function to fetch 24–72 hour signal data for one region
- Normalize result into a common internal format

Example internal format:

```json
{
  "region": "US-CAL-CISO",
  "signal_type": "carbon_intensity",
  "unit": "gCO2eq_per_kWh",
  "points": [
    {"timestamp": "2026-04-25T18:00:00Z", "value": 410}
  ]
}
```

A provider-agnostic internal format makes it easy to start with Electricity Maps and later swap in or add WattTime without changing the scheduler logic.[web:55][web:65][web:74]

### Step 3: Implement baseline + optimizer

- Create baseline schedule generator
- Create feasible-window generator
- Create emissions evaluator
- Return best window

This is the core environmental optimization logic of the project: the backend uses time-varying emissions signals to pick the cleanest feasible schedule.[web:66][web:74][web:117]

### Step 4: Add metrics and reasoning payload

Compute:

- `baseline_emissions_kg`
- `optimized_emissions_kg`
- `co2_saved_kg`
- `percent_reduction`
- `deadline_met`
- average signal in baseline and optimized windows

This structured reasoning payload helps the Gemma layer explain the result clearly without inventing numbers.[web:94][web:97]

### Step 5: Add fallback demo mode

External APIs can fail in demos, so include locally stored fallback data for at least 2–3 regions.[web:65][web:74] If the provider errors or times out, respond using cached data and set a flag like `"source": "fallback_demo_data"` so the app remains usable during judging.

## What to test

- Valid request with one feasible window
- Valid request with multiple feasible windows
- No feasible schedule because deadline is too soon
- API unavailable, fallback succeeds
- Equal-signal hours where optimized = baseline
- Invalid duration or missing fields

Also test that the API contract remains stable because contract-breaking changes slow down frontend and agent integration.[web:191]

## What not to build

Do not spend hackathon time on:

- databases
- Kubernetes
- job queues
- real cloud-provider integration
- GPU telemetry
- multi-region workload placement
- split or preemptible jobs
- enterprise auth in the backend

The goal is a reliable optimizer, not a production cloud scheduler.[web:149][web:170]

## Handoff to teammates

### To frontend

Provide:

- endpoint URL
- request schema
- response schema
- one sample response JSON
- list of supported demo regions

### To AI/agent layer

Provide the `reasoning`, `baseline`, `optimized`, and `metrics` blocks so Gemma can explain decisions and Backboard can store results cleanly.[web:94][web:102]

## Success criteria

This part is done when `POST /optimize` reliably returns a valid baseline schedule, a lower-emissions optimized schedule when one exists, and all required metrics for the UI and explanation layer.[web:55][web:65][web:74][web:117]