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

from google import genai
from google.genai import types

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_MODEL = os.getenv("GEMMA_MODEL", "gemma-3-27b-it")

_SYSTEM_INSTRUCTION = """\
You are a carbon-aware scheduling assistant for GridWise.
Your only job is to explain, in plain English, a scheduling decision that \
has already been made by the optimizer.

Rules you must never break:
- Use ONLY the numbers and time windows provided in the JSON payload.
- Do NOT invent, estimate, or round any metric values.
- Do NOT suggest a different schedule or re-compute savings.
- Do NOT mention machine-learning, AI, or model names.
- Be concise: aim for 3-5 sentences, no bullet points, no markdown.
- Always state: the baseline window, the optimized window, the CO₂ saving \
(kg and percent), and whether the deadline is met.
- Write in a friendly, non-technical tone suitable for a dashboard card.
"""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_prompt(payload: dict) -> str:
    """
    Serialize the optimizer payload as indented JSON and attach it to the
    instruction so Gemma has all facts in a single user turn.
    """
    return (
        "Here is the carbon scheduling result. Explain it to the user.\n\n"
        "```json\n" + json.dumps(payload, indent=2) + "\n```"
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
                system_instruction=_SYSTEM_INSTRUCTION,
                temperature=0.2,  # low = more factual, less creative
                max_output_tokens=300,
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
