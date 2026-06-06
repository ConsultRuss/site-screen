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
ELEVATION_URL = (
    "https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/"
    "ImageServer/exportImage"
)
NLCD_WCS_URL = "https://www.mrlc.gov/geoserver/mrlc_download/wcs"
NLCD_COVERAGE = "mrlc_download:NLCD_2021_Land_Cover_L48"

# Web-Mercator m^2 floor (~38 true acres at this latitude after distortion) — a safe
# server-side pre-filter that never drops a true >=50 ac parcel; the exact >=50 ac
# cut is applied client-side in build.py after reprojecting to an equal-area CRS.
PARCEL_AREA_FLOOR_WM = 200_000
PAGE = 1000
TIMEOUT = 120


class StageNotImplemented(RuntimeError):
    """Kept for import-compatibility; the stage is implemented below."""


def _get(url: str, params: dict[str, Any], retries: int = 4) -> dict[str, Any]:
    """GET + JSON with retry on transient 5xx (some services, e.g. FEMA, flap)."""
    import requests

    delay = 1.0
    for attempt in range(retries):
        try:
            resp = requests.get(url, params=params, timeout=TIMEOUT)
            if resp.status_code >= 500:
                raise RuntimeError(f"HTTP {resp.status_code}")
            resp.raise_for_status()
            data = resp.json()
            err = data.get("error") if isinstance(data, dict) else None
            if err and int(err.get("code", 0)) >= 500:
                raise RuntimeError(f"ArcGIS {err}")
            return data
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(delay)
            delay *= 2
    raise RuntimeError("unreachable")


def _ring_area(ring: list) -> float:
    """Signed shoelace area; ArcGIS outer rings are clockwise (negative)."""
    s = 0.0
    for i in range(len(ring) - 1):
        s += ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1]
    return s / 2.0


def _rings_to_polygon(rings: list) -> dict[str, Any]:
    """Group ArcGIS polygon rings (outer clockwise, holes counter-clockwise) into
    a GeoJSON Polygon/MultiPolygon."""
    polys: list[list] = []
    cur: list | None = None
    for ring in rings:
        if _ring_area(ring) < 0:  # outer
            if cur:
                polys.append(cur)
            cur = [ring]
        else:  # hole (or orphan -> treat as its own polygon)
            if cur:
                cur.append(ring)
            else:
                cur = [ring]
    if cur:
        polys.append(cur)
    if len(polys) == 1:
        return {"type": "Polygon", "coordinates": polys[0]}
    return {"type": "MultiPolygon", "coordinates": polys}


def _esri_to_geojson(feat: dict[str, Any]) -> dict[str, Any]:
    """Convert one esriJSON feature to a GeoJSON Feature (point/line/polygon)."""
    g = feat.get("geometry") or {}
    if "x" in g:
        geom: dict[str, Any] | None = {"type": "Point", "coordinates": [g["x"], g["y"]]}
    elif "paths" in g:
        paths = g["paths"]
        geom = (
            {"type": "LineString", "coordinates": paths[0]}
            if len(paths) == 1
            else {"type": "MultiLineString", "coordinates": paths}
        )
    elif "rings" in g:
        geom = _rings_to_polygon(g["rings"])
    else:
        geom = None
    return {"type": "Feature", "properties": feat.get("attributes", {}), "geometry": geom}


def fetch_arcgis(
    url: str,
    where: str = "1=1",
    geometry: str | None = None,
    out_fields: str = "*",
    page: int = PAGE,
) -> list[dict[str, Any]]:
    """Paginated ArcGIS REST query -> list of GeoJSON features (EPSG:4326).

    Uses esriJSON (``f=json``), which every ArcGIS service supports (some older
    services 500 on ``f=geojson``), then converts to GeoJSON locally. ``page`` can
    be lowered for services that 500 on large geometry payloads (e.g. FEMA NFHL).
    """
    features: list[dict[str, Any]] = []
    offset = 0
    while True:
        params: dict[str, Any] = {
            "where": where,
            "outFields": out_fields,
            "outSR": 4326,
            "f": "json",
            "returnGeometry": "true",
            "resultOffset": offset,
            "resultRecordCount": page,
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
        features.extend(_esri_to_geojson(f) for f in batch)
        if not batch or (len(batch) < page and not data.get("exceededTransferLimit")):
            break
        offset += len(batch)
        time.sleep(0.2)
    return features


def _save(name: str, features: list[dict[str, Any]]) -> int:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    fc = {"type": "FeatureCollection", "features": features}
    (RAW_DIR / f"{name}.geojson").write_text(json.dumps(fc), encoding="utf-8")
    return len(features)


def _flood_cell(tb: str, page: int = 500, depth: int = 0, max_depth: int = 2) -> list:
    """Fetch one flood tile; if it fails (dense floodplain -> 500/timeout), split it
    into quadrants and recurse so dense areas get finer tiles."""
    try:
        return fetch_arcgis(FLOOD_URL, geometry=tb, out_fields="FLD_ZONE", page=page)
    except Exception:
        if depth >= max_depth:
            return []  # give up on this small cell
        xmin, ymin, xmax, ymax = (float(v) for v in tb.split(","))
        mx, my = (xmin + xmax) / 2.0, (ymin + ymax) / 2.0
        quads = [
            f"{xmin},{ymin},{mx},{my}", f"{mx},{ymin},{xmax},{my}",
            f"{xmin},{my},{mx},{ymax}", f"{mx},{my},{xmax},{ymax}",
        ]
        out: list = []
        for q in quads:
            out += _flood_cell(q, page, depth + 1, max_depth)
        return out


def fetch_flood_tiled(bbox: str, nx: int = 4, ny: int = 4, page: int = 500) -> int:
    """FEMA NFHL flaps on large-area geometry queries, so fetch in a tile grid with
    recursive sub-splitting on failure. Cross-tile overlaps are harmless — build
    unions the flood polygons before use."""
    xmin, ymin, xmax, ymax = (float(v) for v in bbox.split(","))
    dx, dy = (xmax - xmin) / nx, (ymax - ymin) / ny
    feats: list[dict[str, Any]] = []
    for i in range(nx):
        for j in range(ny):
            tb = f"{xmin + i*dx},{ymin + j*dy},{xmin + (i+1)*dx},{ymin + (j+1)*dy}"
            feats += _flood_cell(tb, page)
    return _save("flood", feats)


def fetch_nlcd_raster(bbox: str, out_name: str = "nlcd") -> int:
    """Download NLCD 2021 Land Cover for the study bbox from the MRLC WCS (~30 m).

    Categorical raster (class codes); GeoServer WCS uses nearest-neighbor so codes
    are preserved. Zonal majority per parcel happens in build.
    """
    import math

    import requests

    xmin, ymin, xmax, ymax = (float(v) for v in bbox.split(","))
    latc = (ymin + ymax) / 2.0
    w_m = (xmax - xmin) * 111320.0 * math.cos(math.radians(latc))
    h_m = (ymax - ymin) * 110540.0
    cap, res = 4096, 30.0
    pw = max(1, min(cap, int(w_m / res)))
    ph = max(1, min(cap, int(h_m / res)))
    params = {
        "service": "WCS", "version": "1.0.0", "request": "GetCoverage",
        "coverage": NLCD_COVERAGE, "crs": "EPSG:4326", "bbox": bbox,
        "format": "GeoTIFF", "width": pw, "height": ph,
    }
    resp = requests.get(NLCD_WCS_URL, params=params, timeout=TIMEOUT)
    resp.raise_for_status()
    if resp.content[:2] not in (b"II", b"MM"):  # GeoTIFF magic
        raise RuntimeError(f"NLCD WCS returned non-TIFF ({resp.content[:80]!r})")
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    (RAW_DIR / f"{out_name}.tif").write_bytes(resp.content)
    return len(resp.content)


def fetch_slope_raster(bbox: str, out_name: str = "slope") -> int:
    """Download a Slope-Degrees GeoTIFF for the study bbox from USGS 3DEP (~30 m)."""
    import math

    import requests

    xmin, ymin, xmax, ymax = (float(v) for v in bbox.split(","))
    latc = (ymin + ymax) / 2.0
    w_m = (xmax - xmin) * 111320.0 * math.cos(math.radians(latc))
    h_m = (ymax - ymin) * 110540.0
    cap, res = 4096, 30.0
    pw = max(1, min(cap, int(w_m / res)))
    ph = max(1, min(cap, int(h_m / res)))
    params = {
        "bbox": bbox, "bboxSR": 4326, "imageSR": 3857, "size": f"{pw},{ph}",
        "format": "tiff", "pixelType": "F32", "noData": -9999,
        "renderingRule": json.dumps({"rasterFunction": "Slope Degrees"}), "f": "json",
    }
    meta = _get(ELEVATION_URL, params)
    if "href" not in meta:
        raise RuntimeError(f"3DEP exportImage failed: {meta}")
    img = requests.get(meta["href"], timeout=TIMEOUT)
    img.raise_for_status()
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    (RAW_DIR / f"{out_name}.tif").write_bytes(img.content)
    return len(img.content)


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
    _try(status, "flood", lambda: fetch_flood_tiled(bbox_local))
    _try(status, "slope", lambda: fetch_slope_raster(bbox_local))
    _try(status, "nlcd", lambda: fetch_nlcd_raster(bbox_local))

    (RAW_DIR / "fetch_status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
    return status
