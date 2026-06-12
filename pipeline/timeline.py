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


def _nearest(anchors: list[int], value: float) -> int:
    return min(anchors, key=lambda a: abs(a - value))


def time_to_power(parcel: dict[str, Any], cfg: dict[str, Any], variant: str) -> dict[str, Any]:
    """[P10,P50,P90] critical path = interconnection (modulated) + construction tail,
    clamped to the defensible band. Maps P50 to A3's nearest sensitivity row (or
    'miss' when P50 > 60). Diligence/permitting are parallel -> not in the total."""
    pt = cfg["power_timeline"]
    band = pt["band_months"]
    inter = interconnection_months(parcel, cfg, variant)
    tail = pt["phases"][variant]["construction"]
    pts = [max(band["floor"], min(band["ceiling"], inter[i] + tail[i])) for i in range(3)]
    p10, p50, p90 = pts
    miss = p50 > 60
    anchors = cfg["deal_economics"]["exit"]["time_to_power_months"]
    return {
        "p50": round(p50),
        "band": [round(p10), round(p90)],
        "miss_risk": miss,
        "expected_row": "miss" if miss else _nearest(anchors, p50),
    }


def phase_bars(parcel: dict[str, Any], cfg: dict[str, Any], variant: str) -> list[dict[str, Any]]:
    """The four phases for the timeline bars. Interconnection is modulated +
    flagged uncertain; diligence/permitting are flagged parallel (under the pole)."""
    ph = cfg["power_timeline"]["phases"][variant]
    inter = interconnection_months(parcel, cfg, variant)

    def bar(name, pts, parallel, uncertain):
        return {"name": name, "p10": round(pts[0]), "p50": round(pts[1]),
                "p90": round(pts[2]), "parallel": parallel, "uncertain": uncertain}

    return [
        bar("Diligence", ph["diligence"], True, False),
        bar("Interconnection", inter, False, True),
        bar("Permitting", ph["permitting"], True, False),
        bar("Construction", ph["construction"], False, False),
    ]
