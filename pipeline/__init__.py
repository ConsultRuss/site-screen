"""South Texas site-screen scoring pipeline.

Stages:
    fetch  -> download + cache the public source layers (needs the geo stack)
    build  -> clip, exclude, and compute per-parcel metrics (needs the geo stack)
    score  -> turn metrics into a 0-100 weighted suitability score and rank
    export -> write the web GeoJSON + run metadata

The math that converts metrics into scores (``scoring``) and the geometric
helpers (``geometry``) are pure-Python and fully unit-tested without any
geospatial dependencies. Only the fetch/build stages require the heavier
geospatial stack in ``requirements-geo.txt``.
"""

__version__ = "0.1.0"
