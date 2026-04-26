"""
gemma_service.py
----------------
Calls the Google Gemini API (Gemma 4 model) to turn a structured
optimizer response into a concise, factual natural-language explanation.

Required env var:
  GEMINI_API_KEY   — your Google AI Studio / Gemini API key

Optional env var:
  GEMMA_MODEL      — model ID (default: gemma-3-27b-it)
                     Override to e.g. "gemma-4-27b-it" when available.
"""

import asyncio
import json
import os
from datetime import datetime

from google import genai
from google.genai import types

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_MODEL = os.getenv("GEMMA_MODEL", "gemma-3-27b-it")

_SYSTEM_INSTRUCTION = """\
You are a carbon-aware scheduling assistant for GridWise. The optimizer has
already picked the best window — your only job is to explain, in plain English,
WHY that window was chosen AND what is actually happening on the grid that
makes those hours cleaner.

Write 4-5 sentences of plain prose (no bullets, no markdown, no headings) in
this order:

  1. The move. Use the human-friendly strings:
     "We shifted your <request.duration_hours>-hour <request.region> job from
      {display.baseline_window_human} to {display.optimized_window_human}."

  2. The grid story (ONE sentence). Explain WHY those hours are cleaner on this
     specific grid, based on the region code (request.region) and the time-of-
     day pattern in dirtiest_hours_avoided / cleaner_hours_used. Lean on what
     the region is known for — its dominant fuel mix and how it typically
     swings during the day. Use hedged language ("typically", "tends to",
     "usually", "is known for") because you do NOT have real-time fuel-mix
     data, only general knowledge of the grid. Examples of the right shape:
       - US-CAL-CISO with dirty 18:00–21:00, clean 01:00–04:00 →
         "California (CAISO) typically leans on solar during the day and
          ramps gas peakers in the evening as the sun drops, which is why
          the early-evening hours are the dirtiest and overnight is cleaner."
       - US-TEX-ERCO with clean overnight →
         "Texas (ERCOT) usually has strong overnight wind, so the early
          morning hours tend to undercut the gas-heavy daytime ramp."
       - DE with cleaner midday →
         "Germany's mix is heavy on wind and solar — midday usually pulls in
          the most renewables, while evening dips lean on gas to fill the gap."
       - FR (nuclear) or NO/SE/CA-QC (hydro) with a flat signal →
         "France runs largely on nuclear baseload (or: Norway is hydro-
          dominant), so the grid signal barely moves through the day and the
          tiny improvement here is from minor demand swings rather than fuel
          mix."
       - IN-NO / IN-SO / AU-NSW with dirty afternoon →
         "Indian/Australian grids still lean heavily on coal during peak
          demand, so afternoon hours tend to be dirtier than late-night
          minimums."
     If the pattern doesn't fit a story you're confident about for that
     specific region, OMIT this sentence entirely — do not invent one.

  3. The numbers. Cite the average grid intensity in each window
     (reasoning.baseline_avg_signal vs reasoning.optimized_avg_signal,
     gCO₂/kWh) and the specific hour labels from dirtiest_hours_avoided and
     cleaner_hours_used (use the HH:MM strings as-is, e.g. "the dirty 18:00,
     19:00, 20:00, 21:00 evening peak" and "the cleaner 01:00–04:00 overnight
     stretch").

  4. The savings. State metrics.co2_saved_kg kg of CO₂ saved and
     metrics.percent_reduction percent reduction.

  5. The deadline. Confirm using {display.deadline_human}.

Hard rules — break any of these and the answer is wrong:
- NEVER output raw ISO timestamps like "2026-04-26T01:00:00Z". Always use the
  pre-formatted strings under "display".
- For numeric facts (averages, kg saved, percent, hour labels) use ONLY the
  values in the JSON. Do not estimate or recompute them.
- The grid-story sentence is qualitative regional context only. It MUST use
  hedged language and MUST NOT invent percentages, claim a real-time fuel
  mix, or assert anything you're not confident about. If unsure, skip it.
- Do NOT propose a different schedule, mention AI / ML / model names, or use
  hedging words like "approximately" or "roughly" for the metric values.
- Friendly, confident tone — a teammate explaining the trade-off, not a
  robot reading a log line.
"""


# ---------------------------------------------------------------------------
# Time formatting — the optimizer hands us ISO 8601 UTC strings, but Gemma
# tends to parrot those raw timestamps back at the user. We pre-format every
# time field into a human-friendly string and pass both to Gemma; the system
# instruction forbids using the raw ISO version.
#
# Format chosen: "Sun Apr 26, 1:00 AM UTC" — 12-hour clock with AM/PM is the
# most natural for a non-technical dashboard card. We avoid platform-specific
# strftime tokens (%-I, %#I) so this works on macOS, Linux, and Windows.
# ---------------------------------------------------------------------------


def _parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _fmt_time(dt: datetime) -> str:
    """e.g. '1:00 AM' (no leading zero on the hour, portable across OSes)."""
    h12 = dt.hour % 12 or 12
    ampm = "AM" if dt.hour < 12 else "PM"
    return f"{h12}:{dt.minute:02d} {ampm}"


def _fmt_dt(dt: datetime) -> str:
    """e.g. 'Sun Apr 26, 1:00 AM UTC'."""
    return f"{dt.strftime('%a %b')} {dt.day}, {_fmt_time(dt)} UTC"


def _fmt_window(start_iso: str, end_iso: str) -> str:
    """
    Compact window string. Same-day collapses the date:
      'Sat Apr 25, 6:00 PM – 10:00 PM UTC'
    Cross-day spells both ends:
      'Sun Apr 26, 1:00 AM UTC → Sun Apr 26, 5:00 AM UTC'
    """
    s = _parse_iso(start_iso)
    e = _parse_iso(end_iso)
    if s.date() == e.date():
        return f"{s.strftime('%a %b')} {s.day}, {_fmt_time(s)} – {_fmt_time(e)} UTC"
    return f"{_fmt_dt(s)} → {_fmt_dt(e)}"


def _build_display(payload: dict) -> dict:
    """
    Pre-format every time string Gemma might want to mention. Kept separate from
    the optimizer payload so the system rules can say "use display.* instead of
    request.deadline / baseline.start / optimized.start".
    """
    baseline = payload.get("baseline") or {}
    optimized = payload.get("optimized") or {}
    request = payload.get("request") or {}

    out = {}
    if baseline.get("start") and baseline.get("end"):
        out["baseline_window_human"] = _fmt_window(baseline["start"], baseline["end"])
    if optimized.get("start") and optimized.get("end"):
        out["optimized_window_human"] = _fmt_window(optimized["start"], optimized["end"])
    if request.get("deadline"):
        out["deadline_human"] = _fmt_dt(_parse_iso(request["deadline"]))
    return out


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_prompt(payload: dict) -> str:
    """
    Serialize the optimizer payload as indented JSON, attach a `display` block
    of pre-formatted human-friendly time strings, and prepend the system rules
    in the same user turn.

    Why fold display into the same JSON?
        Gemma reliably picks fields from a flat-looking JSON object more than
        from instructions alone. Putting `display.baseline_window_human` next
        to `baseline.start` makes the "use display.*, never the ISO field" rule
        much easier for the model to follow.

    Why not pass `system_instruction` separately?
        Gemma models served via the Gemini API reject `system_instruction`
        with HTTP 400 ("Developer instruction is not enabled for models/
        gemma-*"). Folding the rules into the user message keeps the same
        contract and works across both Gemma and Gemini-family models, so
        switching `GEMMA_MODEL` requires no code change.
    """
    enriched = dict(payload)
    enriched["display"] = _build_display(payload)
    return (
        _SYSTEM_INSTRUCTION
        + "\n\nHere is the carbon scheduling result. Explain it to the user.\n\n"
        + "```json\n" + json.dumps(enriched, indent=2, default=str) + "\n```"
    )


def _get_client() -> genai.Client:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "GEMINI_API_KEY is not set. "
            "Add it to your .env file to enable Gemma explanations."
        )
    return genai.Client(api_key=api_key)


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------


async def generate_explanation(payload: dict) -> str:
    """
    Generate a natural-language explanation for the given optimizer payload.

    Parameters
    ----------
    payload : dict
        The full response body from POST /optimize (backend contract).
        Must contain at minimum: request, baseline, optimized, metrics,
        reasoning.  timeseries and provider are forwarded if present.

    Returns
    -------
    str
        A 3-5 sentence plain-English explanation suitable for display in
        a dashboard card.

    Raises
    ------
    EnvironmentError
        If GEMINI_API_KEY is not configured.
    RuntimeError
        If the Gemini API call fails or returns an empty response.
    """
    client = _get_client()

    prompt = _build_prompt(payload)

    try:
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.2,  # low = more factual, less creative
                # 4–5 sentences with a grid-story line typically lands at
                # ~120–180 tokens; 400 leaves headroom so we don't truncate
                # mid-sentence on longer regions like "US-CAL-CISO".
                max_output_tokens=400,
                candidate_count=1,
            ),
        )
    except Exception as exc:
        raise RuntimeError(f"Gemini API request failed: {exc}") from exc

    # Extract text safely
    try:
        text = response.text.strip()
    except (AttributeError, ValueError) as exc:
        raise RuntimeError(
            f"Gemini returned an empty or blocked response. "
            f"Finish reason: {response.candidates[0].finish_reason if response.candidates else 'unknown'}"
        ) from exc

    if not text:
        raise RuntimeError("Gemma returned an empty explanation.")

    return text
