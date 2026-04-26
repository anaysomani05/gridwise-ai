import os
from contextlib import asynccontextmanager
from typing import Any, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

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
        "Explains carbon-aware scheduling decisions using Gemma 4 and "
        "optionally generates spoken explanations via ElevenLabs."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5500",
        "http://127.0.0.1:5500",
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


def _tts():
    from services.elevenlabs_service import text_to_speech

    return text_to_speech


def _chat_turn():
    from services.chat_service import generate_chat_turn

    return generate_chat_turn


def _equiv():
    from services.equivalency_service import generate_equivalencies

    return generate_equivalencies


# Pydantic models mirror backend POST /optimize (authoritative numbers for /explain).


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


class ExplainResponse(BaseModel):
    explanation_text: str
    audio_available: bool


class AudioExplainResponse(BaseModel):
    explanation_text: str
    audio_b64: Optional[str] = None
    mime_type: str = "audio/mpeg"


class ChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    """Talk-to-agent: goals + optional last_run summary + optional last_optimize digest for negotiation."""

    messages: list[ChatMessage]
    last_run: Optional[dict[str, Any]] = Field(
        default=None,
        description="Slim summary from the browser (region, last metrics).",
    )
    last_optimize: Optional[dict[str, Any]] = Field(
        default=None,
        description="Digest of last POST /optimize (windows, metrics, timeseries) for what-if answers.",
    )
    form_state: dict[str, Any]


class ChatResponse(BaseModel):
    assistant_message: str
    patch: dict[str, Any] = Field(default_factory=dict)
    suggest_optimize: bool = False


class EquivalenciesResponse(BaseModel):
    """Exactly three short lines for the dashboard."""

    equivalencies: list[str] = Field(
        ...,
        min_length=3,
        max_length=3,
        description="Three fun CO₂ analogies grounded in the optimize payload.",
    )


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


@app.post("/equivalencies", response_model=EquivalenciesResponse, tags=["Agent"])
async def equivalencies(payload: OptimizeResponse):
    """
    Turn the POST /optimize JSON into three short, relatable CO₂-saved lines (Gemma),
    with deterministic fallbacks if the model or key is unavailable.
    """
    gen = _equiv()
    try:
        lines = await gen(payload.model_dump())
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"Equivalency generation failed: {exc}"
        ) from exc
    if len(lines) != 3:
        raise HTTPException(status_code=502, detail="Expected exactly three equivalency lines.")
    return EquivalenciesResponse(equivalencies=lines)


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


@app.post("/chat", response_model=ChatResponse, tags=["Agent"])
async def chat(req: ChatRequest):
    """
    Conversational assistant: returns prose plus an optional field patch.
    Frontend merges the patch into the job form and may POST /optimize on the backend.
    """
    generate_chat_turn = _chat_turn()
    msgs = [m.model_dump() for m in req.messages]
    try:
        out = await generate_chat_turn(
            messages=msgs,
            last_run=req.last_run,
            form_state=req.form_state,
            last_optimize=req.last_optimize,
        )
        return ChatResponse(**out)
    except EnvironmentError:
        return ChatResponse(
            assistant_message=(
                "I need GEMINI_API_KEY on this agent service to chat about your run and what-if timing trade-offs. "
                "You can still use quick actions that update job fields locally, then press Optimize on the Dashboard."
            ),
            patch={},
            suggest_optimize=False,
        )
    except Exception as exc:
        return ChatResponse(
            assistant_message=f"I hit a snag talking to the model ({exc!s}). Try a quick action or shorten your message.",
            patch={},
            suggest_optimize=False,
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
