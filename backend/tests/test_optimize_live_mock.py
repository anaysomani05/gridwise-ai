"""
Tests the live Electricity Maps code path with a mocked httpx transport.

This proves:
- past-range and forecast responses are parsed and merged.
- the cache is consulted (second identical /optimize call does not re-fetch).
- a sparse provider response surfaces in `data_quality.coverage`.
- a provider-side 401 maps to HTTP 502.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _hourly(start: datetime, hours: int, signal_seq) -> list[dict]:
    out = []
    for i in range(hours):
        out.append(
            {"datetime": _iso(start + timedelta(hours=i)), "carbonIntensity": signal_seq[i]}
        )
    return out


def _install_mock_transport(monkeypatch, handler):
    """Patch httpx.Client so the provider talks to a MockTransport."""
    real_client = httpx.Client

    def factory(*args, **kwargs):
        kwargs.pop("transport", None)
        return real_client(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx, "Client", factory)


def test_live_mode_parses_past_and_forecast_then_caches(client, live_token_env, monkeypatch):
    start = datetime(2026, 4, 25, 12, 0, 0, tzinfo=timezone.utc)
    deadline = start + timedelta(hours=24)
    span_hours = int((deadline - start).total_seconds() // 3600) + 1

    # Build a clean varying signal
    sig = [200 + (i % 6) * 30 for i in range(span_hours + 4)]

    call_counter = {"past_range": 0, "forecast": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if "past-range" in request.url.path:
            call_counter["past_range"] += 1
            return httpx.Response(
                200,
                json={"history": _hourly(start, span_hours, sig)},
            )
        if "forecast" in request.url.path:
            call_counter["forecast"] += 1
            # forecast continues a few hours past the past-range
            future_start = start + timedelta(hours=span_hours)
            return httpx.Response(
                200,
                json={"forecast": _hourly(future_start, 4, sig[span_hours:])},
            )
        return httpx.Response(404)

    _install_mock_transport(monkeypatch, handler)

    payload = {
        "region": "US-CAL-CISO",
        "duration_hours": 4,
        "power_kw": 12,
        "start_after": _iso(start),
        "deadline": _iso(deadline),
    }

    r1 = client.post("/optimize", json=payload)
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    assert body1["data_source"] == "live"
    assert body1["provider"] == "electricity_maps"
    assert call_counter == {"past_range": 1, "forecast": 1}

    # Same request → must hit the cache, not re-call.
    r2 = client.post("/optimize", json=payload)
    assert r2.status_code == 200
    assert call_counter == {"past_range": 1, "forecast": 1}, "second call should be cached"

    # Cache stats should reflect at least one hit.
    stats = client.get("/health").json()["cache"]
    assert stats["hits"] >= 1


def test_live_mode_sparse_coverage(client, live_token_env, monkeypatch):
    """Provider returns only a few hours of the requested span → coverage < 1.0."""
    start = datetime(2026, 4, 25, 12, 0, 0, tzinfo=timezone.utc)
    deadline = start + timedelta(hours=24)

    # Only return 8 hours starting from the very start.
    partial = _hourly(start, 8, [220, 230, 240, 260, 280, 300, 320, 340])

    def handler(request: httpx.Request) -> httpx.Response:
        if "past-range" in request.url.path:
            return httpx.Response(200, json={"history": partial})
        if "forecast" in request.url.path:
            return httpx.Response(200, json={"forecast": []})
        return httpx.Response(404)

    _install_mock_transport(monkeypatch, handler)

    payload = {
        "region": "US-CAL-CISO",
        "duration_hours": 4,
        "power_kw": 12,
        "start_after": _iso(start),
        "deadline": _iso(deadline),
    }

    r = client.post("/optimize", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["data_source"] == "live"
    dq = body["data_quality"]
    assert dq is not None
    assert dq["coverage"] < 1.0
    assert dq["hours_with_signal"] < dq["span_hours"]


def test_live_mode_provider_auth_failure_maps_to_502(client, live_token_env, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "bad token"})

    _install_mock_transport(monkeypatch, handler)

    payload = {
        "region": "US-CAL-CISO",
        "duration_hours": 4,
        "power_kw": 12,
        "start_after": "2026-04-25T12:00:00Z",
        "deadline": "2026-04-26T12:00:00Z",
    }
    r = client.post("/optimize", json=payload)
    assert r.status_code == 502
    assert "auth" in r.json()["detail"].lower()
