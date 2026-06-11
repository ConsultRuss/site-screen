"""Parcel de-duplication by footprint (pure-Python, no geo dependencies).

The TxGIO StratMap statewide parcel layer stacks multiple records on the same
physical parcel — same footprint, different prop_id / owner / boundary
digitization. Counted as-is they pollute the suitability ranking with identical
entries (the same top parcel appearing several times). We collapse records that
share a footprint (identical centroid + total area) to a single representative,
keying on the physical footprint rather than the parcel id: many genuinely
distinct parcels carry a placeholder prop_id of "0", so an id-based key would
either miss the duplicates or wrongly merge real parcels.
"""

from __future__ import annotations

from typing import Any


def _footprint_key(feature: dict[str, Any]) -> tuple[Any, Any, Any]:
    p = feature["properties"]
    return (p.get("centroid_lat"), p.get("centroid_lon"), p.get("acreage_total"))


def dedupe_by_footprint(features: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse same-footprint duplicate parcels, preserving input order.

    Two features occupy the same footprint when their centroid and total area are
    identical (``build`` rounds centroid to ~1 m and area to 0.1 ac). The first
    occurrence is kept; later duplicates are dropped.
    """
    seen: set[tuple[Any, Any, Any]] = set()
    out: list[dict[str, Any]] = []
    for f in features:
        key = _footprint_key(f)
        if key in seen:
            continue
        seen.add(key)
        out.append(f)
    return out
