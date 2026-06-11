"""Contract for parcel de-duplication (data-integrity fix).

The TxGIO StratMap statewide parcel layer stacks multiple records on the same
physical parcel (same footprint, different prop_id / owner / boundary digitization).
Left in, they pollute the top of the suitability ranking with identical entries.
``dedupe_by_footprint`` collapses records that occupy the same footprint
(identical centroid + area) to one, while never collapsing genuinely distinct
parcels — including the many real parcels that share a placeholder prop_id of "0".
"""

from pipeline.dedupe import dedupe_by_footprint


def _feat(lat, lon, area, **props):
    """A minimal GeoJSON-ish feature carrying the footprint properties build computes."""
    p = {"centroid_lat": lat, "centroid_lon": lon, "acreage_total": area}
    p.update(props)
    return {"type": "Feature", "properties": p, "geometry": {"type": "Polygon", "coordinates": []}}


def test_collapses_features_sharing_a_footprint():
    # Three records on the same footprint (the reported "97-score parcel ×3"):
    # different prop_id and owner, identical centroid + area -> one survivor.
    feats = [
        _feat(28.74398, -98.01401, 910.9, prop_id="111", owner="A"),
        _feat(28.74398, -98.01401, 910.9, prop_id="222", owner="B"),
        _feat(28.74398, -98.01401, 910.9, prop_id="333", owner="C"),
    ]
    out = dedupe_by_footprint(feats)
    assert len(out) == 1


def test_preserves_distinct_footprints():
    feats = [
        _feat(28.70000, -98.00000, 100.0, prop_id="1"),
        _feat(28.80000, -98.10000, 200.0, prop_id="2"),  # different centroid
        _feat(28.70000, -98.00000, 150.0, prop_id="3"),  # same centroid, different area
    ]
    out = dedupe_by_footprint(feats)
    assert len(out) == 3


def test_does_not_collapse_distinct_parcels_sharing_placeholder_id():
    # The trap: many real parcels carry prop_id "0". They are distinct footprints
    # and must all survive — the key is footprint, never the id.
    feats = [
        _feat(28.10, -98.10, 60.0, prop_id="0", owner="X"),
        _feat(28.20, -98.20, 70.0, prop_id="0", owner="Y"),
        _feat(28.30, -98.30, 80.0, prop_id="0", owner="Z"),
    ]
    out = dedupe_by_footprint(feats)
    assert len(out) == 3


def test_keeps_first_occurrence_deterministically():
    feats = [
        _feat(28.5, -98.5, 500.0, prop_id="keep", owner="first"),
        _feat(28.5, -98.5, 500.0, prop_id="drop", owner="second"),
    ]
    out = dedupe_by_footprint(feats)
    assert len(out) == 1
    assert out[0]["properties"]["prop_id"] == "keep"


def test_returns_same_order_for_survivors():
    feats = [
        _feat(28.1, -98.1, 100.0, prop_id="a"),
        _feat(28.2, -98.2, 100.0, prop_id="b"),
        _feat(28.1, -98.1, 100.0, prop_id="a-dup"),  # dup of a
        _feat(28.3, -98.3, 100.0, prop_id="c"),
    ]
    out = dedupe_by_footprint(feats)
    assert [f["properties"]["prop_id"] for f in out] == ["a", "b", "c"]
