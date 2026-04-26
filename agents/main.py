import os
from contextlib import asynccontextmanager
from typing import Any, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

load_dotenv()


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("GridWise Agent Layer starting up…")
    yield
    print("GridWise Agent Layer shutting down…")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="GridWise AI Agent Layer",
    description=(
        "Explains carbon-aware scheduling decisions using Gemma 4, "
        "stores run history, and optionally generates spoken explanations via ElevenLabs."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Lazy service imports
# Missing env vars surface at call-time, not at startup.
# ---------------------------------------------------------------------------


def _gemma():
    from services.gemma_service import generate_explanation

    return generate_explanation


def _memory():
    from services.memory_service import get_history, save_run

    return save_run, get_history


def _tts():
    from services.elevenlabs_service import text_to_speech

    return text_to_speech


# ---------------------------------------------------------------------------
# Pydantic models — mirror the backend POST /optimize response exactly.
#
# Backend contract (frozen sample):
# {
#   "request":   { region, duration_hours, power_kw, deadline },
#   "provider":  "electricity_maps",
#   "signal_type": "carbon_intensity",
#   "baseline":  { start, end, emissions_kg },
#   "optimized": { start, end, emissions_kg },
#   "metrics":   { co2_saved_kg, percent_reduction, deadline_met },
#   "timeseries": [ { timestamp, signal } … ],
#   "reasoning": { baseline_avg_signal, optimized_avg_signal,
#                  dirtiest_hours_avoided, cleaner_hours_used },
#   "source":    "live" | "fallback_demo_data"   (optional)
# }
#
# Units:
#   timeseries[].signal  — gCO₂eq/kWh
#   emissions_kg         — kg CO₂
#   All timestamps       — ISO 8601 UTC
# ---------------------------------------------------------------------------


class RequestInfo(BaseModel):
    region: str
    duration_hours: float
    power_kw: float
    deadline: str  # ISO 8601 UTC


class Window(BaseModel):
    start: str  # ISO 8601 UTC
    end: str  # ISO 8601 UTC
    emissions_kg: float  # kg CO₂


class Metrics(BaseModel):
    co2_saved_kg: float
    percent_reduction: float
    deadline_met: bool


class TimeseriesPoint(BaseModel):
    timestamp: str  # ISO 8601 UTC
    signal: float  # gCO₂eq/kWh


class Reasoning(BaseModel):
    baseline_avg_signal: float  # gCO₂eq/kWh
    optimized_avg_signal: float  # gCO₂eq/kWh
    dirtiest_hours_avoided: list[str]  # e.g. ["18:00", "19:00"]
    cleaner_hours_used: list[str]  # e.g. ["01:00", "02:00"]


class OptimizeResponse(BaseModel):
    """
    Exact shape of the backend POST /optimize response.
    Pass this whole object to POST /explain — do not recompute any numbers.
    """

    request: RequestInfo
    provider: str  # e.g. "electricity_maps"
    signal_type: str  # e.g. "carbon_intensity"
    baseline: Window
    optimized: Window
    metrics: Metrics
    timeseries: list[TimeseriesPoint]
    reasoning: Reasoning
    source: Optional[str] = None  # "live" | "fallback_demo_data"


# ---------------------------------------------------------------------------
# Request / response wrappers for agent-layer routes
# ---------------------------------------------------------------------------


class SaveRunRequest(BaseModel):
    payload: OptimizeResponse
    explanation: str
    user_id: Optional[str] = "default"


class ExplainResponse(BaseModel):
    explanation_text: str
    audio_available: bool


class AudioExplainResponse(BaseModel):
    explanation_text: str
    audio_b64: Optional[str] = None
    mime_type: str = "audio/mpeg"


class SaveRunResponse(BaseModel):
    status: str
    run_id: str


class HistoryResponse(BaseModel):
    runs: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/", tags=["Health"])
def root():
    """Quick liveness check."""
    return {"status": "GridWise Agent Layer is running", "version": "1.0.0"}


@app.get("/health", tags=["Health"])
def health():
    """Health probe for load-balancers / CI checks."""
    return {"status": "ok", "service": "agents", "version": "1.0.0"}


@app.post("/explain", response_model=ExplainResponse, tags=["Agent"])
async def explain(payload: OptimizeResponse):
    """
    Accept the **full** backend POST /optimize response and return a
    natural-language explanation generated by Gemma 4.

    Rules enforced by the prompt:
    - Only narrate numbers already present in the JSON.
    - Never invent metric values, change windows, or recompute emissions.
    - Mention: baseline window, optimized window, CO₂ saved, % reduction,
      deadline status, and dirtiest/cleaner hours.
    """
    generate_explanation = _gemma()

    try:
        explanation_text = await generate_explanation(payload.model_dump())
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"Gemma service error: {exc}"
        ) from exc

    audio_available = bool(os.getenv("ELEVENLABS_API_KEY"))

    return ExplainResponse(
        explanation_text=explanation_text,
        audio_available=audio_available,
    )


@app.post("/explain/audio", response_model=AudioExplainResponse, tags=["Agent"])
async def explain_with_audio(payload: OptimizeResponse):
    """
    Generate a Gemma 4 explanation **and** convert it to speech via ElevenLabs.
    Returns both the text and an audio URL / base-64 blob.

    Requires: ELEVENLABS_API_KEY environment variable.
    """
    if not os.getenv("ELEVENLABS_API_KEY"):
        raise HTTPException(
            status_code=503,
            detail="ELEVENLABS_API_KEY is not configured — audio is unavailable.",
        )

    generate_explanation = _gemma()
    text_to_speech = _tts()

    try:
        explanation_text = await generate_explanation(payload.model_dump())
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"Gemma service error: {exc}"
        ) from exc

    try:
        audio_b64 = await text_to_speech(explanation_text)
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"ElevenLabs service error: {exc}"
        ) from exc

    return AudioExplainResponse(
        explanation_text=explanation_text,
        audio_b64=audio_b64,
        mime_type="audio/mpeg",
    )


@app.post("/save-run", response_model=SaveRunResponse, tags=["Memory"])
async def save_run_endpoint(body: SaveRunRequest):
    """
    Persist the current optimization run + explanation to memory.
    The payload is the full OptimizeResponse so history comparisons
    can reference exact signal values and windows.
    """
    save_run, _ = _memory()

    try:
        run_id = await save_run(
            payload=body.payload.model_dump(),
            explanation=body.explanation,
            user_id=body.user_id or "default",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"Memory service error: {exc}"
        ) from exc

    return SaveRunResponse(status="saved", run_id=run_id)


@app.get("/history", response_model=HistoryResponse, tags=["Memory"])
async def history(user_id: str = "default"):
    """
    Return previous optimization runs for a given user.

    The frontend uses this for the history panel and comparison messages
    such as "Compared to your last run, this schedule saved 4% more CO₂."
    """
    _, get_history = _memory()

    try:
        runs = await get_history(user_id=user_id)
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"Memory service error: {exc}"
        ) from exc

    return HistoryResponse(runs=runs)


# ---------------------------------------------------------------------------
# Entry-point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.getenv("AGENT_PORT", "8001")),
        reload=os.getenv("RELOAD", "true").lower() == "true",
    )
