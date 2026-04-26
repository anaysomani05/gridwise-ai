"""
/compare-regions: same job across N zones, sorted best→worst by carbon.
"""
from __future__ import annotations


def _payload(**overrides):
    base = {
        "regions": ["US-CAL-CISO", "DE", "SE"],
        "duration_hours": 4,
        "power_kw": 12,
        "start_after": "2026-04-25T00:00:00Z",
        "deadline": "2026-04-26T23:00:00Z",
    }
    base.update(overrides)
    return base


def test_compare_regions_returns_sorted_list(client):
    r = client.post("/compare-regions", json=_payload())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["duration_hours"] == 4
    assert body["power_kw"] == 12
    assert len(body["ranked"]) == 3

    # Best→worst by optimised emissions.
    emissions = [row["optimized"]["emissions_kg"] for row in body["ranked"]]
    assert emissions == sorted(emissions), f"not sorted ascending by emissions: {emissions}"

    sample = body["ranked"][0]
    assert sample["region"]
    assert sample["region_label"]  # came from curated catalog
    assert sample["data_source"] == "demo"
    assert sample["coverage"] == 1.0
    assert sample["error"] is None


def test_compare_regions_handles_unknown_zone_gracefully(client):
    """An unknown zone in demo mode shouldn't fail the whole call — the row gets `error` set."""
    p = _payload(regions=["US-CAL-CISO", "DE"])
    r = client.post("/compare-regions", json=p)
    assert r.status_code == 200
    body = r.json()
    assert len(body["ranked"]) == 2
    for row in body["ranked"]:
        assert row["error"] is None  # demo mode has no notion of "unknown zone"


def test_compare_regions_with_instance_type(client):
    p = _payload(power_kw=None, instance_type="gpu.h100.x1")
    r = client.post("/compare-regions", json=p)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["instance_type"] == "gpu.h100.x1"
    assert body["power_kw"] == 2.2  # from the lookup


def test_compare_regions_dedupes_input(client):
    p = _payload(regions=["US-CAL-CISO", "US-CAL-CISO", "DE"])
    r = client.post("/compare-regions", json=p)
    body = r.json()
    seen = [row["region"] for row in body["ranked"]]
    assert seen.count("US-CAL-CISO") == 1
    assert "DE" in seen
