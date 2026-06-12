"""Deal-economics engine (Feature A3) — pure-Python, config-driven.

Development-margin / option economics for the per-parcel Deal Sheet: a control
position (purchase-option) -> diligence -> de-risked exit. NOT stabilized-NOI.
Mirrors verdicts.py: pure functions over a parcel dict + cfg. All figures are
illustrative; sourced in docs/RESEARCH_2026-06-11_deal-economics.md. Math lives
here (pytest-covered); the web layer only formats.
"""

from __future__ import annotations

from typing import Any


def land_price(parcel: dict[str, Any]) -> float:
    """Acquisition value the option controls — whole tract."""
    return float(parcel["est_price_per_ac"]) * float(parcel["acreage_total"])


def mw_estimate(parcel: dict[str, Any], cfg: dict[str, Any]) -> float:
    """Illustrative MW from buildable acres at the configured density (~8 ac/MW)."""
    return float(parcel["acreage_buildable"]) / cfg["deal_economics"]["mw"]["ac_per_mw"]


def control_cost(parcel: dict[str, Any], cfg: dict[str, Any]) -> float:
    """At-risk control capital: purchase-option fee = option_pct of land price."""
    return cfg["deal_economics"]["control"]["option_pct"] * land_price(parcel)


def diligence_total(cfg: dict[str, Any]) -> float:
    """Sum of midpoints of the verified diligence table."""
    table = cfg["deal_economics"]["diligence_usd"]
    return sum((lo + hi) / 2 for lo, hi in table.values())


def capital_deployed(parcel: dict[str, Any], cfg: dict[str, Any]) -> float:
    return control_cost(parcel, cfg) + diligence_total(cfg)


def carry(parcel: dict[str, Any], cfg: dict[str, Any], months: int) -> float:
    """Cost-of-capital on deployed dollars, compounded annually over the hold."""
    rate = cfg["deal_economics"]["carry"]["annual_rate"]
    return capital_deployed(parcel, cfg) * ((1 + rate) ** (months / 12) - 1)


def flip_gross_uplift(parcel: dict[str, Any], mult: float) -> float:
    """Uplift captured = (exit multiple − 1) × basis × total acres."""
    return (mult - 1) * float(parcel["est_price_per_ac"]) * float(parcel["acreage_total"])


def multiple_on_control(parcel: dict[str, Any], cfg: dict[str, Any], mult: float) -> float:
    """How many times the control (option) capital the success-case uplift is."""
    return flip_gross_uplift(parcel, mult) / control_cost(parcel, cfg)


def flip_net(parcel: dict[str, Any], cfg: dict[str, Any], months: int, mult: float) -> float:
    """Net flip profit (success case): uplift − diligence − carry over the hold."""
    return flip_gross_uplift(parcel, mult) - diligence_total(cfg) - carry(parcel, cfg, months)


def money_multiple(parcel: dict[str, Any], cfg: dict[str, Any], months: int, mult: float) -> float:
    """Total-return multiple on deployed capital (success case): (capital + net) / capital.
    Unlike multiple-on-control (which is constant = (mult−1)/option_pct), this VARIES by
    parcel because diligence is a fixed cost in the denominator."""
    cap = capital_deployed(parcel, cfg)
    return (cap + flip_net(parcel, cfg, months, mult)) / cap


def flip_irr(
    parcel: dict[str, Any], cfg: dict[str, Any], months: int | None, mult: float
) -> float:
    """IRR on deployed control+diligence capital for the flip exit.

    months=None is the 'misses the window' case: the option is not exercised, so
    control + diligence are written off -> net = -capital -> IRR = -100%, for any
    exit multiple. That is the interconnection-first thesis in money form.
    """
    if months is None:
        return -1.0
    cap = capital_deployed(parcel, cfg)
    net = flip_net(parcel, cfg, months, mult)
    return (1 + net / cap) ** (12 / months) - 1


def risk_adjusted_irr(
    parcel: dict[str, Any], cfg: dict[str, Any], months: int, mult: float
) -> float:
    """Probability-weighted view: p × success-IRR + (1−p) × total-loss. Honest
    counterweight to the success-case grid (industry chance-of-success 10–50%)."""
    p = cfg["deal_economics"]["exit"]["success_probability"]
    return p * flip_irr(parcel, cfg, months, mult) + (1 - p) * (-1.0)


def sensitivity_grid(parcel: dict[str, Any], cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """The centerpiece: rows = energization months (+ a miss-window row),
    cols = exit multiples. Each cell carries IRR + hurdle flag. Independent axes;
    the miss row collapses every column to −100% — exit price scales, time gates."""
    ex = cfg["deal_economics"]["exit"]
    hurdle = ex["hurdle_irr"]
    rows: list[dict[str, Any]] = []
    for months in [*ex["time_to_power_months"], None]:
        cells = []
        for mult in ex["uplift_multiples"]:
            irr = flip_irr(parcel, cfg, months, mult)
            cells.append({"mult": mult, "irr": irr, "clears": irr >= hurdle})
        rows.append({"months": months, "cells": cells})
    return rows


def lease_tier(parcel: dict[str, Any]) -> str:
    """Interconnection-quality tier for the ground-lease rate.
    prime: >=345 kV; near_substation: >=138 kV within ~1 mi; good_transmission:
    >=138 kV but farther; standard: below 138 kV. (Illustrative tiering.)"""
    kv = float(parcel.get("nearest_sub_kv") or 0)
    dist = float(parcel.get("dist_substation_mi") or 99)
    if kv >= 345:
        return "prime"
    if kv >= 138 and dist <= 1.0:
        return "near_substation"
    if kv >= 138:
        return "good_transmission"
    return "standard"


def _mid(pair: list[float]) -> float:
    return (pair[0] + pair[1]) / 2


def lease_economics(parcel: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    le = cfg["deal_economics"]["lease"]
    tier = lease_tier(parcel)
    rate = _mid(le["tiers_usd_per_ac_yr"][tier])
    annual = rate * float(parcel["acreage_buildable"])
    return {
        "tier": tier,
        "rate_per_ac_yr": rate,
        "annual": annual,
        "yield_on_basis": annual / land_price(parcel),
        "escalation_pct": le["escalation_pct"],
        "term_years": le["term_years"],
        "structure": le["structure"],
    }


def jv_economics(parcel: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    """Softest panel — present as a hedged scenario, not a point estimate."""
    jv = cfg["deal_economics"]["jv"]
    lo, base, hi = jv["retained_pct"]
    s_lo, s_hi = jv["stabilized_share_pct"]
    mw = mw_estimate(parcel, cfg)
    stabilized_value = mw * jv["per_mw_stabilized_usd"]
    return {
        "retained_pct": {"low": lo, "base": base, "high": hi},
        "stabilized_share_pct": {"low": s_lo, "high": s_hi},
        "retained_value_base": base * s_hi * stabilized_value,
        "valuation_basis": jv["valuation_basis"],
        "note": jv["note"],
    }


def _budget(parcel: dict[str, Any], cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Computed budget side of budget-vs-actual (actuals are authored in deal-notes)."""
    dl = cfg["deal_economics"]["diligence_usd"]
    diligence = sum((lo + hi) / 2 for k, (lo, hi) in dl.items() if k != "title_cure_legal")
    return [
        {"stage": "option", "budget": round(control_cost(parcel, cfg))},
        {"stage": "diligence", "budget": round(diligence)},
        {"stage": "legal", "budget": round(_mid(dl["title_cure_legal"]))},
    ]


def parcel_economics(parcel: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    ex = cfg["deal_economics"]["exit"]
    cap = capital_deployed(parcel, cfg)
    # Passthrough fields — drop keys whose value is None to avoid null leaks in JSON output
    passthrough: dict[str, Any] = {
        k: v for k, v in {
            "county": parcel.get("county"),
            "acreage_total": parcel.get("acreage_total"),
            "acreage_buildable": parcel.get("acreage_buildable"),
            "est_price_per_ac": parcel.get("est_price_per_ac"),
            "suitability_rank": parcel.get("suitability_rank"),
        }.items() if v is not None
    }
    return {
        "parcel_id": parcel["parcel_id"],
        **passthrough,
        "land_price": round(land_price(parcel)),
        "mw_est": round(mw_estimate(parcel, cfg), 1),
        "control_cost": round(control_cost(parcel, cfg)),
        "diligence_total": round(diligence_total(cfg)),
        "capital_deployed": round(cap),
        "flip": {
            "money_multiple": {
                m: round(money_multiple(parcel, cfg, ex["time_to_power_months"][1], m), 1)
                for m in ex["uplift_multiples"]
            },
            "uplift_per_ac": {m: round((m - 1) * parcel["est_price_per_ac"])
                              for m in ex["uplift_multiples"]},
            "ntp_fee_per_mw": ex["ntp_fee_per_mw"],
            "sensitivity": [
                {"months": "miss" if r["months"] is None else r["months"],
                 "cells": [{"mult": c["mult"], "irr": round(c["irr"], 3),
                            "ra": round(risk_adjusted_irr(parcel, cfg, r["months"], c["mult"]), 3),
                            "clears": c["clears"]}
                           for c in r["cells"]]}
                for r in sensitivity_grid(parcel, cfg)
            ],
            "hurdle_irr": ex["hurdle_irr"],
            "success_probability": ex["success_probability"],
        },
        "lease": lease_economics(parcel, cfg),
        "jv": jv_economics(parcel, cfg),
        "budget": _budget(parcel, cfg),
    }


def build_economics(parcels: list[dict[str, Any]], cfg: dict[str, Any]) -> dict[str, Any]:
    """Per-shortlist-parcel economics + an echoed assumptions block for the UI."""
    de = cfg["deal_economics"]
    out = {p["parcel_id"]: parcel_economics(p, cfg)
           for p in parcels if p.get("pipeline_status")}
    return {
        "_note": "Generated by pipeline/economics.py — illustrative development-margin/option "
                 "economics; basis in config.yaml deal_economics. Authored actuals/notes in "
                 "deal-notes.json. Synthetic + illustrative.",
        "assumptions": {
            "option_pct": de["control"]["option_pct"],
            "carry_rate": de["carry"]["annual_rate"],
            "ac_per_mw": de["mw"]["ac_per_mw"],
            "uplift_multiples": de["exit"]["uplift_multiples"],
            "time_to_power_months": de["exit"]["time_to_power_months"],
            "hurdle_irr": de["exit"]["hurdle_irr"],
            "diligence_usd": de["diligence_usd"],
            "diligence_order_of_magnitude": de["diligence_order_of_magnitude"],
            "incentives_note": de["incentives"]["note"],
            "sb6_framing": de["sb6_framing"],
            "disclosure": de["disclosure"],
        },
        "parcels": out,
    }


def write_economics(fc: dict[str, Any], cfg: dict[str, Any], out_path) -> int:
    """Compute economics for the finalized shortlist and write web/data/economics.json.
    Returns the number of parcels written."""
    import json
    from pathlib import Path

    props = [f["properties"] for f in fc["features"]]
    data = build_economics(props, cfg)
    Path(out_path).write_text(json.dumps(data, ensure_ascii=False, indent=0), encoding="utf-8")
    return len(data["parcels"])
