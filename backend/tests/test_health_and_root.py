def test_root_lists_endpoints(client):
    r = client.get("/")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "GridWise API"
    for key in ("optimize", "chat", "equivalencies", "regions", "instance_types", "compare_regions", "health"):
        assert key in body, f"root index should advertise {key}"


def test_health_ok_with_cache_stats(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "version" in body
    assert "cache" in body
    cache = body["cache"]
    for k in ("size", "hits", "misses", "ttl_seconds", "max_size"):
        assert k in cache
