"""Contract for the deal-economics engine (Feature A3).

Development-margin / option economics — NOT stabilized-NOI. All figures are
illustrative; sourced in RESEARCH_2026-06-11_deal-economics.md. These tests pin
the math to hand-computed expecteds and guard the verified-claims constraints
(no SB6 $, JETI unsettled). Mirrors test_verdicts.py: tiny dict parcels + CFG.
"""

import math

from pipeline import economics as ec
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


def test_flip_gross_uplift_is_multiple_minus_one_times_basis():
    # m=4: (4-1)*3450*2000 = 20,700,000
    assert ec.flip_gross_uplift(P, 4) == 3 * 3450 * 2000.0


def test_multiple_on_control_capital():
    # gross_uplift(4) / control_cost = 20.7M / 207K = 100x
    assert math.isclose(ec.multiple_on_control(P, CFG, 4), 100.0, rel_tol=1e-9)


def test_flip_irr_in_window_is_positive_and_annualized():
    irr = ec.flip_irr(P, CFG, months=48, mult=4)
    cap = ec.capital_deployed(P, CFG)
    net = ec.flip_gross_uplift(P, 4) - ec.diligence_total(CFG) - ec.carry(P, CFG, 48)
    expected = (1 + net / cap) ** (12 / 48) - 1
    assert math.isclose(irr, expected, rel_tol=1e-9)
    assert irr > 0


def test_flip_irr_shorter_time_to_power_beats_longer_at_same_exit():
    # The thesis (within window): faster energization -> higher annualized IRR.
    assert ec.flip_irr(P, CFG, 36, 4) > ec.flip_irr(P, CFG, 60, 4)


def test_flip_irr_miss_window_is_total_loss_regardless_of_exit():
    # The thesis hammer: miss the window -> control+diligence written off -> -100%,
    # for EVERY exit column.
    for m in (2, 4, 6):
        assert ec.flip_irr(P, CFG, months=None, mult=m) == -1.0


def test_sensitivity_grid_shape_and_miss_row():
    grid = ec.sensitivity_grid(P, CFG)
    # rows = months [36,48,60] + miss; cols = multiples [2,4,6]
    assert [r["months"] for r in grid] == [36, 48, 60, None]
    assert all(len(r["cells"]) == 3 for r in grid)
    miss = grid[-1]
    assert all(c["irr"] == -1.0 and not c["clears"] for c in miss["cells"])


def test_sensitivity_cells_carry_hurdle_flag():
    grid = ec.sensitivity_grid(P, CFG)
    top = grid[0]["cells"][-1]  # 36 months, 6x — the strongest in-window cell
    assert top["clears"] is (top["irr"] >= CFG["deal_economics"]["exit"]["hurdle_irr"])


def test_risk_adjusted_irr_applies_success_probability():
    # expected = p*success_irr + (1-p)*(-1.0)
    p = CFG["deal_economics"]["exit"]["success_probability"]
    s = ec.flip_irr(P, CFG, 48, 4)
    assert math.isclose(ec.risk_adjusted_irr(P, CFG, 48, 4), p * s + (1 - p) * (-1.0), rel_tol=1e-9)


def test_lease_tier_by_interconnection():
    # 345 kV on-parcel -> prime; weak (<138, far) -> standard
    assert ec.lease_tier({"nearest_sub_kv": 345.0, "dist_substation_mi": 0.0}) == "prime"
    assert ec.lease_tier({"nearest_sub_kv": 138.0, "dist_substation_mi": 1.0}) == "near_substation"
    assert (
        ec.lease_tier({"nearest_sub_kv": 138.0, "dist_substation_mi": 3.0}) == "good_transmission"
    )
    assert ec.lease_tier({"nearest_sub_kv": 69.0, "dist_substation_mi": 8.0}) == "standard"


def test_lease_economics_rate_annual_yield():
    le = ec.lease_economics(P, CFG)            # P is 345 kV on-parcel -> prime
    assert le["tier"] == "prime"
    assert le["rate_per_ac_yr"] == (1500 + 2000) / 2           # tier midpoint 1750
    assert le["annual"] == 1750 * 1600.0                        # rate x buildable
    assert math.isclose(le["yield_on_basis"], (1750 * 1600.0) / ec.land_price(P), rel_tol=1e-9)


def test_jv_economics_is_hedged_scenario():
    jv = ec.jv_economics(P, CFG)
    assert jv["retained_pct"] == {"low": 0.05, "base": 0.10, "high": 0.15}
    assert jv["stabilized_share_pct"] == {"low": 0.02, "high": 0.05}
    # retained value (base) = retained_base x stabilized_share_high x (mw x per_mw)
    assert ec.mw_estimate(P, CFG) > 0  # confirms mw_estimate feeds retained_value_base
    assert jv["retained_value_base"] > 0 and "as-entitled" in jv["valuation_basis"]


def test_parcel_economics_assembles_all_panels():
    rec = ec.parcel_economics(P, CFG)
    for key in ("land_price", "mw_est", "capital_deployed", "flip", "lease", "jv", "budget"):
        assert key in rec
    assert rec["flip"]["ntp_fee_per_mw"] == [80000, 120000]
    assert len(rec["flip"]["sensitivity"]) == 4
    # budget side: option + diligence + legal stages, each with a budget number
    stages = {b["stage"] for b in rec["budget"]}
    assert {"option", "diligence", "legal"} <= stages


def test_build_economics_covers_only_shortlist_with_no_none_leaks():
    parcels = [
        dict(P, parcel_id="KAR-000004", pipeline_status="LOI"),
        {"parcel_id": "X", "pipeline_status": None},  # not shortlist -> skipped
    ]
    out = ec.build_economics(parcels, CFG)
    assert set(out["parcels"]) == {"KAR-000004"}
    assert "assumptions" in out  # echoed for the UI assumptions block
    # no None leaks in the computed record
    import json
    assert "null" not in json.dumps(out["parcels"]["KAR-000004"])


def test_flip_net_matches_irr_decomposition():
    cap = ec.capital_deployed(P, CFG)
    net = ec.flip_net(P, CFG, 48, 4)
    assert math.isclose(ec.flip_irr(P, CFG, 48, 4), (1 + net / cap) ** (12 / 48) - 1, rel_tol=1e-9)


def test_money_multiple_varies_by_parcel():
    big = dict(P)  # 2000 ac, $3450 -> large land value
    small = dict(P, acreage_total=600.0, acreage_buildable=560.0)  # smaller tract, same price
    mm_big = ec.money_multiple(big, CFG, 48, 4)
    mm_small = ec.money_multiple(small, CFG, 48, 4)
    assert mm_big > mm_small > 1  # fixed diligence drags small tracts down


def test_parcel_record_has_money_multiple_not_constant_control_metric():
    rec = ec.parcel_economics(P, CFG)
    assert "money_multiple" in rec["flip"]
    assert "multiple_on_control" not in rec["flip"]  # replaced in the surfaced record


def test_sensitivity_cells_have_risk_adjusted():
    rec = ec.parcel_economics(P, CFG)
    grid = rec["flip"]["sensitivity"]
    assert all("ra" in c for row in grid for c in row["cells"])
    miss = grid[-1]
    assert all(c["ra"] == -1.0 for c in miss["cells"])  # miss row risk-adj is total loss too


def test_diligence_overhead_block_present_and_emitted():
    do = DE["diligence_overhead"]
    assert len(do["fixed_reserve_usd"]) == 2
    assert do["fixed_reserve_usd"][0] < do["fixed_reserve_usd"][1]
    assert do["components"] and "note" in do
    # surfaced into the emitted economics.json assumptions block (one source for the memo)
    out = ec.build_economics([dict(P, pipeline_status="LOI")], CFG)
    assert out["assumptions"]["diligence_overhead"] == do
