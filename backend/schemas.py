from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class OptimizeRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "region": "US-CAL-CISO",
                "job_name": "demo-job",
                "duration_hours": 4,
                "power_kw": 12,
                "start_after": "2026-04-25T12:00:00Z",
                "deadline": "2026-04-27T04:00:00Z",
            }
        }
    )

    region: str = Field(..., examples=["US-CAL-CISO"])
    job_name: str | None = Field(default=None, examples=["nightly-training"])
    duration_hours: int = Field(..., ge=1, le=168, description="Contiguous run length in hours")
    power_kw: float | None = Field(
        default=None,
        gt=0,
        description="Constant power for the run. Optional only when `instance_type` is set.",
    )
    instance_type: str | None = Field(
        default=None,
        description="Optional hardware preset (see GET /instance-types). When set, overrides power_kw.",
    )
    start_after: datetime
    deadline: datetime

    @model_validator(mode="after")
    def _power_or_instance(self) -> "OptimizeRequest":
        if self.power_kw is None and self.instance_type is None:
            raise ValueError(
                "either power_kw or instance_type must be provided"
            )
        return self


class CompareRegionsRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "regions": ["US-CAL-CISO", "DE", "SE"],
                "job_name": "demo-job",
                "duration_hours": 4,
                "power_kw": 12,
                "start_after": "2026-04-25T12:00:00Z",
                "deadline": "2026-04-27T04:00:00Z",
            }
        }
    )
    regions: list[str] = Field(..., min_length=1, max_length=10)
    job_name: str | None = None
    duration_hours: int = Field(..., ge=1, le=168)
    power_kw: float | None = Field(default=None, gt=0)
    instance_type: str | None = None
    start_after: datetime
    deadline: datetime

    @model_validator(mode="after")
    def _power_or_instance(self) -> "CompareRegionsRequest":
        if self.power_kw is None and self.instance_type is None:
            raise ValueError(
                "either power_kw or instance_type must be provided"
            )
        return self


class RequestEcho(BaseModel):
    region: str
    duration_hours: int
    power_kw: float
    deadline: datetime
    instance_type: str | None = None


class WindowResult(BaseModel):
    start: datetime
    end: datetime
    emissions_kg: float


class MetricsBlock(BaseModel):
    co2_saved_kg: float
    percent_reduction: float
    deadline_met: bool


class TimeseriesPoint(BaseModel):
    timestamp: datetime
    signal: int


class ReasoningBlock(BaseModel):
    baseline_avg_signal: int
    optimized_avg_signal: int
    dirtiest_hours_avoided: list[str]
    cleaner_hours_used: list[str]
    variation_hint: str | None = Field(
        default=None,
        description="Present when the grid signal barely moves; suggests region/window for stronger shifts.",
    )


class DataQualityBlock(BaseModel):
    """Coverage of the provider's hourly signal across the optimization span (no imputation)."""

    span_hours: int = Field(
        description="Number of hours in the optimization candidate span (first possible start through last job hour)."
    )
    hours_with_signal: int = Field(
        description="How many of those hours have a value from the provider. Missing hours are left empty (not imputed).",
    )
    coverage: float = Field(
        ge=0.0,
        le=1.0,
        description="hours_with_signal / span_hours. 1.0 = every hour in the span is reported; lower means sparse data in that range.",
    )


class OptimizeResponse(BaseModel):
    request: RequestEcho
    provider: str
    signal_type: str = "carbon_intensity"
    baseline: WindowResult
    optimized: WindowResult
    metrics: MetricsBlock
    timeseries: list[TimeseriesPoint]
    reasoning: ReasoningBlock
    data_source: Literal["live", "demo"] = "demo"
    optimization_note: str | None = Field(
        default=None,
        description="Plain-language honesty when the best window barely beats baseline—timing may not matter much for that grid/period. Null when the gap is material (e.g. many regions with strong daily patterns show higher %).",
    )
    data_quality: DataQualityBlock | None = Field(
        default=None,
        description="How dense the reported signal is in the optimization span. Optimizer only uses real hourly values (no fill).",
    )


class RegionInfo(BaseModel):
    code: str
    label: str
    country: str
    variation_hint: Literal["strong", "moderate", "flat"]


class RegionsResponse(BaseModel):
    regions: list[RegionInfo]


class InstanceTypeInfo(BaseModel):
    name: str
    power_kw: float
    label: str
    category: Literal["cpu", "gpu", "training-cluster"]


class InstanceTypesResponse(BaseModel):
    instance_types: list[InstanceTypeInfo]


class CompareRegionResult(BaseModel):
    region: str
    region_label: str | None = None
    optimized: WindowResult
    baseline: WindowResult
    metrics: MetricsBlock
    data_source: Literal["live", "demo"]
    coverage: float | None = None
    error: str | None = Field(
        default=None,
        description="Set when this region failed (no feasible window, provider error, etc.). Other fields will be null.",
    )


class CompareRegionsResponse(BaseModel):
    duration_hours: int
    power_kw: float
    instance_type: str | None = None
    ranked: list[CompareRegionResult] = Field(
        description=(
            "Regions sorted best→worst by optimised emissions (lowest first). "
            "Regions with errors are appended last with `error` set."
        )
    )
