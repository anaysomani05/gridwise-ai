"""
Live Electricity Maps — carbon intensity for the optimizer.

Official API reference: https://app.electricitymaps.com/developer-hub/api
(Authorization, zones, and Carbon Intensity endpoints are under API Reference → Carbon Intensity.)

Auth header: `auth-token: <API token>`

Base path used here: `{base}/v3/...` (set `ELECTRICITY_MAPS_BASE_URL` if your account uses another host/version per the hub).

- GET /v3/carbon-intensity/past-range — `zone`, `start`, `end` (ISO UTC)
- GET /v3/carbon-intensity/forecast — `zone`, `temporalGranularity=hourly` (horizon from “now”)
- GET /v3/zones — zone catalog for the API token (`fetch_zones_catalog_rows`)

Responses use a `history`, `data`, or `forecast` array of objects with
`datetime` and `carbonIntensity` (gCO2e/kWh), or signal-specific numeric fields.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from config import settings
from services.cache import provider_cache, zones_catalog_cache


class ElectricityMapsError(Exception):
    """Could not load carbon intensity from the Electricity Maps API."""


def _base() -> str:
    return (settings.electricity_maps_base_url or "https://api.electricitymaps.com/v3").rstrip(
        "/"
    )


def _headers() -> dict[str, str]:
    t = settings.electricity_maps_api_token
    return {"auth-token": t} if t else {}


def _ts_iso_utc(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _em_error(r: httpx.Response) -> str:
    try:
        j: dict[str, Any] = r.json()
        return str(j.get("message", j.get("error", r.text)))
    except Exception:
        return r.text or f"HTTP {r.status_code}"


def _parse_series(body: object) -> list[dict[str, str | float]]:
    if not isinstance(body, dict):
        return []
    rows: list[dict[str, Any]] = []
    for key in ("forecast", "history", "data", "result"):
        chunk = body.get(key)
        if isinstance(chunk, list):
            rows = chunk
            break
    out: list[dict[str, str | float]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        ts = row.get("datetime") or row.get("time") or row.get("timestamp")
        val = (
            row.get("carbonIntensity")
            or row.get("carbon_intensity")
            or row.get("intensity")
        )
        if ts is None or val is None:
            continue
        s = str(ts).replace("Z", "+00:00")
        try:
            tdt = datetime.fromisoformat(s)
        except ValueError:
            continue
        tdt = tdt.astimezone(timezone.utc)
        out.append({"timestamp": _ts_iso_utc(tdt), "value": float(val)})
    return out


def _by_timestamp(points: list[dict[str, str | float]]) -> dict[str, float]:
    m: dict[str, float] = {}
    for p in points:
        m[str(p["timestamp"])] = float(p["value"])
    return m


def _filter_window(
    points: list[dict[str, str | float]], start: datetime, end: datetime
) -> list[dict[str, str | float]]:
    s0 = (start if start.tzinfo else start.replace(tzinfo=timezone.utc)).astimezone(
        timezone.utc
    )
    e0 = (end if end.tzinfo else end.replace(tzinfo=timezone.utc)).astimezone(
        timezone.utc
    )
    out: list[dict[str, str | float]] = []
    for p in points:
        s = str(p["timestamp"]).replace("Z", "+00:00")
        tdt = datetime.fromisoformat(s).astimezone(timezone.utc)
        if s0 <= tdt <= e0:
            out.append({"timestamp": str(p["timestamp"]), "value": float(p["value"])})
    return sorted(out, key=lambda x: str(x["timestamp"]))


def fetch_carbon_intensity_forecast(
    region: str,
    start: datetime,
    end: datetime,
) -> list[dict[str, str | float]] | None:
    """
    If `ELECTRICITY_MAPS_API_TOKEN` is missing → return `None` (scheduler may use demo).

    If the token is set → call the API. On success, return
    [{ "timestamp": ISO, "value": gCO2/kWh }, ...] inside [start, end].
    On failure (bad token, no data, network) → raise `ElectricityMapsError`.
    """
    if not settings.electricity_maps_api_token:
        return None

    cache_key = (region, _ts_iso_utc(start), _ts_iso_utc(end))
    cached = provider_cache.get(cache_key)
    if cached is not None:
        return cached

    url = _base()
    with httpx.Client(timeout=60.0, headers=_headers()) as c:
        combined: dict[str, float] = {}

        r = c.get(
            f"{url}/carbon-intensity/past-range",
            params={
                "zone": region,
                "start": _ts_iso_utc(start),
                "end": _ts_iso_utc(end),
            },
        )
        if r.status_code in (401, 403):
            raise ElectricityMapsError(
                f"Electricity Maps auth failed ({r.status_code}): {_em_error(r)}. "
                "Check ELECTRICITY_MAPS_API_TOKEN in .env."
            )
        if r.status_code == 200:
            combined.update(_by_timestamp(_parse_series(r.json())))
        # else: 400/404/empty is OK — we try forecast

        r2 = c.get(
            f"{url}/carbon-intensity/forecast",
            params={"zone": region, "temporalGranularity": "hourly"},
        )
        if r2.status_code in (401, 403):
            if not combined:
                raise ElectricityMapsError(
                    f"Electricity Maps auth failed ({r2.status_code}): {_em_error(r2)}"
                )
        elif r2.status_code == 200:
            for ts, v in _by_timestamp(_parse_series(r2.json())).items():
                if ts not in combined:
                    combined[ts] = v
        elif not combined:
            if r2.status_code != 200:
                msg = _em_error(r2)
            else:
                msg = f"past-range: {_em_error(r) if r.status_code != 200 else 'empty'}"
            raise ElectricityMapsError(
                f"Could not get carbon data for {region!r}: {msg}. "
                "Check the zone in the Electricity Maps zone list (e.g. CA-NU)."
            )

        points = [
            {"timestamp": t, "value": v} for t, v in sorted(combined.items())
        ]
        filtered = _filter_window(
            [dict(p) for p in points],
            start,
            end,
        )
        if not filtered:
            raise ElectricityMapsError(
                f"No data points in window {_ts_iso_utc(start)}–{_ts_iso_utc(end)}. "
                "The forecast may not cover far-future times — use a window starting near "
                "the present, or a zone your token can access."
            )
        provider_cache.set(cache_key, filtered)
        return filtered


ZONES_CATALOG_CACHE_KEY = "v1"


def _parse_zones_response(body: object) -> list[dict[str, str]]:
    """
    Normalize Electricity Maps /zones JSON into rows:
    { "code", "zoneName", "countryCode" }.
    """
    if not isinstance(body, dict):
        return []
    root = body.get("zones")
    if not isinstance(root, dict):
        root = body
    if not isinstance(root, dict):
        return []

    rows: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(code: str, zone_name: str, country_code: str) -> None:
        code = (code or "").strip()
        if not code or code in seen:
            return
        seen.add(code)
        rows.append(
            {
                "code": code,
                "zoneName": (zone_name or code).strip(),
                "countryCode": (country_code or "").strip(),
            }
        )

    for key, val in root.items():
        if not isinstance(val, dict):
            continue
        zk = str(val.get("zoneKey") or key).strip()
        zn = str(val.get("zoneName") or val.get("zone_name") or zk).strip()
        cc = str(val.get("countryCode") or val.get("country") or "").strip()
        add(zk, zn, cc)
        subs = val.get("subZoneKeys") or val.get("sub_zones") or []
        if isinstance(subs, list):
            for sub in subs:
                if isinstance(sub, str) and sub.strip():
                    s = sub.strip()
                    add(s, s, cc)

    rows.sort(key=lambda r: r["code"])
    return rows


def fetch_zones_catalog_rows() -> list[dict[str, str]] | None:
    """
    GET /v3/zones with auth-token.

    Returns zones your token can access (cached ~1h). ``None`` if no token is
    configured or the HTTP call fails (caller should fall back to the static
    UI catalog).

    On 401/403 or other HTTP errors, returns ``None`` so ``GET /regions`` can
    still serve the static catalog without failing the request.
    """
    if not settings.electricity_maps_api_token:
        return None

    hit = zones_catalog_cache.get(ZONES_CATALOG_CACHE_KEY)
    if hit is not None:
        return hit

    url = _base()
    try:
        with httpx.Client(timeout=45.0, headers=_headers()) as c:
            r = c.get(f"{url}/zones")
    except httpx.RequestError:
        return None

    if r.status_code in (401, 403, 404):
        return None
    if r.status_code != 200:
        return None
    try:
        body = r.json()
    except Exception:
        return None

    rows = _parse_zones_response(body)
    zones_catalog_cache.set(ZONES_CATALOG_CACHE_KEY, rows)
    return rows
