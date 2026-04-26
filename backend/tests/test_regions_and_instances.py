def test_regions_merges_zones_from_em_api(client, live_token_env, monkeypatch):
    import httpx

    from services.cache import zones_catalog_cache

    zones_catalog_cache.clear()
    real_client = httpx.Client

    def factory(*args, **kwargs):
        kwargs.pop("transport", None)

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/zones"):
                return httpx.Response(
                    200,
                    json={
                        "XX-GRIDWISE-TEST": {
                            "zoneKey": "XX-GRIDWISE-TEST",
                            "zoneName": "API test grid",
                            "countryCode": "XX",
                            "subZoneKeys": [],
                        }
                    },
                )
            return httpx.Response(404)

        return real_client(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx, "Client", factory)
    r = client.get("/regions")
    assert r.status_code == 200
    codes = {row["code"] for row in r.json()["regions"]}
    assert "XX-GRIDWISE-TEST" in codes
    assert "US-CAL-CISO" in codes


def test_regions_endpoint_returns_curated_list(client):
    r = client.get("/regions")
    assert r.status_code == 200
    body = r.json()
    assert "regions" in body
    regions = body["regions"]
    assert len(regions) >= 10  # we ship a real catalog
    codes = {row["code"] for row in regions}
    # Spot-check a few that the FE story relies on.
    for code in ("US-CAL-CISO", "DE", "SE", "IN-NO", "IN", "US-MIDW-MISO"):
        assert code in codes, f"regions list should include {code}"

    sample = regions[0]
    for key in ("code", "label", "country", "variation_hint"):
        assert key in sample
    assert sample["variation_hint"] in {"strong", "moderate", "flat"}


def test_instance_types_endpoint(client):
    r = client.get("/instance-types")
    assert r.status_code == 200
    body = r.json()
    assert "instance_types" in body
    items = body["instance_types"]
    assert len(items) >= 5
    names = {row["name"] for row in items}
    assert "gpu.h100.x8" in names
    assert "preset.a100_pcie" in names
    assert "preset.h100_node8" in names
    sample = items[0]
    for key in ("name", "power_kw", "label", "category"):
        assert key in sample
    assert sample["category"] in {"cpu", "gpu", "training-cluster"}
    assert sample["power_kw"] > 0
