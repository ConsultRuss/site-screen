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
