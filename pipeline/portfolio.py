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


def allocate(
    economics_parcels: dict[str, Any], verdicts_by_id: dict[str, str],
    cfg: dict[str, Any], budget: float,
) -> dict[str, Any]:
    """Greedy option-spread within `budget`, by priority (skip-and-continue), then
    stage diligence on the top-N controlled winners. Returns controlled / unfunded /
    excluded lists + portfolio totals."""
    pcfg = cfg["deal_economics"]["portfolio"]
    elig = eligible_priority(economics_parcels, verdicts_by_id, cfg)
    elig_ids = {pid for pid, _, _ in elig}

    controlled: list[dict[str, Any]] = []
    unfunded: list[dict[str, Any]] = []
    remaining = float(budget)
    for pid, e, v in elig:
        cost = float(e["control_cost"])
        row = {
            "parcel_id": pid, "county": e.get("county"), "verdict": v,
            "option_cost": e["control_cost"], "diligence_total": e["diligence_total"],
            "acreage_buildable": e.get("acreage_buildable"), "mw_est": e.get("mw_est"),
            "ra": round(best_ra(e), 3), "suitability_rank": e.get("suitability_rank"),
        }
        if cost <= remaining:
            remaining -= cost
            row["cumulative_option"] = round(budget - remaining)
            row["stage_next"] = False
            controlled.append(row)
        else:
            unfunded.append(row)

    # stage diligence on the top-N controlled by risk-adjusted return
    top = sorted(controlled, key=lambda r: -r["ra"])[: pcfg["stage_top_n"]]
    top_ids = {r["parcel_id"] for r in top}
    for r in controlled:
        r["stage_next"] = r["parcel_id"] in top_ids

    excluded = [
        {"parcel_id": pid, "verdict": verdicts_by_id.get(pid)}
        for pid in economics_parcels
        if pid not in elig_ids
    ]

    capital = sum(r["option_cost"] for r in controlled)
    staged = [r for r in controlled if r["stage_next"]]
    ras = [r["ra"] for r in controlled]
    return {
        "budget": budget,
        "controlled": controlled, "unfunded": unfunded, "excluded": excluded,
        "n_controlled": len(controlled),
        "acres_controlled": round(sum(r["acreage_buildable"] or 0 for r in controlled)),
        "mw_controlled": round(sum(r["mw_est"] or 0 for r in controlled), 1),
        "capital_deployed": round(capital),
        "budget_utilization": round(capital / budget, 3) if budget else 0,
        "n_staged": len(staged),
        "staged_diligence_usd": round(sum(r["diligence_total"] for r in staged)),
        "blended_ra": round(sum(ras) / len(ras), 3) if ras else None,
    }
