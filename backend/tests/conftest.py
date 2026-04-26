"""
Shared pytest fixtures for the GridWise backend.

Strategy: never reload modules. The provider holds a *reference* to the
`config.settings` singleton, so mutating attributes on that singleton in place
flips the runtime config (live vs demo) without creating new
`ElectricityMapsError` classes — which would otherwise break `except` matching
in the FastAPI handler.

Tests that exercise the live-API code path request the `live_token_env` fixture
and patch httpx with `httpx.MockTransport`.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make `backend/` importable when pytest is run from the repo root.
_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))


@pytest.fixture(autouse=True)
def _reset_caches_and_env():
    """
    Each test starts in deterministic demo mode with an empty cache.

    We mutate `settings.electricity_maps_api_token = None` on the singleton
    instead of touching env vars + reloading modules; that keeps the exception
    classes stable across tests.
    """
    from config import settings
    from services.cache import provider_cache

    saved_token = settings.electricity_maps_api_token
    settings.electricity_maps_api_token = None
    provider_cache.clear()
    try:
        yield
    finally:
        settings.electricity_maps_api_token = saved_token
        provider_cache.clear()


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    import main

    return TestClient(main.app)


@pytest.fixture
def live_token_env():
    """Flip the live-API code path on for the duration of one test."""
    from config import settings
    from services.cache import provider_cache

    settings.electricity_maps_api_token = "test-token-not-real"
    provider_cache.clear()
    try:
        yield
    finally:
        settings.electricity_maps_api_token = None
        provider_cache.clear()
