"""Emissions metric helpers (kept small; core math lives in `scheduler.py`)."""


def percent_reduction(baseline: float, optimized: float) -> float:
    """
    Generic percent reduction: how much smaller `optimized` is than `baseline`.

    Returns 0.0 when the baseline is non-positive (avoids divide-by-zero and a
    misleading 100% saving when the baseline itself is essentially zero).
    """
    if baseline <= 0:
        return 0.0
    return round(100.0 * (1.0 - optimized / baseline), 2)
