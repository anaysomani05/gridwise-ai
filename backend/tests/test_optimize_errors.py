"""
Validation and error-mapping tests: bad inputs should map to 400 (ValueError),
provider failures to 502, schema violations to 422.
"""
from __future__ import annotations


def _payload(**overrides):
    base = {
        "region": "US-CAL-CISO",
        "duration_hours": 4,
        "power_kw": 12,
        "start_after": "2026-04-25T12:00:00Z",
        "deadline": "2026-04-27T04:00:00Z",
    }
    base.update(overrides)
    return base


def test_deadline_before_start_returns_400(client):
    p = _payload(start_after="2026-04-25T12:00:00Z", deadline="2026-04-25T11:00:00Z")
    r = client.post("/optimize", json=p)
    assert r.status_code == 400
    assert "deadline" in r.json()["detail"].lower()


def test_no_feasible_window_returns_400(client):
    """duration > available hours → infeasible."""
    p = _payload(
        start_after="2026-04-25T12:00:00Z",
        deadline="2026-04-25T14:00:00Z",
        duration_hours=4,
    )
    r = client.post("/optimize", json=p)
    assert r.status_code == 400
    assert "feasible" in r.json()["detail"].lower() or "deadline" in r.json()["detail"].lower()


def test_invalid_duration_returns_422(client):
    p = _payload(duration_hours=0)
    r = client.post("/optimize", json=p)
    assert r.status_code == 422


def test_invalid_power_kw_returns_422(client):
    p = _payload(power_kw=-5)
    r = client.post("/optimize", json=p)
    assert r.status_code == 422
