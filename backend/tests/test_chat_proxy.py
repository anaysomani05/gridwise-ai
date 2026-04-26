"""POST /chat forwards JSON to the configured agent service."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def chat_proxy_env():
    from config import settings

    saved = settings.agent_service_url
    settings.agent_service_url = "http://fake-agent:8001"
    try:
        yield
    finally:
        settings.agent_service_url = saved


def test_chat_proxy_forwards_and_returns_json(client, chat_proxy_env):
    import main

    class FakeResp:
        status_code = 200

        def json(self):
            return {
                "assistant_message": "proxied",
                "patch": {"mode": "carbon"},
                "suggest_optimize": True,
            }

    class FakeClient:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, json=None, **kwargs):
            assert url == "http://fake-agent:8001/chat"
            assert json["messages"] == [{"role": "user", "content": "hi"}]
            return FakeResp()

    with patch.object(main.httpx, "Client", return_value=FakeClient()):
        r = client.post(
            "/chat",
            json={
                "messages": [{"role": "user", "content": "hi"}],
                "last_run": None,
                "form_state": {"region": "DE"},
            },
        )
    assert r.status_code == 200
    data = r.json()
    assert data["assistant_message"] == "proxied"
    assert data["patch"]["mode"] == "carbon"
    assert data["suggest_optimize"] is True
