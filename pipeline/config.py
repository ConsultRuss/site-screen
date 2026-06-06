"""Load and validate the suitability model configuration (``config.yaml``)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = REPO_ROOT / "config.yaml"

# Each of these blocks carries a ``weights`` map that must sum to 1.0.
_WEIGHTED_BLOCKS = ("model", "flex_load_lens", "agrivoltaic_lens")


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """Read ``config.yaml`` and validate it. Raises ``ValueError`` on a bad model."""
    cfg_path = Path(path) if path else DEFAULT_CONFIG
    with open(cfg_path, encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    validate_config(cfg)
    return cfg


def validate_config(cfg: dict[str, Any]) -> None:
    """Fail loudly if any weighted block does not sum to 1.0 (within tolerance)."""
    for block in _WEIGHTED_BLOCKS:
        if block not in cfg or "weights" not in cfg[block]:
            raise ValueError(f"config: missing '{block}.weights'")
        total = sum(cfg[block]["weights"].values())
        if abs(total - 1.0) > 1e-6:
            raise ValueError(
                f"config: {block}.weights sum to {total:.6f}, expected 1.0"
            )
