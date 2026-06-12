"""Data-integrity / audit engine (Feature A4) — pure-Python.

Computes the audit panel's content from the run artifacts (fetch_status.json,
screen_run.json, the parcels GeoJSON) joined with config.data_integrity. The
license-restricted ERCOT GIS Report is surfaced as a GOVERNANCE signal, never
displayed raw. Mirrors portfolio.py: read artifacts -> build -> write.
"""

from __future__ import annotations

from typing import Any


def layer_freshness(
    fetch_status: dict[str, Any], run_meta: dict[str, Any], cfg: dict[str, Any]
) -> list[dict[str, Any]]:
    """Public layers (config map x fetch counts x run time) + the restricted ERCOT row."""
    di = cfg["data_integrity"]
    retrieved = (run_meta or {}).get("run_utc")
    rows: list[dict[str, Any]] = []
    for layer, meta in di["layers"].items():
        fs = (fetch_status or {}).get(layer) or {}
        rows.append({
            "layer": layer, "source": meta["source"], "license": meta["license"],
            "role": meta["role"], "status": "live" if fs.get("ok") else "pending",
            "count": fs.get("count"), "retrieved": retrieved,
        })
    for _, meta in di["restricted"].items():
        rows.append({
            "layer": meta["source"], "source": meta["source"], "license": meta["license"],
            "role": meta["role"], "status": "backend-abstracted", "count": None,
            "retrieved": retrieved,
        })
    return rows


def run_summary(run_meta: dict[str, Any]) -> dict[str, Any]:
    rm = run_meta or {}
    return {
        "run_utc": rm.get("run_utc"),
        "parcel_count": rm.get("parcel_count"),
        "shortlist_count": rm.get("shortlist_count"),
        "criteria_status": rm.get("criteria_status") or {},
        "lenses": rm.get("lenses") or {},
        "verdict_layer": rm.get("verdict_layer"),
    }


def provenance(fetch_status: dict[str, Any], run_meta: dict[str, Any]) -> dict[str, Any]:
    fetched = ((fetch_status or {}).get("parcels") or {}).get("count")
    final = (run_meta or {}).get("parcel_count")
    return {
        "fetched": fetched,
        "final": final,
        "shortlist": (run_meta or {}).get("shortlist_count"),
        "note": "Parcel records fetched -> distinct parcels after the ≥50-acre floor + "
                "footprint de-duplication. Geometry/infrastructure real + sourced; "
                "ownership + deal pipeline synthetic.",
    }
