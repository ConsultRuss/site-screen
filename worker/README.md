# Ask-the-map Worker

A thin Cloudflare Worker that turns a plain-English question into a **validated
filter object** the web app applies to the parcel GeoJSON. It never sees the data.

## Contract

`POST /` with `{ "question": "over 300 buildable acres within 3 miles of a 138 kV substation, no floodplain" }`
returns:

```json
{ "filter": { "minBuildableAcres": 300, "maxDistSubstationMi": 3, "minKv": 138, "noFloodplain": true }, "source": "llm" }
```

Only these keys are ever emitted (`FILTER_FIELDS` in `src/index.js`):
`county`, `minBuildableAcres`, `maxDistSubstationMi`, `minKv`, `noFloodplain`.
`source` is `"llm"`, `"rules"`, or `"rate_limited"`.

## Two layers (graceful degradation)

1. **LLM** — OpenRouter, **pinned models** (`models: [primary, fallback]`), **JSON output
   mode** (`response_format: json_object`), **temperature 0**, `max_tokens: 200`. Primary
   `google/gemini-2.5-flash`, fallback `anthropic/claude-haiku-4.5`.
2. The result is **validated** against the whitelist; on any miss (no key, bad JSON,
   model down, rate-limited) it falls back to the deterministic `ruleParse()`. The
   browser also keeps its own copy of the parser, so the feature works even if the
   Worker is unreachable.

## Guardrails (cost / abuse)

- **Per-IP rate limit** — 12 requests / 60 s via the Cloudflare Rate Limiting binding
  (`[[ratelimits]]` in `wrangler.toml`); returns `429` + `source: "rate_limited"`.
- **Input cap** — questions truncated to 280 chars.
- **Output cap** — `max_tokens: 200` (the filter JSON is tiny) keeps per-call cost ~$0.
- **CORS** — restricted to `ALLOWED_ORIGINS` (sites.consultruss.com + localhost).
- **Key** — `OPENROUTER_API_KEY` is a secret, never committed.

## Run / deploy

```bash
npm i -g wrangler                              # or use npx
npx wrangler dev                               # local (no key -> rule fallback)
npx wrangler secret put OPENROUTER_API_KEY     # set the key (never committed)
npx wrangler deploy                            # publish
```

After deploy, set `WORKER_URL` in `web/js/app.js` to the deployed URL
(a custom domain on your zone, e.g. `https://ask.consultruss.com`). Confirm exact model
slugs on `openrouter.ai/models` at setup — slugs drift.
