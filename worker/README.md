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
   `meta-llama/llama-3.3-70b-instruct`, fallback `meta-llama/llama-3.1-8b-instruct`
   (ZDR-compliant providers — turning a sentence into a small JSON filter needs no frontier model).
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

## Eval — measured, including the misses

54 labelled questions in [`evals/cases.jsonl`](evals/cases.jsonl), each paired with the filter
it *should* produce. Ground truth is a judgment about what the question means, not a recording
of current parser output. Run it with `node evals/run.mjs`; CI runs it on every push.

Baseline **2026-08-24**, deterministic rule parser:

| Metric | Value |
|---|---|
| Exact-match rate | **75.9%** (41 / 54) |
| Correct refusals — out-of-scope + inexpressible questions returning `{}` | **71.4%** (15 / 21) |
| `county` / `minBuildableAcres` per-field accuracy | 92.6% / 92.6% |
| `maxDistSubstationMi` / `minKv` / `noFloodplain` per-field accuracy | 96.3% / 96.3% / 98.1% |
| Median latency | 0.002 ms |
| Prompt-injection cases resisted | **3 / 3** |
| Worker vs. browser parser drift | none |

By category: `simple` 100% (10/10) · `compound` 87.5% · `out_of_scope` 87.5% · `county` 72.7% ·
`units` 70% · `unrepresentable` 66.7% · `adversarial` 62.5% · `range` 25% (1/4).

**The LLM path is not measured yet.** The replay mechanism ships and CI runs it, but
`evals/fixtures/openrouter.json` is empty until someone runs `--live --record` with a key. So
the **fallback rate — the most informative number here, since it is what turns "a deterministic
parser stands behind the model" from a design claim into evidence — is currently unknown.**
Everything above describes the rule parser alone.

### Known failures

Published rather than fixed. These describe the parser as it has been running in production;
repairing them in the same pass would make the numbers describe code nobody has used.

| Case | Question | Correct | Parser returns |
|---|---|---|---|
| `units-07` | over 1,000 acres | `{"minBuildableAcres":1000}` | `{"minBuildableAcres":0}` |
| `adversarial-04` | over 99999 acres | `{}` | `{"minBuildableAcres":9999}` |
| `adversarial-07` | 999999999 kv | `{}` | `{"minKv":345}` |
| `adversarial-05` | -50 acres | `{}` | `{"minBuildableAcres":50}` |
| `unrepresentable-01` | parcels more than 5 miles from any substation | `{}` | `{"maxDistSubstationMi":5}` |
| `unrepresentable-02` | parcels under 100 acres | `{}` | `{"minBuildableAcres":100}` |
| `outofscope-01` | what's the weather in Karnes City | `{}` | `{"county":"Karnes"}` |
| `county-04` | Wilson or Karnes, over 300 acres | `{"minBuildableAcres":300}` | `{"county":"Wilson",…}` |
| `county-01` | parcels near Floresville | `{"county":"Wilson"}` | `{}` |
| `county-02` | parcels near Kenedy | `{"county":"Karnes"}` | `{}` |
| `units-06` | 138 kilovolt lines | `{"minKv":138}` | `{}` |
| `units-08` | half a mile from a substation | `{"maxDistSubstationMi":0.5}` | `{}` |
| `compound-03` | …and no flood zone | `noFloodplain: true` | field absent |

Four patterns, in rough order of severity:

1. **A thousands separator parses to zero.** `\d{2,4}` skips `1,` and matches `000` in
   "1,000 acres", so the filter silently becomes "at least 0 acres" — a *wrong* answer
   presented as a successful parse, which is worse than a refusal.
2. **No range validation.** Absurd acreage and voltage are accepted and clamped rather than
   rejected; a negative acreage loses its sign.
3. **Direction is not understood.** "More than 5 miles from" and "under 100 acres" are
   inverted, because the DSL has only a maximum-distance and a minimum-acreage field. The
   honest fix is refusal, not a guess.
4. **Bare keyword matching over-fires and under-fires.** A county name in an unrelated question
   sets a county filter; a town name that implies a county does not. Synonyms
   ("kilovolt", "flood zone", "half a mile") are missed.

The LLM layer exists to absorb exactly (3) and (4). Measuring it is the next step, and the
fallback rate will show how much of that load it actually carries.

Details, definitions, and what the eval deliberately does not cover: [`evals/README.md`](evals/README.md).

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
