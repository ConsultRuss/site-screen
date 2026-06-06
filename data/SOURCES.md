# Data Sources

Every layer used by the screen is **public, free, and citable**. Retrieval dates
are filled in when the pipeline (`fetch`) caches each layer during a run; the
placeholders below mark layers not yet pulled in this checkout.

**Coordinate systems.** Data is stored/served in **EPSG:4326 (WGS84)** for the
web app; all area/distance math is done in a Texas-appropriate projected CRS
(**EPSG:3083 — NAD83 Texas Centric Albers Equal Area**) for accuracy.

**License note.** All layers below are public-domain or open. **MLS/IDX listing
data is deliberately excluded** (license-restricted, not republishable).

| Layer | Source | Endpoint | Format | Use in model | License | Retrieved |
|---|---|---|---|---|---|---|
| Parcels (by county) | TxGIO (formerly TNRIS) StratMap Land Parcels | `data.tnris.org`; `tnris.org/stratmap/land-parcels.html` | Shapefile / GeoJSON | Base geometry, acreage, ownership (→ replaced with synthetic) | Public | _pending_ |
| County CAD (richer attrs) | Wilson CAD, Karnes CAD | county appraisal district GIS / open records | Shapefile | Land-use codes, acreage validation | Public | _pending_ |
| Transmission lines | HIFLD (DHS) Electric Power Transmission Lines | `catalog.data.gov` (HIFLD) | GeoJSON / Shapefile | Distance-to-line, voltage class | Public domain | _pending_ |
| Substations | HIFLD Electric Substations | `catalog.data.gov` (HIFLD) | GeoJSON / Shapefile | Distance-to-substation, min kV | Public domain | _pending_ |
| Generator interconnection queue | ERCOT GIS Report (monthly) | `ercot.com/mp/data-products` (id pg7-200-er) | XLSX | Nearby queued generation (flex-load lens) — **abstracted, see below** | **Restricted** | _backend only_ |
| Large-load context | ERCOT Large Load Integration | `ercot.com/services/rq/large-load-integration` | PDF / data | Narrative context only | Public | _pending_ |
| Floodplain | FEMA National Flood Hazard Layer (NFHL) | FEMA Map Service Center / NFHL | Shapefile / WMS | Exclusion (% parcel in SFHA) | Public domain | _pending_ |
| Terrain / slope | USGS 3DEP DEM (10 m; 1 m where available) | The National Map (`apps.nationalmap.gov`) | GeoTIFF | Mean slope per parcel | Public domain | _pending_ |
| Land cover | USGS NLCD / USDA Cropland Data Layer (CDL) | MRLC / USDA NASS | GeoTIFF | Current-use scoring | Public domain | _pending_ |
| Wetlands | USFWS National Wetlands Inventory (NWI) | `fws.gov/program/national-wetlands-inventory` | Shapefile | Exclusion | Public domain | _pending_ |
| Protected areas | USGS PAD-US | USGS | Shapefile | Exclusion | Public domain | _pending_ |
| Roads | TxDOT / Census TIGER | TxDOT Open Data / Census | Shapefile | Road-access proximity | Public domain | _pending_ |
| Aerial imagery | USDA NAIP (real, public) | The National Map / USDA | imagery / WMS | Basemap — **NAIP only, no AI-generated imagery** | Public domain | _pending_ |
| Existing generation | EIA-860 / EIA power plants | `eia.gov` | CSV / GeoJSON | Proximity-to-generation (flex-load lens) | Public domain | _pending_ |
| Soils / farmland class | USDA-NRCS SSURGO / Web Soil Survey (Land Capability Class) | `websoilsurvey.nrcs.usda.gov` / SDA / gSSURGO | Shapefile / GDB | Penalize prime farmland (LCC I–II), favor marginal (LCC III–IV) | Public domain | _pending_ |
| Oil/gas wells & pipelines | Texas Railroad Commission (RRC) GIS | `rrc.texas.gov/.../gis-viewer/` | Shapefile / GIS | Eagle Ford exclusion buffers (150 ft wellhead, 50 ft pipeline) | Public | _pending_ |

## Pipeline run status (M1 — 2026-06-06)

The `fetch` stage queries these endpoints server-side (by county FIPS or study-area bbox):

- **Parcels — LIVE.** TxGIO StratMap "most recent" — `feature.geographic.texas.gov/.../Parcels/stratmap_land_parcels_48_most_recent/MapServer/0` (public). **6,080 parcels ≥ 50 ac** across Wilson + Karnes.
- **Substations — LIVE.** HIFLD Electric Substations — `services5.arcgis.com/HDRa0B57OVrv2E1q/.../Electric_Substations` (189 in study area; `MAX_VOLT` ≥ 138 kV used).
- **Transmission — LIVE.** HIFLD via DOE NETL Energy Transition Atlas — `arcgis.netl.doe.gov/.../Energy_Transition_Atlas_493d6/FeatureServer/18` (321 lines; `voltage` ≥ 138 kV used).
- **Floodplain (FEMA NFHL) — PENDING.** Endpoint returned HTTP 500 on the last run; the hazard criterion scores neutral until it loads.
- **Terrain (DEM), land cover (NLCD), soils (NRCS), roads (TIGER), wells/pipelines (RRC) — PENDING.** Wired into the model; not populated this pass.

Live criteria (interconnection 35%, buildable acreage 20%, shape 5%) drive ~60% of the model. Pending criteria score a neutral 50 and are flagged in `screen_run.json` (`criteria_status`), so rankings are driven by what is actually measured. The flexible-load lens is provisional (live criteria only); the agrivoltaics lens is pending its land-cover + soils inputs.

## Restricted-data discipline

The **ERCOT GIS Report (`pg7-200-er`)** and the detailed ERCOT network model are
**license/NDA-restricted** and are **never displayed raw** in this public asset —
no raw bus locations, line ratings, or unmasked substation attributes. They are
used for **backend context only**; any capacity signal derived from them is
**abstracted** in the pipeline and surfaced only as a stylized **0–100 "Grid
Connectivity Index."** The public transmission/substation overlay on the map
comes from **HIFLD (public domain)**, not the ERCOT report. Any **named** grid
asset shown is independently confirmable in public sources (HIFLD, PUCT CCN
dockets, or utility project pages).

## Synthetic data

Per the project's ethics note (see README and the About view): geospatial and
infrastructure attributes are real and derived from the sources above; **owner
names and the entire deal pipeline (statuses, dates, prices, notes) are
synthetic**, generated for demonstration only.
