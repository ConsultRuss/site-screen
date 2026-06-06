"""Mini-eval contract for the scoring engine (spec Feature #3).

Asserts the model behaves the way the methodology claims:
  * normalization anchors hit their endpoints,
  * a parcel fully inside a flood zone scores 0 on the hazard criterion,
  * categorical lookups resolve as configured,
  * ranking is deterministic and orders a clearly-better parcel first.
"""

import copy

from pipeline.config import load_config
from pipeline.scoring import (
    normalize,
    normalize_linear,
    rank_parcels,
    suitability_breakdown,
    suitability_score,
)

CFG = load_config()


def _parcel(**overrides):
    base = {
        "parcel_id": "WIL-000001",
        "dist_substation_mi": 1.0,
        "acreage_buildable": 640.0,
        "slope_pct_mean": 1.0,
        "floodplain_pct": 0.0,
        "landcover_class": "pasture_hay",
        "soil_lcc_class": "III",
        "dist_road_mi": 0.4,
        "compactness": 0.8,
    }
    base.update(overrides)
    return base


def test_normalize_linear_anchors_descending():
    spec = CFG["model"]["normalization"]["interconnection"]
    assert normalize(1.0, spec) == 100.0  # at/under full-score anchor
    assert normalize(10.0, spec) == 0.0  # at/over zero-score anchor
    assert normalize(0.5, spec) == 100.0  # clamped above 100
    assert normalize(20.0, spec) == 0.0  # clamped below 0


def test_normalize_linear_ascending_acreage():
    spec = CFG["model"]["normalization"]["buildable_acreage"]
    assert normalize(50.0, spec) == 0.0  # at the floor
    assert normalize(640.0, spec) == 100.0  # at the cap
    # midpoint between 50 and 640 is 345 -> ~50
    assert abs(normalize_linear(345.0, 640.0, 50.0) - 50.0) < 1e-6


def test_sfha_parcel_scores_zero_on_hazard():
    # 100% inside the floodplain -> 0% hazard-free -> hazard criterion == 0.
    flooded = suitability_breakdown(_parcel(floodplain_pct=100.0), CFG)
    assert flooded["hazard_free"] == 0.0
    dry = suitability_breakdown(_parcel(floodplain_pct=0.0), CFG)
    assert dry["hazard_free"] == 100.0


def test_landcover_and_soil_lookups():
    norm = CFG["model"]["normalization"]
    assert normalize("pasture_hay", norm["landcover"]) == 90.0
    assert normalize("water", norm["landcover"]) == 0.0
    assert normalize("nonsense", norm["landcover"]) == 50.0  # default
    assert normalize("3", norm["soils_lcc"]) == 90.0  # NRCS class 3 — marginal, favored
    assert normalize("1", norm["soils_lcc"]) == 30.0  # class 1 — prime farmland, penalized


def test_ideal_parcel_scores_near_top():
    score = suitability_score(_parcel(), CFG)
    assert score > 90.0


def test_pending_criteria_score_neutral():
    # Criteria with no data yet (None) must score a neutral 50 — not 0 or a falsely
    # perfect 100 — so the weighted total stays well-defined while live criteria drive it.
    p = {
        "parcel_id": "X", "dist_substation_mi": 1.0, "acreage_buildable": 640.0,
        "compactness": 0.8, "slope_pct_mean": None, "dist_road_mi": None,
        "landcover_class": None, "soil_lcc_class": None, "floodplain_pct": None,
    }
    b = suitability_breakdown(p, CFG)
    assert b["terrain"] == 50.0
    assert b["road_access"] == 50.0
    assert b["hazard_free"] == 50.0  # no flood layer -> neutral, not 100
    assert b["interconnection"] == 100.0  # live criterion still real
    assert b["buildable_acreage"] == 100.0


def test_ranking_is_deterministic_and_orders_by_quality():
    good = _parcel(parcel_id="WIL-GOOD")  # close sub, big, flat, dry
    poor = _parcel(
        parcel_id="WIL-POOR",
        dist_substation_mi=9.0,
        acreage_buildable=60.0,
        slope_pct_mean=4.5,
        floodplain_pct=60.0,
        landcover_class="forest",
        soil_lcc_class="I",
        dist_road_mi=4.0,
        compactness=0.2,
    )
    parcels = [poor, good]
    ranked = rank_parcels(parcels, CFG)
    assert ranked[0]["parcel_id"] == "WIL-GOOD"
    assert ranked[0]["suitability_rank"] == 1
    assert ranked[1]["suitability_rank"] == 2

    # Re-running on a fresh copy yields the identical ordering.
    again = rank_parcels(copy.deepcopy(parcels), CFG)
    assert [p["parcel_id"] for p in again] == [p["parcel_id"] for p in ranked]
