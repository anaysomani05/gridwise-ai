"""
Multi-region comparison: run the same job across N zones, rank by emissions.

Reuses the single-region optimizer per zone and sorts ascending by the optimised
window's emissions. Errors per region are caught and surfaced — one bad zone
never breaks the whole comparison.
"""
from __future__ import annotations

from schemas import (
    CompareRegionResult,
    CompareRegionsRequest,
    CompareRegionsResponse,
)
from services.regions import get_region
from services.scheduler import _run_optimize_core, resolve_power_kw


def run_compare_regions(req: CompareRegionsRequest) -> CompareRegionsResponse:
    p_kw = resolve_power_kw(req.power_kw, req.instance_type)

    successes: list[CompareRegionResult] = []
    failures: list[CompareRegionResult] = []

    seen: set[str] = set()
    for region in req.regions:
        if region in seen:
            continue
        seen.add(region)

        meta = get_region(region)
        label = meta.label if meta else None
        try:
            art = _run_optimize_core(
                region=region,
                duration_hours=req.duration_hours,
                power_kw=p_kw,
                start_after=req.start_after,
                deadline=req.deadline,
                instance_type=req.instance_type,
            )
            resp = art.response
            successes.append(
                CompareRegionResult(
                    region=region,
                    region_label=label,
                    optimized=resp.optimized,
                    baseline=resp.baseline,
                    metrics=resp.metrics,
                    data_source=resp.data_source,
                    coverage=resp.data_quality.coverage if resp.data_quality else None,
                )
            )
        except Exception as exc:  # noqa: BLE001 — we want to surface any failure verbatim
            failures.append(
                CompareRegionResult(
                    region=region,
                    region_label=label,
                    optimized=_blank_window(),
                    baseline=_blank_window(),
                    metrics=_blank_metrics(),
                    data_source="demo",
                    coverage=None,
                    error=str(exc),
                )
            )

    successes.sort(key=lambda r: r.optimized.emissions_kg)
    ranked = successes + failures

    return CompareRegionsResponse(
        duration_hours=req.duration_hours,
        power_kw=p_kw,
        instance_type=req.instance_type,
        ranked=ranked,
    )


def _blank_window():
    from datetime import datetime, timezone

    from schemas import WindowResult

    z = datetime(1970, 1, 1, tzinfo=timezone.utc)
    return WindowResult(start=z, end=z, emissions_kg=0.0)


def _blank_metrics():
    from schemas import MetricsBlock

    return MetricsBlock(
        co2_saved_kg=0.0,
        percent_reduction=0.0,
        deadline_met=False,
    )
