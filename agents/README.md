# Agent README

This directory owns the **AI experience layer** for GridWise. The agent layer should not replace the optimizer; it should explain, remember, and optionally speak the optimizer’s decisions.[web:93][web:94][web:98][web:102]

## What this part does

The agent layer takes structured optimization output and turns it into a user-friendly experience by:

- generating natural-language explanations with Gemma 4,[web:93][web:94][web:97]
- storing preferences and prior runs with Backboard,[web:102][web:177]
- optionally generating spoken explanations with ElevenLabs.[web:98][web:101]

The core scheduling math should remain in the backend. This layer is about trust, memory, and usability.

## Recommended stack

- Node.js or Python, whichever the owner prefers
- Google Gemini API with Gemma 4 model access.[web:93][web:94]
- Backboard for persistent memory.[web:102][web:177]
- ElevenLabs Text-to-Speech API for optional audio.[web:98][web:101]

## Directory structure

```text
agent/
  README.md
  prompts/
    explain_schedule.md
  services/
    gemma_service.py
    memory_service.py
    elevenlabs_service.py
  routes/
    explain.py
    history.py
```

## Key principle

The AI layer should consume **structured facts** from the backend and explain them. It should not invent scheduling logic, change the optimized window, or recompute emissions.[web:93][web:94]

## Inputs from backend

The agent layer should expect a payload like:

```json
{
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
  "reasoning": {
    "baseline_avg_signal": 402,
    "optimized_avg_signal": 281,
    "dirtiest_hours_avoided": ["18:00", "19:00", "20:00"],
    "cleaner_hours_used": ["01:00", "02:00", "03:00", "04:00"]
  },
  "request": {
    "region": "US-CAL-CISO",
    "duration_hours": 4,
    "power_kw": 12,
    "deadline": "2026-04-26T08:00:00Z"
  }
}
```

## Gemma 4 integration

Gemma 4 is available through Google Gemini APIs and is suitable for building fast, private-feeling AI features with open models.[web:93][web:94][web:96]

### What Gemma should do

Generate explanations like:

- why the baseline was dirtier,
- why the chosen window is cleaner,
- whether the deadline is still satisfied,
- what tradeoff was made.

### What Gemma should not do

- invent new metric values
- change the optimized schedule
- claim savings not present in the backend payload
- hallucinate unsupported grid facts

### Prompt design

Prompt Gemma using structured fields only.

Suggested prompt skeleton:

```text
You are explaining a carbon-aware scheduling decision to a user.
Use only the provided values.
Be concise, specific, and factual.
Mention the baseline window, optimized window, emissions reduction, and deadline status.
Do not invent numbers.
```

Then pass the structured JSON payload below the instruction.

## Backboard integration

Backboard focuses on persistent AI memory and state across sessions, which fits the “compare this run to previous runs” feature well.[web:102][web:177][web:180]

### What to store

- past optimize requests
- emissions outcomes
- preferred regions
- preferred optimization mode
- last explanation text

### Useful user-facing features

- “Compared to your last run, this schedule saved 4% more CO2.”
- “You usually prefer low-carbon mode in California.”
- “Your previous 3 runs mostly shifted jobs away from evening peak hours.”

Keep memory minimal and useful.

## ElevenLabs integration

ElevenLabs exposes text-to-speech APIs that can turn the explanation into a spoken result for the demo.[web:98][web:101]

### Suggested UX

Button: **Play explanation**

Input text:
- the final Gemma explanation

Output:
- streamed or downloadable audio clip

This is a nice demo enhancement, but it is optional. Do not block the rest of the agent layer on audio.

## API endpoints this layer can expose

### POST /explain

Input:
- backend optimize response

Output:

```json
{
  "explanation_text": "GridWise shifted your 4-hour workload away from the evening high-emissions period and into an overnight lower-carbon window, reducing expected emissions by 26.35% while still meeting the deadline.",
  "audio_available": true
}
```

### POST /save-run

Store current run and user preferences in Backboard.

### GET /history

Return prior optimization runs and summary statistics for the frontend history panel.

## Build order

### Step 1: Work from mock backend JSON

Start immediately using one sample optimize response so the AI layer can be built in parallel with backend and frontend.[web:171][web:179]

### Step 2: Gemma explanation endpoint

- connect to Gemma via Gemini API
- build prompt template
- return concise explanation text

### Step 3: Backboard memory

- store the request + result
- retrieve previous runs
- generate one simple comparison message

### Step 4: ElevenLabs audio

- convert explanation text to speech
- return audio URL/blob or expose a separate endpoint

## What not to build

Do not spend time on:

- open-ended chat interfaces
- autonomous tool-calling agents with complex loops
- elaborate RAG pipelines
- multi-agent orchestration
- trying to make the AI decide the schedule itself

This layer is successful when it makes the optimizer easier to understand and more memorable, not when it becomes the whole app.

## Integration notes

### With backend

The backend should remain the single source of truth for numbers and time windows.

### With frontend

The frontend should simply render:

- `explanation_text`
- audio playback control if present
- previous run summaries

## Success criteria

This part is done when the app can:

1. explain a scheduling result with Gemma,[web:93][web:94]
2. remember at least one previous run with Backboard,[web:102][web:177]
3. optionally speak the explanation with ElevenLabs.[web:98][web:101]