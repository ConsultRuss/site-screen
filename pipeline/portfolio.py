"""Option-budget portfolio allocator (Feature A1.5) — pure-Python, config-driven.

Portfolio-level "the model ranks, the analyst decides": rank eligible parcels by
risk-adjusted return within verdict tier, spread option capital across them within
a budget, and stage diligence on the top speed-to-power winners. Passes are
excluded. Inherits A3's deal_economics + economics.json; adds an allocation layer.
Math lives here (pytest-covered); the web layer only formats.
"""

from __future__ import annotations

from typing import Any

VERDICT_TIER = {"pursue": 0, "pursue_if": 1}  # pass intentionally absent -> excluded


def best_ra(parcel_econ: dict[str, Any]) -> float:
    """Best risk-adjusted return among in-window sensitivity cells (miss row ignored)."""
    ras = [
        c["ra"]
        for row in parcel_econ["flip"]["sensitivity"]
        if row["months"] != "miss"
        for c in row["cells"]
    ]
    return max(ras) if ras else -1.0


def eligible_priority(
    economics_parcels: dict[str, Any], verdicts_by_id: dict[str, str], cfg: dict[str, Any]
) -> list[tuple[str, dict[str, Any], str]]:
    """Eligible parcels (pursue / pursue-if), sorted by (verdict tier, -best_ra, rank)."""
    exclude = set(cfg["deal_economics"]["portfolio"]["exclude_verdicts"])
    elig = []
    for pid, e in economics_parcels.items():
        v = verdicts_by_id.get(pid)
        if v is None or v in exclude or v not in VERDICT_TIER:
            continue
        elig.append((pid, e, v))
    elig.sort(key=lambda t: (VERDICT_TIER[t[2]], -best_ra(t[1]), t[1]["suitability_rank"]))
    return elig
