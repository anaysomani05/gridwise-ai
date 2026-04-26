"""
Tiny TTL cache: hits/misses and expiration.
"""
from __future__ import annotations

import time

from services.cache import TTLCache


def test_cache_hit_and_miss():
    c = TTLCache[str, int](ttl_seconds=60.0, max_size=8)
    assert c.get("a") is None
    c.set("a", 1)
    assert c.get("a") == 1
    assert c.get("b") is None
    stats = c.stats()
    assert stats["hits"] == 1
    assert stats["misses"] == 2


def test_cache_expires():
    c = TTLCache[str, int](ttl_seconds=0.05, max_size=8)
    c.set("a", 1)
    assert c.get("a") == 1
    time.sleep(0.1)
    assert c.get("a") is None  # expired


def test_cache_eviction_when_full():
    c = TTLCache[str, int](ttl_seconds=60.0, max_size=2)
    c.set("a", 1)
    time.sleep(0.001)
    c.set("b", 2)
    time.sleep(0.001)
    c.set("c", 3)  # forces eviction of the entry with the soonest expiry ("a")
    assert c.get("c") == 3
    # one of a or b is gone; size is bounded.
    assert c.stats()["size"] <= 2


def test_cache_clear_resets_stats():
    c = TTLCache[str, int](ttl_seconds=60.0)
    c.set("a", 1)
    c.get("a")
    c.get("missing")
    c.clear()
    s = c.stats()
    assert s["size"] == 0 and s["hits"] == 0 and s["misses"] == 0
