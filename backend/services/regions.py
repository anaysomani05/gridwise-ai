"""
Curated catalog of regions (Electricity Maps zone codes) we expose to the UI.

Each entry carries:
- `code`: the Electricity Maps zone string (what we send to the API).
- `label`: a human-friendly name for the dropdown.
- `country`: ISO-ish country/region grouping.
- `variation_hint`: short tag the UI can use to set expectations
  ("strong daily swing" vs "mostly flat").

Only this file decides which zones the frontend offers — there is no magic
"any zone" mode. Add a row here to support a new region.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Region:
    code: str
    label: str
    country: str
    variation_hint: str  # "strong" | "moderate" | "flat"


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


def list_regions() -> list[Region]:
    """All curated regions, in display order."""
    return list(_REGIONS)


def get_region(code: str) -> Region | None:
    """Look up a curated region by Electricity Maps zone code."""
    return _BY_CODE.get(code)
