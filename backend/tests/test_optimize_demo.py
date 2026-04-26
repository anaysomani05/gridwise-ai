"""
Happy-path /optimize tests using the deterministic demo-data provider
(no API token in the env, so the scheduler falls back to demo).
"""
from __future__ import annotations


def _demo_payload(**overrides):
    base = {
        "region": "US-CAL-CISO",
        "job_name": "demo-job",
        "duration_hours": 4,
        "power_kw": 12,
        "start_after": "2026-04-25T12:00:00Z",
        "deadline": "2026-04-27T04:00:00Z",
    }
    base.update(overrides)
    return base


def test_optimize_demo_basic(client):
    r = client.post("/optimize", json=_demo_payload())
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["data_source"] == "demo"
    assert body["provider"] == "demo"

    b = body["baseline"]
    o = body["optimized"]
    assert o["emissions_kg"] <= b["emissions_kg"], "optimised should never be worse than baseline"
    assert body["metrics"]["co2_saved_kg"] >= 0
    assert body["metrics"]["percent_reduction"] >= 0
    assert body["metrics"]["deadline_met"] is True

    assert body["data_quality"]["coverage"] == 1.0  # demo data is always full
    assert len(body["timeseries"]) >= body["request"]["duration_hours"]
    r_block = body["reasoning"]
    assert len(r_block["dirtiest_hours_avoided"]) > 0
    assert len(r_block["cleaner_hours_used"]) > 0


def test_optimize_demo_real_savings(client):
    """Demo curve has a strong day/night swing; the optimizer must beat ASAP."""
    r = client.post("/optimize", json=_demo_payload())
    body = r.json()
    assert body["metrics"]["percent_reduction"] > 0
    assert body["baseline"]["start"] != body["optimized"]["start"]


def test_optimize_demo_short_window_one_feasible(client):
    """When start_after and deadline barely fit the duration, baseline == optimized."""
    payload = _demo_payload(
        start_after="2026-04-25T12:00:00Z",
        deadline="2026-04-25T16:00:00Z",
        duration_hours=4,
    )
    r = client.post("/optimize", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["baseline"]["start"] == body["optimized"]["start"]
    assert body["metrics"]["co2_saved_kg"] == 0.0
    assert body["metrics"]["percent_reduction"] == 0.0
    # Optimization note should kick in for zero-improvement runs.
    assert body["optimization_note"] is not None
