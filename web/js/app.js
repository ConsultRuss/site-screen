/* South Texas Site Screen — front-end.
 * Loads the scored GeoJSON and drives three views: Map, Pipeline, About.
 * The "Ask the map" box uses a built-in rule-based parser; the LLM-assisted
 * version (Cloudflare Worker) is a later milestone and degrades to these rules. */
(() => {
  "use strict";

  const DATA_URL = "data/parcels.geojson";
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
  let charts = {};

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
    drawParcels();
    applyFilters(true);
    buildTracker();
    buildCharts();
    buildKpis();
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
  function popupHtml(p) {
    const row = (k, val) => `<dt>${k}</dt><dd>${val}</dd>`;
    let html = `<div class="pp-title">${p.parcel_id} · ${p.county} Co.</div>`;
    html += `<div class="pp-scorewrap"><span class="pp-score">Suitability ${p.suitability_score}</span>`;
    html += `<span class="pp-rank">#${p.suitability_rank} of ${FEATURES.length.toLocaleString()}</span></div>`;
    html += scoreBar(p.suitability_score);
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
    html += `</dl><div class="pp-synthetic">Owner “${p.owner}” &amp; any pipeline data are synthetic.</div>`;
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

  /* Rule-based natural-language parser (the deterministic fallback). */
  function askTheMap(text) {
    if (!text.trim()) return;
    const t = text.toLowerCase();
    const applied = [];
    let m;
    if ((m = t.match(/(\d{2,4})\s*\+?\s*(?:buildable\s*)?acre/))) {
      state.minAcres = +m[1]; $("#f-acres").value = Math.min(2000, state.minAcres);
      $("#f-acres-val").textContent = state.minAcres; applied.push(`≥ ${state.minAcres} buildable ac`);
    }
    if ((m = t.match(/(\d+(?:\.\d+)?)\s*(?:mi|mile)/))) {
      state.maxDist = +m[1]; $("#f-dist").value = Math.min(15, state.maxDist);
      $("#f-dist-val").textContent = state.maxDist; applied.push(`≤ ${state.maxDist} mi to substation`);
    }
    if ((m = t.match(/(\d{2,3})\s*kv/))) {
      state.minKv = +m[1]; $("#f-kv").value = String(state.minKv); applied.push(`≥ ${state.minKv} kV`);
    }
    if (/no floodplain|outside (?:the )?floodplain|not in (?:the )?floodplain/.test(t)) {
      state.noFlood = true; $("#f-noflood").checked = true; applied.push("no floodplain");
    }
    if (t.includes("wilson")) { state.county = "Wilson"; $("#f-county").value = "Wilson"; applied.push("Wilson Co."); }
    else if (t.includes("karnes")) { state.county = "Karnes"; $("#f-county").value = "Karnes"; applied.push("Karnes Co."); }

    $("#ask-status").innerHTML = applied.length
      ? `Applied (rule-based): <strong>${applied.join(" · ")}</strong>.`
      : `No filters recognized. Try: “over 300 buildable acres within 3 miles of a 138 kV substation, no floodplain”.`;
    applyFilters(true);
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

  function renderRows() {
    const rows = shortlist().sort((a, b) => {
      const x = a[sortKey], y = b[sortKey];
      if (x == null) return 1; if (y == null) return -1;
      return (x > y ? 1 : x < y ? -1 : 0) * sortDir;
    });
    const tbody = $("#tracker tbody");
    tbody.innerHTML = rows.map((p) => `
      <tr data-id="${p.parcel_id}">
        <td>${p.parcel_id}</td><td>${p.county}</td>
        <td>${p.pipeline_status}</td><td>${p.acreage_buildable}</td>
        <td>${p.est_price_per_ac ? "$" + p.est_price_per_ac.toLocaleString() : "—"}</td>
        <td><span class="pill ${p.title_flag}">${p.title_flag}</span></td>
        <td>${p.suitability_score}</td><td>${p.status_date}</td>
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

  document.addEventListener("DOMContentLoaded", init);
})();
