"""
Deterministic what-if emissions for the Talk-to-agent negotiator.

Uses the same hour-by-hour model as the backend optimizer: for a candidate start,
sum(signal_g_per_kwh * power_kw) for each hour in the job, then / 1000 → kg.
Only shifts with full hourly coverage in `timeseries` are included.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

UTC = timezone.utc


def _parse_ts(s: str) -> datetime:
    s = (s or "").strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _floor_hour(dt: datetime) -> datetime:
    dt = dt.astimezone(UTC)
    return dt.replace(minute=0, second=0, microsecond=0)


def _timeseries_map(series: list[dict[str, Any]]) -> dict[datetime, float]:
    m: dict[datetime, float] = {}
    for p in series:
        if not isinstance(p, dict):
            continue
        ts = p.get("timestamp")
        sig = p.get("signal")
        if ts is None or sig is None:
            continue
        try:
            t = _floor_hour(_parse_ts(str(ts)))
            m[t] = float(sig)
        except (ValueError, TypeError, OSError):
            continue
    return m


def _window_kg(
    hour_to_signal: dict[datetime, float],
    start: datetime,
    duration_hours: int,
    power_kw: float,
) -> float | None:
    if duration_hours < 1 or power_kw <= 0:
        return None
    t = _floor_hour(start)
    total_g = 0.0
    for _ in range(duration_hours):
        sig = hour_to_signal.get(t)
        if sig is None:
            return None
        total_g += sig * power_kw
        t += timedelta(hours=1)
    return total_g / 1000.0


def compute_shift_scenarios(last_optimize: dict[str, Any] | None, *, max_shift: int = 12) -> dict[str, Any]:
    """
    Returns a JSON-serializable dict for the model context, or {} if not computable.
    """
    if not last_optimize or not isinstance(last_optimize, dict):
        return {}

    try:
        opt = last_optimize.get("optimized") or {}
        req = last_optimize.get("request") or {}
        base = last_optimize.get("baseline") or {}
        ts_list = last_optimize.get("timeseries") or []
        if not isinstance(ts_list, list) or not opt.get("start"):
            return {}

        duration = int(round(float(req.get("duration_hours", 1))))
        power_kw = float(req.get("power_kw", 0) or 0)
        if duration < 1 or power_kw <= 0:
            return {}

        m = _timeseries_map(ts_list)
        if not m:
            return {}

        o_start = _floor_hour(_parse_ts(str(opt["start"])))
        opt_kg = float(opt.get("emissions_kg", 0))
        base_kg = float(base.get("emissions_kg", 0)) if isinstance(base, dict) else 0.0

        scenarios: list[dict[str, Any]] = []
        for h in range(-max_shift, max_shift + 1):
            if h == 0:
                continue
            ns = o_start + timedelta(hours=h)
            wk = _window_kg(m, ns, duration, power_kw)
            if wk is None:
                continue
            delta = wk - opt_kg
            pct_vs_opt = (100.0 * delta / opt_kg) if opt_kg > 1e-9 else None
            scenarios.append(
                {
                    "shift_optimized_start_hours": h,
                    "estimated_emissions_kg": round(wk, 3),
                    "delta_kg_vs_current_optimized": round(delta, 3),
                    "delta_percent_vs_current_optimized": None if pct_vs_opt is None else round(pct_vs_opt, 2),
                }
            )

        return {
            "reference_optimized_start_utc": opt.get("start"),
            "reference_optimized_end_utc": opt.get("end"),
            "current_optimized_emissions_kg": opt_kg,
            "baseline_emissions_kg": base_kg,
            "duration_hours": duration,
            "power_kw": power_kw,
            "scenarios": scenarios,
            "note": (
                "Each scenario is the same job duration and power, starting the optimized window "
                f"{max_shift}h earlier through {max_shift}h later, only where hourly grid data exists."
            ),
        }
    except (ValueError, TypeError, KeyError, OSError):
        return {}
