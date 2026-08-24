/* Filter-DSL parsing for the "Ask the map" Worker.
 *
 * Split out of index.js so it can be exercised directly by the eval suite in
 * ../evals/ — the eval measures the code that actually ships, not a copy of it.
 * This module is dependency-free and has no Worker/runtime bindings: it is pure
 * text -> filter object. index.js owns the HTTP layer (CORS, rate limit, routing).
 */

export const MAX_QUESTION_CHARS = 280;
export const DEFAULT_PRIMARY = "meta-llama/llama-3.3-70b-instruct";
export const DEFAULT_FALLBACK = "meta-llama/llama-3.1-8b-instruct";

// Whitelisted filter fields — the only keys we ever emit or accept.
export const FILTER_FIELDS = {
  county: (v) => (v === "Wilson" || v === "Karnes" ? v : null),
  minBuildableAcres: (v) => (Number.isFinite(+v) ? +v : null),
  maxDistSubstationMi: (v) => (Number.isFinite(+v) ? +v : null),
  minKv: (v) => ([69, 138, 345].includes(+v) ? +v : null),
  noFloodplain: (v) => (typeof v === "boolean" ? v : null),
};

// JSON schema pinned for OpenRouter structured outputs (all fields nullable).
export const FILTER_SCHEMA = {
  name: "parcel_filter",
  strict: true,
  schema: {
    type: "object",
    additionalProperties: false,
    required: ["county", "minBuildableAcres", "maxDistSubstationMi", "minKv", "noFloodplain"],
    properties: {
      county: { type: ["string", "null"], enum: ["Wilson", "Karnes", null] },
      minBuildableAcres: { type: ["number", "null"] },
      maxDistSubstationMi: { type: ["number", "null"] },
      minKv: { type: ["number", "null"], enum: [69, 138, 345, null] },
      noFloodplain: { type: ["boolean", "null"] },
    },
  },
};

export const SYSTEM_PROMPT =
  "Convert the user's plain-English question about South Texas land parcels into a JSON " +
  "filter. Use ONLY these fields: county ('Wilson'|'Karnes'|null), minBuildableAcres " +
  "(number|null), maxDistSubstationMi (number|null), minKv (69|138|345|null), " +
  "noFloodplain (boolean|null). Set a field to null if the question does not mention it. " +
  "Never invent values. Return only the JSON object.";

/** Keep only whitelisted keys with values that survive their coercion. */
export function validateFilter(obj) {
  const out = {};
  if (obj && typeof obj === "object") {
    for (const [k, coerce] of Object.entries(FILTER_FIELDS)) {
      if (k in obj && obj[k] !== null) {
        const v = coerce(obj[k]);
        if (v !== null) out[k] = v;
      }
    }
  }
  return out;
}

/** Deterministic rule-based parser — the guaranteed fallback.
 *
 * NOTE: web/js/app.js keeps a byte-identical copy of this function body so the
 * feature still works when the Worker is unreachable. The eval's drift check
 * (evals/run.mjs) fails if the two sets of regexes stop agreeing. */
export function ruleParse(text) {
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

/** Pull a JSON object out of a model response — handles ```json fences and JSON
 * embedded in prose (some providers don't honor response_format: json_object). */
export function extractJson(text) {
  let t = String(text).trim().replace(/^```(?:json)?\s*/i, "").replace(/\s*```$/i, "").trim();
  try {
    return JSON.parse(t);
  } catch {
    /* fall through to brace extraction */
  }
  const m = t.match(/\{[\s\S]*\}/);
  if (m) {
    try {
      return JSON.parse(m[0]);
    } catch {
      /* give up -> deterministic fallback */
    }
  }
  return null;
}
