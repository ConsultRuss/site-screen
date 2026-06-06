"""Stage 2 - build: clip / reproject / compute per-parcel metrics.

Reads the cached layers from fetch, reprojects to the equal-area analysis CRS,
applies the exact >=50 ac filter, and computes the metrics the scorer needs:

  * interconnection  - distance (mi) to nearest >=138 kV substation and line  [LIVE]
  * buildable acres  - parcel area minus floodplain minus boundary setback     [LIVE]
  * hazard-free %    - share of the parcel outside the floodplain             [LIVE if flood]
  * compactness      - Polsby-Popper from geometry                            [LIVE]
  * terrain / land cover / soils / road access                                [PENDING -> None]

Criteria with no fetched layer this pass are left as ``None``; the scorer treats
None as a neutral 50 so the weighted total stays well-defined, and which criteria
are live vs pending is recorded in data/screen_run.json. Heavy deps are imported
lazily so the rest of the CLI loads without the geo stack.
"""

from __future__ import annotations

import json
import math
from typing import Any

from .fetch import RAW_DIR

ANALYSIS_CRS = "EPSG:3083"
M2_PER_ACRE = 4046.8564224
MILES_PER_M = 1.0 / 1609.344

# NLCD class code -> config landcover key (see config.yaml normalization.landcover)
NLCD_TO_KEY = {
    11: "water", 21: "developed_open", 22: "developed", 23: "developed", 24: "developed",
    31: "default", 41: "forest", 42: "forest", 43: "forest", 52: "shrubland",
    71: "grassland_pasture", 81: "pasture_hay", 82: "cultivated_crops",
    90: "wetlands", 95: "wetlands",
}


def _round_coords(obj: Any, nd: int = 5) -> Any:
    """Round GeoJSON coordinates to ~1 m precision to keep the web payload small."""
    if isinstance(obj, (list, tuple)):
        if obj and isinstance(obj[0], (int, float)):
            return [round(float(obj[0]), nd), round(float(obj[1]), nd)]
        return [_round_coords(x, nd) for x in obj]
    return obj


def _to_kv(series):
    """Coerce a voltage column to numeric kV; HIFLD uses -999999 for unknown."""
    import pandas as pd

    v = pd.to_numeric(series, errors="coerce")
    return v.where((v >= 1) & (v < 1000))  # drop sentinels / nonsense


def _load(name: str):
    import geopandas as gpd

    path = RAW_DIR / f"{name}.geojson"
    if not path.exists():
        return None
    gdf = gpd.read_file(path)
    if gdf.empty:
        return None
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")
    return gdf.to_crs(ANALYSIS_CRS)


def run(cfg: dict[str, Any]) -> dict[str, Any]:
    import geopandas as gpd

    floor_ac = cfg["study_area"]["parcel_min_acres"]
    setback_m = cfg["exclusions"]["setbacks_ft"]["parcel_boundary"] * 0.3048

    parcels = _load("parcels")
    if parcels is None:
        raise RuntimeError("no parcels cached — run fetch first")

    parcels["area_ac"] = parcels.geometry.area / M2_PER_ACRE
    parcels = parcels[parcels["area_ac"] >= floor_ac].copy().reset_index(drop=True)
    print(f"  parcels >= {floor_ac} ac: {len(parcels)}")

    status: dict[str, str] = {
        "interconnection": "pending",
        "buildable_acreage": "live",
        "hazard_free": "pending",
        "shape": "live",
        "terrain": "pending",
        "landcover_soils": "pending",
        "road_access": "pending",
    }

    # --- interconnection: nearest >=138 kV substation + line ---
    subs = _load("substations")
    dist_sub_mi = None
    near_kv = None
    if subs is not None and "MAX_VOLT" in subs:
        subs = subs.assign(kv=_to_kv(subs["MAX_VOLT"]))
        subs138 = subs[subs["kv"] >= 138][["kv", "geometry"]].reset_index(drop=True)
        if len(subs138):
            joined = gpd.sjoin_nearest(parcels[["geometry"]], subs138, distance_col="_d")
            joined = joined[~joined.index.duplicated(keep="first")]
            dist_sub_mi = (joined["_d"] * MILES_PER_M).reindex(parcels.index)
            near_kv = joined["kv"].reindex(parcels.index)
            status["interconnection"] = "live"

    lines = _load("transmission")
    dist_line_mi = None
    if lines is not None and "voltage" in lines:
        lines = lines.assign(kv=_to_kv(lines["voltage"]))
        lines138 = lines[lines["kv"] >= 138][["geometry"]].reset_index(drop=True)
        if len(lines138):
            jl = gpd.sjoin_nearest(parcels[["geometry"]], lines138, distance_col="_d")
            jl = jl[~jl.index.duplicated(keep="first")]
            dist_line_mi = (jl["_d"] * MILES_PER_M).reindex(parcels.index)

    # --- floodplain overlay -> hazard %, and buildable acreage ---
    flood = _load("flood")
    flood_union = None
    if flood is not None and len(flood) and "FLD_ZONE" in flood:
        sfha = set(cfg["exclusions"]["fema_flood_zones"])  # high-risk only; Zone X is not flood
        flood = flood[flood["FLD_ZONE"].isin(sfha)]
        if len(flood):
            flood_union = flood.geometry.union_all()
            status["hazard_free"] = "live"

    geom = parcels.geometry
    if flood_union is not None:
        flood_area = geom.intersection(flood_union).area
        flood_pct = (100.0 * flood_area / geom.area).clip(0, 100)
        non_flood = geom.difference(flood_union)
    else:
        flood_pct = geom.area * 0.0  # all zeros
        non_flood = geom
    buildable_ac = (non_flood.buffer(-setback_m).area / M2_PER_ACRE).clip(lower=0)

    # --- compactness (Polsby-Popper) ---
    perim = geom.length
    compactness = (4.0 * math.pi * geom.area) / (perim.pow(2))
    compactness = compactness.clip(0, 1)

    # --- terrain: mean slope (3DEP Slope-Degrees raster) -> percent grade ---
    slope_pct = None
    slope_path = RAW_DIR / "slope.tif"
    if slope_path.exists():
        try:
            import rasterio
            from rasterstats import zonal_stats

            with rasterio.open(slope_path) as src:
                rcrs = src.crs
            pz = parcels.to_crs(rcrs) if rcrs else parcels.to_crs("EPSG:3857")
            zs = zonal_stats(list(pz.geometry), str(slope_path), stats=["mean"], nodata=-9999.0)
            slope_pct = [
                round(math.tan(math.radians(s["mean"])) * 100.0, 1)
                if s and s.get("mean") is not None
                else None
                for s in zs
            ]
            status["terrain"] = "live"
        except Exception as exc:  # raster optional — never sink the run
            print(f"  slope zonal failed: {exc}")

    # --- land cover: NLCD dominant class per parcel -> config key ---
    landcover = None
    nlcd_path = RAW_DIR / "nlcd.tif"
    if nlcd_path.exists():
        try:
            import rasterio
            from rasterstats import zonal_stats

            with rasterio.open(nlcd_path) as src:
                ncrs = src.crs
            pz = parcels.to_crs(ncrs) if ncrs else parcels.to_crs("EPSG:4326")
            zs = zonal_stats(list(pz.geometry), str(nlcd_path), categorical=True, nodata=0)
            landcover = [
                NLCD_TO_KEY.get(int(max(s, key=s.get)), "default") if s else None for s in zs
            ]
            status["landcover_soils"] = "live (landcover; soils pending)"
        except Exception as exc:
            print(f"  nlcd zonal failed: {exc}")

    # --- road access: distance to nearest TIGER road ---
    dist_road_mi = None
    roads = _load("roads")
    if roads is not None and len(roads):
        jr = gpd.sjoin_nearest(parcels[["geometry"]], roads[["geometry"]], distance_col="_d")
        jr = jr[~jr.index.duplicated(keep="first")]
        dist_road_mi = (jr["_d"] * MILES_PER_M).reindex(parcels.index)
        status["road_access"] = "live"

    # --- soils: NRCS Land Capability Class via parcel-centroid spatial join ---
    soil_lcc = None
    soils = _load("soils")
    if soils is not None and len(soils) and "lcc" in soils:
        cent_g = gpd.GeoDataFrame(geometry=parcels.geometry.centroid, crs=parcels.crs)
        sj = gpd.sjoin(cent_g, soils[["lcc", "geometry"]], how="left", predicate="within")
        sj = sj[~sj.index.duplicated(keep="first")].reindex(parcels.index)
        soil_lcc = [v if isinstance(v, str) and v else None for v in sj["lcc"]]
        if any(soil_lcc):
            status["landcover_soils"] = "live (landcover + soils)"

    # --- flex co-location: distance to nearest existing power plant (EIA) ---
    dist_gen_mi = None
    gen = _load("generation")
    if gen is not None and len(gen):
        jg = gpd.sjoin_nearest(parcels[["geometry"]], gen[["geometry"]], distance_col="_d")
        jg = jg[~jg.index.duplicated(keep="first")]
        dist_gen_mi = (jg["_d"] * MILES_PER_M).reindex(parcels.index)

    # --- assemble features (output geometry simplified, EPSG:4326) ---
    out = parcels.to_crs("EPSG:4326")
    cent = parcels.geometry.centroid.to_crs("EPSG:4326")  # centroid in projected CRS, then WGS84
    simp = out.geometry.simplify(0.00025, preserve_topology=True)

    def val(series, i, ndigits=2):
        if series is None:
            return None
        x = series.iloc[i]
        import pandas as pd

        return None if pd.isna(x) else round(float(x), ndigits)

    features: list[dict[str, Any]] = []
    for i in range(len(parcels)):
        county = str(parcels["county"].iloc[i]).title() if "county" in parcels else "Unknown"
        props = {
            "county": county,
            "acreage_total": round(float(parcels["area_ac"].iloc[i]), 1),
            "acreage_buildable": round(float(buildable_ac.iloc[i]), 1),
            "centroid_lat": round(float(cent.y.iloc[i]), 5),
            "centroid_lon": round(float(cent.x.iloc[i]), 5),
            "dist_substation_mi": val(dist_sub_mi, i),
            "nearest_sub_kv": val(near_kv, i, 0),
            "dist_transmission_mi": val(dist_line_mi, i),
            "dist_generation_mi": val(dist_gen_mi, i),
            "floodplain_pct": (
                round(float(flood_pct.iloc[i]), 1) if flood_union is not None else None
            ),
            "compactness": round(float(compactness.iloc[i]), 3),
            "slope_pct_mean": (slope_pct[i] if slope_pct is not None else None),
            "landcover_class": (landcover[i] if landcover is not None else None),
            "soil_lcc_class": (soil_lcc[i] if soil_lcc is not None else None),
            "dist_road_mi": val(dist_road_mi, i),
            # pending: mineral-exclusion % (RRC wells/pipelines) — not in this pass
            "mineral_excl_pct": None,
        }
        gi = simp.iloc[i].__geo_interface__
        features.append(
            {
                "type": "Feature",
                "properties": props,
                "geometry": {"type": gi["type"], "coordinates": _round_coords(gi["coordinates"])},
            }
        )

    (RAW_DIR / "build_status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
    return {
        "type": "FeatureCollection",
        "_criteria_status": status,
        "features": features,
    }
