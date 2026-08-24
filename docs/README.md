# Developer guide

## Layout

```
site-screen/
  README.md            project overview + framing
  config.yaml          the whole suitability model (weights, anchors, exclusions, lenses)
  pipeline/            Python scoring pipeline (fetch/build/score/export) + geo deps
  web/                 static Cloudflare Pages app (Leaflet + Chart.js) + data/parcels.geojson
  worker/              Cloudflare Worker for "Ask the map" (NL -> validated filter)
  worker/evals/        labelled eval for the NL layer (54 cases, offline runner)
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

`fetch`, `build`, `rebuild`, and the full `run` need the geospatial stack (GeoPandas, Rasterio, Shapely, pyproj), pinned separately because those wheels are
large and platform-sensitive:

```bash
python -m venv .venv && . .venv/Scripts/activate   # (Windows) or .venv/bin/activate
pip install -e ".[dev]"
pip install -r pipeline/requirements-geo.txt        # heavy; only for rebuilding from source data
```

## Tests / eval

```bash
pip install -e ".[dev]"
pytest -q          # unit tests + the mini-eval contract
ruff check .       # lint
```

95 tests across 10 modules. The **mini-eval** (`tests/test_scoring.py`) — 7 tests,
24 assertions — asserts the model behaves as the methodology claims: normalization
anchors hit their endpoints, a parcel fully in a flood zone scores 0 on the hazard
criterion, a criterion with no data scores a neutral 50 rather than a perfect 100,
lookups resolve as configured, and ranking is deterministic. CI runs it on every push.

The natural-language layer has its own eval — see **Worker** below.

## Worker

See [`../worker/README.md`](../worker/README.md) for the contract, the guardrails, and the
measured eval results.

Its eval is a separate suite from the Python one and runs in its own CI job:

```bash
node worker/evals/run.mjs            # offline: rule parser over 54 labelled cases
node worker/evals/run.mjs --failures # ...plus every failing case in full
node worker/evals/run.mjs --ci       # exit 1 below the floors in evals/thresholds.json
```

The live-model run costs money and is manual:
`OPENROUTER_API_KEY=... node worker/evals/run.mjs --live --record`.
Definitions and coverage gaps: [`../worker/evals/README.md`](../worker/evals/README.md).
