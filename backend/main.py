from __future__ import annotations

from fastapi import FastAPI, HTTPException
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
    """Curated list of supported zones for the dropdown — keeps the FE from guessing zone strings."""
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
