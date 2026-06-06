# Ask-the-map Worker

A thin Cloudflare Worker that turns a plain-English question into a **validated
filter object** the web app applies to the parcel GeoJSON. It never sees the data.

## Contract

`POST /` with `{ "question": "over 300 buildable acres within 3 miles of a 138 kV substation, no floodplain" }`
returns:

```json
{ "filter": { "minBuildableAcres": 300, "maxDistSubstationMi": 3, "minKv": 138, "noFloodplain": true }, "source": "rules" }
```

Only these keys are ever emitted (`FILTER_FIELDS` in `src/index.js`):
`county`, `minBuildableAcres`, `maxDistSubstationMi`, `minKv`, `noFloodplain`.

## Two layers

1. **LLM** (OpenRouter, structured outputs, `temperature: 0`) proposes a filter —
   primary `google/gemini-2.5-flash`, fallback `anthropic/claude-haiku-4.5`.
2. The result is **validated** against the whitelist; on any miss it falls back to
   the deterministic `ruleParse()`. So the feature works keyless and degrades
   gracefully. The LLM layer is wired in M3; M0 ships the rule-based fallback.

## Run / deploy (M3)

```bash
npx wrangler dev          # local
npx wrangler secret put OPENROUTER_API_KEY   # set the key (never committed)
npx wrangler deploy       # publish
```

Confirm exact model slugs on `openrouter.ai/models` at setup — slugs drift.
