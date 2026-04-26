"""
Region catalog for the UI (Electricity Maps zone codes).

- **Curated** rows in `_REGIONS` keep hand-written labels, cloud hints, and
  `variation_hint` for zones we care about most in demos.
- When `ELECTRICITY_MAPS_API_TOKEN` is set, `GET /regions` **also merges** zones
  from Electricity Maps `GET /v3/zones` (cached ~1h) so your API plan can expose
  every zone your token can access, not only the static list.

Add or edit rows in `_REGIONS` for nicer copy; the EM merge only appends zones
that are not already present by `code`.
"""
from __future__ import annotations

from dataclasses import dataclass

from providers.electricity_maps import fetch_zones_catalog_rows


@dataclass(frozen=True)
class Region:
    code: str
    label: str
    country: str
    variation_hint: str  # "strong" | "moderate" | "flat"


_COUNTRY_LABEL: dict[str, str] = {
    "US": "United States",
    "DE": "Germany",
    "FR": "France",
    "GB": "United Kingdom",
    "ES": "Spain",
    "SE": "Sweden",
    "NO": "Norway",
    "FI": "Finland",
    "PL": "Poland",
    "IN": "India",
    "AU": "Australia",
    "JP": "Japan",
    "CA": "Canada",
    "BR": "Brazil",
    "NL": "Netherlands",
    "IT": "Italy",
    "AT": "Austria",
    "CH": "Switzerland",
    "DK": "Denmark",
    "IE": "Ireland",
    "PT": "Portugal",
    "NZ": "New Zealand",
    "KR": "South Korea",
    "SG": "Singapore",
    "MX": "Mexico",
}


def _country_label(iso2: str) -> str:
    cc = (iso2 or "").strip().upper()
    return _COUNTRY_LABEL.get(cc, cc or "Other")


_REGIONS: list[Region] = [
    Region(
        "US-CAL-CISO",
        "California (CAISO) — Azure westus / US West (US-CAL-CISO)",
        "United States",
        "strong",
    ),
    Region("US-TEX-ERCO", "Texas (ERCOT)",             "United States", "strong"),
    Region(
        "US-NW-PACW",
        "Pacific Northwest — AWS us-west-2 Oregon (US-NW-PACW)",
        "United States",
        "moderate",
    ),
    Region(
        "US-MIDA-PJM",
        "PJM — AWS us-east-1 / Azure eastus Virginia (US-MIDA-PJM)",
        "United States",
        "moderate",
    ),
    Region(
        "US-MIDW-MISO",
        "Central US (MISO) — GCP us-central1 Iowa (US-MIDW-MISO)",
        "United States",
        "moderate",
    ),
    Region("US-NE-ISNE",  "New England (ISO-NE)",      "United States", "moderate"),
    Region("US-NY-NYIS",  "New York (NYISO)",          "United States", "moderate"),
    Region("DE",          "Germany",                   "Germany",       "strong"),
    Region("FR",          "France",                    "France",        "flat"),
    Region("GB",          "Great Britain",             "United Kingdom","moderate"),
    Region("ES",          "Spain",                     "Spain",         "strong"),
    Region("SE",          "Sweden",                    "Sweden",        "flat"),
    Region("NO",          "Norway",                    "Norway",        "flat"),
    Region("FI",          "Finland",                   "Finland",       "moderate"),
    Region("PL",          "Poland",                    "Poland",        "moderate"),
    Region(
        "IN",
        "India (country) — AWS ap-south-1 Mumbai (IN)",
        "India",
        "moderate",
    ),
    Region("IN-NO",       "India — Northern grid (IN-NO)",     "India",         "moderate"),
    Region("IN-SO",       "India — Southern grid (IN-SO)",     "India",         "strong"),
    Region(
        "AU-NSW",
        "Australia NSW — AWS ap-southeast-2 Sydney (AU-NSW)",
        "Australia",
        "strong",
    ),
    Region("AU-VIC",      "Australia (Victoria)",      "Australia",     "strong"),
    Region("JP-TK",       "Japan (Tokyo)",             "Japan",         "moderate"),
    Region("CA-ON",       "Canada (Ontario)",          "Canada",        "moderate"),
    Region("CA-QC",       "Canada (Québec)",           "Canada",        "flat"),
    Region("CA-NU",       "Canada (Nunavut)",          "Canada",        "flat"),
    Region("BR-CS",       "Brazil (Central-South)",    "Brazil",        "moderate"),
]

_BY_CODE: dict[str, Region] = {r.code: r for r in _REGIONS}


def _regions_from_em_catalog() -> list[Region]:
    rows = fetch_zones_catalog_rows()
    if not rows:
        return []
    seen = {r.code for r in _REGIONS}
    extra: list[Region] = []
    for row in rows:
        code = row.get("code") or ""
        if not code or code in seen:
            continue
        seen.add(code)
        zn = row.get("zoneName") or code
        cc = row.get("countryCode") or ""
        label = f"{zn} ({code})"
        extra.append(
            Region(
                code=code,
                label=label,
                country=_country_label(cc),
                variation_hint="moderate",
            )
        )
    extra.sort(key=lambda r: r.code)
    return extra


def list_regions() -> list[Region]:
    """Curated regions first, then any extra zones from Electricity Maps /zones."""
    return list(_REGIONS) + _regions_from_em_catalog()


def get_region(code: str) -> Region | None:
    """Curated row wins; else a synthetic row if the code appears in the EM catalog."""
    if code in _BY_CODE:
        return _BY_CODE[code]
    for row in fetch_zones_catalog_rows() or []:
        if row.get("code") == code:
            zn = row.get("zoneName") or code
            cc = row.get("countryCode") or ""
            return Region(
                code=code,
                label=f"{zn} ({code})",
                country=_country_label(cc),
                variation_hint="moderate",
            )
    return None
