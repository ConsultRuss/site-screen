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
 *
 * The parsing layer lives in ./parser.js so the eval suite (../evals/) can measure
 * the shipped code directly. This file is the HTTP layer only.
 */

import {
  DEFAULT_FALLBACK,
  DEFAULT_PRIMARY,
  MAX_QUESTION_CHARS,
  SYSTEM_PROMPT,
  extractJson,
  ruleParse,
  validateFilter,
} from "./parser.js";

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
