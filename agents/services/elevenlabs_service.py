"""
elevenlabs_service.py
---------------------
Converts a text explanation to speech using the ElevenLabs TTS REST API.

Required environment variable:
    ELEVENLABS_API_KEY   — your ElevenLabs secret key

Optional environment variables:
    ELEVENLABS_VOICE_ID  — ElevenLabs voice ID (default: the free "Rachel" voice)
    ELEVENLABS_MODEL_ID  — model to use          (default: eleven_turbo_v2)

The public function returns a base-64-encoded MP3 string so the caller
(FastAPI route) can embed it directly in a JSON response without needing
a separate file-serving layer.
"""

import asyncio
import base64
import os

import requests
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Constants / defaults
# ---------------------------------------------------------------------------

_BASE_URL = "https://api.elevenlabs.io/v1/text-to-speech"

# "Rachel" — available on the free tier
_DEFAULT_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"
_DEFAULT_MODEL_ID = "eleven_turbo_v2"


# ---------------------------------------------------------------------------
# Internal (sync) helper — runs in a thread so it doesn't block the event loop
# ---------------------------------------------------------------------------

def _call_elevenlabs(text: str) -> str:
    """
    Call the ElevenLabs TTS endpoint synchronously and return
    a base-64-encoded MP3 string.

    Raises:
        EnvironmentError  — ELEVENLABS_API_KEY is not set
        RuntimeError      — the API returned a non-200 status
    """
    api_key = os.getenv("ELEVENLABS_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "ELEVENLABS_API_KEY is not set. "
            "Add it to your .env file or environment before calling /explain/audio."
        )

    voice_id = os.getenv("ELEVENLABS_VOICE_ID", _DEFAULT_VOICE_ID)
    model_id = os.getenv("ELEVENLABS_MODEL_ID", _DEFAULT_MODEL_ID)

    url = f"{_BASE_URL}/{voice_id}"

    headers = {
        "xi-api-key": api_key,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }

    body = {
        "text": text,
        "model_id": model_id,
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.75,
        },
    }

    response = requests.post(url, headers=headers, json=body, timeout=30)

    if response.status_code != 200:
        raise RuntimeError(
            f"ElevenLabs API error {response.status_code}: {response.text}"
        )

    # Encode the raw audio bytes as base-64 so the result is JSON-safe
    audio_b64 = base64.b64encode(response.content).decode("utf-8")
    return audio_b64


# ---------------------------------------------------------------------------
# Public async interface
# ---------------------------------------------------------------------------

async def text_to_speech(text: str) -> str:
    """
    Convert *text* to speech via ElevenLabs and return a base-64 MP3 string.

    The string can be embedded in a JSON response like:
        { "audio_b64": "<result>", "mime_type": "audio/mpeg" }

    The frontend can decode it with:
        const blob = await fetch(`data:audio/mpeg;base64,${audio_b64}`).then(r => r.blob());

    This function is async-safe — the blocking HTTP call runs in a thread pool
    so it does not stall the FastAPI event loop.
    """
    audio_b64 = await asyncio.to_thread(_call_elevenlabs, text)
    return audio_b64
