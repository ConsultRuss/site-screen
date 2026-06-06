"""Stage 4 - export: write the scored GeoJSON + a run-metadata record.

``write_geojson`` serializes a FeatureCollection. ``write_run_metadata`` records
the weights used and source dates, so any published dataset is reproducible
(this is the "data integrity / auditability" story).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import __version__


def write_geojson(feature_collection: dict[str, Any], out_path: str | Path) -> None:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(feature_collection, fh, ensure_ascii=False)


def write_run_metadata(cfg: dict[str, Any], out_path: str | Path) -> dict[str, Any]:
    """Write data/screen_run.json: weights + study area + timestamp."""
    meta = {
        "pipeline_version": __version__,
        "run_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "study_area": cfg.get("study_area"),
        "crs": cfg.get("crs"),
        "model_weights": cfg["model"]["weights"],
        "note": "Geospatial layers are public + sourced (data/SOURCES.md). "
        "Ownership names and the deal pipeline are synthetic.",
    }
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)
    return meta
