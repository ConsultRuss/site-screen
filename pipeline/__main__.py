"""CLI entry point: ``python -m pipeline <command> [--config config.yaml]``.

Commands:
    fetch   download + cache the public source layers          (M1)
    build   clip / exclude / compute per-parcel metrics        (M1)
    score   (re)apply the weighted model to a parcels GeoJSON   (works now)
    export  write run metadata (weights, study area, timestamp) (works now)
    run     fetch -> build -> score -> export, end to end       (M1)
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import build, export, fetch
from .config import REPO_ROOT, load_config
from .dedupe import dedupe_by_footprint
from .scoring import rank_parcels
from .verdicts import county_price_medians, parcel_flags


def _add_common(sp: argparse.ArgumentParser) -> None:
    sp.add_argument("--config", default=None, help="path to config.yaml (default: repo root)")


def cmd_score(args: argparse.Namespace) -> int:
    """Recompute suitability + rank for every feature in a parcels GeoJSON."""
    cfg = load_config(args.config)
    src = Path(args.input)
    fc = json.loads(src.read_text(encoding="utf-8"))
    props = [f["properties"] for f in fc.get("features", [])]
    rank_parcels(props, cfg)
    out = Path(args.output) if args.output else src
    out.write_text(json.dumps(fc, ensure_ascii=False), encoding="utf-8")
    print(f"scored {len(props)} parcels -> {out}")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    meta = export.write_run_metadata(cfg, args.output)
    print(f"wrote run metadata -> {args.output} (run {meta['run_utc']})")
    return 0


def cmd_fetch(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    status = fetch.run(cfg)
    ok = sum(1 for v in status.values() if v.get("ok"))
    print(f"fetch complete: {ok}/{len(status)} layers ok")
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    fc = build.run(cfg)
    out = REPO_ROOT / "data" / "raw" / "parcels_built.geojson"
    out.write_text(json.dumps(fc), encoding="utf-8")
    print(f"build complete: {len(fc['features'])} parcels -> {out}")
    return 0


_SYNTH_FIELDS = (
    "owner", "pipeline_status", "status_date", "title_flag", "est_price_per_ac", "notes"
)
WEB_GEOJSON = REPO_ROOT / "web" / "data" / "parcels.geojson"
RUN_META = REPO_ROOT / "data" / "screen_run.json"


def _finalize(fc: dict, cfg: dict) -> dict:
    """Post-build chain: de-dup duplicate footprints, (re)score + rank, lenses,
    synthetic ids, verdict flags. Idempotent — strips prior synthetic / flag /
    id fields first, so it is safe to re-run on an already-finalized GeoJSON."""
    from .scoring import agrivoltaic_score, flex_load_score
    from .synthetic import assign_synthetic

    fc["features"] = dedupe_by_footprint(fc["features"])
    props = [f["properties"] for f in fc["features"]]
    for p in props:
        for k in (*_SYNTH_FIELDS, "parcel_id", "flags", "suitability_rank"):
            p.pop(k, None)
    rank_parcels(props, cfg)
    for p in props:
        p["flex_load_score"] = flex_load_score(p, cfg)
        p["agrivoltaic_score"] = agrivoltaic_score(p, cfg)
    assign_synthetic(fc, cfg)
    medians = county_price_medians(props, cfg)
    for p in props:
        p["flags"] = parcel_flags(p, cfg, medians)
    return fc


def _run_meta_extra(fc: dict, existing: dict | None = None) -> dict:
    props = [f["properties"] for f in fc["features"]]
    existing = existing or {}
    return {
        "parcel_count": len(fc["features"]),
        "shortlist_count": sum(1 for p in props if p.get("pipeline_status")),
        "criteria_status": fc.get("_criteria_status") or existing.get("criteria_status"),
        "lenses": existing.get("lenses")
        or {
            "flex_load": "live (curtailment-basis neutral — needs nodal LMP)",
            "agrivoltaic": "live",
        },
        "verdict_layer": "live — config-driven flags (config.yaml verdict_rules); "
        "authored verdicts in web/data/verdicts.json",
    }


def cmd_run(args: argparse.Namespace) -> int:
    """fetch -> build -> finalize -> export, end to end."""
    cfg = load_config(args.config)
    print("== fetch ==")
    fetch.run(cfg)
    print("== build ==")
    fc = build.run(cfg)
    print("== finalize (dedup + score + synthesize + flags) ==")
    _finalize(fc, cfg)
    print("== export ==")
    export.write_geojson(fc, WEB_GEOJSON)
    export.write_run_metadata(cfg, RUN_META, extra=_run_meta_extra(fc))
    print(f"run complete: {len(fc['features'])} parcels -> {WEB_GEOJSON}")
    return 0


def cmd_rebuild(args: argparse.Namespace) -> int:
    """build (from cached raw) -> finalize -> export. Like ``run`` without re-fetching."""
    cfg = load_config(args.config)
    print("== build (cached raw) ==")
    fc = build.run(cfg)
    print("== finalize (dedup + score + synthesize + flags) ==")
    _finalize(fc, cfg)
    export.write_geojson(fc, WEB_GEOJSON)
    export.write_run_metadata(cfg, RUN_META, extra=_run_meta_extra(fc))
    print(f"rebuild complete: {len(fc['features'])} parcels -> {WEB_GEOJSON}")
    return 0


def cmd_finalize(args: argparse.Namespace) -> int:
    """Run the post-build chain on an existing built/scored GeoJSON (no geo stack)."""
    cfg = load_config(args.config)
    src = Path(args.input)
    fc = json.loads(src.read_text(encoding="utf-8"))
    before = len(fc["features"])
    _finalize(fc, cfg)
    out = Path(args.output) if args.output else src
    export.write_geojson(fc, out)
    existing = json.loads(RUN_META.read_text(encoding="utf-8")) if RUN_META.exists() else {}
    export.write_run_metadata(cfg, RUN_META, extra=_run_meta_extra(fc, existing))
    print(f"finalized {before} -> {len(fc['features'])} parcels -> {out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pipeline", description="South Texas site-screen scoring pipeline"
    )
    sub = p.add_subparsers(dest="command", required=True)

    sp_fetch = sub.add_parser("fetch", help="download + cache public source layers")
    _add_common(sp_fetch)
    sp_fetch.set_defaults(func=cmd_fetch)

    sp_build = sub.add_parser("build", help="clip / exclude / compute per-parcel metrics")
    _add_common(sp_build)
    sp_build.set_defaults(func=cmd_build)

    sp_run = sub.add_parser("run", help="fetch -> build -> finalize -> export, end to end")
    _add_common(sp_run)
    sp_run.set_defaults(func=cmd_run)

    sp_rebuild = sub.add_parser(
        "rebuild", help="build from cached raw -> finalize -> export (no fetch)"
    )
    _add_common(sp_rebuild)
    sp_rebuild.set_defaults(func=cmd_rebuild)

    sp_finalize = sub.add_parser(
        "finalize", help="dedup + score + synthesize + verdict flags on a built GeoJSON"
    )
    _add_common(sp_finalize)
    sp_finalize.add_argument("--input", default="web/data/parcels.geojson")
    sp_finalize.add_argument("--output", default=None, help="defaults to overwriting --input")
    sp_finalize.set_defaults(func=cmd_finalize)

    sp_score = sub.add_parser("score", help="(re)apply the weighted model to a GeoJSON")
    _add_common(sp_score)
    sp_score.add_argument("--input", default="web/data/parcels.geojson")
    sp_score.add_argument("--output", default=None, help="defaults to overwriting --input")
    sp_score.set_defaults(func=cmd_score)

    sp_export = sub.add_parser("export", help="write run metadata")
    _add_common(sp_export)
    sp_export.add_argument("--output", default="data/screen_run.json")
    sp_export.set_defaults(func=cmd_export)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
