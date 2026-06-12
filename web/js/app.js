/* South Texas Site Screen — front-end.
 * Loads the scored GeoJSON and drives three views: Map, Pipeline, About.
 * The "Ask the map" box uses a built-in rule-based parser; the LLM-assisted
 * version (Cloudflare Worker) is a later milestone and degrades to these rules. */
(() => {
  "use strict";

  const DATA_URL = "data/parcels.geojson?v=a6";
  // Ask-the-map Worker endpoint (deployed on the consultruss.com zone).
  // Empty string = built-in rule parser only (works fully offline).
  const WORKER_URL = "https://ask.consultruss.com";
  const METRIC_LABELS = {
    suitability_score: "Suitability",
    flex_load_score: "Flexible-load",
    agrivoltaic_score: "Agrivoltaics",
  };
  const LAND_LABELS = {
    pasture_hay: "Pasture / hay", grassland_pasture: "Grassland", shrubland: "Shrub / scrub",
    cultivated_crops: "Cropland", forest: "Forest", developed: "Developed",
    developed_open: "Developed (open)", water: "Water", wetlands: "Wetlands", default: "Other",
  };
  const landLabel = (c) => (c ? LAND_LABELS[c] || c : null);
  const VERDICT_LABEL = { pursue: "Pursue", pursue_if: "Pursue-if", pass: "Pass" };
  const VERDICT_ORDER = { pursue: 0, pursue_if: 1, pass: 2 };
  const FLAG_LABEL = {
    prime_soil: "Prime soil", floodplain: "Floodplain >10%", weak_interconnect: "Weak interconnect",
    poor_shape: "Poor shape", title_cloud: "Title cloud", price_rich: "Price-rich",
  };
  const FLAG_DESC = {
    prime_soil: "Prime farmland (NRCS land-capability class 1–2) — siting and community-relations risk",
    floodplain: "More than 10% of the parcel in mapped floodplain",
    weak_interconnect: "Below 138 kV, or off the 345 kV backbone and far from transmission",
    poor_shape: "Low compactness — harder to lay out an array",
    title_cloud: "A non-clear title flag",
    price_rich: "Priced well above the county shortlist norm",
  };
  const BUCKETS = [
    { min: 80, color: "#3f6b3a", label: "80–100" },
    { min: 60, color: "#7f9b4e", label: "60–79" },
    { min: 40, color: "#c8a87c", label: "40–59" },
    { min: 20, color: "#bf7a3a", label: "20–39" },
    { min: 0, color: "#9e3b2c", label: "0–19" },
  ];
  const STATUS_ORDER = [
    "Identified", "Screened", "Outreach", "LOI", "Option/Lease Negotiation",
    "Under Option", "Site Control Secured", "Title/Survey Clearing", "Cleared",
  ];

  let MAP, GEO_LAYER, FEATURES = [];
  const LAYERS = new Map(); // parcel_id -> leaflet layer
  const VERDICTS = new Map(); // parcel_id -> authored verdict entry
  let MEMO = null; // the verdict entry carrying the featured pass memo
  let charts = {};

  // Deal sheet (A3): development-margin economics + authored deal notes.
  let ECON = null, NOTES = null;
  let PORT = null; // Portfolio (A1.5): option-budget allocations over the shortlist.
  const PROPS = new Map(); // parcel_id -> geojson properties (pipeline status/date/rank)

  const state = {
    metric: "suitability_score",
    county: "", minAcres: 0, maxDist: 15, minKv: 0, noFlood: false,
  };

  const $ = (sel) => document.querySelector(sel);
  const colorFor = (v) => (BUCKETS.find((b) => v >= b.min) || BUCKETS[BUCKETS.length - 1]).color;

  /* ---------------- bootstrap ---------------- */
  async function init() {
    wireTabs();
    wireControls();
    initMap();
    try {
      const res = await fetch(DATA_URL);
      const data = await res.json();
      FEATURES = data.features || [];
    } catch (err) {
      $("#ask-status").textContent = "Could not load parcel data: " + err;
      return;
    }
    FEATURES.forEach((f) => PROPS.set(f.properties.parcel_id, f.properties));
    try {
      const vr = await fetch("data/verdicts.json?v=a6");
      const vd = await vr.json();
      (vd.verdicts || []).forEach((v) => { VERDICTS.set(v.parcel_id, v); if (v.memo) MEMO = v; });
    } catch { /* verdicts are optional — flags still render without them */ }
    try {
      const [er, nr] = await Promise.all([
        fetch("data/economics.json?v=a6"),
        fetch("data/deal-notes.json?v=a6"),
      ]);
      ECON = await er.json();
      NOTES = await nr.json();
      PORT = await (await fetch("data/portfolio.json?v=a6")).json();
      buildDealSheet();
      buildPortfolio();
    } catch (err) {
      // Deal data is optional — degrade gracefully, never break the rest of the site.
      const body = $("#deal-body");
      if (body) body.innerHTML = `<p class="hint">Deal data unavailable right now (${esc(String(err))}).</p>`;
    }
    drawParcels();
    applyFilters(true);
    buildTracker();
    buildCharts();
    buildKpis();
    mountMemo();
  }

  /* ---------------- tabs ---------------- */
  function wireTabs() {
    document.querySelectorAll(".tab").forEach((t) =>
      t.addEventListener("click", () => activateView(t.dataset.view)));
  }
  function activateView(view) {
    document.querySelectorAll(".tab").forEach((t) =>
      t.classList.toggle("is-active", t.dataset.view === view));
    document.querySelectorAll(".view").forEach((v) =>
      v.classList.toggle("is-active", v.id === "view-" + view));
    if (view === "map" && MAP) setTimeout(() => MAP.invalidateSize(), 50);
  }

  /* ---------------- map ---------------- */
  function initMap() {
    // preferCanvas: render thousands of parcels efficiently.
    MAP = L.map("map", { preferCanvas: true }).setView([29.0, -98.0], 9);
    const street = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19, attribution: "&copy; OpenStreetMap contributors",
    }).addTo(MAP);
    const aerial = L.tileLayer(
      "https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
      { maxZoom: 19, attribution: "Imagery &copy; Esri, USDA NAIP" }
    );
    L.control.layers({ Street: street, "Aerial (NAIP)": aerial }, null, { position: "topright" }).addTo(MAP);
  }

  const HIDDEN = { opacity: 0, fillOpacity: 0 };
  function visibleStyle(p) {
    const v = p[state.metric];
    const fill = (v === null || v === undefined) ? "#7a756e" : colorFor(v); // grey = no data
    return { fillColor: fill, color: "#2b2b26", weight: 0.6, opacity: 0.5, fillOpacity: 0.72 };
  }

  const pend = "<span class='pp-pend'>pending</span>";
  const na = (v, suf = "") => (v === null || v === undefined ? pend : v + suf);
  function scoreBar(v) {
    const c = v == null ? "#7a756e" : colorFor(v);
    return `<div class="pp-bar"><span style="width:${v || 0}%;background:${c}"></span></div>`;
  }
  function flagChips(p) {
    const flags = p.flags || [];
    if (!flags.length) return "";
    const chips = flags.map((f) =>
      `<span class="flag-chip ${f.class}" title="${FLAG_DESC[f.id] || ""}">${FLAG_LABEL[f.id] || f.id}</span>`
    ).join("");
    return `<div class="pp-flags flags-row">${chips}</div>`;
  }
  function verdictAndFlags(p) {
    const v = VERDICTS.get(p.parcel_id);
    let html = "";
    if (v) {
      html += `<div class="pp-verdictwrap"><span class="verdict ${v.verdict}">${VERDICT_LABEL[v.verdict]}</span></div>`;
      if (v.rationale) html += `<div class="pp-verdict-rationale">${v.rationale}</div>`;
      if (v.memo) html += `<span class="pp-memo-link" onclick="openMemo()">Read the full memo →</span>`;
    }
    return html + flagChips(p);
  }
  function popupHtml(p) {
    const row = (k, val) => `<dt>${k}</dt><dd>${val}</dd>`;
    let html = `<div class="pp-title">${p.parcel_id} · ${p.county} Co.</div>`;
    html += `<div class="pp-scorewrap"><span class="pp-score">Suitability ${p.suitability_score}</span>`;
    html += `<span class="pp-rank">#${p.suitability_rank} of ${FEATURES.length.toLocaleString()}</span></div>`;
    html += scoreBar(p.suitability_score);
    html += verdictAndFlags(p);
    html += `<dl class="pp-grid">`;
    html += row("Buildable", `${p.acreage_buildable} ac <span class="pp-dim">of ${p.acreage_total}</span>`);
    html += row("Substation", na(p.dist_substation_mi, " mi") + (p.nearest_sub_kv ? ` · ${p.nearest_sub_kv} kV` : ""));
    html += row("≥138 kV line", na(p.dist_transmission_mi, " mi"));
    html += row("Slope", na(p.slope_pct_mean, "%"));
    html += row("Land cover", na(landLabel(p.landcover_class)));
    html += row("Soil class", p.soil_lcc_class ? "LCC " + p.soil_lcc_class : pend);
    html += row("Floodplain", p.floodplain_pct == null ? pend : p.floodplain_pct + "%");
    html += row("Road · gen", na(p.dist_road_mi, " mi") + " · " + na(p.dist_generation_mi, " mi"));
    html += row("Flex · agri", na(p.flex_load_score) + " · " + na(p.agrivoltaic_score));
    if (p.pipeline_status) {
      html += row("Pipeline", p.pipeline_status);
      html += row("Title", `<span class="pill ${p.title_flag}">${p.title_flag}</span>`);
      html += row("Est. $/ac", p.est_price_per_ac ? "$" + p.est_price_per_ac.toLocaleString() : "—");
    }
    html += `</dl>`;
    if (p.pipeline_status) {
      html += `<div class="pp-deal-link" onclick="openDeal('${p.parcel_id}')">Deal sheet →</div>`;
    }
    html += `<div class="pp-synthetic">Owner “${p.owner}” &amp; any pipeline data are synthetic.</div>`;
    return html;
  }

  function drawParcels() {
    LAYERS.clear();
    GEO_LAYER = L.geoJSON({ type: "FeatureCollection", features: FEATURES }, {
      style: (f) => visibleStyle(f.properties),
      onEachFeature: (feature, layer) => {
        LAYERS.set(feature.properties.parcel_id, layer);
        layer.bindPopup(() => popupHtml(layer.feature.properties), { maxWidth: 300 });
      },
    }).addTo(MAP);
  }

  function passesFilters(p) {
    if (state.county && p.county !== state.county) return false;
    if (p.acreage_buildable < state.minAcres) return false;
    if (p.dist_substation_mi > state.maxDist) return false;
    if (state.minKv && (p.nearest_sub_kv || 0) < state.minKv) return false;
    if (state.noFlood && (p.floodplain_pct || 0) > 10) return false;
    return true;
  }

  function applyFilters(fit) {
    let shown = 0;
    const bounds = [];
    LAYERS.forEach((layer) => {
      const p = layer.feature.properties;
      if (passesFilters(p)) {
        layer.setStyle(visibleStyle(p));
        if (fit) bounds.push(layer.getBounds());
        shown++;
      } else {
        layer.setStyle(HIDDEN);
      }
    });
    $("#count").textContent = shown.toLocaleString();
    updateLegend();
    if (fit && bounds.length) {
      const all = bounds.reduce((acc, b) => acc.extend(b), L.latLngBounds(bounds[0]));
      MAP.fitBounds(all.pad(0.08));
    }
  }

  function updateLegend() {
    $("#legend-title").textContent = METRIC_LABELS[state.metric];
    const hasData = FEATURES.some((f) => f.properties[state.metric] != null);
    if (!hasData) {
      $("#legend").innerHTML =
        `<div class="row"><span class="swatch" style="background:#7a756e"></span>computed in a later pass</div>`;
      return;
    }
    $("#legend").innerHTML = BUCKETS.map(
      (b) => `<div class="row"><span class="swatch" style="background:${b.color}"></span>${b.label}</div>`
    ).join("");
  }

  /* ---------------- controls ---------------- */
  function wireControls() {
    $("#metric").addEventListener("change", (e) => { state.metric = e.target.value; applyFilters(false); });
    $("#f-county").addEventListener("change", (e) => { state.county = e.target.value; applyFilters(false); });
    $("#f-acres").addEventListener("input", (e) => {
      state.minAcres = +e.target.value; $("#f-acres-val").textContent = e.target.value; applyFilters(false);
    });
    $("#f-dist").addEventListener("input", (e) => {
      state.maxDist = +e.target.value; $("#f-dist-val").textContent = e.target.value; applyFilters(false);
    });
    $("#f-kv").addEventListener("change", (e) => { state.minKv = +e.target.value; applyFilters(false); });
    $("#f-noflood").addEventListener("change", (e) => { state.noFlood = e.target.checked; applyFilters(false); });
    $("#f-reset").addEventListener("click", resetFilters);
    $("#ask-go").addEventListener("click", () => askTheMap($("#ask").value));
    $("#ask").addEventListener("keydown", (e) => { if (e.key === "Enter") askTheMap($("#ask").value); });
  }

  function resetFilters() {
    Object.assign(state, { county: "", minAcres: 0, maxDist: 15, minKv: 0, noFlood: false });
    $("#f-county").value = ""; $("#f-acres").value = 0; $("#f-acres-val").textContent = "0";
    $("#f-dist").value = 15; $("#f-dist-val").textContent = "15"; $("#f-kv").value = "0";
    $("#f-noflood").checked = false; $("#ask").value = "";
    $("#ask-status").innerHTML = "Filters reset.";
    applyFilters(true);
  }

  /* "Ask the map": try the Worker (LLM, locked model) then fall back to the
   * built-in deterministic parser. Both paths emit the same filter-DSL shape. */
  function localRuleParse(text) {
    const t = text.toLowerCase();
    const f = {};
    let m;
    if ((m = t.match(/(\d{2,4})\s*\+?\s*(?:buildable\s*)?acre/))) f.minBuildableAcres = +m[1];
    if ((m = t.match(/(\d+(?:\.\d+)?)\s*(?:mi|mile)/))) f.maxDistSubstationMi = +m[1];
    if ((m = t.match(/(\d{2,3})\s*kv/))) {
      const kv = +m[1];
      f.minKv = kv >= 345 ? 345 : kv >= 138 ? 138 : 69;
    }
    if (/no floodplain|outside (?:the )?floodplain|not in (?:the )?floodplain/.test(t)) f.noFloodplain = true;
    if (t.includes("wilson")) f.county = "Wilson";
    else if (t.includes("karnes")) f.county = "Karnes";
    return f;
  }

  function applyFilterObject(f, source) {
    const applied = [];
    if (f.minBuildableAcres != null) {
      state.minAcres = f.minBuildableAcres; $("#f-acres").value = Math.min(2000, state.minAcres);
      $("#f-acres-val").textContent = state.minAcres; applied.push(`≥ ${state.minAcres} buildable ac`);
    }
    if (f.maxDistSubstationMi != null) {
      state.maxDist = f.maxDistSubstationMi; $("#f-dist").value = Math.min(15, state.maxDist);
      $("#f-dist-val").textContent = state.maxDist; applied.push(`≤ ${state.maxDist} mi to substation`);
    }
    if (f.minKv != null) { state.minKv = f.minKv; $("#f-kv").value = String(state.minKv); applied.push(`≥ ${state.minKv} kV`); }
    if (f.noFloodplain) { state.noFlood = true; $("#f-noflood").checked = true; applied.push("no floodplain"); }
    if (f.county) { state.county = f.county; $("#f-county").value = f.county; applied.push(`${f.county} Co.`); }
    $("#ask-status").innerHTML = applied.length
      ? `Applied (${source}): <strong>${applied.join(" · ")}</strong>.`
      : `No filters recognized. Try: “over 300 buildable acres within 3 miles of a 138 kV substation, no floodplain”.`;
    applyFilters(true);
  }

  async function askTheMap(text) {
    if (!text.trim()) return;
    if (WORKER_URL) {
      try {
        const r = await fetch(WORKER_URL, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ question: text }), signal: AbortSignal.timeout(9000),
        });
        if (r.ok) {
          const d = await r.json();
          if (d && d.filter) { applyFilterObject(d.filter, d.source === "llm" ? "AI" : "rules"); return; }
        }
      } catch { /* fall through to the offline parser */ }
    }
    applyFilterObject(localRuleParse(text), WORKER_URL ? "rules · offline" : "rules");
  }

  /* ---------------- tracker ---------------- */
  function shortlist() { return FEATURES.map((f) => f.properties).filter((p) => p.pipeline_status); }

  let sortKey = "suitability_score", sortDir = -1;
  function buildTracker() {
    document.querySelectorAll("#tracker th").forEach((th) =>
      th.addEventListener("click", () => {
        const k = th.dataset.sort;
        sortDir = k === sortKey ? -sortDir : -1; sortKey = k; renderRows();
      }));
    renderRows();
  }

  function sortVal(p, key) {
    if (key === "verdict") {
      const v = VERDICTS.get(p.parcel_id);
      return v ? VERDICT_ORDER[v.verdict] : 99;
    }
    return p[key];
  }
  function verdictCell(p) {
    const v = VERDICTS.get(p.parcel_id);
    if (!v) return `<span class="verdict-none">—</span>`;
    const title = (v.rationale || "").replace(/"/g, "&quot;");
    return `<span class="verdict ${v.verdict}" title="${title}">${VERDICT_LABEL[v.verdict]}</span>`;
  }

  function renderRows() {
    const rows = shortlist().sort((a, b) => {
      const x = sortVal(a, sortKey), y = sortVal(b, sortKey);
      if (x == null) return 1; if (y == null) return -1;
      return (x > y ? 1 : x < y ? -1 : 0) * sortDir;
    });
    const tbody = $("#tracker tbody");
    tbody.innerHTML = rows.map((p) => `
      <tr data-id="${p.parcel_id}">
        <td>${p.parcel_id}</td><td>${p.county}</td>
        <td>${p.pipeline_status}</td><td>${p.acreage_buildable}</td>
        <td><span class="deal-link" onclick="event.stopPropagation();openDeal('${p.parcel_id}')" title="Open the deal sheet">${p.est_price_per_ac ? "$" + p.est_price_per_ac.toLocaleString() : "—"}</span></td>
        <td><span class="pill ${p.title_flag}">${p.title_flag}</span></td>
        <td>${p.suitability_score}</td><td>${verdictCell(p)}</td><td>${p.status_date}</td>
      </tr>`).join("");
    tbody.querySelectorAll("tr").forEach((tr) =>
      tr.addEventListener("click", () => locateOnMap(tr.dataset.id)));
  }

  function locateOnMap(id) {
    activateView("map");
    const layer = LAYERS.get(id);
    if (!layer) return;
    setTimeout(() => {
      MAP.invalidateSize();
      layer.setStyle(visibleStyle(layer.feature.properties)); // ensure visible if filtered out
      MAP.fitBounds(layer.getBounds(), { maxZoom: 14, padding: [40, 40] });
      layer.openPopup();
    }, 80);
  }

  /* ---------------- charts + KPIs ---------------- */
  const money = (v) => (v >= 1e6 ? "$" + (v / 1e6).toFixed(1) + "M" : "$" + Math.round(v).toLocaleString());

  function buildCharts() {
    const counts = {}, acres = {}, cost = {};
    STATUS_ORDER.forEach((s) => { counts[s] = 0; acres[s] = 0; cost[s] = 0; });
    shortlist().forEach((p) => {
      counts[p.pipeline_status]++;
      acres[p.pipeline_status] += p.acreage_buildable;
      cost[p.pipeline_status] += p.acreage_buildable * (p.est_price_per_ac || 0);
    });
    const used = STATUS_ORDER.filter((s) => counts[s] > 0);

    Chart.defaults.font.family = "'DM Sans', system-ui, sans-serif";
    Chart.defaults.color = "#8a8580";
    const grid = "rgba(255,255,255,0.06)";
    const opts = (tickFmt) => ({
      indexAxis: "y",
      plugins: { legend: { display: false } },
      scales: {
        x: { grid: { color: grid }, border: { color: grid }, ticks: { precision: 0, callback: tickFmt } },
        y: { grid: { display: false }, border: { color: grid } },
      },
    });
    const bar = (id, data, color, tickFmt) =>
      new Chart($(id), {
        type: "bar",
        data: { labels: used, datasets: [{ data, backgroundColor: color, borderRadius: 3 }] },
        options: opts(tickFmt),
      });

    charts.funnel = bar("#chart-funnel", used.map((s) => counts[s]), "#c8a87c");
    charts.acres = bar("#chart-acres", used.map((s) => Math.round(acres[s])), "#7f9b4e");
    charts.cost = bar("#chart-cost", used.map((s) => Math.round(cost[s])), "#bf7a3a", (v) => money(v));
  }

  function buildKpis() {
    const sl = shortlist();
    const totalAc = sl.reduce((a, p) => a + p.acreage_buildable, 0);
    const prices = sl.map((p) => p.est_price_per_ac).filter(Boolean);
    const avg = prices.length ? Math.round(prices.reduce((a, b) => a + b, 0) / prices.length) : 0;
    const totalVal = sl.reduce((a, p) => a + p.acreage_buildable * (p.est_price_per_ac || 0), 0);
    const securedIdx = STATUS_ORDER.indexOf("Site Control Secured");
    const secured = sl.filter((p) => STATUS_ORDER.indexOf(p.pipeline_status) >= securedIdx).length;
    const kpi = (num, lbl) => `<div class="kpi"><span class="num">${num}</span><span class="lbl">${lbl}</span></div>`;
    $("#kpis").innerHTML =
      kpi(sl.length, "parcels in pipeline") +
      kpi(totalAc.toLocaleString() + " ac", "buildable under control") +
      kpi(money(totalVal), "est. pipeline value") +
      kpi("$" + avg.toLocaleString(), "avg. est. $/ac") +
      kpi(secured, "at/after site control");
  }

  /* ---------------- deal sheet (A3) ---------------- */
  // Development-margin economics per parcel: flip / ground-lease / JV, a
  // time-to-power × exit-value sensitivity, and budget-vs-actual. All figures
  // are synthetic + illustrative; every assumption is stated in-panel.
  const EXIT_MULTS = ["2", "4", "6"]; // money_multiple / uplift_per_ac keys are strings
  const pct = (frac, dp = 0) => (frac * 100).toFixed(dp) + "%"; // 0.485 -> "48%"
  const esc = (s) => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const TIER_LABEL = {
    prime: "Prime", near_substation: "Near substation",
    good_transmission: "Good transmission", standard: "Standard",
  };
  const tierLabel = (t) => TIER_LABEL[t] || (t ? t.replace(/_/g, " ") : "—");

  function buildDealSheet() {
    const sel = $("#deal-parcel");
    if (!sel || !ECON || !ECON.parcels) return;
    const ids = Object.keys(ECON.parcels).sort();
    sel.innerHTML = ids.map((id) => {
      const p = ECON.parcels[id];
      return `<option value="${id}">${id} · ${p.county} · #${p.suitability_rank}</option>`;
    }).join("");
    const featured = (NOTES && ECON.parcels[NOTES.featured_parcel]) ? NOTES.featured_parcel : ids[0];
    sel.value = featured;
    if (NOTES && NOTES.methodology) $("#deal-methodology").textContent = NOTES.methodology;
    sel.addEventListener("change", (e) => renderDeal(e.target.value));
    renderDeal(featured);
  }

  // success-case grid uses IRR; risk-adjusted grid uses RA. Cells are keyed by
  // numeric mult; we look up by mult so we never rely on array order.
  function sensiTable(rows, field, posClass, negClass) {
    const head = `<tr><th>Time to power</th>${EXIT_MULTS.map((m) => `<th>${m}×</th>`).join("")}</tr>`;
    const body = rows.map((r) => {
      const miss = r.months === "miss";
      const label = miss ? "Misses the window" : `${r.months} months`;
      const cells = EXIT_MULTS.map((m) => {
        const cell = r.cells.find((c) => c.mult === +m);
        const v = cell ? cell[field] : null;
        const txt = v == null ? "—" : Math.round(v * 100) + "%";
        let cls;
        if (field === "irr") cls = cell && cell.clears ? posClass : negClass;
        else cls = v != null && v >= 0 ? posClass : negClass;
        return `<td class="${cls}">${txt}</td>`;
      }).join("");
      return `<tr class="${miss ? "miss-row" : ""}"><th scope="row">${label}</th>${cells}</tr>`;
    }).join("");
    return `<div class="deal-table-wrap"><table class="deal-sensi-table"><thead>${head}</thead><tbody>${body}</tbody></table></div>`;
  }

  function renderDeal(id) {
    const body = $("#deal-body");
    const d = ECON && ECON.parcels ? ECON.parcels[id] : null;
    if (!body || !d) { if (body) body.innerHTML = `<p class="hint">No deal data for ${esc(id)}.</p>`; return; }
    const props = PROPS.get(id) || {};
    const flip = d.flip, lease = d.lease, jv = d.jv;
    const A = ECON.assumptions || {};
    const notes = NOTES || {};
    const ablocks = notes.assumption_blocks || {};

    /* 1 — header */
    const v = VERDICTS.get(id);
    const verdictChip = v ? `<span class="verdict ${v.verdict}">${VERDICT_LABEL[v.verdict]}</span>` : "";
    const statusBit = props.pipeline_status
      ? `Status: ${esc(props.pipeline_status)}${props.status_date ? ` (updated ${esc(props.status_date)})` : ""}`
      : "Status: —";
    const header = `
      <div class="deal-parcel-head">
        <div class="deal-ph-top">
          <h3>${esc(id)} · ${esc(d.county)} Co.</h3>
          ${verdictChip}
        </div>
        <div class="deal-ph-meta">
          <span>${statusBit}</span>
          <span>Suitability #${d.suitability_rank}</span>
        </div>
        <div class="deal-figrow">
          <div class="deal-fig"><span class="deal-fig-num">${money(d.land_price)}</span><span class="deal-fig-lbl">Land price</span></div>
          <div class="deal-fig"><span class="deal-fig-num">~${d.mw_est} MW</span><span class="deal-fig-lbl">Est. capacity</span></div>
          <div class="deal-fig"><span class="deal-fig-num">${money(d.capital_deployed)}</span><span class="deal-fig-lbl">Capital deployed</span></div>
          <div class="deal-fig"><span class="deal-fig-num">$${(d.est_price_per_ac || 0).toLocaleString()}/ac</span><span class="deal-fig-lbl">Est. basis</span></div>
        </div>
      </div>`;

    /* 2 — three structures side by side */
    const flipRows = EXIT_MULTS.map((k) =>
      `<li><span class="ds-k">${k}× exit</span><span class="ds-v">${flip.money_multiple[k]}× on capital · $${(flip.uplift_per_ac[k] || 0).toLocaleString()}/ac uplift</span></li>`
    ).join("");
    const flipCard = `
      <div class="deal-card">
        <span class="deal-card-tag">A · Flip at NTP-ready</span>
        <ul class="ds-list">${flipRows}</ul>
        <dl class="ds-grid">
          <dt>$/MW NTP fee</dt><dd>${money(flip.ntp_fee_per_mw[0])}–${money(flip.ntp_fee_per_mw[1])}</dd>
          <dt>Capital at risk</dt><dd>${money(d.capital_deployed)}</dd>
        </dl>
        <p class="assumption-block">${esc(ablocks.flip || "")}</p>
      </div>`;

    const leaseCard = `
      <div class="deal-card">
        <span class="deal-card-tag">B · Powered-land ground lease</span>
        <dl class="ds-grid">
          <dt>Tier</dt><dd>${tierLabel(lease.tier)}</dd>
          <dt>Rate</dt><dd>$${(lease.rate_per_ac_yr || 0).toLocaleString()}/ac/yr</dd>
          <dt>Annual</dt><dd>${money(lease.annual)}</dd>
          <dt>Yield</dt><dd>${pct(lease.yield_on_basis)} <span class="ds-dim">implied yield on land basis, not a market cap rate</span></dd>
          <dt>Terms</dt><dd>${(lease.escalation_pct * 100).toFixed(0)}%/yr · ${lease.term_years}-yr · ${esc(lease.structure)}</dd>
        </dl>
        <p class="assumption-block">${esc(ablocks.lease || "")}</p>
      </div>`;

    const jvCard = `
      <div class="deal-card">
        <span class="deal-card-tag">C · JV retained interest <span class="ds-flag">most speculative</span></span>
        <dl class="ds-grid">
          <dt>Retained interest</dt><dd>${pct(jv.retained_pct.low)}–${pct(jv.retained_pct.high)}</dd>
          <dt>Stabilized share</dt><dd>${pct(jv.stabilized_share_pct.low)}–${pct(jv.stabilized_share_pct.high)}</dd>
          <dt>Illustrative value</dt><dd>${money(jv.retained_value_base)}</dd>
          <dt>Valuation</dt><dd>${esc(jv.valuation_basis)}</dd>
        </dl>
        <p class="assumption-block">${esc(ablocks.jv || "")}</p>
      </div>`;

    const structures = `<div class="deal-structures">${flipCard}${leaseCard}${jvCard}</div>`;

    /* 3 — sensitivity (centerpiece, dual grid) */
    const sensitivity = `
      <div class="deal-sensitivity">
        <p class="deal-sensi-cap">Time-to-power × exit value — <strong>exit price scales the return; time-to-power gates it.</strong></p>
        <p class="deal-sensi-sub">Success case — IRR if the exit happens.</p>
        ${sensiTable(flip.sensitivity, "irr", "clears", "below")}
        <p class="deal-sensi-sub">Risk-adjusted — at ~${Math.round(flip.success_probability * 100)}% odds of reaching NTP. Only fast energization clears.</p>
        ${sensiTable(flip.sensitivity, "ra", "ra-pos", "ra-neg")}
        <p class="hint">Success case assumes the exit happens; the miss row is a total write-off of control + diligence. Hurdle shown: ${(flip.hurdle_irr * 100).toFixed(0)}% IRR.</p>
      </div>`;

    /* 4 — budget vs actual (only where authored actuals exist) */
    const actuals = (notes.parcels && notes.parcels[id]) ? notes.parcels[id].budget_actuals : null;
    const budget = d.budget || [];
    let bva;
    if (actuals && actuals.length) {
      let tB = 0, tA = 0;
      const rows = actuals.map((a) => {
        const b = budget.find((x) => x.stage === a.stage);
        const budv = b ? b.budget : 0;
        const actv = budv * (1 + a.actual_delta_pct);
        const varc = actv - budv;
        tB += budv; tA += actv;
        const vcls = varc > 0 ? "over" : varc < 0 ? "under" : "";
        const vsign = varc > 0 ? "+" : "";
        return `<tr>
          <th scope="row">${esc(a.stage)}</th>
          <td>${money(budv)}</td>
          <td>${money(actv)}</td>
          <td class="variance ${vcls}">${vsign}${money(varc)}</td>
          <td class="ds-note">${esc(a.note || "")}</td>
        </tr>`;
      }).join("");
      const tVar = tA - tB;
      const tcls = tVar > 0 ? "over" : tVar < 0 ? "under" : "";
      const tsign = tVar > 0 ? "+" : "";
      bva = `
        <div class="deal-bva">
          <h4>Budget vs actual</h4>
          <div class="deal-table-wrap"><table class="deal-bva-table">
            <thead><tr><th>Stage</th><th>Budget</th><th>Actual</th><th>Variance</th><th>Note</th></tr></thead>
            <tbody>${rows}
              <tr class="bva-total">
                <th scope="row">Total</th><td>${money(tB)}</td><td>${money(tA)}</td>
                <td class="variance ${tcls}">${tsign}${money(tVar)}</td><td></td>
              </tr>
            </tbody>
          </table></div>
        </div>`;
    } else {
      const totalBudget = budget.reduce((s, x) => s + (x.budget || 0), 0);
      bva = `
        <div class="deal-bva">
          <h4>Budget vs actual</h4>
          <p class="hint">Budget-vs-actual appears once a parcel is under option — this one is at “${esc(props.pipeline_status || "—")}”. Budgeted control + diligence + legal: ${money(totalBudget)}.</p>
        </div>`;
    }

    /* 5 — load-bearing assumptions */
    const dilig = A.diligence_usd || {};
    const oom = A.diligence_order_of_magnitude || [];
    const diligRows = Object.keys(dilig).map((k) => {
      const [lo, hi] = dilig[k];
      const label = k.replace(/_/g, " ");
      const tag = oom.includes(k) ? " (order-of-magnitude)" : "";
      return `<li><span class="ds-k">${esc(label)}</span><span class="ds-v">$${lo.toLocaleString()}–$${hi.toLocaleString()}${tag}</span></li>`;
    }).join("");
    const multsTxt = (A.uplift_multiples || []).join("×, ") + "×";
    const assumptions = `
      <div class="deal-assumptions">
        <h4>Load-bearing assumptions</h4>
        <ul class="ds-assume-keys">
          <li>Option: ${(A.option_pct * 100).toFixed(0)}% of price</li>
          <li>Carry: ${(A.carry_rate * 100).toFixed(0)}%/yr</li>
          <li>${A.ac_per_mw} ac/MW</li>
          <li>Exit: ${multsTxt}</li>
          <li>Hurdle: ${(A.hurdle_irr * 100).toFixed(0)}% IRR</li>
        </ul>
        <ul class="ds-list ds-dilig">${diligRows}</ul>
        <p class="deal-assume-line">${esc(notes.incentives_line || A.incentives_note || "")}</p>
        <p class="deal-assume-line">${esc(A.sb6_framing || "")}</p>
        <p class="deal-assume-disc">${esc(A.disclosure || "")}</p>
      </div>`;

    body.innerHTML = header + structures + sensitivity + bva + assumptions;
  }

  function openDeal(id) {
    activateView("deal");
    const sel = $("#deal-parcel");
    if (sel) sel.value = id;
    renderDeal(id);
  }
  window.openDeal = openDeal;

  /* ---------------- portfolio (A1.5) ---------------- */
  // Given an option budget, how the capital deploys across the pursue / pursue-if
  // shortlist: spread options to control the best parcels, stage diligence on the
  // speed-to-power winners. The model ranks; the analyst allocates. All synthetic.
  const budgetLabel = (b) => (b >= 1e6 ? "$" + b / 1e6 + "M" : "$" + b / 1000 + "K");
  function buildPortfolio() {
    if (!PORT || !PORT.allocations) return;
    const strat = $("#pf-strategy");
    if (strat && NOTES && NOTES.portfolio) strat.textContent = NOTES.portfolio.strategy || "";
    const wrap = $("#pf-budgets");
    if (!wrap) return;
    const budgets = PORT.assumptions.budgets_usd || [];
    wrap.innerHTML = budgets.map((b) =>
      `<button class="pf-budget" data-b="${b}">${budgetLabel(b)}</button>`).join("");
    wrap.querySelectorAll(".pf-budget").forEach((btn) =>
      btn.addEventListener("click", () => renderPortfolio(+btn.dataset.b)));
    if (budgets.length) renderPortfolio(budgets[0]);
  }

  function renderPortfolio(budget) {
    const a = PORT.allocations.find((x) => x.budget === budget);
    document.querySelectorAll(".pf-budget").forEach((btn) =>
      btn.classList.toggle("is-active", +btn.dataset.b === budget));
    const body = $("#pf-body");
    if (!body || !a) { if (body) body.innerHTML = `<p class="hint">No allocation for ${esc(money(budget))}.</p>`; return; }

    /* 1 — KPIs */
    const kpi = (num, lbl) => `<div class="kpi"><span class="num">${num}</span><span class="lbl">${lbl}</span></div>`;
    const kpis = `<div class="kpis pf-kpis">` +
      kpi(a.n_controlled, "parcels controlled") +
      kpi(a.acres_controlled.toLocaleString(), "buildable acres") +
      kpi(`~${a.mw_controlled} MW`, "solar-generation potential") +
      kpi(money(a.capital_deployed), `option capital · ${Math.round(a.budget_utilization * 100)}% of ${budgetLabel(budget)}`) +
      kpi(`${a.n_staged} · ${money(a.staged_diligence_usd)}`, "staged for diligence") +
      kpi(`${Math.round(a.blended_ra * 100)}%`, "blended risk-adj") +
      `</div>`;

    /* 2 — allocation table */
    const head = `<tr>
      <th>Parcel</th><th>County</th><th>Verdict</th><th>Action</th>
      <th>Option $</th><th>Cumulative</th><th>Controls</th><th>Risk-adj</th></tr>`;
    const rows = a.controlled.map((r) => `
      <tr class="${r.stage_next ? "pf-staged" : ""}">
        <td><span class="deal-link" onclick="openDeal('${r.parcel_id}')">${r.parcel_id}</span></td>
        <td>${esc(r.county)}</td>
        <td><span class="verdict ${r.verdict}">${VERDICT_LABEL[r.verdict]}</span></td>
        <td>${r.stage_next ? "Option + diligence staged" : "Option (now)"}</td>
        <td>${money(r.option_cost)}</td>
        <td>${money(r.cumulative_option)}</td>
        <td>${Math.round(r.acreage_buildable)} ac · ${Math.round(r.mw_est)} MW</td>
        <td>${Math.round(r.ra * 100)}%</td>
      </tr>`).join("");
    const table = `<div class="deal-table-wrap"><table class="pf-table">
      <thead>${head}</thead><tbody>${rows}</tbody></table></div>`;

    /* 3 — tail: what's left out at this budget */
    const tail = `<p class="pf-tail">Not funded at ${money(budget)}: ${esc((a.unfunded || []).map((u) => u.parcel_id).join(", "))}<br>` +
      `Excluded (analyst pass): ${esc((a.excluded || []).map((e) => e.parcel_id).join(", "))}</p>`;

    /* 4 — authored by-budget rationale */
    const note = (NOTES && NOTES.portfolio && NOTES.portfolio.by_budget) || {};
    const rationale = `<p class="pf-note">${esc(note[String(budget)] || "")}</p>`;

    body.innerHTML = kpis + table + tail + rationale;
  }

  /* ---------- featured pass memo ---------- */
  function mountMemo() {
    const mount = $("#memo-mount");
    if (!mount || !MEMO || !MEMO.memo) return;
    const m = MEMO.memo;
    const paras = (m.paragraphs || []).map((t) => `<p>${t}</p>`).join("");
    mount.innerHTML =
      `<details class="memo-panel">
        <summary>
          <span class="memo-eyebrow">Analyst's call<span class="memo-pass-badge">PASS</span></span>
          <span class="memo-headline">${m.headline}</span>
          <span class="memo-cue">Why I'd pass on a top-ranked parcel in my own model →</span>
        </summary>
        <div class="memo-body">
          ${paras}
          <p class="memo-kicker">${m.kicker || ""}</p>
          <button class="btn btn-ghost memo-locate" type="button">Show the parcel on the map</button>
        </div>
      </details>`;
    const det = mount.querySelector(".memo-panel");
    mount.querySelector(".memo-locate").addEventListener("click", () => locateOnMap(MEMO.parcel_id));
    det.addEventListener("toggle", () => { if (det.open) locateOnMap(MEMO.parcel_id); });
  }
  function openMemo() {
    const det = document.querySelector(".memo-panel");
    if (det) { det.open = true; det.scrollIntoView({ behavior: "smooth", block: "nearest" }); }
  }
  window.openMemo = openMemo;

  document.addEventListener("DOMContentLoaded", init);
})();
