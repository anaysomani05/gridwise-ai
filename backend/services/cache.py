"""
Tiny in-process TTL cache.

Used to avoid re-hitting Electricity Maps for the same (zone, hour-floor start,
hour-floor end) tuple inside a short window — useful during demos so a flurry
of /optimize and /compare-regions calls doesn't burn the rate limit.

This is deliberately not Redis. It is per-process, lives in module state, and
disappears when the server restarts. That's fine for the MVP.
"""
from __future__ import annotations

import threading
import time
from typing import Generic, Hashable, TypeVar

K = TypeVar("K", bound=Hashable)
V = TypeVar("V")


class TTLCache(Generic[K, V]):
    def __init__(self, ttl_seconds: float = 300.0, max_size: int = 256) -> None:
        self._ttl = float(ttl_seconds)
        self._max = int(max_size)
        self._store: dict[K, tuple[float, V]] = {}
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def _now(self) -> float:
        return time.monotonic()

    def get(self, key: K) -> V | None:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self.misses += 1
                return None
            expires_at, value = entry
            if expires_at < self._now():
                # expired
                self._store.pop(key, None)
                self.misses += 1
                return None
            self.hits += 1
            return value

    def set(self, key: K, value: V) -> None:
        with self._lock:
            if len(self._store) >= self._max:
                # cheap eviction: drop the oldest-expiring item
                oldest = min(self._store.items(), key=lambda kv: kv[1][0])[0]
                self._store.pop(oldest, None)
            self._store[key] = (self._now() + self._ttl, value)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()
            self.hits = 0
            self.misses = 0

    def stats(self) -> dict[str, int | float]:
        with self._lock:
            return {
                "size": len(self._store),
                "hits": self.hits,
                "misses": self.misses,
                "ttl_seconds": self._ttl,
                "max_size": self._max,
            }


# Singleton used by the live provider. Tests that need a clean slate can
# import this and call `.clear()` in a fixture.
provider_cache: TTLCache[tuple[str, str, str], list[dict[str, str | float]]] = TTLCache(
    ttl_seconds=300.0,
    max_size=128,
)
