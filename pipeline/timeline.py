"""Speed-to-power / energization-timeline engine (Feature A4) — pure-Python.

A disclosed phase model gated on the ERCOT interconnection queue. Critical path =
interconnection (long pole, modulated per-parcel by live grid quality) +
construction tail; diligence/permitting run parallel and are excluded. Mirrors
economics.py: pure functions over a parcel dict + cfg. The license-restricted
ERCOT GIS Report is never a display source. All figures illustrative; the
interconnection duration is directional/UNCERTAIN and always shown with a band.
"""

from __future__ import annotations

from typing import Any


def grid_quality_factor(parcel: dict[str, Any], cfg: dict[str, Any]) -> float:
    """Bounded multiplier on the interconnection long pole from LIVE grid quality.
    Better grid (345 kV backbone, short gen-tie) -> lower factor -> faster power.
    Null-safe: missing kv/dist fall back to the worst case."""
    g = cfg["power_timeline"]["grid_quality_factor"]
    kv = float(parcel.get("nearest_sub_kv") or 0)
    dist_raw = parcel.get("dist_substation_mi")
    dist = float(dist_raw) if dist_raw is not None else g["dist_far_mi"]
    kv_score = 1.0 if kv >= g["kv_backbone"] else (0.55 if kv >= g["kv_transmission"] else 0.15)
    span = g["dist_far_mi"] - g["dist_near_mi"]
    dist_score = max(0.0, min(1.0, 1 - (dist - g["dist_near_mi"]) / span))
    quality = 0.5 * kv_score + 0.5 * dist_score          # 0..1
    return g["max"] - quality * (g["max"] - g["min"])


def interconnection_months(
    parcel: dict[str, Any], cfg: dict[str, Any], variant: str
) -> list[float]:
    """The interconnection long pole [P10,P50,P90], modulated by grid quality."""
    base = cfg["power_timeline"]["phases"][variant]["interconnection"]
    f = grid_quality_factor(parcel, cfg)
    return [p * f for p in base]
