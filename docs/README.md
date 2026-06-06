# Developer guide

## Layout

```
site-screen/
  README.md            project overview + framing
  config.yaml          the whole suitability model (weights, anchors, exclusions, lenses)
  pipeline/            Python scoring pipeline (fetch/build/score/export) + geo deps
  web/                 static Cloudflare Pages app (Leaflet + Chart.js) + data/parcels.geojson
  worker/              Cloudflare Worker for "Ask the map" (NL -> validated filter)
  data/SOURCES.md      every public layer, with endpoint, license, retrieval date
  tests/               mini-eval + unit tests (pure-Python, no geo deps)
```

## Run the web app

```bash
cd web && python -m http.server 8000   # open http://localhost:8000
```

The app reads `web/data/parcels.geojson` directly — no backend needed.

## Pipeline

```bash
python -m pipeline score  --input web/data/parcels.geojson   # (re)score + rank in place
python -m pipeline export --output data/screen_run.json      # write run metadata
python -m pipeline --help                                    # all commands
```

`fetch`, `build`, and the full `run` need the geospatial stack and land in M1:

```bash
python -m venv .venv && . .venv/Scripts/activate   # (Windows) or .venv/bin/activate
pip install -e ".[dev]"
pip install -r pipeline/requirements-geo.txt        # verify pins first (supply-chain policy)
```

## Tests / eval

```bash
pip install -e ".[dev]"
pytest -q          # unit tests + the mini-eval contract
ruff check .       # lint
```

The **mini-eval** (`tests/test_scoring.py`) asserts the model behaves as the
methodology claims: normalization anchors hit their endpoints, a parcel fully in
a flood zone scores 0 on the hazard criterion, lookups resolve as configured, and
ranking is deterministic. CI runs it on every push.

## Worker

See [`../worker/README.md`](../worker/README.md).
