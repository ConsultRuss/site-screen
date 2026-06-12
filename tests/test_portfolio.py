"""Contract for the option-budget portfolio allocator (Feature A1.5).

Portfolio-level "the model ranks, I decide": objective economics rank the field,
the analyst authors the allocation. Spread option capital across pursue/pursue-if
parcels; stage diligence on the speed-to-power winners; passes excluded. Inherits
A3 deal_economics. Mirrors test_economics.py: tiny dict fixtures + hand-computed.
"""

from pipeline.config import load_config

CFG = load_config()
PF = CFG["deal_economics"]["portfolio"]


def test_portfolio_config_present_with_locked_values():
    assert PF["budgets_usd"] == [250000, 500000, 1000000]
    assert PF["exclude_verdicts"] == ["pass"]
    assert PF["stage_top_n"] == 3
    assert PF["priority"] == "risk_adjusted"
