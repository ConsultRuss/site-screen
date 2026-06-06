/* "Ask the map" Worker — translates a plain-English question into a *validated*
 * filter object against a fixed schema. The browser applies the filter to the
 * in-memory GeoJSON; this Worker never sees or returns the parcel data.
 *
 * Two-layer design (the LLM layer lands in M3):
 *   1. LLM (OpenRouter, structured outputs, temperature 0) -> candidate filter
 *   2. validate against FILTER_FIELDS; on ANY miss, fall back to ruleParse()
 * The deterministic ruleParse() below is the fallback and is what M0 ships, so
 * the feature works with no API key and degrades gracefully if the model is down.
 */

// Whitelisted filter fields — the only keys we ever emit or accept.
const FILTER_FIELDS = {
  county: (v) => (v === "Wilson" || v === "Karnes" ? v : null),
  minBuildableAcres: (v) => (Number.isFinite(+v) ? +v : null),
  maxDistSubstationMi: (v) => (Number.isFinite(+v) ? +v : null),
  minKv: (v) => ([69, 138, 345].includes(+v) ? +v : null),
  noFloodplain: (v) => (typeof v === "boolean" ? v : null),
};

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
};

function validateFilter(obj) {
  const out = {};
  if (obj && typeof obj === "object") {
    for (const [k, coerce] of Object.entries(FILTER_FIELDS)) {
      if (k in obj) {
        const v = coerce(obj[k]);
        if (v !== null) out[k] = v;
      }
    }
  }
  return out;
}

// Deterministic rule-based parser — the guaranteed fallback.
function ruleParse(text) {
  const t = (text || "").toLowerCase();
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

// Placeholder for the M3 LLM layer. Returns null today so we use ruleParse().
async function llmParse(_question, _env) {
  // M3: POST to https://openrouter.ai/api/v1/chat/completions with
  //   { model: env.PRIMARY_MODEL, models: [env.FALLBACK_MODEL], temperature: 0,
  //     response_format: { type: "json_schema", json_schema: FILTER_SCHEMA }, messages: [...] }
  // using Authorization: Bearer ${env.OPENROUTER_API_KEY}. Then validateFilter().
  return null;
}

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") return new Response(null, { headers: CORS });
    if (request.method !== "POST") {
      return json({ error: "POST a JSON body { question }" }, 405);
    }
    let body;
    try {
      body = await request.json();
    } catch {
      return json({ error: "invalid JSON" }, 400);
    }
    const question = (body && body.question) || "";

    let filter = null;
    const llm = await llmParse(question, env).catch(() => null);
    if (llm) filter = validateFilter(llm);
    let source = "llm";
    if (!filter || Object.keys(filter).length === 0) {
      filter = validateFilter(ruleParse(question));
      source = "rules";
    }
    return json({ filter, source });
  },
};

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "Content-Type": "application/json", ...CORS },
  });
}
