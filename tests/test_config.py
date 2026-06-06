"""The model must be well-formed: every weighted block sums to 1.0."""

import pytest

from pipeline.config import load_config, validate_config


def test_default_config_loads_and_validates():
    cfg = load_config()  # repo-root config.yaml
    assert cfg["study_area"]["parcel_min_acres"] == 50
    assert cfg["model"]["weights"]["interconnection"] == 0.35


def test_all_weighted_blocks_sum_to_one():
    cfg = load_config()
    for block in ("model", "flex_load_lens", "agrivoltaic_lens"):
        assert abs(sum(cfg[block]["weights"].values()) - 1.0) < 1e-9, block


def test_validate_rejects_bad_weights():
    bad = {
        "model": {"weights": {"a": 0.5, "b": 0.4}},
        "flex_load_lens": {"weights": {"x": 1.0}},
        "agrivoltaic_lens": {"weights": {"y": 1.0}},
    }
    with pytest.raises(ValueError):
        validate_config(bad)
