"""Contract for the data-integrity / audit engine (Feature A4).

Audits the screen's own provenance, license posture, and field completeness from
the run artifacts. The restricted ERCOT GIS Report is surfaced as a GOVERNANCE
signal, never displayed raw. Mirrors test_economics.py: small fixtures + CFG.
"""

from pipeline import audit
from pipeline.config import load_config

CFG = load_config()
DI = CFG["data_integrity"]


def test_data_integrity_block_present():
    assert 0 < DI["null_rate_warn"] < 1
    assert "suitability_score" in DI["audit_fields"]
    # public layers map keys match fetch_status keys
    assert "substations" in DI["layers"] and "generation" in DI["layers"]
    # the restricted ERCOT row is flagged for the governance signal, never raw
    assert "restricted" in DI["restricted"]["ercot_gis_report"]["license"].lower()
    assert "HIFLD" in DI["governance_note"]
