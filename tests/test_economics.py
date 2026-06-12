"""Contract for the deal-economics engine (Feature A3).

Development-margin / option economics — NOT stabilized-NOI. All figures are
illustrative; sourced in RESEARCH_2026-06-11_deal-economics.md. These tests pin
the math to hand-computed expecteds and guard the verified-claims constraints
(no SB6 $, JETI unsettled). Mirrors test_verdicts.py: tiny dict parcels + CFG.
"""

import math

from pipeline.config import load_config

CFG = load_config()
DE = CFG["deal_economics"]


def test_deal_economics_block_present_with_locked_values():
    assert DE["control"]["option_pct"] == 0.03
    assert DE["mw"]["ac_per_mw"] == 8
    assert DE["carry"]["annual_rate"] == 0.12
    assert DE["exit"]["uplift_multiples"] == [2, 4, 6]
    assert DE["exit"]["time_to_power_months"] == [36, 48, 60]
    assert DE["exit"]["hurdle_irr"] == 0.25
    # diligence table — verified subset
    dl = DE["diligence_usd"]
    assert dl["phase_i_esa"] == [4000, 10000]
    assert dl["alta_survey"] == [15000, 50000]
    assert set(DE["diligence_order_of_magnitude"]) == {"geotech", "drainage_hh"}
    # incentives wording is locked — JETI must be "unsettled", never excluded/included
    note = DE["incentives"]["note"].lower()
    assert "151.359" in note and "312" in note
    assert "unsettled" in note
    assert "excluded" not in note and "included" not in note
    # SB6 framing is direction-only — no dollar figure
    assert "$" not in DE["sb6_framing"]


from pipeline import economics as ec

# A representative shortlist parcel (values like KAR-000004-ish; round for hand-calc)
P = {
    "parcel_id": "KAR-000004", "county": "Karnes",
    "acreage_total": 2000.0, "acreage_buildable": 1600.0, "est_price_per_ac": 3450,
    "nearest_sub_kv": 345.0, "dist_substation_mi": 0.0, "dist_transmission_mi": 0.0,
}


def test_land_price_uses_total_acreage():
    assert ec.land_price(P) == 3450 * 2000.0


def test_mw_estimate_uses_buildable_over_density():
    assert ec.mw_estimate(P, CFG) == 1600.0 / 8  # 200 MW


def test_control_cost_is_option_pct_of_land_price():
    assert ec.control_cost(P, CFG) == 0.03 * 3450 * 2000.0  # 207,000


def test_diligence_total_sums_midpoints():
    # mids: 7000+32500+10000+12500+5750+30000+50000 = 147750
    assert ec.diligence_total(CFG) == 147750.0


def test_capital_deployed_is_control_plus_diligence():
    assert ec.capital_deployed(P, CFG) == 207000.0 + 147750.0  # 354750


def test_carry_compounds_annually_over_months():
    cap = ec.capital_deployed(P, CFG)
    expected = cap * ((1.12) ** (48 / 12) - 1)
    assert math.isclose(ec.carry(P, CFG, 48), expected, rel_tol=1e-9)
