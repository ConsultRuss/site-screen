"""Config-driven suitability scoring (pure-Python, no geo dependencies).

This is the math that turns per-parcel metrics into a 0-100 weighted score and a
rank. It reads its breakpoints, weights, and lookup tables from ``config.yaml``
so the model is fully auditable and re-tunable without code changes.

Normalization is hybrid (see config "normalization"):
  * linear   - anchored piecewise-linear; works in either direction
  * identity - value already on a 0..100 scale (clamped)
  * scale    - value * factor (clamped); e.g. a 0..1 ratio -> 0..100
  * lookup   - categorical class -> score via a table (with a default)
"""

from __future__ import annotations

from typing import Any


def clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def normalize_linear(value: float, full_score_at: float, zero_score_at: float) -> float:
    """Piecewise-linear map to 0..100.

    100 at ``full_score_at``, 0 at ``zero_score_at``, linear between, clamped
    outside. Direction is inferred from the anchors, so it handles both
    "smaller is better" (e.g. distance) and "larger is better" (e.g. acreage).
    """
    if full_score_at == zero_score_at:
        return 100.0 if value <= full_score_at else 0.0
    frac = (value - full_score_at) / (zero_score_at - full_score_at)
    return clamp(100.0 * (1.0 - frac))


def normalize(value: Any, spec: dict[str, Any]) -> float:
    """Dispatch a single metric to 0..100 according to its normalization spec."""
    kind = spec["type"]
    if kind == "linear":
        return normalize_linear(float(value), spec["full_score_at"], spec["zero_score_at"])
    if kind == "identity":
        return clamp(float(value))
    if kind == "scale":
        return clamp(float(value) * spec["factor"])
    if kind == "lookup":
        table = spec["table"]
        if value in table:
            return float(table[value])
        return float(table.get(str(value), table.get("default", 0.0)))
    raise ValueError(f"unknown normalization type: {kind!r}")


def weighted_lens(normalized: dict[str, float], weights: dict[str, float]) -> float:
    """Weighted sum of already-normalized (0..100) criteria. Shared by all lenses."""
    return sum(weights[c] * normalized[c] for c in weights)


NEUTRAL = 50.0


def _norm_or_neutral(value: Any, spec: dict[str, Any]) -> float:
    """Normalize, but a not-yet-measured (None) criterion scores a neutral 50."""
    return NEUTRAL if value is None else normalize(value, spec)


def suitability_breakdown(parcel: dict[str, Any], cfg: dict[str, Any]) -> dict[str, float]:
    """Per-criterion normalized scores (0..100) for one parcel under the base model.

    Maps the parcel's raw attributes onto the base-model criteria, then normalizes
    each via ``config.yaml``. Returned as a dict so the web app can show a
    click-a-parcel breakdown.
    """
    norm = cfg["model"]["normalization"]
    blend = cfg["model"]["landcover_soils_blend"]

    landcover = normalize(parcel.get("landcover_class"), norm["landcover"])
    soils = normalize(parcel.get("soil_lcc_class"), norm["soils_lcc"])
    landcover_soils = (
        landcover * blend["landcover_weight"] + soils * blend["soils_weight"]
    )

    # % of the parcel OUTSIDE hazards = 100 - % inside floodplain/wetlands.
    # None (no flood layer this pass) -> neutral, not a falsely-perfect 100.
    fp = parcel.get("floodplain_pct")
    hazard_free = NEUTRAL if fp is None else normalize(100.0 - float(fp), norm["hazard_free"])

    g = _norm_or_neutral
    return {
        "interconnection": g(parcel.get("dist_substation_mi"), norm["interconnection"]),
        "buildable_acreage": g(parcel.get("acreage_buildable"), norm["buildable_acreage"]),
        "terrain": g(parcel.get("slope_pct_mean"), norm["terrain"]),
        "landcover_soils": landcover_soils,
        "hazard_free": hazard_free,
        "road_access": g(parcel.get("dist_road_mi"), norm["road_access"]),
        "shape": g(parcel.get("compactness"), norm["shape"]),
    }


def provisional_flex_score(parcel: dict[str, Any], cfg: dict[str, Any]) -> float:
    """Provisional flexible-load lens from the criteria that are LIVE today
    (interconnection, buildable acreage, hazard-free). The full lens adds
    proximity-to-generation and curtailment/basis once those layers are wired."""
    b = suitability_breakdown(parcel, cfg)
    return round(
        0.5 * b["interconnection"] + 0.3 * b["buildable_acreage"] + 0.2 * b["hazard_free"], 1
    )


def suitability_score(parcel: dict[str, Any], cfg: dict[str, Any]) -> float:
    """Base-model suitability for one parcel, 0..100 (rounded to 1 decimal)."""
    breakdown = suitability_breakdown(parcel, cfg)
    return round(weighted_lens(breakdown, cfg["model"]["weights"]), 1)


def rank_parcels(parcels: list[dict[str, Any]], cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Score every parcel and assign a 1-based ``suitability_rank``.

    Deterministic: ties break by ``parcel_id`` so a re-run yields identical order.
    Returns the same dicts, mutated in place with ``suitability_score`` and
    ``suitability_rank``.
    """
    for p in parcels:
        p["suitability_score"] = suitability_score(p, cfg)
    ordered = sorted(
        parcels, key=lambda p: (-p["suitability_score"], str(p.get("parcel_id", "")))
    )
    for i, p in enumerate(ordered, start=1):
        p["suitability_rank"] = i
    return ordered
