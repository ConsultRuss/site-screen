"""Contract for the option-budget portfolio allocator (Feature A1.5).

Portfolio-level "the model ranks, I decide": objective economics rank the field,
the analyst authors the allocation. Spread option capital across pursue/pursue-if
parcels; stage diligence on the speed-to-power winners; passes excluded. Inherits
A3 deal_economics. Mirrors test_economics.py: tiny dict fixtures + hand-computed.
"""

from pipeline import portfolio as pf
from pipeline.config import load_config

CFG = load_config()
PF = CFG["deal_economics"]["portfolio"]


def test_portfolio_config_present_with_locked_values():
    assert PF["budgets_usd"] == [250000, 500000, 1000000]
    assert PF["exclude_verdicts"] == ["pass"]
    assert PF["stage_top_n"] == 3
    assert PF["priority"] == "risk_adjusted"


def _econ(pid, ra, rank, control, dilig=148000, mw=100, build=800):
    # minimal economics record with one in-window sensitivity cell carrying `ra`
    return {
        "parcel_id": pid, "county": "Karnes", "suitability_rank": rank,
        "control_cost": control, "diligence_total": dilig, "capital_deployed": control + dilig,
        "mw_est": mw, "acreage_buildable": build,
        "flip": {"sensitivity": [
            {"months": 36, "cells": [{"mult": 4, "irr": 1.0, "ra": ra, "clears": True}]},
            {"months": "miss", "cells": [{"mult": 4, "irr": -1.0, "ra": -1.0, "clears": False}]},
        ]},
    }

ECON = {
    "A": _econ("A", 0.60, 4, 200000), "B": _econ("B", 0.40, 1, 95000),
    "C": _econ("C", 0.50, 8, 150000), "D": _econ("D", 0.32, 3, 71000),  # D is a pass
}
VERD = {"A": "pursue", "B": "pursue", "C": "pursue_if", "D": "pass"}


def test_best_ra_is_max_in_window_cell():
    assert pf.best_ra(ECON["A"]) == 0.60


def test_eligible_excludes_passes():
    elig = pf.eligible_priority(ECON, VERD, CFG)
    assert [p[0] for p in elig] == ["A", "B", "C"]  # D (pass) excluded


def test_priority_pursue_tier_before_pursue_if_then_ra_desc():
    # pursue (A,B) before pursue_if (C); within pursue, A(ra .60) before B(ra .40)
    assert [p[0] for p in pf.eligible_priority(ECON, VERD, CFG)] == ["A", "B", "C"]
