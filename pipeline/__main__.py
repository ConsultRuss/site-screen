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
from .scoring import rank_parcels


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


def cmd_run(args: argparse.Namespace) -> int:
    """fetch -> build -> score -> synthesize -> export, end to end."""
    from .synthetic import assign_synthetic

    cfg = load_config(args.config)
    print("== fetch ==")
    fetch.run(cfg)
    print("== build ==")
    fc = build.run(cfg)
    print("== score + synthesize ==")
    from .scoring import agrivoltaic_score, flex_load_score

    props = [f["properties"] for f in fc["features"]]
    rank_parcels(props, cfg)
    for p in props:
        p["flex_load_score"] = flex_load_score(p, cfg)
        p["agrivoltaic_score"] = agrivoltaic_score(p, cfg)
    assign_synthetic(fc, cfg)
    print("== export ==")
    out = REPO_ROOT / "web" / "data" / "parcels.geojson"
    export.write_geojson(fc, out)
    export.write_run_metadata(
        cfg,
        REPO_ROOT / "data" / "screen_run.json",
        extra={
            "parcel_count": len(fc["features"]),
            "shortlist_count": sum(1 for p in props if p["pipeline_status"]),
            "criteria_status": fc.get("_criteria_status"),
            "lenses": {
                "flex_load": "live (curtailment-basis neutral — needs nodal LMP)",
                "agrivoltaic": "live",
            },
        },
    )
    print(f"run complete: {len(fc['features'])} parcels -> {out}")
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

    sp_run = sub.add_parser("run", help="fetch -> build -> score -> export, end to end")
    _add_common(sp_run)
    sp_run.set_defaults(func=cmd_run)

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
