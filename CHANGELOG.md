# Changelog

## v1.0.0 — 2026-08-24

First tagged release. The tool has been live at
[sites.consultruss.com](https://sites.consultruss.com) since 2026-06-07 and in use since; this
tag marks the point where the repository documents it accurately and both of its evals are
published.

### What it is

A multi-criteria land screen and site-control tracker for South Texas — the two halves of
early-stage energy land development in one clickable map. Every rural parcel of 50 acres or
more in the study area is scored on a transparent weighted overlay led by interconnection
proximity, then ranked; a shortlist is tracked from *identified* through *title cleared*.

### Data coverage

**5,130 parcels** across **Wilson (2,538)** and **Karnes (2,592)** counties in the Eagle Ford,
southeast of San Antonio. **24** carried through the site-control pipeline.

Real and sourced, every layer cited with a retrieval date in [`data/SOURCES.md`](data/SOURCES.md):
parcels from TxGIO StratMap · transmission and substations from HIFLD · floodplain from FEMA
NFHL · terrain and land cover from USGS 3DEP / NLCD · soils and farmland class from USDA-NRCS
SSURGO · wetlands and protected land from USFWS NWI and USGS PAD-US · wells and pipelines from
the Texas Railroad Commission · generation and interconnection context from the ERCOT GIS
Report and EIA · imagery from USDA NAIP.

**Synthetic, and labeled as such throughout the app:** owner names, the deal pipeline and its
statuses, title flags, and per-acre prices (calibrated against observed MLS ranges, not drawn
from MLS/IDX data, which is not used). No restricted ERCOT network-model data is displayed
raw — it is abstracted to a 0–100 Grid Connectivity Index; the public overlay is HIFLD.

### What ships

- **Screen** — weighted suitability model, fully specified in `config.yaml`, with the full
  per-criterion breakdown on every parcel.
- **Track** — site-control pipeline: status funnel, acreage and cost by stage, budget burn,
  title and survey flags, each row linked to its parcel.
- **Ask the map** — plain-English question to a validated filter, via a Cloudflare Worker with
  a deterministic rule-based parser behind a pinned LLM.
- **Two lenses** — flexible/large-load siting and whole-site dual use (agrivoltaics).
- **Verdicts** — an authored pursue / pursue-if / pass call on every shortlist parcel,
  including a documented pass on the parcel the model itself ranked third.
- **Deal sheet** — three exit structures side by side, with a time-to-power × exit sensitivity
  grid shown both at success and risk-adjusted, plus budget versus actual.
- **Portfolio** — stepped option-budget allocation across $500K / $1M / $1.5M.
- **Power and timeline** — per-parcel speed-to-power with an honest uncertainty band and a
  co-location fast path near existing generation.
- **Data integrity** — per-layer provenance, license, completeness, and anomalies.
- **Executive memo** — a per-parcel investment memo, print-to-PDF from the browser.

### Evals

Both run in CI on every push, alongside `ruff` and a pinned full-history `gitleaks` scan.

- **Scoring model** — 95 tests across 10 modules. `tests/test_scoring.py` is a mini-eval: 7
  tests, 24 assertions checking that normalization anchors hit and clamp at their endpoints,
  that a parcel wholly inside a flood zone scores 0 on hazard, that a criterion with no data
  scores a neutral 50 rather than a false 100, that prime farmland is penalized rather than
  rewarded, and that ranking is deterministic. It does not validate the weights themselves,
  which are illustrative and tunable by design.
- **Natural-language layer** — 54 labelled cases, new in this release. Deterministic parser
  baseline: 75.9% exact match (41/54), 71.4% correct refusals on out-of-scope and inexpressible
  questions, 3/3 prompt-injection attempts resisted, no drift between the Worker's parser and
  the browser's offline copy. All 13 failures are published in
  [`worker/README.md`](worker/README.md) rather than fixed, so the numbers describe the version
  that has been running.

**Known gap:** the LLM path is not measured yet. The offline replay mechanism ships and CI runs
it, but the fixtures are empty until a live recording run — so the fallback rate, the number
that would turn "a deterministic parser stands behind a pinned model" from a design claim into
evidence, is still unknown.

### Also in this release

- The README's description of how this was built now matches the live Methodology page: the
  analytical model — criteria, weights, exclusions — is authored; the implementation was an
  AI-assisted build. An earlier, stronger claim about hands-on GIS tooling was retracted on
  2026-06-07 and corrected on the site; it had never been corrected here.
- The Quickstart now works on a clean machine. It previously led with a command that required
  the geospatial stack with no install step in front of it.
- Internal milestone labels and build shorthand removed from public-facing files.
