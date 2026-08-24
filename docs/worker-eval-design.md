# Design — an eval for the Ask-the-map Worker

**Status:** complete · **Written:** 2026-08-24

## Problem

The Ask-the-map Worker is the only LLM component in this repository, and it was the only
component with no eval. The Python pipeline has 95 tests including a mini-eval that asserts
the scoring model behaves as the methodology claims. The natural-language layer had nothing —
no labelled cases, no accuracy number, no measured fallback rate.

That gap matters more than it looks. The Worker's design story is that a deterministic
rule-based parser stands behind a pinned LLM, so the feature never breaks. That is a claim
about a guardrail, and a guardrail without a measurement is an assertion.

## Approach

Four pieces.

**1. Extract the parser.** `worker/src/index.js` mixed transport concerns (CORS, rate
limiting, routing) with parsing logic, and the parsing functions were not exported — so
nothing could test them without booting a Worker. `worker/src/parser.js` now holds the filter
whitelist, the JSON schema, the system prompt, `validateFilter`, `ruleParse`, and
`extractJson`. `index.js` imports them and keeps only the HTTP layer. Behavior is unchanged.

**2. A labelled case set.** `worker/evals/cases.jsonl`, one JSON object per line, each with a
question and the *correct* filter as ground truth. Ground truth is a human judgment about what
the question means — deliberately not a recording of what the parser currently produces, which
would make the eval tautological. Cases cover single-criterion questions, compound questions,
unit variations, county references, out-of-scope input, requests the filter DSL cannot express,
and adversarial input including prompt injection.

**3. An offline runner.** `worker/evals/run.mjs` — plain Node, no dependencies. It runs every
case through the shipped `ruleParse` + `validateFilter` and reports exact-match rate, per-field
accuracy, refusal correctness, and latency. It also replays recorded model responses through
`extractJson` + `validateFilter` when fixtures exist. Deterministic, free, no API key, so CI
can run it on every push. A `--live` mode hits OpenRouter for real and records fixtures; that
stays manual.

**4. A drift check.** The browser keeps its own copy of the rule parser in `web/js/app.js` so
the feature works when the Worker is unreachable. Two copies of the same regexes will drift.
The runner extracts the regex literals from both and fails if they disagree.

## Alternatives considered

**A Python runner, reusing the existing CI job.** Rejected. `ruleParse` is JavaScript; a Python
runner would have to reimplement it, and would then be measuring a reimplementation rather than
the code that ships. The whole point is to test the deployed parser.

**Live-model-only evaluation.** Rejected for CI. It costs money on every push, needs a secret,
and is non-deterministic, so a red build would not reliably mean a regression. Recorded
fixtures give a deterministic replay of real model output; the live run stays a manual command.

**Adding an explicit refusal signal to the Worker's response.** Rejected for this pass. Today
an unparseable question returns an empty filter `{}`, and the browser says "No filters
recognized." Adding a `refused` field would be cleaner semantically but changes the Worker's
public JSON contract, requires a matching change in the web app, and requires a redeploy. The
eval measures the behavior that actually ships: for an out-of-scope question, an empty filter
with no hallucinated fields is a correct refusal.

**Fixing parser defects the eval uncovers.** Deliberately out of scope. The eval publishes what
it finds, including the failures, and the published rate describes the version that has been
live. Fixing defects in the same pass would mix a behavior change into a measurement and make
the number describe code nobody has run in production.

## Files affected

| File | Change |
|---|---|
| `worker/src/parser.js` | New. Filter whitelist, schema, prompt, `validateFilter`, `ruleParse`, `extractJson`. |
| `worker/src/index.js` | Imports from `parser.js`; keeps only the HTTP layer. |
| `worker/evals/cases.jsonl` | New. Labelled question set. |
| `worker/evals/run.mjs` | New. Offline + live runner. |
| `worker/evals/thresholds.json` | New. Regression floors enforced by `--ci`. |
| `worker/evals/fixtures/openrouter.json` | New. Recorded model responses, populated by `--live --record`. |
| `worker/evals/README.md` | New. How to run it, what it measures, what it does not. |
| `worker/README.md` | Results section. |
| `README.md` | Quality section. |
| `.github/workflows/ci.yml` | Node job running the offline eval. |

## What this does not measure

Stated plainly, because a partial eval described as complete is worse than none:

- **The LLM path is only measured once fixtures are recorded.** The mechanism ships; the
  fixtures file starts empty. Until someone runs `--live --record` with an OpenRouter key, the
  runner reports the LLM path as *not measured* and the published numbers cover the
  deterministic parser alone.
- **Fallback rate** is a live-path metric. It is unmeasurable offline for the same reason.
- **Transport-layer guardrails** — the per-IP rate limit, CORS origin restriction, and the
  280-character input cap — are not exercised. The runner applies the same character cap the
  Worker does so that truncation is reflected in the parse, but it does not test the limiter.
- **End-to-end behavior in the browser** — that the returned filter actually moves the map — is
  not covered here.
