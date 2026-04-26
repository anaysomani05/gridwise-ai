"""
Chat assistant for the Talk to agent workspace.

Returns structured JSON so the frontend can update scheduling fields and call
POST /optimize on the backend. Does not run optimization itself.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Any

from google import genai
from google.genai import types
from google.genai.types import FinishReason

from services.chat_scenarios import compute_shift_scenarios

_MODEL = os.getenv("GEMMA_MODEL", "gemma-3-27b-it")
# JSON + long negotiator replies need headroom; 900 was truncating mid-response.
_CHAT_MAX_OUT = int(os.getenv("CHAT_MAX_OUTPUT_TOKENS", "4096"))

_SYSTEM = """You are GridWise's scheduling negotiator: a natural chat about the job, the last optimization
the user ran, and trade-offs (e.g. "can we start one hour earlier?").

You MUST respond with a single JSON object only (no markdown, no code fences, no prose outside JSON). Keys:
- "assistant_message" (string, 2–6 sentences, conversational). You MAY cite concrete numbers ONLY from:
  (1) the "last_optimize" object (baseline vs optimized windows, metrics, reasoning averages), and/or
  (2) the "computed_scenarios" list (precomputed what-if shifts of the optimized start, with delta_kg and delta_percent).
  For shifts not listed in computed_scenarios, say you need to re-run optimize or widen the search — do not guess kg/%.
  When comparing to the optimized run, prefer scenarios' delta_percent_vs_current_optimized when present.
- "patch" (object, optional). Allowed patch keys only (carbon-only product — never include "mode"):
  - "region" (string): a valid Electricity Maps zone code if the user names a region you recognize (e.g. US-CAL-CISO, DE, GB). Empty string "" means no change.
  - "deadline_extend_hours" (number): hours to ADD to the current deadline (widen flexibility). 0 means none.
  - "deadline_shorten_hours" (number): hours to SUBTRACT from deadline (tighter). 0 means none.
  - "start_shift_hours" (number): hours to add to earliest start (delay start). 0 means none.
  - "duration_hours" (number): set job duration in hours if user asks; omit or null for no change.
- "suggest_optimize" (boolean): true if they want to re-run optimization after your patches OR you recommend a fresh /optimize for a shift you cannot quantify; false for pure Q&A using existing numbers.

Negotiation style:
- Reference the last run: region, how much was saved vs baseline (from last_optimize.metrics / windows), and what moving time would cost using computed_scenarios when the user asks "earlier", "later", "sooner", "delay", or "hour".
- If computed_scenarios is empty but last_optimize exists, explain qualitatively using reasoning.baseline_avg_signal vs optimized_avg_signal, and suggest re-optimize for an exact shifted window.

Preset intents (patch + suggest_optimize when appropriate):
- "maximize carbon savings" → modest deadline_extend_hours (e.g. 12), suggest_optimize true.
- If the user asks for cost or balanced optimization, explain the app only minimizes grid carbon; offer deadline/region tweaks instead (patch accordingly).
- "Be more aggressive" / "widen search" → deadline_extend_hours around 24.
- "Keep it close to now" / "tight deadline" → deadline_shorten_hours small (e.g. 4–8) without impossible windows.
- "Run again" / "same setup" → empty patch, suggest_optimize true.

Context JSON after this instruction includes: last_run (lightweight summary), last_optimize (full last POST /optimize response or a slim digest), form_state, computed_scenarios (server-derived), conversation.
"""


def _get_client() -> genai.Client:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise EnvironmentError("GEMINI_API_KEY is not set.")
    return genai.Client(api_key=api_key)


def _closing_brace_index(text: str, open_idx: int) -> int:
    """Index of the matching `}` for `{` at open_idx, respecting JSON strings."""
    depth = 0
    in_string = False
    escape = False
    i = open_idx
    while i < len(text):
        c = text[i]
        if escape:
            escape = False
            i += 1
            continue
        if in_string:
            if c == "\\":
                escape = True
            elif c == '"':
                in_string = False
            i += 1
            continue
        if c == '"':
            in_string = True
            i += 1
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _extract_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    text = text.strip()
    start = text.find("{")
    if start == -1:
        raise ValueError("No JSON object in model output")
    end = _closing_brace_index(text, start)
    if end == -1:
        raise ValueError("Unbalanced or truncated JSON in model output")
    return json.loads(text[start : end + 1])


async def generate_chat_turn(
    *,
    messages: list[dict[str, str]],
    last_run: dict[str, Any] | None,
    form_state: dict[str, Any],
    last_optimize: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Returns a dict with keys: assistant_message (str), patch (dict), suggest_optimize (bool).
    """
    client = _get_client()

    scenarios = compute_shift_scenarios(last_optimize, max_shift=12)
    ctx = {
        "last_run": last_run,
        "last_optimize": last_optimize,
        "computed_scenarios": scenarios,
        "form_state": form_state,
        "conversation": messages[-12:],
    }
    user_block = (
        _SYSTEM
        + "\n\nContext JSON:\n```json\n"
        + json.dumps(ctx, separators=(",", ":"), default=str)
        + "\n```\n\nReply with the single JSON object described above."
    )

    try:
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=_MODEL,
            contents=user_block,
            config=types.GenerateContentConfig(
                temperature=0.25,
                max_output_tokens=max(512, min(_CHAT_MAX_OUT, 8192)),
                candidate_count=1,
            ),
        )
    except Exception as exc:
        raise RuntimeError(f"Gemini chat request failed: {exc}") from exc

    try:
        raw = response.text.strip()
    except (AttributeError, ValueError) as exc:
        raise RuntimeError("Gemini returned an empty chat response.") from exc

    data = _extract_json_object(raw)
    msg = str(data.get("assistant_message", "")).strip() or "I could not parse a reply."
    fr = response.candidates[0].finish_reason if getattr(response, "candidates", None) else None
    hit_max = fr == FinishReason.MAX_TOKENS or getattr(fr, "name", "") == "MAX_TOKENS"
    if hit_max:
        msg += (
            "\n\n—(Model output limit was reached; if this still looks cut off, "
            "ask a shorter follow-up or set CHAT_MAX_OUTPUT_TOKENS higher on the agent service.)"
        )
    patch = data.get("patch") if isinstance(data.get("patch"), dict) else {}
    suggest = bool(data.get("suggest_optimize", False))
    return {
        "assistant_message": msg,
        "patch": patch,
        "suggest_optimize": suggest,
    }
