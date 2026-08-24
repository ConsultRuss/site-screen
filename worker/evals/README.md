# Ask-the-map eval

A labelled eval for the natural-language layer: 54 questions, each paired with the filter it
*should* produce. Ground truth is a judgment about what the question means — not a recording
of what the parser currently returns, which would make the eval agree with itself by
construction.

## Run it

```bash
node evals/run.mjs                 # offline report (what CI runs)
node evals/run.mjs --ci            # same, exit 1 below the floors in thresholds.json
node evals/run.mjs --failures      # report plus every failing case in full
node evals/run.mjs --json          # machine-readable

OPENROUTER_API_KEY=... node evals/run.mjs --live --record   # call the model, record fixtures
```

Offline is deterministic, free, and needs no key, so it runs on every push. The live run costs
money and stays manual.

## What it measures

| Metric | Meaning |
|---|---|
| **Exact-match rate** | The whole filter matches ground truth on all five fields. |
| **Per-field accuracy** | Each field independently; absent-and-should-be-absent counts as correct. |
| **Refusal correctness** | Over the cases whose correct answer is *no filter at all* — out-of-scope questions and questions the DSL cannot express — how often the parser returns `{}` instead of inventing a constraint. |
| **Fallback rate** | How often the LLM produced nothing usable and the deterministic parser caught it. This is the number that turns the two-layer design from a claim into evidence. Live path only. |
| **Median latency** | Rule parser offline; end-to-end model latency in `--live`. |
| **Parser drift** | `web/js/app.js` keeps its own copy of the rule parser so the map still works when the Worker is unreachable. The runner extracts the regex literals from both and fails if they disagree. |

## Case categories

`simple` · `compound` · `units` (mi/mile/mi., kV/kv/kilovolt, decimals, thousands separators) ·
`county` and `geography` (place names that imply a county) · `out_of_scope` ·
`unrepresentable` (questions the five-field DSL genuinely cannot express — "more than 5 miles
from a substation" has no inverse field) · `adversarial` (prompt injection, absurd numbers,
negative values, input past the 280-character cap) · `vague` · `edge` (empty, whitespace).

## What it does not measure

- **The LLM path, until fixtures are recorded.** The replay mechanism ships;
  `fixtures/openrouter.json` starts empty. While it is empty the runner prints *not measured*
  for the LLM path and the fallback rate rather than guessing, and the published numbers
  describe the deterministic parser alone.
- **Transport guardrails.** The per-IP rate limit and CORS origin restriction are not
  exercised. The runner does apply the same 280-character cap the Worker applies before
  parsing, so truncation is reflected in the result.
- **End-to-end browser behavior** — that a returned filter actually moves the map.

## Thresholds

`thresholds.json` holds the floors `--ci` enforces, set from the measured baseline on
2026-08-24, not from an aspiration. The build should go red when the parser gets *worse*, not
stay red because it was never perfect. Raise them when the parser improves; do not lower them
to make a build pass.
