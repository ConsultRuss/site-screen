"""Pure-Python geometric helpers used by scoring and the mini-eval.

These are deliberately dependency-free so they can be unit-tested in CI without
the geospatial stack. The heavy geometry (clipping, exclusion masks, area math)
lives in ``build`` and uses shapely/pyproj.
"""

from __future__ import annotations

import math

# Mean Earth radius in miles (used for great-circle distance).
_EARTH_RADIUS_MI = 3958.7613


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two WGS84 points, in miles.

    Sanity anchor: one degree of latitude is ~69 miles, so
    ``haversine_miles(29, -98, 30, -98)`` is ~69.
    """
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * _EARTH_RADIUS_MI * math.asin(math.sqrt(a))


def polsby_popper(area: float, perimeter: float) -> float:
    """Polsby-Popper compactness, 0..1. A circle scores 1.0; thin slivers approach 0."""
    if perimeter <= 0:
        return 0.0
    return (4.0 * math.pi * area) / (perimeter**2)
