"""Stage 1 - fetch: pull study-area layers from public ArcGIS REST services.

Each layer is queried server-side (by county FIPS or by a study-area bounding box)
so only the data we need crosses the wire — no multi-GB national downloads. Results
are cached as GeoJSON (EPSG:4326) under data/raw/ (git-ignored). Every layer is
wrapped so one flaky endpoint degrades gracefully instead of failing the run; the
per-layer status is recorded and surfaced in data/screen_run.json.

Endpoints are documented in data/SOURCES.md.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

from .config import REPO_ROOT

RAW_DIR = REPO_ROOT / "data" / "raw"

FIPS = {"Wilson": "48493", "Karnes": "48255"}

# --- public ArcGIS REST endpoints (see data/SOURCES.md) ---
PARCELS_URL = (
    "https://feature.geographic.texas.gov/arcgis/rest/services/Parcels/"
    "stratmap_land_parcels_48_most_recent/MapServer/0/query"
)
SUBSTATIONS_URL = (
    "https://services5.arcgis.com/HDRa0B57OVrv2E1q/ArcGIS/rest/services/"
    "Electric_Substations/FeatureServer/0/query"
)
TRANSMISSION_URL = (
    "https://arcgis.netl.doe.gov/server/rest/services/Hosted/"
    "Energy_Transition_Atlas_493d6/FeatureServer/18/query"
)
FLOOD_URL = "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query"

# Web-Mercator m^2 floor (~38 true acres at this latitude after distortion) — a safe
# server-side pre-filter that never drops a true >=50 ac parcel; the exact >=50 ac
# cut is applied client-side in build.py after reprojecting to an equal-area CRS.
PARCEL_AREA_FLOOR_WM = 200_000
PAGE = 1000
TIMEOUT = 120


class StageNotImplemented(RuntimeError):
    """Kept for import-compatibility; the stage is implemented below."""


def _get(url: str, params: dict[str, Any]) -> dict[str, Any]:
    import requests

    resp = requests.get(url, params=params, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def fetch_arcgis(
    url: str, where: str = "1=1", geometry: str | None = None, out_fields: str = "*"
) -> list[dict[str, Any]]:
    """Paginated ArcGIS REST query returning GeoJSON features (EPSG:4326)."""
    features: list[dict[str, Any]] = []
    offset = 0
    while True:
        params: dict[str, Any] = {
            "where": where,
            "outFields": out_fields,
            "outSR": 4326,
            "f": "geojson",
            "returnGeometry": "true",
            "resultOffset": offset,
            "resultRecordCount": PAGE,
        }
        if geometry:
            params.update(
                {
                    "geometry": geometry,
                    "geometryType": "esriGeometryEnvelope",
                    "inSR": 4326,
                    "spatialRel": "esriSpatialRelIntersects",
                }
            )
        data = _get(url, params)
        if "error" in data:
            raise RuntimeError(f"ArcGIS error: {data['error']}")
        batch = data.get("features", [])
        features.extend(batch)
        if len(batch) < PAGE:
            break
        offset += PAGE
        time.sleep(0.2)
    return features


def _save(name: str, features: list[dict[str, Any]]) -> int:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    fc = {"type": "FeatureCollection", "features": features}
    (RAW_DIR / f"{name}.geojson").write_text(json.dumps(fc), encoding="utf-8")
    return len(features)


def _iter_xy(geom: dict[str, Any]):
    t, c = geom.get("type"), geom.get("coordinates")
    if not c:
        return
    if t == "Point":
        yield c[0], c[1]
    elif t in ("LineString", "MultiPoint"):
        yield from ((p[0], p[1]) for p in c)
    elif t in ("Polygon", "MultiLineString"):
        for part in c:
            yield from ((p[0], p[1]) for p in part)
    elif t == "MultiPolygon":
        for poly in c:
            for ring in poly:
                yield from ((p[0], p[1]) for p in ring)


def _bbox(features: list[dict[str, Any]], pad: float = 0.0) -> str:
    xs: list[float] = []
    ys: list[float] = []
    for f in features:
        for x, y in _iter_xy(f.get("geometry") or {}):
            xs.append(x)
            ys.append(y)
    return f"{min(xs) - pad},{min(ys) - pad},{max(xs) + pad},{max(ys) + pad}"


def _try(status: dict[str, Any], name: str, fn: Callable[[], int]) -> None:
    try:
        n = fn()
        status[name] = {"ok": True, "count": n}
        print(f"  [{name}] {n} features")
    except Exception as exc:  # one bad endpoint must not sink the run
        status[name] = {"ok": False, "error": str(exc)}
        print(f"  [{name}] FAILED: {exc}")


def run(cfg: dict[str, Any]) -> dict[str, Any]:
    """Fetch every layer; return a per-layer status dict."""
    status: dict[str, Any] = {}
    counties = cfg["study_area"]["counties"]
    fips_in = ",".join(f"'{FIPS[c]}'" for c in counties)

    # 1. Parcels (essential) — server-side area pre-filter, per county.
    where = f"fips IN ({fips_in}) AND st_area(shape) >= {PARCEL_AREA_FLOOR_WM}"
    print("Fetching parcels...")
    parcels = fetch_arcgis(
        PARCELS_URL,
        where=where,
        out_fields="prop_id,geo_id,owner_name,gis_area,legal_area,county,fips,stat_land_use,loc_land_use",
    )
    if not parcels:
        raise RuntimeError("no parcels returned — cannot continue")
    n = _save("parcels", parcels)
    status["parcels"] = {"ok": True, "count": n}
    print(f"  [parcels] {n} features")

    bbox_infra = _bbox(parcels, pad=0.30)  # ~20 mi: catch substations/lines off-parcel
    bbox_local = _bbox(parcels, pad=0.05)

    # 2-4. Infrastructure + hazard (graceful).
    _try(status, "substations", lambda: _save(
        "substations",
        fetch_arcgis(
            SUBSTATIONS_URL, geometry=bbox_infra,
            out_fields="NAME,STATE,COUNTY,MAX_VOLT,MIN_VOLT",
        ),
    ))
    _try(status, "transmission", lambda: _save(
        "transmission",
        fetch_arcgis(TRANSMISSION_URL, geometry=bbox_infra, out_fields="voltage,volt_class,owner"),
    ))
    _try(status, "flood", lambda: _save(
        "flood",
        fetch_arcgis(FLOOD_URL, geometry=bbox_local, out_fields="FLD_ZONE,ZONE_SUBTY"),
    ))

    (RAW_DIR / "fetch_status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
    return status
