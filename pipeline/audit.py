"""Data-integrity / audit engine (Feature A4) — pure-Python.

Computes the audit panel's content from the run artifacts (fetch_status.json,
screen_run.json, the parcels GeoJSON) joined with config.data_integrity. The
license-restricted ERCOT GIS Report is surfaced as a GOVERNANCE signal, never
displayed raw. Mirrors portfolio.py: read artifacts -> build -> write.
"""

from __future__ import annotations

from typing import Any  # noqa: F401  (used by the functions added in the next task)
