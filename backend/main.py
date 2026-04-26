from __future__ import annotations

from typing import Any

import httpx
from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from providers.electricity_maps import ElectricityMapsError
from schemas import (
    CompareRegionsRequest,
    CompareRegionsResponse,
    InstanceTypeInfo,
    InstanceTypesResponse,
    OptimizeRequest,
    OptimizeResponse,
    RegionInfo,
    RegionsResponse,
)
from services.cache import provider_cache
from services.compare import run_compare_regions
from services.instance_types import UnknownInstanceType, list_instance_types
from services.regions import list_regions
from services.scheduler import run_optimize


def _proxy_agent_json(path: str, body: dict[str, Any]) -> dict[str, Any]:
    """POST JSON to the agent service; used by /chat and /equivalencies proxies."""
    base = settings.agent_service_url.rstrip("/")
    url = f"{base}{path}"
    try:
        with httpx.Client(timeout=90.0) as client:
            r = client.post(url, json=body)
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Agent service unreachable at {url}: {exc}",
        ) from exc
    if r.status_code >= 400:
        raise HTTPException(
            status_code=r.status_code,
            detail=(r.text or "agent error")[:800],
        )
    try:
        return r.json()
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Agent returned non-JSON: {exc}",
        ) from exc


app = FastAPI(
    title="GridWise API",
    description="Carbon-aware compute scheduling (optimizer backend).",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root() -> dict[str, str]:
    """So opening http://127.0.0.1:8000/ in a browser is not 404."""
    return {
        "name": "GridWise API",
        "docs": "/docs",
        "health": "/health",
        "regions": "GET /regions",
        "instance_types": "GET /instance-types",
        "optimize": "POST /optimize",
        "chat": "POST /chat (proxies to agent scheduling assistant)",
        "equivalencies": "POST /equivalencies (proxies to agent fun CO₂ lines)",
        "compare_regions": "POST /compare-regions",
    }


@app.get("/health")
def health() -> dict[str, object]:
    return {
        "status": "ok",
        "version": app.version,
        "cache": provider_cache.stats(),
    }


@app.get("/regions", response_model=RegionsResponse)
def regions() -> RegionsResponse:
    """Zones for the dropdown: hand-picked catalog plus any extra from EM ``GET /v3/zones`` when a token is set."""
    return RegionsResponse(
        regions=[
            RegionInfo(
                code=r.code,
                label=r.label,
                country=r.country,
                variation_hint=r.variation_hint,  # type: ignore[arg-type]
            )
            for r in list_regions()
        ]
    )


@app.get("/instance-types", response_model=InstanceTypesResponse)
def instance_types() -> InstanceTypesResponse:
    """Hardware presets clients can pass as `instance_type` instead of raw `power_kw`."""
    return InstanceTypesResponse(
        instance_types=[
            InstanceTypeInfo(
                name=i.name,
                power_kw=i.power_kw,
                label=i.label,
                category=i.category,  # type: ignore[arg-type]
            )
            for i in list_instance_types()
        ]
    )


@app.post("/chat")
def chat_proxy(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """
    Proxy to the agent service's POST /chat so the browser only needs the
    optimizer base URL for both carbon math (/optimize) and conversational tuning (/chat).
    """
    return _proxy_agent_json("/chat", body)


@app.post("/equivalencies")
def equivalencies_proxy(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Proxy POST /equivalencies → agent (same pattern as /chat)."""
    return _proxy_agent_json("/equivalencies", body)


@app.post("/optimize", response_model=OptimizeResponse)
def optimize(body: OptimizeRequest) -> OptimizeResponse:
    try:
        return run_optimize(body)
    except UnknownInstanceType as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ElectricityMapsError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@app.post("/compare-regions", response_model=CompareRegionsResponse)
def compare_regions(body: CompareRegionsRequest) -> CompareRegionsResponse:
    try:
        return run_compare_regions(body)
    except UnknownInstanceType as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
