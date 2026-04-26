"""
Synthetic hourly carbon intensity (gCO2/kWh) for demos when the live API is off.
Scales a simple day/night pattern across the requested UTC range.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

UTC = timezone.utc


def _hourly_range(start: datetime, end: datetime) -> list[datetime]:
    """All UTC hour starts from floor(start) through last hour before end (inclusive span for optimization)."""
    t = _floor_utc_hour(start)
    end_floor = _floor_utc_hour(end)
    if t > end_floor:
        return []
    out: list[datetime] = []
    while t <= end_floor:
        out.append(t)
        t += timedelta(hours=1)
    return out


def _floor_utc_hour(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    dt = dt.astimezone(UTC)
    return dt.replace(minute=0, second=0, microsecond=0)


def _synthetic_signal(hour_utc: datetime) -> int:
    """Rough CA-like pattern: high evening, low early morning. Deterministic, demo-only."""
    h = hour_utc.astimezone(UTC).hour
    if 0 <= h <= 6:
        return 260 + (h * 3) % 30
    if 7 <= h <= 15:
        return 300 + h * 4
    if 16 <= h <= 23:
        return 380 + (h - 16) * 10
    return 350


def build_demo_series(
    region: str,
    start_after: datetime,
    deadline: datetime,
) -> list[tuple[datetime, int]]:
    """
    Hourly gCO2/kWh points from the first needed hour through the last hour that can
    appear in any job window ending on or before `deadline` (hourly grid, UTC).
    `region` is reserved for future zone-specific curves.
    """
    _ = region
    t0 = _floor_utc_hour(start_after)
    # Last hour a job can occupy ends strictly before the instant `deadline`; for hour-aligned
    # jobs, the last start hour h satisfies h + D <= floor(deadline) when deadline is on the hour.
    t_last = _floor_utc_hour(deadline) - timedelta(hours=1)
    times = _hourly_range(t0, t_last)
    return [(h, _synthetic_signal(h)) for h in times]
