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


def flip_irr(
    parcel: dict[str, Any], cfg: dict[str, Any], months: int | None, mult: float
) -> float:
    """IRR on deployed control+diligence capital for the flip exit.

    months=None is the 'misses the window' case: the option is not exercised, so
    control + diligence are written off -> net = -capital -> IRR = -100%, for any
    exit multiple. That is the interconnection-first thesis in money form.
    """
    cap = capital_deployed(parcel, cfg)
    if months is None:
        return -1.0
    net = flip_gross_uplift(parcel, mult) - diligence_total(cfg) - carry(parcel, cfg, months)
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
