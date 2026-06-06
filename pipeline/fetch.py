"""Stage 1 - fetch: download + cache the public source layers.

Implemented in M1. Requires the geospatial stack (see pipeline/requirements-geo.txt)
and network access. Pulls the layers listed in data/SOURCES.md for the study-area
counties and caches them under data/raw/ (git-ignored).
"""

from __future__ import annotations

from typing import Any


class StageNotImplemented(RuntimeError):
    """Raised by M1 stages that are not wired up yet."""


def run(cfg: dict[str, Any]) -> None:
    raise StageNotImplemented(
        "fetch lands in M1 (needs the geospatial stack + network). "
        "See data/SOURCES.md for the layers and pipeline/requirements-geo.txt for deps."
    )
