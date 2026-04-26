"""
Instance-type override and required-input validation on /optimize.
"""
from __future__ import annotations


def _payload(**overrides):
    base = {
        "region": "US-CAL-CISO",
        "duration_hours": 4,
        "power_kw": 12,
        "start_after": "2026-04-25T00:00:00Z",
        "deadline": "2026-04-26T23:00:00Z",
    }
    base.update(overrides)
    return base


def test_instance_type_overrides_power_kw(client):
    """If instance_type is set, the response must reflect its power_kw."""
    payload = _payload(power_kw=None, instance_type="gpu.h100.x8")
    r = client.post("/optimize", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["request"]["instance_type"] == "gpu.h100.x8"
    assert body["request"]["power_kw"] == 12.0  # gpu.h100.x8 → 12 kW from lookup


def test_instance_type_unknown_returns_400(client):
    payload = _payload(power_kw=None, instance_type="gpu.totally-fake")
    r = client.post("/optimize", json=payload)
    assert r.status_code == 400
    assert "Unknown instance_type" in r.json()["detail"]


def test_optimize_requires_power_or_instance(client):
    payload = _payload(power_kw=None, instance_type=None)
    r = client.post("/optimize", json=payload)
    # pydantic returns 422 for model-level validation errors
    assert r.status_code == 422
