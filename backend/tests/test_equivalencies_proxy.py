"""POST /equivalencies forwards JSON to the configured agent service."""

from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.fixture
def equiv_proxy_env():
    from config import settings

    saved = settings.agent_service_url
    settings.agent_service_url = "http://fake-agent:8001"
    try:
        yield
    finally:
        settings.agent_service_url = saved


def test_equivalencies_proxy_forwards_and_returns_json(client, equiv_proxy_env):
    import main

    class FakeResp:
        status_code = 200

        def json(self):
            return {
                "equivalencies": [
                    "About enough avoided CO₂ to charge ~100 phones (illustrative).",
                    "Roughly skipping a 3-mile drive (ballpark).",
                    "Similar ballpark to a laptop at low draw for a few days — not exact science.",
                ],
            }

    class FakeClient:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, json=None, **kwargs):
            assert url == "http://fake-agent:8001/equivalencies"
            assert json["metrics"]["co2_saved_kg"] == 1.5
            return FakeResp()

    with patch.object(main.httpx, "Client", return_value=FakeClient()):
        r = client.post(
            "/equivalencies",
            json={"metrics": {"co2_saved_kg": 1.5}},
        )
    assert r.status_code == 200
    data = r.json()
    assert len(data["equivalencies"]) == 3
