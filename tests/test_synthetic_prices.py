"""Contract for synthetic land prices (calibrated, disclosed-synthetic).

Prices are invented for the demo, but their magnitude and spread are calibrated
to recent local vacant-land sales (Karnes/Wilson, >50 ac, last 24 mo, houses
excluded) so the tracker reads like a real deal book: small tracts price higher
per acre, large tracts carry the size discount, Wilson runs above Karnes, and
there is genuine spread (so the price-rich flag is meaningful, not dead).
"""

from pipeline.synthetic import _price_per_ac


def test_deterministic():
    assert _price_per_ac("KAR-000007", "Karnes", 600) == _price_per_ac("KAR-000007", "Karnes", 600)


def test_small_karnes_tract_is_realistic():
    # ~300 ac Karnes tract — well above the old flat $3,200-4,500, below small-tract comps.
    p = _price_per_ac("KAR-000019", "Karnes", 317)
    assert 4000 <= p <= 8000


def test_large_tract_discount():
    # Same id isolates the size effect from per-parcel variation.
    small = _price_per_ac("X-1", "Karnes", 300)
    large = _price_per_ac("X-1", "Karnes", 1900)
    assert large < small


def test_wilson_premium_over_karnes():
    k = _price_per_ac("Z-1", "Karnes", 800)
    w = _price_per_ac("Z-1", "Wilson", 800)
    assert w > k


def test_floor_respected_on_huge_tract():
    assert _price_per_ac("Y-1", "Karnes", 6000) >= 2600


def test_real_spread_across_parcels():
    prices = {_price_per_ac(f"KAR-{i:06d}", "Karnes", 600) for i in range(1, 25)}
    assert max(prices) - min(prices) >= 1200  # not a tight cluster like the old model


def test_rounded_to_50():
    assert _price_per_ac("KAR-000003", "Karnes", 623) % 50 == 0
