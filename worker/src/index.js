/* "Ask the map" Worker — translates a plain-English question into a *validated*
 * filter object against a fixed schema. The browser applies the filter to the
 * in-memory GeoJSON; this Worker never sees or returns the parcel data.
 *
 * Two-layer design:
 *   1. LLM (OpenRouter, locked models, structured output, temperature 0) -> filter
 *   2. validate against FILTER_FIELDS; on ANY miss, fall back to ruleParse()
 * So the feature works with no API key and degrades gracefully if the model is down.
 *
 * Guardrails: per-IP rate limit, input-length cap, small max_tokens, pinned models,
 * origin-restricted CORS. The OpenRouter key is a secret (never committed):
 *   npx wrangler secret put OPENROUTER_API_KEY
 */

const MAX_QUESTION_CHARS = 280;
const DEFAULT_PRIMARY = "meta-llama/llama-3.3-70b-instruct";
const DEFAULT_FALLBACK = "meta-llama/llama-3.1-8b-instruct";

// Whitelisted filter fields — the only keys we ever emit or accept.
const FILTER_FIELDS = {
  county: (v) => (v === "Wilson" || v === "Karnes" ? v : null),
  minBuildableAcres: (v) => (Number.isFinite(+v) ? +v : null),
  maxDistSubstationMi: (v) => (Number.isFinite(+v) ? +v : null),
  minKv: (v) => ([69, 138, 345].includes(+v) ? +v : null),
  noFloodplain: (v) => (typeof v === "boolean" ? v : null),
};

// JSON schema pinned for OpenRouter structured outputs (all fields nullable).
const FILTER_SCHEMA = {
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

const SYSTEM_PROMPT =
  "Convert the user's plain-English question about South Texas land parcels into a JSON " +
  "filter. Use ONLY these fields: county ('Wilson'|'Karnes'|null), minBuildableAcres " +
  "(number|null), maxDistSubstationMi (number|null), minKv (69|138|345|null), " +
  "noFloodplain (boolean|null). Set a field to null if the question does not mention it. " +
  "Never invent values. Return only the JSON object.";

function validateFilter(obj) {
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

// LLM layer — OpenRouter with pinned primary + fallback models, structured output.
async function llmParse(question, env) {
  if (!env.OPENROUTER_API_KEY) return null; // no key -> deterministic fallback
  const models = [env.PRIMARY_MODEL || DEFAULT_PRIMARY, env.FALLBACK_MODEL || DEFAULT_FALLBACK];
  const resp = await fetch("https://openrouter.ai/api/v1/chat/completions", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.OPENROUTER_API_KEY}`,
      "Content-Type": "application/json",
      "HTTP-Referer": "https://sites.consultruss.com",
      "X-Title": "Site Screen ask-the-map",
    },
    body: JSON.stringify({
      models, // first is primary, second is fallback (OpenRouter routing)
      temperature: 0,
      max_tokens: 200,
      response_format: { type: "json_object" },
      messages: [
        { role: "system", content: SYSTEM_PROMPT },
        { role: "user", content: question },
      ],
    }),
    signal: AbortSignal.timeout(8000),
  });
  if (!resp.ok) return null;
  const data = await resp.json();
  const content = data?.choices?.[0]?.message?.content;
  if (!content) return null;
  return extractJson(content);
}

// Robustly pull a JSON object from a model response — handles ```json fences and
// JSON embedded in prose (some providers don't honor response_format: json_object).
function extractJson(text) {
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

function corsHeaders(origin, env) {
  const allowed = (env.ALLOWED_ORIGINS || "https://sites.consultruss.com")
    .split(",")
    .map((s) => s.trim());
  const ok = allowed.includes(origin) || /^http:\/\/localhost(:\d+)?$/.test(origin);
  return {
    "Access-Control-Allow-Origin": ok ? origin : allowed[0],
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    Vary: "Origin",
  };
}

function json(obj, status, cors) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "Content-Type": "application/json", ...cors },
  });
}

export default {
  async fetch(request, env) {
    const cors = corsHeaders(request.headers.get("Origin") || "", env);
    if (request.method === "OPTIONS") return new Response(null, { headers: cors });
    if (request.method !== "POST") return json({ error: "POST { question }" }, 405, cors);

    // Per-IP rate limit (graceful if the binding isn't configured, e.g. local dev).
    const ip = request.headers.get("CF-Connecting-IP") || "anon";
    if (env.ASK_RATE_LIMITER) {
      const { success } = await env.ASK_RATE_LIMITER.limit({ key: ip });
      if (!success) {
        return json({ filter: {}, source: "rate_limited", error: "slow down a moment" }, 429, cors);
      }
    }

    let body;
    try {
      body = await request.json();
    } catch {
      return json({ error: "invalid JSON" }, 400, cors);
    }
    let question = body && typeof body.question === "string" ? body.question : "";
    if (question.length > MAX_QUESTION_CHARS) question = question.slice(0, MAX_QUESTION_CHARS);

    let filter = null;
    let source = "llm";
    const llm = await llmParse(question, env).catch(() => null);
    if (llm) filter = validateFilter(llm);
    if (!filter || Object.keys(filter).length === 0) {
      filter = validateFilter(ruleParse(question));
      source = "rules";
    }
    return json({ filter, source }, 200, cors);
  },
};
