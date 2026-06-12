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


FETCH = {"parcels": {"ok": True, "count": 7264}, "substations": {"ok": True, "count": 189},
         "transmission": {"ok": True, "count": 321}, "flood": {"ok": True, "count": 3966},
         "slope": {"ok": True, "count": 39327564}, "nlcd": {"ok": True, "count": 10619532},
         "roads": {"ok": True, "count": 14434}, "soils": {"ok": True, "count": 245262},
         "generation": {"ok": True, "count": 43}}
RUN = {"run_utc": "2026-06-12T17:45:52+00:00", "parcel_count": 5130, "shortlist_count": 24,
       "criteria_status": {"interconnection": "live", "buildable_acreage": "live"},
       "lenses": {
           "flex_load": "live (curtailment-basis neutral — needs nodal LMP)",
           "agrivoltaic": "live",
       },
       "verdict_layer": "live"}


def test_layer_freshness_joins_config_with_fetch_and_flags_restricted():
    rows = audit.layer_freshness(FETCH, RUN, CFG)
    by = {r["layer"]: r for r in rows}
    assert by["substations"]["count"] == 189 and by["substations"]["status"] == "live"
    # the restricted ERCOT row is present and flagged
    assert any(r["license"] == "restricted" for r in rows)
    ercot = next(r for r in rows if r["license"] == "restricted")
    assert "never displayed raw" in ercot["role"]


def test_run_summary_reads_screen_run():
    s = audit.run_summary(RUN)
    assert s["parcel_count"] == 5130 and s["shortlist_count"] == 24
    assert s["run_utc"].startswith("2026-06-12")


def test_provenance_chain_uses_real_artifact_numbers():
    p = audit.provenance(FETCH, RUN)
    assert p["fetched"] == 7264 and p["final"] == 5130 and p["shortlist"] == 24


def _fc(props_list):
    return {"features": [{"properties": p} for p in props_list]}


def test_field_completeness_computes_null_rates_and_flags():
    fc = _fc([
        {"suitability_score": 80, "nearest_sub_kv": 345},
        {"suitability_score": 60, "nearest_sub_kv": None},  # 50% null on kv
    ])
    rows = audit.field_completeness(fc, CFG)
    by = {r["field"]: r for r in rows}
    assert by["suitability_score"]["null_rate"] == 0.0 and by["suitability_score"]["ok"] is True
    assert by["nearest_sub_kv"]["null_rate"] == 0.5 and by["nearest_sub_kv"]["ok"] is False


def test_build_audit_assembles_all_sections():
    fc = _fc([{"suitability_score": 80, "nearest_sub_kv": 345, "pipeline_status": "LOI"}])
    rep = audit.build_audit(fc, FETCH, RUN, CFG)
    for key in ("run", "provenance", "layers", "completeness",
                "governance_note", "reconciled", "anomalies"):
        assert key in rep
    # curtailment-neutral lens surfaces as an honest anomaly
    assert any("curtailment" in a.lower() for a in rep["anomalies"])
