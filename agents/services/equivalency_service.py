"""
Fun CO₂ equivalencies for the dashboard — short relatable lines from optimize JSON.

Uses Gemma when GEMINI_API_KEY is set; otherwise deterministic fallbacks from kg saved.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from google import genai
from google.genai import types

from services.chat_service import _extract_json_object

_MODEL = os.getenv("GEMMA_MODEL", "gemma-3-27b-it")

_SYSTEM = """You write exactly THREE short "fun equivalency" lines for a general audience about CO₂ AVOIDED on a cloud compute job.

The user will paste JSON from POST /optimize. Use ONLY these numeric facts:
- metrics.co2_saved_kg (kg CO₂ avoided vs baseline — this is the quantity to illustrate)
- metrics.percent_reduction (optional context)
- request.region, request.duration_hours, request.power_kw (for flavor only; do not invent new kg)

Rules:
- Output ONLY a JSON object (no markdown, no code fences): {"equivalencies": ["line1","line2","line3"]}
- Exactly three strings. Each ONE clause, max 95 characters, upbeat and concrete.
- Start each line with a fragment like "About enough avoided CO₂ to " or "Roughly " or "Similar ballpark to " so they read as equivalencies.
- Use "about", "roughly", or "~" for analogies — never fake extra significant figures.
- Mix three DIFFERENT angles (e.g. short drive, phone charges, laptop time, light-bulb days, kettle boils — pick what fits the scale of co2_saved_kg).
- If co2_saved_kg is 0 or missing, three gentle lines that this run did not beat the baseline (no fake savings).

Do not output any keys other than "equivalencies".
"""


def _get_client() -> genai.Client:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise EnvironmentError("GEMINI_API_KEY is not set.")
    return genai.Client(api_key=api_key)


def deterministic_equivalencies(kg: float) -> list[str]:
    """Order-of-magnitude lines when the model is unavailable. kg = CO₂ avoided."""
    try:
        x = float(kg)
    except (TypeError, ValueError):
        x = 0.0
    if x <= 0:
        return [
            "This run did not beat the baseline on CO₂ — try widening the deadline or another zone.",
            "No extra 'fun' savings to show until the optimizer finds a cleaner window.",
            "Same job; timing did not land on a lower-carbon slice this time.",
        ]

    kg_per_mile_car = 0.35
    miles = max(1.0, x / kg_per_mile_car)
    kg_per_phone = 0.034
    phones = max(10, int(round(x / kg_per_phone)))
    laptop_kw = 0.025
    kg_per_kwh = 0.42
    hours_laptop = x / (laptop_kw * kg_per_kwh)
    weeks = max(0.5, hours_laptop / (24 * 7))

    return [
        f"Roughly enough avoided CO₂ as skipping ~{miles:.0f} miles of average car driving (ballpark).",
        f"About the same order of magnitude as ~{phones} smartphone full charges from the grid (illustrative).",
        f"In the ballpark of running a modest laptop (~25 W) for ~{weeks:.1f} weeks at a typical grid factor — not exact science.",
    ]


def _normalize_three(items: list[Any]) -> list[str]:
    out: list[str] = []
    for it in items:
        if isinstance(it, str) and (s := it.strip()):
            out.append(s)
        if len(out) >= 3:
            break
    while len(out) < 3:
        out.append("Roughly one more way to picture that CO₂ saving — illustrative only.")
    return out[:3]


async def generate_equivalencies(payload: dict[str, Any]) -> list[str]:
    """
    Returns exactly three human-readable equivalency strings.
    """
    kg = 0.0
    try:
        m = payload.get("metrics") or {}
        kg = float(m.get("co2_saved_kg", 0) or 0)
    except (TypeError, ValueError):
        kg = 0.0

    try:
        client = _get_client()
    except EnvironmentError:
        return deterministic_equivalencies(kg)

    user_block = (
        _SYSTEM
        + "\n\nOptimize JSON:\n```json\n"
        + json.dumps(payload, separators=(",", ":"), default=str)[:24000]
        + "\n```\n\nReply with the JSON object only."
    )

    try:
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=_MODEL,
            contents=user_block,
            config=types.GenerateContentConfig(
                temperature=0.55,
                max_output_tokens=500,
                candidate_count=1,
            ),
        )
    except Exception:
        return deterministic_equivalencies(kg)

    try:
        raw = response.text.strip()
    except (AttributeError, ValueError):
        return deterministic_equivalencies(kg)

    try:
        data = _extract_json_object(raw)
        eq = data.get("equivalencies")
        if isinstance(eq, list) and eq:
            return _normalize_three(eq)
    except (ValueError, json.JSONDecodeError, TypeError, KeyError):
        pass

    return deterministic_equivalencies(kg)
