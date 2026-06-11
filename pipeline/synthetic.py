"""Synthetic, disclosed data (spec section 10).

Real CAD owner names are public record, but a public portfolio piece must not look
like it targets real landowners — so owner names are replaced with generated ones,
and the entire deal-control pipeline (status, dates, prices, title flags, notes) is
invented. Assignment is deterministic (hashed by parcel id) so re-runs are stable.
The About view and README disclose this.
"""

from __future__ import annotations

import math
from typing import Any

# Generic, non-identifying owners (LLCs, trusts, initial+surname).
_OWNERS = [
    "Cibolo Creek Ranch LLC", "M. Delgado Family Trust", "Rolling Oaks Land Co.",
    "T. Whitfield", "Esperanza Holdings LLC", "Brushy Hollow Partners",
    "R. Nakamura", "Lone Mesquite LLC", "D. Okafor", "Sandia Vista Ranch LP",
    "K. Boudreaux", "Twin Windmills LLC", "A. Ramirez", "Persimmon Flats Trust",
    "Greenbrier Land Group", "S. Petrov", "Calaveras Bend LLC", "J. Okonkwo",
    "Cottonwood Draw Partners", "L. Yates", "Rio Seco Holdings LLC", "M. Fitzgerald",
    "Bluestem Prairie LP", "Hidalgo Ranch Trust", "P. Andersson", "Salt Branch LLC",
    "W. Castillo", "Mesquite Crossing Land Co.", "E. Novak", "Pecan Bottom LLC",
    "Tres Robles Partners", "C. Mbeki", "Rattlesnake Ridge LP", "B. Sorensen",
    "Agua Dulce Holdings", "N. Vance", "Coyote Mesa LLC", "G. Halvorsen",
    "Sycamore Hollow Trust", "F. Delacroix",
]

# Funnel: more parcels early, fewer near closing (status, title_flag).
_FUNNEL = (
    [("Identified", "clear")] * 5
    + [("Screened", "clear")] * 4
    + [("Outreach", "clear")] * 3
    + [("LOI", "clear")] * 3
    + [("Option/Lease Negotiation", "clear")] * 3
    + [("Under Option", "survey_pending")] * 2
    + [("Site Control Secured", "clear")] * 2
    + [("Title/Survey Clearing", "title_issue")] * 1
    + [("Cleared", "clear")] * 1
)

_NOTES = {
    "Identified": "Flagged by the screen; not yet contacted.",
    "Screened": "Passed constraints review; owner research underway.",
    "Outreach": "Initial owner outreach sent.",
    "LOI": "Letter of intent issued.",
    "Option/Lease Negotiation": "Negotiating option/lease terms.",
    "Under Option": "Option executed; boundary survey ordered.",
    "Site Control Secured": "Option executed; due diligence underway.",
    "Title/Survey Clearing": "Severed minerals; surface-use agreement needed.",
    "Cleared": "Title clear; ready for development.",
}


def _stable_idx(key: str, n: int) -> int:
    h = 2166136261
    for ch in key:
        h = (h ^ ord(ch)) * 16777619 & 0xFFFFFFFF
    return h % n


# --- Synthetic land prices, calibrated to recent local vacant-land sales ---
# A ConnectMLS pull of SOLD/PENDING tracts > 50 ac in Karnes & Wilson over the
# last 24 months, with houses excluded (improved tracts ran ~28% higher per acre),
# anchors the magnitude: Karnes vacant land ~$7,270/ac at ~75 ac, with per-acre
# price falling as tract size grows (the large-tract size discount; South Texas
# regional sold average ~$5,900/ac). Wilson runs above Karnes (San Antonio growth
# corridor). Prices stay SYNTHETIC and are disclosed as such — calibrated, invented.
_PPA_REF_AC = 75.0              # reference tract size for the anchor
_PPA_REF = 7270.0              # Karnes vacant median $/ac at the reference size
_PPA_DECLINE = 1310.0          # $/ac drop per natural-log step in tract size
_PPA_FLOOR = 2600.0            # large-tract / brush-country floor
_PPA_COUNTY = {"Wilson": 1.30}  # county premium vs Karnes (default 1.0)


def _price_per_ac(parcel_id: str, county: str, total_acres: float) -> int:
    """Calibrated synthetic asking price per acre, rounded to $50.

    Larger tracts price lower per acre (size discount); a per-parcel ±20%
    variation gives the realistic spread that makes the price-rich flag meaningful.
    """
    acres = max(float(total_acres or _PPA_REF_AC), _PPA_REF_AC)
    base = _PPA_REF - _PPA_DECLINE * math.log(acres / _PPA_REF_AC)
    base *= _PPA_COUNTY.get(county, 1.0)
    variation = 1.0 + (_stable_idx(parcel_id + "p", 41) - 20) / 100.0  # +/-20%
    return int(round(max(base * variation, _PPA_FLOOR) / 50.0) * 50)


def assign_synthetic(fc: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    feats = fc["features"]

    # Stable per-county parcel ids (ordered by suitability rank for legibility).
    feats.sort(key=lambda f: f["properties"].get("suitability_rank") or 10**9)
    counters: dict[str, int] = {}
    for f in feats:
        p = f["properties"]
        pre = str(p.get("county", "XXX"))[:3].upper()
        counters[pre] = counters.get(pre, 0) + 1
        p["parcel_id"] = f"{pre}-{counters[pre]:06d}"
        p["owner"] = _OWNERS[_stable_idx(p["parcel_id"], len(_OWNERS))]
        p.setdefault("pipeline_status", None)
        for k in ("status_date", "title_flag", "est_price_per_ac", "notes"):
            p.setdefault(k, None)

    # Shortlist: a spread of strong candidates across the funnel.
    shortlist = feats[: len(_FUNNEL)]
    for offset, (f, (status, title)) in enumerate(zip(shortlist, _FUNNEL, strict=False)):
        p = f["properties"]
        price = _price_per_ac(p["parcel_id"], p.get("county", ""), p.get("acreage_total", 0.0))
        day = 1 + _stable_idx(p["parcel_id"] + "d", 27)
        month = 4 + (offset % 3)  # Apr-Jun 2026
        p["pipeline_status"] = status
        p["title_flag"] = title
        p["est_price_per_ac"] = price
        p["status_date"] = f"2026-{month:02d}-{day:02d}"
        p["notes"] = _NOTES[status]
    return fc
