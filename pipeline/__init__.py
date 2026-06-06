"""South Texas site-screen scoring pipeline.

Stages:
    fetch  -> download + cache the public source layers (M1; needs the geo stack)
    build  -> clip, exclude, and compute per-parcel metrics (M1; needs the geo stack)
    score  -> turn metrics into a 0-100 weighted suitability score and rank
    export -> write the web GeoJSON + run metadata

The math that converts metrics into scores (``scoring``) and the geometric
helpers (``geometry``) are pure-Python and fully unit-tested without any
geospatial dependencies. The fetch/build stages are land in M1.
"""

__version__ = "0.1.0"
