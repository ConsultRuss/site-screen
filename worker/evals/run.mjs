#!/usr/bin/env node
/* Eval runner for the Ask-the-map Worker.
 *
 *   node worker/evals/run.mjs                 offline report (default; what CI runs)
 *   node worker/evals/run.mjs --ci            offline + exit 1 if below thresholds.json
 *   node worker/evals/run.mjs --json          machine-readable results
 *   node worker/evals/run.mjs --failures      offline report + every failing case
 *   node worker/evals/run.mjs --live          call OpenRouter for real (needs OPENROUTER_API_KEY)
 *   node worker/evals/run.mjs --live --record ...and overwrite fixtures/openrouter.json
 *
 * Offline is deterministic, free, and needs no key: it runs the shipped rule parser
 * over the labelled cases and replays any recorded model responses. The live mode
 * spends money and is never run in CI.
 *
 * No dependencies. Node 18+.
 */

import { readFile, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";

import {
  DEFAULT_FALLBACK,
  DEFAULT_PRIMARY,
  FILTER_FIELDS,
  MAX_QUESTION_CHARS,
  SYSTEM_PROMPT,
  extractJson,
  ruleParse,
  validateFilter,
} from "../src/parser.js";

const HERE = new URL("./", import.meta.url);
const CASES_PATH = new URL("cases.jsonl", HERE);
const FIXTURES_PATH = new URL("fixtures/openrouter.json", HERE);
const THRESHOLDS_PATH = new URL("thresholds.json", HERE);
const APP_JS_PATH = new URL("../../web/js/app.js", HERE);
const PARSER_PATH = new URL("../src/parser.js", HERE);

const FIELDS = Object.keys(FILTER_FIELDS);
const argv = new Set(process.argv.slice(2));

/* ---------------------------------------------------------------- helpers */

const pct = (n, d) => (d === 0 ? 0 : (100 * n) / d);
const fmtPct = (n, d) => `${pct(n, d).toFixed(1)}%`;

function median(xs) {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b);
  const mid = s.length >> 1;
  return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
}

/** Filters are equal when every whitelisted field agrees (absent === absent). */
function filtersEqual(a, b) {
  return FIELDS.every((f) => (a?.[f] ?? null) === (b?.[f] ?? null));
}

const compact = (f) =>
  Object.keys(f).length === 0 ? "{}" : JSON.stringify(f);

async function loadCases() {
  const text = await readFile(CASES_PATH, "utf8");
  return text
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean)
    .map((l, i) => {
      try {
        return JSON.parse(l);
      } catch (e) {
        throw new Error(`cases.jsonl line ${i + 1} is not valid JSON: ${e.message}`);
      }
    });
}

/** The Worker truncates before parsing; the eval must do the same or it would
 *  measure behavior the deployed endpoint never exhibits. */
const asWorkerSees = (q) => (q || "").slice(0, MAX_QUESTION_CHARS);

/* ------------------------------------------------------------ drift check */

/** Extract a function body by brace matching from its declaration. */
function functionBody(source, declaration) {
  const start = source.indexOf(declaration);
  if (start === -1) return null;
  const open = source.indexOf("{", start);
  if (open === -1) return null;
  let depth = 0;
  for (let i = open; i < source.length; i++) {
    if (source[i] === "{") depth++;
    else if (source[i] === "}" && --depth === 0) return source.slice(open, i + 1);
  }
  return null;
}

/** Collect regex literals from a function body. Adequate here because neither
 *  copy of the parser contains a division operator or a regex in a string. */
function regexLiterals(body) {
  const out = body.match(/\/(?:\\.|\[(?:\\.|[^\]])*\]|[^/\\\n])+\/[gimsuy]*/g) || [];
  return out.map((r) => r.trim());
}

async function driftCheck() {
  const [appSrc, parserSrc] = await Promise.all([
    readFile(APP_JS_PATH, "utf8"),
    readFile(PARSER_PATH, "utf8"),
  ]);
  const browser = functionBody(appSrc, "function localRuleParse(");
  const worker = functionBody(parserSrc, "export function ruleParse(");
  if (!browser || !worker) {
    return { ok: false, reason: "could not locate one of the two parser functions" };
  }
  const a = regexLiterals(worker);
  const b = regexLiterals(browser);
  const same = a.length === b.length && a.every((r, i) => r === b[i]);
  return {
    ok: same,
    reason: same
      ? `${a.length} regex literals identical in both copies`
      : `worker: ${JSON.stringify(a)}\n    browser: ${JSON.stringify(b)}`,
  };
}

/* ---------------------------------------------------------- rule-path eval */

function evalRules(cases) {
  const perField = Object.fromEntries(FIELDS.map((f) => [f, { ok: 0, n: 0 }]));
  const latencies = [];
  const results = [];

  for (const c of cases) {
    const q = asWorkerSees(c.question);
    const t0 = performance.now();
    const got = validateFilter(ruleParse(q));
    latencies.push(performance.now() - t0);

    for (const f of FIELDS) {
      perField[f].n++;
      if ((got[f] ?? null) === (c.expect[f] ?? null)) perField[f].ok++;
    }
    results.push({ ...c, got, pass: filtersEqual(got, c.expect) });
  }

  const refusals = results.filter((r) => Object.keys(r.expect).length === 0);
  return {
    results,
    perField,
    exactMatch: results.filter((r) => r.pass).length,
    total: results.length,
    refusalOk: refusals.filter((r) => Object.keys(r.got).length === 0).length,
    refusalTotal: refusals.length,
    medianLatencyMs: median(latencies),
  };
}

/* ----------------------------------------------------------- LLM-path eval */

async function loadFixtures() {
  if (!existsSync(fileURLToPath(FIXTURES_PATH))) return null;
  const raw = JSON.parse(await readFile(FIXTURES_PATH, "utf8"));
  return raw?.responses && Object.keys(raw.responses).length ? raw : null;
}

/** Replay recorded model output through the same extract+validate path the
 *  Worker uses, so the numbers describe the shipped pipeline, not the raw model. */
function evalFixtures(cases, fixtures) {
  const byId = fixtures.responses;
  const rows = [];
  for (const c of cases) {
    const rec = byId[c.id];
    if (!rec) continue;
    const parsed = extractJson(rec.content ?? "");
    const filter = parsed ? validateFilter(parsed) : {};
    // The Worker falls back to rules when the LLM yields nothing usable.
    const fellBack = !parsed || Object.keys(filter).length === 0;
    rows.push({
      id: c.id,
      expect: c.expect,
      got: filter,
      pass: filtersEqual(filter, c.expect),
      fellBack,
      latencyMs: rec.latencyMs ?? null,
    });
  }
  if (!rows.length) return null;
  return {
    n: rows.length,
    exactMatch: rows.filter((r) => r.pass).length,
    fallbacks: rows.filter((r) => r.fellBack).length,
    medianLatencyMs: median(rows.map((r) => r.latencyMs).filter((x) => x != null)),
    recordedAt: fixtures.recorded_utc ?? null,
    models: fixtures.models ?? null,
    rows,
  };
}

/* --------------------------------------------------------------- live mode */

async function runLive(cases, record) {
  const key = process.env.OPENROUTER_API_KEY;
  if (!key) {
    console.error("--live needs OPENROUTER_API_KEY in the environment.");
    process.exit(2);
  }
  const models = [
    process.env.PRIMARY_MODEL || DEFAULT_PRIMARY,
    process.env.FALLBACK_MODEL || DEFAULT_FALLBACK,
  ];
  const responses = {};
  for (const c of cases) {
    const q = asWorkerSees(c.question);
    const t0 = performance.now();
    let content = "";
    try {
      const resp = await fetch("https://openrouter.ai/api/v1/chat/completions", {
        method: "POST",
        headers: {
          Authorization: `Bearer ${key}`,
          "Content-Type": "application/json",
          "HTTP-Referer": "https://sites.consultruss.com",
          "X-Title": "Site Screen ask-the-map eval",
        },
        body: JSON.stringify({
          models,
          temperature: 0,
          max_tokens: 200,
          response_format: { type: "json_object" },
          messages: [
            { role: "system", content: SYSTEM_PROMPT },
            { role: "user", content: q },
          ],
        }),
        signal: AbortSignal.timeout(20000),
      });
      const data = resp.ok ? await resp.json() : null;
      content = data?.choices?.[0]?.message?.content ?? "";
    } catch {
      content = "";
    }
    responses[c.id] = { content, latencyMs: performance.now() - t0 };
    process.stderr.write(".");
  }
  process.stderr.write("\n");

  const payload = { recorded_utc: new Date().toISOString(), models, responses };
  if (record) {
    await writeFile(FIXTURES_PATH, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
    console.error(`recorded ${Object.keys(responses).length} responses -> ${FIXTURES_PATH.pathname}`);
  }
  return payload;
}

/* ----------------------------------------------------------------- report */

function report(rules, llm, drift, cases) {
  const L = [];
  L.push("# Ask-the-map eval\n");
  L.push(`Cases: **${rules.total}** · fields: ${FIELDS.join(", ")}\n`);

  L.push("## Deterministic rule parser (offline, every push)\n");
  L.push("| Metric | Value |");
  L.push("|---|---|");
  L.push(`| Exact-match rate | **${fmtPct(rules.exactMatch, rules.total)}** (${rules.exactMatch}/${rules.total}) |`);
  L.push(`| Correct refusals | **${fmtPct(rules.refusalOk, rules.refusalTotal)}** (${rules.refusalOk}/${rules.refusalTotal}) |`);
  L.push(`| Median latency | ${rules.medianLatencyMs.toFixed(3)} ms |`);
  L.push("");

  L.push("### Per-field accuracy\n");
  L.push("| Field | Accuracy |");
  L.push("|---|---|");
  for (const f of FIELDS) {
    const { ok, n } = rules.perField[f];
    L.push(`| \`${f}\` | ${fmtPct(ok, n)} (${ok}/${n}) |`);
  }
  L.push("");

  L.push("### By category\n");
  const tags = [...new Set(cases.flatMap((c) => c.tags || []))].sort();
  L.push("| Category | Exact-match |");
  L.push("|---|---|");
  for (const t of tags) {
    const sub = rules.results.filter((r) => (r.tags || []).includes(t));
    if (sub.length < 2) continue;
    L.push(`| ${t} | ${fmtPct(sub.filter((r) => r.pass).length, sub.length)} (${sub.filter((r) => r.pass).length}/${sub.length}) |`);
  }
  L.push("");

  const fails = rules.results.filter((r) => !r.pass);
  L.push(`### Known failures (${fails.length})\n`);
  if (!fails.length) {
    L.push("None.\n");
  } else {
    L.push("| Case | Question | Correct | Parser returns |");
    L.push("|---|---|---|---|");
    for (const f of fails) {
      const q = f.question.length > 60 ? `${f.question.slice(0, 57)}…` : f.question || "(empty)";
      L.push(`| \`${f.id}\` | ${q.replace(/\|/g, "\\|")} | \`${compact(f.expect)}\` | \`${compact(f.got)}\` |`);
    }
    L.push("");
  }

  L.push("## LLM path\n");
  if (!llm) {
    L.push("**Not measured.** No recorded model responses in `fixtures/openrouter.json`.");
    L.push("Run `node worker/evals/run.mjs --live --record` with an `OPENROUTER_API_KEY` to");
    L.push("populate them; until then the fallback rate and model accuracy are unknown, and");
    L.push("the numbers above describe the deterministic parser alone.\n");
  } else {
    L.push("| Metric | Value |");
    L.push("|---|---|");
    L.push(`| Exact-match rate | **${fmtPct(llm.exactMatch, llm.n)}** (${llm.exactMatch}/${llm.n}) |`);
    L.push(`| Fallback rate (LLM yielded nothing usable → rules) | **${fmtPct(llm.fallbacks, llm.n)}** (${llm.fallbacks}/${llm.n}) |`);
    if (llm.medianLatencyMs != null) L.push(`| Median latency | ${Math.round(llm.medianLatencyMs)} ms |`);
    if (llm.models) L.push(`| Models | ${llm.models.join(" → ")} |`);
    if (llm.recordedAt) L.push(`| Recorded | ${llm.recordedAt} |`);
    L.push("");
  }

  L.push("## Parser drift (worker vs. browser copy)\n");
  L.push(drift.ok ? `PASS — ${drift.reason}\n` : `**FAIL** — the two copies disagree:\n\n    ${drift.reason}\n`);

  return L.join("\n");
}

/* ------------------------------------------------------------------- main */

const cases = await loadCases();
const rules = evalRules(cases);
const drift = await driftCheck();

let fixtures = await loadFixtures();
if (argv.has("--live")) fixtures = await runLive(cases, argv.has("--record"));
const llm = fixtures ? evalFixtures(cases, fixtures) : null;

if (argv.has("--json")) {
  console.log(
    JSON.stringify(
      {
        cases: rules.total,
        rules: {
          exact_match: pct(rules.exactMatch, rules.total),
          refusal_correctness: pct(rules.refusalOk, rules.refusalTotal),
          median_latency_ms: rules.medianLatencyMs,
          per_field: Object.fromEntries(
            FIELDS.map((f) => [f, pct(rules.perField[f].ok, rules.perField[f].n)])
          ),
          failures: rules.results.filter((r) => !r.pass).map((r) => r.id),
        },
        llm: llm
          ? {
              exact_match: pct(llm.exactMatch, llm.n),
              fallback_rate: pct(llm.fallbacks, llm.n),
              median_latency_ms: llm.medianLatencyMs,
            }
          : null,
        drift_ok: drift.ok,
      },
      null,
      2
    )
  );
} else {
  console.log(report(rules, llm, drift, cases));
  if (argv.has("--failures")) {
    console.log("\n## Failing cases in full\n");
    for (const f of rules.results.filter((r) => !r.pass)) {
      console.log(`- ${f.id}: ${JSON.stringify(f.question)}`);
      console.log(`    expect ${compact(f.expect)}  got ${compact(f.got)}`);
      if (f.note) console.log(`    note: ${f.note}`);
    }
  }
}

if (argv.has("--ci")) {
  const th = JSON.parse(await readFile(THRESHOLDS_PATH, "utf8"));
  const checks = [
    ["rule exact-match", pct(rules.exactMatch, rules.total), th.min_exact_match_pct],
    ["refusal correctness", pct(rules.refusalOk, rules.refusalTotal), th.min_refusal_correctness_pct],
  ];
  let failed = !drift.ok;
  if (!drift.ok) console.error("FAIL parser drift: the worker and browser parsers disagree");
  for (const [name, got, floor] of checks) {
    if (got + 1e-9 < floor) {
      console.error(`FAIL ${name}: ${got.toFixed(1)}% < floor ${floor}%`);
      failed = true;
    }
  }
  process.exit(failed ? 1 : 0);
}
