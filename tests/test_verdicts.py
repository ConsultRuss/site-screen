"""Contract for the verdict-flag engine (Feature A1).

Flags are objective, config-driven signals computed from a parcel's metrics —
the analyst's authored verdict (pursue / pursue-if / pass) is separate and lives
in web/data/verdicts.json. These tests pin each flag to its config threshold and
class, and confirm flags are absent when the inputs aren't measured.
"""

from pipeline.config import load_config
from pipeline.verdicts import county_price_medians, parcel_flags

CFG = load_config()


def _ids(flags):
    return {f["id"] for f in flags}


def _class_of(flags, fid):
    return next(f["class"] for f in flags if f["id"] == fid)


def test_prime_soil_fires_on_class_1_and_2_only():
    assert "prime_soil" in _ids(parcel_flags({"soil_lcc_class": "1"}, CFG, {}))
    assert "prime_soil" in _ids(parcel_flags({"soil_lcc_class": "2"}, CFG, {}))
    assert "prime_soil" not in _ids(parcel_flags({"soil_lcc_class": "3"}, CFG, {}))
    assert _class_of(parcel_flags({"soil_lcc_class": "1"}, CFG, {}), "prime_soil") == "kill-risk"


def test_floodplain_fires_above_threshold_only():
    assert "floodplain" in _ids(parcel_flags({"floodplain_pct": 25.0}, CFG, {}))
    assert "floodplain" not in _ids(parcel_flags({"floodplain_pct": 5.0}, CFG, {}))
    assert "floodplain" not in _ids(parcel_flags({"floodplain_pct": None}, CFG, {}))


def test_weak_interconnect_below_138kv():
    assert "weak_interconnect" in _ids(parcel_flags({"nearest_sub_kv": 69.0}, CFG, {}))


def test_weak_interconnect_138kv_far_from_backbone():
    # The flagship case: 138 kV sub, but >2 mi from the transmission backbone.
    p = {"nearest_sub_kv": 138.0, "dist_transmission_mi": 4.38}
    assert "weak_interconnect" in _ids(parcel_flags(p, CFG, {}))


def test_strong_interconnect_345kv_not_flagged():
    # On the 345 kV backbone, distance to transmission is irrelevant.
    p = {"nearest_sub_kv": 345.0, "dist_transmission_mi": 4.38}
    assert "weak_interconnect" not in _ids(parcel_flags(p, CFG, {}))


def test_138kv_close_to_backbone_not_weak():
    p = {"nearest_sub_kv": 138.0, "dist_transmission_mi": 0.3}
    assert "weak_interconnect" not in _ids(parcel_flags(p, CFG, {}))


def test_poor_shape_below_compactness_threshold():
    assert "poor_shape" in _ids(parcel_flags({"compactness": 0.41}, CFG, {}))
    assert "poor_shape" not in _ids(parcel_flags({"compactness": 0.78}, CFG, {}))


def test_title_cloud_on_non_clear_only():
    assert "title_cloud" in _ids(parcel_flags({"title_flag": "title_issue"}, CFG, {}))
    assert "title_cloud" in _ids(parcel_flags({"title_flag": "survey_pending"}, CFG, {}))
    assert "title_cloud" not in _ids(parcel_flags({"title_flag": "clear"}, CFG, {}))
    assert "title_cloud" not in _ids(parcel_flags({"title_flag": None}, CFG, {}))


def test_price_rich_uses_county_shortlist_median():
    # County median (shortlist) = 4000; 1.25x = 5000.
    medians = {"Karnes": 4000}
    rich = {"county": "Karnes", "est_price_per_ac": 6000}
    fair = {"county": "Karnes", "est_price_per_ac": 4200}
    assert "price_rich" in _ids(parcel_flags(rich, CFG, medians))
    assert "price_rich" not in _ids(parcel_flags(fair, CFG, medians))


def test_county_price_medians_uses_shortlist_only():
    parcels = [
        {"county": "Karnes", "pipeline_status": "LOI", "est_price_per_ac": 3000},
        {"county": "Karnes", "pipeline_status": "Outreach", "est_price_per_ac": 5000},
        {"county": "Karnes", "pipeline_status": None, "est_price_per_ac": 99},  # not shortlist
        {"county": "Karnes", "pipeline_status": None, "est_price_per_ac": None},
    ]
    medians = county_price_medians(parcels, CFG)
    assert medians["Karnes"] == 4000  # median of 3000, 5000 — ignores non-shortlist


def test_clean_parcel_has_no_flags():
    p = {
        "soil_lcc_class": "3", "floodplain_pct": 0.0, "nearest_sub_kv": 345.0,
        "dist_transmission_mi": 0.0, "compactness": 0.8, "title_flag": "clear",
    }
    assert parcel_flags(p, CFG, {}) == []
