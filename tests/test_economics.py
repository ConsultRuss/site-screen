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
