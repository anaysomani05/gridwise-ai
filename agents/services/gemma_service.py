"""
gemma_service.py
----------------
Calls the Google Gemini API (Gemma 4 model) to turn a structured
optimizer response into a concise, factual natural-language explanation.

Required env var:
  GEMINI_API_KEY   — your Google AI Studio / Gemini API key

Optional env vars:
  GEMMA_MODEL              — model ID (default: gemma-3-27b-it)
  EXPLAIN_MAX_OUTPUT_TOKENS — cap for /explain prose (default 2048). The old
                             default of ~420 tokens often cut mid-sentence.
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
_EXPLAIN_MAX_OUT = int(os.getenv("EXPLAIN_MAX_OUTPUT_TOKENS", "2048"))

_SYSTEM_INSTRUCTION = """\
You are GridWise's scheduling explainer. The dashboard already shows the
baseline window and the recommended window above your text — do not repeat
those clock times, full date lines, or any ISO timestamps.

Write FOUR to FIVE sentences of plain prose (no bullets, markdown, headings, or
greeting). Each sentence should add new information — no padding.

STRUCTURE (follow in order):

  (1) DATA — what the schedule changed in hour terms. Ground this in
      `reasoning.dirtiest_hours_avoided` and `reasoning.cleaner_hours_used`
      when non-empty: name the UTC hours or bands you see (e.g. "the 18:00–
      21:00 UTC bucket") and describe what the run avoided vs what it leaned
      into. If those arrays are empty, say the optimizer lowered the average
      carbon over the job without listing invented hours.

  (2–3) WHY — mechanism for THIS grid only. One or TWO sentences with hedged
      language ("typically", "often", "tends to") tying the hour pattern to
      plausible drivers for `request.region` — e.g. solar + evening gas ramp
      for US-CAL-CISO, overnight wind vs daytime gas for US-TEX-ERCO, imports
      and demand cycles for PJM/MISO, nuclear baseload flatness for FR, etc.
      These are qualitative hypotheses, not live fuel-mix facts: do NOT
      invent percentages or claim you read real-time plant dispatch.

      Geography rules (strict):
      - Never merge unrelated regions (no "Indian/Australian" in one phrase).
      - `IN` = India-wide aggregate only; `IN-NO` / `IN-SO` = that
        interconnection only; `AU-NSW` = eastern Australia / NSW only.
      - Coal/thermal peak-demand stories: only for `IN*`, `AU*`, or similar
        zones where that narrative fits; never default to coal for FR, NO,
        SE, or CA-QC.
      - If you are not confident about the mechanism for this exact code,
        write one shorter hedged sentence instead of two.

  (4) NUMBERS — one sentence with ONLY JSON metrics: reasoning.baseline_avg_signal
      vs reasoning.optimized_avg_signal (gCO₂/kWh), metrics.co2_saved_kg (kg
      CO₂), metrics.percent_reduction (percent). Example: "Average grid carbon
      falls from 80 to 73 gCO₂/kWh, saving 0.5 kg CO₂ — an 8.9 percent
      improvement for this run length and power draw."

  (5) WRAP — one short optional sentence (you may merge into (4) if tight)
      on what that means in plain terms: same compute, lower marginal grid
      emissions during the chosen hours. Do NOT mention the deadline — the UI
      already shows it.

NO-IMPROVEMENT CASE (metrics.co2_saved_kg == 0 OR baseline.start == optimized.start):
  Write THREE sentences: (a) no cleaner contiguous slot in range, (b) why the
  curve might be flat or monotonic for this region using hedged language, (c)
  one constructive lever (wider deadline or a more volatile zone).

Hard bans:
  - Raw ISO like "2026-04-26T01:00:00Z".
  - Restating display.baseline_window_human / display.optimized_window_human.
  - "Approximately" / "roughly" next to JSON numerals — use the given values.
  - Model names, bullet lists, markdown.

Tone: informed engineer walking a teammate through the result — concrete,
readable, not marketing.
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
        Four to five plain-English sentences (three for the no-improvement
        variant) suitable for the dashboard card.

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
                temperature=0.16,
                max_output_tokens=max(512, min(_EXPLAIN_MAX_OUT, 8192)),
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
