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
