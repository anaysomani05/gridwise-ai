# Frontend README

This directory owns the **user-facing dashboard** for GridWise. The frontend should make the scheduling decision instantly understandable: what the job is, what the baseline is, what the optimized window is, and how much CO2 was avoided.[web:108][web:111][web:117]

## What this part does

The frontend is a single-page dashboard for submitting a workload and visualizing the difference between a default schedule and a carbon-aware schedule.[web:108][web:111] It should feel like a modern energy decision tool, not a chatbot app.[web:75][web:88]

## Design goals

- Clear in under 10 seconds
- Chart-first, not chat-first
- Minimal text above the fold
- Strong result card
- Clean, modern, trustworthy styling

The UI should visually communicate that grid emissions vary by time and that shifting a job can lower total emissions.[web:154][web:157][web:159]

## Recommended stack

Use one of these:

- React + Tailwind + Recharts/Chart.js
- Next.js if one teammate is already comfortable with it
- Streamlit only if speed matters more than polish

For a polished sponsor-facing demo, a small React app is usually the strongest option for layout control and chart quality.

## Directory structure

```text
frontend/
  README.md
  src/
    components/
      Header.tsx
      JobForm.tsx
      RecommendationCard.tsx
      CarbonChart.tsx
      MetricsRow.tsx
      ExplanationPanel.tsx
      HistoryPanel.tsx
    pages/
    lib/
      api.ts
      types.ts
```

## Page structure

Build a **single-page dashboard** with the following sections:

### 1. Header

Show:

- GridWise logo/name
- tagline: “Smarter timing for cleaner compute”
- region selector (optional if region is in form)
- dark mode toggle
- optional profile/login button if Auth0 is added

### 2. Top row: input + recommendation

#### Left card: Job input form

Fields:

- Region / grid zone
- Workload type, default “AI batch job”
- Duration (hours)
- Power draw (kW) or total energy (kWh)
- Completion deadline
- Optimization mode (carbon, balanced, cost) if backend supports it

Buttons:

- **Optimize Schedule**
- **Load Demo Scenario**

#### Right card: Recommendation summary

Display after optimization:

- Recommended time window
- Baseline time window
- CO2 saved
- Percent reduction
- Deadline met badge
- Optional “peak hours avoided” badge

This should be the visual hero of the page.

### 3. Main chart section

Create a full-width chart showing hourly carbon signal over time.[web:108][web:111][web:117]

Overlay:

- baseline window in muted red/orange
- optimized window in green/teal
- optional shaded “high carbon” periods

This chart should visually answer: “Why is the optimized window better?”

### 4. KPI row

Show 3–4 metric cards:

- CO2 avoided (kg)
- emissions reduction (%)
- baseline emissions (kg)
- optimized emissions (kg)
- optional peak-hour load shifted

### 5. Explanation panel

This panel renders the Gemma-generated explanation text from the AI layer.[web:93][web:94]

Include:

- explanation text
- “Explain with AI” button if needed
- “Play audio explanation” button if ElevenLabs is integrated.[web:98][web:101]

### 6. History panel

If Backboard is integrated, show the most recent optimization runs and a simple trend line such as “4% better than your previous run.”[web:102][web:177]

## API integration plan

The frontend should start with **mock JSON** before the backend is done. This allows parallel development and reduces merge conflicts.[web:171][web:179]

### Suggested `api.ts` functions

- `optimizeJob(payload)`
- `getDemoScenarios()`
- `getRegions()`
- `getHistory()` if AI/memory layer exposes it

### Required frontend types

Mirror the backend schema in `types.ts` so the UI is strongly typed and stable.

## Component responsibilities

### `JobForm`

Owns all user inputs and submits the optimize request.

### `RecommendationCard`

Shows:

- recommended start/end
- baseline start/end
- CO2 saved
- deadline status

### `CarbonChart`

Plots:

- hourly carbon signal
- highlighted baseline window
- highlighted optimized window

### `MetricsRow`

Shows metric cards using backend-calculated numbers.

### `ExplanationPanel`

Displays the AI explanation and optional audio controls.

### `HistoryPanel`

Shows previous runs from Backboard or from a mock history list.

## Styling guidance

Use a neutral dashboard aesthetic with restrained accent colors.

Recommended color meaning:

- green/teal = optimized / cleaner
- orange/red = baseline / dirtier
- neutral gray/white/black = structure

Avoid neon gradients, purple AI aesthetics, or crypto-looking UI. The design should feel analytical, polished, and climate-tech aligned.

## Build order

### Step 1: Mock-first setup

- create static page scaffold
- hardcode one sample response JSON
- build layout from mock data

### Step 2: Core components

Implement in order:

1. Header
2. JobForm
3. RecommendationCard
4. CarbonChart
5. MetricsRow

### Step 3: AI and memory sections

- add ExplanationPanel
- add HistoryPanel
- wire buttons for audio and prior-run comparison if available

### Step 4: Connect live APIs

Swap mock data for real backend endpoints and keep the mock toggle for demo fallback.

## What not to build

Do not waste hackathon time on:

- multi-page app routing
- complex nav/sidebar systems
- admin panels
- giant data tables
- custom design systems from scratch
- too many filters
- chatbot-first landing pages

The frontend is successful when a judge can understand the result in one glance.

## Integration notes

### With backend

Consume:

- `baseline`
- `optimized`
- `metrics`
- `timeseries`
- `reasoning`

Do not compute important emissions metrics in the browser; trust backend outputs.

### With AI layer

Consume:

- explanation text
- optional audio URL/blob
- prior-run comparison data

## Demo success criteria

The page should support this flow cleanly:

1. user loads demo scenario
2. clicks optimize
3. sees chart and metrics update
4. reads or hears AI explanation
5. optionally compares with previous runs

If that flow works smoothly, the frontend is doing its job.[web:88][web:108][web:111]