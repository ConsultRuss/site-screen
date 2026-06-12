"""Contract for the speed-to-power / energization-timeline engine (Feature A4).

A disclosed phase model gated on the ERCOT interconnection queue — NOT a scraped
COD. Verified phase durations (VERIFICATION_2026-06-11_permitting-guide); the
interconnection long pole is modulated per-parcel by live grid quality. All
figures illustrative; the restricted ERCOT GIS Report is never used as a display
source. Mirrors test_economics.py: tiny dict parcels + CFG.
"""

import math

from pipeline import timeline as tl
from pipeline.config import load_config

CFG = load_config()
PT = CFG["power_timeline"]


def test_power_timeline_block_present_with_locked_values():
    assert PT["default_variant"] == "solar"
    # verified non-interconnection phases (P10/P50/P90)
    assert PT["phases"]["solar"]["diligence"] == [3, 6, 9]
    assert PT["phases"]["solar"]["permitting"] == [8, 14, 24]
    assert PT["phases"]["solar"]["construction"] == [12, 18, 24]
    assert PT["phases"]["dc"]["construction"] == [18, 24, 36]
    # band + modulation bounds
    assert PT["band_months"]["floor"] == 36 and PT["band_months"]["ceiling"] == 72
    gqf = PT["grid_quality_factor"]
    assert gqf["min"] < 1.0 < gqf["max"]
    # queue context is PUBLIC + cited; locked labels present
    qc = PT["queue_context"]
    assert "Batch Zero" in qc["batch_zero"] and "PGRR145" in qc["batch_zero"]
    assert "58481" in qc["sb6"] and "$" not in qc["sb6"]   # SB6 direction-only, no dollars
    assert "LLIS" in qc["llis"]
    # restricted-data discipline stated
    assert "HIFLD" in PT["license_discipline"]
    assert "restricted" in PT["license_discipline"].lower() or "abstracted" in PT["license_discipline"].lower()


# Representative shortlist parcels (grid quality varies; round for hand-calc)
STRONG = {"parcel_id": "KAR-000004", "county": "Karnes", "acreage_buildable": 1600.0,
          "suitability_rank": 4, "pipeline_status": "LOI",
          "nearest_sub_kv": 345.0, "dist_substation_mi": 0.0}
WEAK = {"parcel_id": "KAR-000099", "county": "Karnes", "acreage_buildable": 200.0,
        "suitability_rank": 99, "pipeline_status": "Screened",
        "nearest_sub_kv": 69.0, "dist_substation_mi": 12.0}


def test_grid_quality_factor_strong_is_floor_fast():
    # 345 kV on-parcel -> best quality -> factor at min
    assert math.isclose(tl.grid_quality_factor(STRONG, CFG), PT["grid_quality_factor"]["min"], rel_tol=1e-9)


def test_grid_quality_factor_weak_is_slow():
    f = tl.grid_quality_factor(WEAK, CFG)
    assert f > 1.2  # weak grid -> well above 1.0 (slower)


def test_grid_quality_factor_is_monotonic():
    # better grid is never slower
    assert tl.grid_quality_factor(STRONG, CFG) < tl.grid_quality_factor(WEAK, CFG)


def test_grid_quality_factor_null_safe():
    # missing fields fall back to the worst defaults, never crash
    f = tl.grid_quality_factor({"nearest_sub_kv": None, "dist_substation_mi": None}, CFG)
    assert PT["grid_quality_factor"]["min"] <= f <= PT["grid_quality_factor"]["max"]


def test_interconnection_p50_scales_with_factor():
    base = PT["phases"]["solar"]["interconnection"][1]  # P50
    expected = base * tl.grid_quality_factor(STRONG, CFG)
    assert math.isclose(tl.interconnection_months(STRONG, CFG, "solar")[1], expected, rel_tol=1e-9)
