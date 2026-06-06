"""Stage 2 - build: clip, exclude, and compute per-parcel metrics.

Implemented in M1. Requires the geospatial stack (geopandas/rasterio/shapely/
pyproj). Reprojects to the analysis CRS, applies the >=50-acre filter, subtracts
the hard exclusions and setbacks from config.yaml to derive buildable acreage,
and computes each criterion metric (distances, mean slope, hazard %, compactness,
land-cover/soil class) that ``scoring`` then normalizes.
"""

from __future__ import annotations

from typing import Any

from .fetch import StageNotImplemented


def run(cfg: dict[str, Any]) -> None:
    raise StageNotImplemented(
        "build lands in M1 (needs geopandas/rasterio/shapely/pyproj). "
        "It derives buildable acreage + criterion metrics per config.yaml."
    )
