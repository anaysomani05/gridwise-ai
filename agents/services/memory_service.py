"""
memory_service.py
-----------------
Persistent run history for the GridWise agent layer, powered by Backboard.

Each optimization run is sent to a Backboard thread as a structured message.
Because Backboard uses memory="Auto", the assistant automatically remembers
previous runs and generates meaningful comparison messages like:
  "Compared to your last run, this schedule saved 4% more CO₂."

The local _store dict acts as a fast in-process cache so GET /history
does not need to round-trip to Backboard on every request.

Required env vars:
    BACKBOARD_API_KEY    — your Backboard secret key
    BACKBOARD_THREAD_ID  — the thread ID to post messages into
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any

from backboard import BackboardClient
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Local in-process cache  {user_id: [run_dict, ...]}  (chronological)
# ---------------------------------------------------------------------------
_store: dict[str, list[dict[str, Any]]] = {}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_client() -> BackboardClient:
    api_key = os.getenv("BACKBOARD_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "BACKBOARD_API_KEY is not set. "
            "Add it to your .env file to enable persistent memory."
        )
    return BackboardClient(api_key=api_key)


def _get_thread_id() -> str:
    thread_id = os.getenv("BACKBOARD_THREAD_ID")
    if not thread_id:
        raise EnvironmentError(
            "BACKBOARD_THREAD_ID is not set. Add it to your .env file."
        )
    return thread_id


def _build_memory_message(
    payload: dict[str, Any],
    explanation: str,
    user_id: str,
    run_id: str,
) -> str:
    """
    Build the message text that gets stored in the Backboard thread.
    Structured as plain text so the assistant can parse it naturally.
    """
    metrics = payload.get("metrics", {})
    optimized = payload.get("optimized", {})
    baseline = payload.get("baseline", {})
    request_info = payload.get("request", {})
    reasoning = payload.get("reasoning", {})

    return (
        f"[GridWise Run Saved]\n"
        f"run_id:             {run_id}\n"
        f"user_id:            {user_id}\n"
        f"region:             {request_info.get('region', 'unknown')}\n"
        f"duration_hours:     {request_info.get('duration_hours')}\n"
        f"power_kw:           {request_info.get('power_kw')}\n"
        f"deadline:           {request_info.get('deadline')}\n"
        f"\n"
        f"baseline_window:    {baseline.get('start')} → {baseline.get('end')}\n"
        f"baseline_emissions: {baseline.get('emissions_kg')} kg CO₂\n"
        f"\n"
        f"optimized_window:   {optimized.get('start')} → {optimized.get('end')}\n"
        f"optimized_emissions:{optimized.get('emissions_kg')} kg CO₂\n"
        f"\n"
        f"co2_saved_kg:       {metrics.get('co2_saved_kg')}\n"
        f"percent_reduction:  {metrics.get('percent_reduction')}%\n"
        f"deadline_met:       {metrics.get('deadline_met')}\n"
        f"\n"
        f"baseline_avg_signal:  {reasoning.get('baseline_avg_signal')} gCO₂eq/kWh\n"
        f"optimized_avg_signal: {reasoning.get('optimized_avg_signal')} gCO₂eq/kWh\n"
        f"dirtiest_hours_avoided: {reasoning.get('dirtiest_hours_avoided')}\n"
        f"cleaner_hours_used:     {reasoning.get('cleaner_hours_used')}\n"
        f"\n"
        f"explanation: {explanation}\n"
        f"\n"
        f"If this is not the first run for this user, compare the co2_saved_kg "
        f"and percent_reduction with the most recent previous run and write one "
        f"plain-English sentence summarising the difference. "
        f"If this is the first run, write: 'This is your first GridWise run — "
        f"nothing to compare yet, but your results will appear here next time.'"
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def save_run(
    payload: dict[str, Any],
    explanation: str,
    user_id: str = "default",
) -> str:
    """
    Persist one optimization run.

    1. Assigns a unique run_id and timestamps the record.
    2. Posts a structured message to the Backboard thread so the assistant
       builds memory of this run.
    3. Uses the assistant's response as the comparison_message for this run.
    4. Caches the full record locally for fast GET /history responses.

    Parameters
    ----------
    payload:
        The full POST /optimize response from the backend.
    explanation:
        The Gemma-generated natural-language explanation text.
    user_id:
        Caller-supplied identifier (defaults to "default").

    Returns
    -------
    str
        A unique run_id (UUID4) for this record.
    """
    run_id = str(uuid.uuid4())
    saved_at = datetime.now(timezone.utc).isoformat()

    metrics = payload.get("metrics", {})
    optimized = payload.get("optimized", {})
    request_info = payload.get("request", {})

    # ── 1. Send to Backboard and get the comparison message ───────────────
    comparison_message = ""
    try:
        client = _get_client()
        thread_id = _get_thread_id()

        message_text = _build_memory_message(payload, explanation, user_id, run_id)

        response = await client.add_message(
            thread_id=thread_id,
            content=message_text,
            memory="Auto",
            stream=False,
        )

        comparison_message = (
            response.content.strip() if response and response.content else ""
        )

    except EnvironmentError:
        # Backboard not configured — degrade gracefully, still save locally
        comparison_message = ""
    except Exception as exc:
        # Network / API errors should not block saving the run
        comparison_message = f"(Memory service unavailable: {exc})"

    # ── 2. Build the local record ─────────────────────────────────────────
    run = {
        "run_id": run_id,
        "saved_at": saved_at,
        "user_id": user_id,
        # provenance
        "region": request_info.get("region"),
        "provider": payload.get("provider"),
        "source": payload.get("source"),  # "live" | "fallback_demo_data"
        # key metrics (flat, for fast reads)
        "co2_saved_kg": metrics.get("co2_saved_kg"),
        "percent_reduction": metrics.get("percent_reduction"),
        "deadline_met": metrics.get("deadline_met"),
        "optimized_emissions_kg": optimized.get("emissions_kg"),
        "optimized_start": optimized.get("start"),
        "optimized_end": optimized.get("end"),
        # AI-generated comparison from Backboard
        "comparison_message": comparison_message,
        # full detail
        "explanation": explanation,
        "full_payload": payload,
    }

    if user_id not in _store:
        _store[user_id] = []
    _store[user_id].append(run)

    # Cap history at 50 runs per user to prevent unbounded memory growth
    _store[user_id] = _store[user_id][-50:]

    return run_id


async def get_history(user_id: str = "default") -> list[dict[str, Any]]:
    """
    Return all saved runs for *user_id*, newest first.

    Each run includes:
    - flat metric fields for the history panel cards
    - comparison_message generated by Backboard at save time
    - full_payload for the detail / chart view

    Returns an empty list if the user has no history yet.
    """
    runs = _store.get(user_id, [])

    if not runs:
        return []

    # Return newest first; strip internal-only keys if needed in future
    return list(reversed(runs))


def get_summary_stats(user_id: str = "default") -> dict[str, Any]:
    """
    Aggregate stats across all runs for *user_id*.
    Available for future GET /stats endpoint.
    """
    runs = _store.get(user_id, [])
    if not runs:
        return {}

    kg_values = [r["co2_saved_kg"] for r in runs if r.get("co2_saved_kg") is not None]
    pct_values = [
        r["percent_reduction"] for r in runs if r.get("percent_reduction") is not None
    ]
    regions = [r["region"] for r in runs if r.get("region")]

    return {
        "total_runs": len(runs),
        "total_co2_saved_kg": round(sum(kg_values), 3) if kg_values else None,
        "avg_percent_reduction": round(sum(pct_values) / len(pct_values), 2)
        if pct_values
        else None,
        "most_used_region": max(set(regions), key=regions.count) if regions else None,
        "first_run_at": runs[0]["saved_at"],
        "last_run_at": runs[-1]["saved_at"],
    }
