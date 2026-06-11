"""Verdict-flag engine (Feature A1) — pure-Python, config-driven.

The model ranks; the analyst decides. These functions compute objective *flags*
from a parcel's already-scored metrics, per the thresholds in config.yaml's
``verdict_rules``. They never author a verdict — pursue / pursue-if / pass is
human judgment, kept in web/data/verdicts.json. Each flag carries a class
(kill-risk | caution) so the UI can style it.
"""

from __future__ import annotations

from statistics import median
from typing import Any


def county_price_medians(
    parcels: list[dict[str, Any]], cfg: dict[str, Any]
) -> dict[str, float]:
    """Median ``est_price_per_ac`` among the synthetic shortlist, by county.

    Only shortlist parcels (those with a ``pipeline_status``) carry a price, so
    the norm ``price_rich`` compares against is the shortlist's county median.
    """
    by_county: dict[str, list[float]] = {}
    for p in parcels:
        if not p.get("pipeline_status"):
            continue
        price = p.get("est_price_per_ac")
        if price is None:
            continue
        by_county.setdefault(p.get("county"), []).append(float(price))
    return {c: median(v) for c, v in by_county.items() if v}


def parcel_flags(
    parcel: dict[str, Any], cfg: dict[str, Any], price_medians: dict[str, float]
) -> list[dict[str, str]]:
    """Objective flags for one parcel, computed from ``config.verdict_rules``."""
    rules = cfg["verdict_rules"]
    flags: list[dict[str, str]] = []

    def add(fid: str) -> None:
        flags.append({"id": fid, "class": rules[fid]["class"]})

    # prime_soil — prime farmland (NRCS LCC 1-2)
    if parcel.get("soil_lcc_class") in rules["prime_soil"]["soil_lcc_classes"]:
        add("prime_soil")

    # floodplain — material floodplain share remaining
    fp = parcel.get("floodplain_pct")
    if fp is not None and float(fp) > rules["floodplain"]["pct_over"]:
        add("floodplain")

    # weak_interconnect — below 138 kV, or off the 345 kV backbone and far from it
    kv = parcel.get("nearest_sub_kv")
    if kv is not None:
        wr = rules["weak_interconnect"]
        tx = parcel.get("dist_transmission_mi")
        if kv < wr["min_kv"] or (
            tx is not None and tx > wr["backbone_dist_mi"] and kv < wr["backbone_kv"]
        ):
            add("weak_interconnect")

    # poor_shape — low compactness
    c = parcel.get("compactness")
    if c is not None and float(c) < rules["poor_shape"]["compactness_under"]:
        add("poor_shape")

    # title_cloud — any non-clear title flag
    tf = parcel.get("title_flag")
    if tf is not None and tf != "clear":
        add("title_cloud")

    # price_rich — priced above the county shortlist norm
    price = parcel.get("est_price_per_ac")
    med = price_medians.get(parcel.get("county"))
    if price and med and float(price) > med * rules["price_rich"]["median_multiple"]:
        add("price_rich")

    return flags
