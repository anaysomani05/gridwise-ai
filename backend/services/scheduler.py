"""
Hourly carbon-aware window selection.

Picks the contiguous N-hour window between `start_after` and `deadline` whose
total grid emissions are lowest, using the provider's hourly carbon intensity
(gCO2/kWh) and a fixed `power_kw` for the run.

Baseline is always ASAP among data-complete starts, so `metrics.co2_saved_kg`
answers: "how much cleaner than just running it right now?"
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from providers.electricity_maps import fetch_carbon_intensity_forecast
from schemas import (
    DataQualityBlock,
    MetricsBlock,
    OptimizeRequest,
    OptimizeResponse,
    ReasoningBlock,
    RequestEcho,
    TimeseriesPoint,
    WindowResult,
)
from services import demo_data
from services.instance_types import power_kw_for
from services.metrics import percent_reduction

UTC = timezone.utc


def _utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def floor_hour(dt: datetime) -> datetime:
    dt = _utc(dt)
    return dt.replace(minute=0, second=0, microsecond=0)


def ceil_hour(dt: datetime) -> datetime:
    dt = _utc(dt)
    if dt == dt.replace(minute=0, second=0, microsecond=0):
        return dt
    return dt.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)


def resolve_power_kw(power_kw: float | None, instance_type: str | None) -> float:
    """
    Pick the effective power for the run.

    `instance_type` (if given) wins, because we treat it as the user telling us
    the SKU explicitly. Otherwise we fall back to the literal `power_kw`.
    Validation that at least one is set lives in the request schema.
    """
    if instance_type:
        return power_kw_for(instance_type)
    assert power_kw is not None  # guaranteed by schema validator
    return float(power_kw)


@dataclass
class _Series:
    points: list[tuple[datetime, int]]
    provider: str
    data_source: str


def _load_series(region: str, start_after: datetime, deadline: datetime) -> _Series:
    start = _utc(start_after)
    dead = _utc(deadline)
    if dead <= start:
        raise ValueError("deadline must be after start_after")

    live = fetch_carbon_intensity_forecast(region, start, dead)
    if live:
        pts = [
            (datetime.fromisoformat(p["timestamp"].replace("Z", "+00:00")), int(round(p["value"])))
            for p in live
        ]
        pts.sort(key=lambda x: x[0])
        return _Series(pts, "electricity_maps", "live")
    demo = demo_data.build_demo_series(region, start, dead)
    return _Series(demo, "demo", "demo")


def _as_map(points: list[tuple[datetime, int]]) -> dict[datetime, int]:
    return {floor_hour(t): v for t, v in points}


def _span_hour_coverage(
    m: dict[datetime, int], h_start: datetime, h_end: datetime
) -> tuple[int, int]:
    """Count hours in [h_start, h_end] that have a value in m, vs total hours in the span."""
    h_start = floor_hour(_utc(h_start))
    h_end = floor_hour(_utc(h_end))
    if h_end < h_start:
        return 0, 0
    t = h_start
    total = 0
    with_data = 0
    while t <= h_end:
        total += 1
        if t in m:
            with_data += 1
        t += timedelta(hours=1)
    return with_data, total


def _window_has_data(m: dict[datetime, int], start: datetime, duration: int) -> bool:
    """True if every hour in [start, start+duration) exists in the carbon map."""
    t = floor_hour(_utc(start))
    for _ in range(duration):
        if t not in m:
            return False
        t += timedelta(hours=1)
    return True


def _window_kg(
    m: dict[datetime, int],
    start: datetime,
    duration: int,
    power_kw: float,
) -> float:
    total = 0.0
    t = floor_hour(_utc(start))
    for _ in range(duration):
        total += m[t] * power_kw
        t += timedelta(hours=1)
    return total / 1000.0


def _window_hours_local(start: datetime, duration: int) -> list[datetime]:
    t = floor_hour(_utc(start))
    return [t + timedelta(hours=i) for i in range(duration)]


def _label(h: datetime) -> str:
    h = _utc(h)
    return f"{h.hour:02d}:00"


# If max–min across the candidate hour span (gCO2/kWh) is at or below this, the grid looks flat.
LOW_CARBON_SPREAD_G = 20

LOW_VARIATION_HINT = (
    "Some regions and time windows have much more variation in carbon intensity than what "
    "you're seeing here, so: change to a region that's known to swing more over the day (for "
    "example, one with lots of solar and wind so midday or overnight is cleaner than the evening), "
    "and try a different start_after / deadline window that covers both daytime and evening so "
    "your candidate run windows can see more variation."
)

# If savings are at or below this % (or no savings at all), the UI can say "timing may not matter much."
HONEST_WEAK_SAVINGS_PCT = 2.0

HONEST_WEAK_SAVINGS_NOTE = (
    "The cleanest time window we found is only slightly better than running as soon as you can. "
    "In some regions the grid's carbon intensity changes little with time of day, so when you run "
    "may not matter much here—that is normal. If you need a larger improvement, try a region with a "
    "stronger daily pattern (e.g. a lot of solar or wind) or a deadline that spans day and night. "
    "Other regions can show a few percent to 10% or more when the mix swings enough."
)

HONEST_NO_IMPROVEMENT_NOTE = (
    "We could not find a time window in this request that improves on \"run as soon as possible\" "
    "for carbon: any slot you pick in this range looks about the same. For some grids that is expected."
)


def _optimization_note(pct: float, saved: float) -> str | None:
    """Mentor-friendly honesty: small or zero gain → say timing may not matter here."""
    if saved <= 0.0:
        return HONEST_NO_IMPROVEMENT_NOTE
    if pct <= HONEST_WEAK_SAVINGS_PCT:
        return HONEST_WEAK_SAVINGS_NOTE
    return None


def _carbon_spread_in_span(
    m: dict[datetime, int], h_start: datetime, h_end: datetime
) -> int:
    h_start = floor_hour(_utc(h_start))
    h_end = floor_hour(_utc(h_end))
    t = h_start
    vals: list[int] = []
    while t <= h_end:
        if t in m:
            vals.append(m[t])
        t += timedelta(hours=1)
    if len(vals) < 2:
        return 0
    return max(vals) - min(vals)


def _reasoning(
    m: dict[datetime, int],
    b_hours: list[datetime],
    o_hours: list[datetime],
    variation_hint: str | None,
) -> ReasoningBlock:
    b_vals = [m[floor_hour(x)] for x in b_hours]
    o_vals = [m[floor_hour(x)] for x in o_hours]
    b_avg = int(round(sum(b_vals) / len(b_vals)))
    o_avg = int(round(sum(o_vals) / len(o_vals)))

    # Show ALL hours of each window in chronological order so the two lists are
    # symmetric and account for the full duration. Previously baseline was capped
    # at top-3 dirtiest, which (for a 4h job) silently dropped the 4th hour and
    # made the UI look inconsistent with `cleaner_hours_used` (which always
    # showed every optimized hour). Averages already convey "how much cleaner".
    return ReasoningBlock(
        baseline_avg_signal=b_avg,
        optimized_avg_signal=o_avg,
        dirtiest_hours_avoided=[_label(t) for t in b_hours],
        cleaner_hours_used=[_label(t) for t in o_hours],
        variation_hint=variation_hint,
    )


@dataclass
class _OptimizeArtifacts:
    """Internal computation result, used both for /optimize and /compare-regions."""

    response: OptimizeResponse
    score_value: float


def _run_optimize_core(
    region: str,
    duration_hours: int,
    power_kw: float,
    start_after: datetime,
    deadline: datetime,
    instance_type: str | None,
) -> _OptimizeArtifacts:
    start = _utc(start_after)
    dead = _utc(deadline)
    d = duration_hours
    p_kw = float(power_kw)

    if dead <= start:
        raise ValueError("deadline must be after start_after")

    first_start = ceil_hour(start)
    last_start = floor_hour(dead) - timedelta(hours=d)
    if first_start > last_start:
        raise ValueError("no feasible schedule: not enough time before the deadline for this duration")

    series = _load_series(region, start, dead)
    m = _as_map(series.points)
    if not m:
        raise ValueError("no carbon data for this window")

    span_end = last_start + timedelta(hours=d - 1)
    known_hours, span_h = _span_hour_coverage(m, first_start, span_end)

    feasible: list[datetime] = []
    s = first_start
    while s <= last_start:
        if _window_has_data(m, s, d):
            feasible.append(s)
        s += timedelta(hours=1)
    if not feasible:
        raise ValueError(
            "no run fits using only the hours the provider actually reported — we do not fill "
            "missing values. The series may be sparse or the forecast may not cover the full "
            "start_after to deadline range. Try a shorter horizon (e.g. next 24–48 hours from now), "
            "a smaller duration_hours, or a window starting closer to the present."
        )

    win_kg: dict[datetime, float] = {s: _window_kg(m, s, d, p_kw) for s in feasible}

    # Baseline: ASAP among data-complete starts (earliest hour with full coverage)
    b_start = feasible[0]
    b_kg = win_kg[b_start]
    b_hours = _window_hours_local(b_start, d)

    o_start = min(feasible, key=lambda s: win_kg[s])
    o_kg = win_kg[o_start]
    o_hours = _window_hours_local(o_start, d)

    saved_kg = round(b_kg - o_kg, 2)
    pct_kg = percent_reduction(b_kg, o_kg)

    span_start = first_start
    span_end = last_start + timedelta(hours=d - 1)
    spread = _carbon_spread_in_span(m, span_start, span_end)
    vhint = LOW_VARIATION_HINT if spread <= LOW_CARBON_SPREAD_G else None

    opt_note = _optimization_note(pct_kg, saved_kg)

    r = _reasoning(m, b_hours, o_hours, vhint)

    cover = round(known_hours / span_h, 4) if span_h else 0.0
    dq = DataQualityBlock(
        span_hours=span_h,
        hours_with_signal=known_hours,
        coverage=cover,
    )

    ts = [TimeseriesPoint(timestamp=t, signal=int(v)) for t, v in sorted(m.items(), key=lambda x: x[0])]

    response = OptimizeResponse(
        request=RequestEcho(
            region=region,
            duration_hours=duration_hours,
            power_kw=p_kw,
            deadline=deadline,
            instance_type=instance_type,
        ),
        provider=series.provider,
        signal_type="carbon_intensity",
        baseline=WindowResult(
            start=b_start,
            end=b_start + timedelta(hours=d),
            emissions_kg=round(b_kg, 2),
        ),
        optimized=WindowResult(
            start=o_start,
            end=o_start + timedelta(hours=d),
            emissions_kg=round(o_kg, 2),
        ),
        metrics=MetricsBlock(
            co2_saved_kg=saved_kg,
            percent_reduction=pct_kg,
            deadline_met=True,
        ),
        timeseries=ts,
        reasoning=r,
        data_source=series.data_source,  # type: ignore[arg-type]
        optimization_note=opt_note,
        data_quality=dq,
    )
    return _OptimizeArtifacts(response=response, score_value=o_kg)


def run_optimize(req: OptimizeRequest) -> OptimizeResponse:
    """Public entry for POST /optimize."""
    p_kw = resolve_power_kw(req.power_kw, req.instance_type)
    return _run_optimize_core(
        region=req.region,
        duration_hours=req.duration_hours,
        power_kw=p_kw,
        start_after=req.start_after,
        deadline=req.deadline,
        instance_type=req.instance_type,
    ).response
