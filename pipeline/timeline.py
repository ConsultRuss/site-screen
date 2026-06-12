"""Speed-to-power / energization-timeline engine (Feature A4) — pure-Python.

A disclosed phase model gated on the ERCOT interconnection queue. Critical path =
interconnection (long pole, modulated per-parcel by live grid quality) +
construction tail; diligence/permitting run parallel and are excluded. Mirrors
economics.py: pure functions over a parcel dict + cfg. The license-restricted
ERCOT GIS Report is never a display source. All figures illustrative; the
interconnection duration is directional/UNCERTAIN and always shown with a band.
"""

from __future__ import annotations

from typing import Any  # noqa: F401  (used by the functions added in the next task)
