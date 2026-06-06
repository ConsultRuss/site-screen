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
import sys
from pathlib import Path

from . import build, export, fetch
from .config import load_config
from .scoring import rank_parcels


def _add_common(sp: argparse.ArgumentParser) -> None:
    sp.add_argument("--config", default="config.yaml", help="path to config.yaml")


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


def cmd_m1_stub(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    stage = {"fetch": fetch, "build": build}.get(args.command)
    try:
        if stage is not None:
            stage.run(cfg)
        else:  # run = full pipeline
            fetch.run(cfg)
    except fetch.StageNotImplemented as exc:
        print(f"[{args.command}] {exc}", file=sys.stderr)
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pipeline", description="South Texas site-screen scoring pipeline"
    )
    sub = p.add_subparsers(dest="command", required=True)

    for name, helptext in [
        ("fetch", "download + cache public source layers (M1)"),
        ("build", "clip / exclude / compute per-parcel metrics (M1)"),
        ("run", "fetch -> build -> score -> export, end to end (M1)"),
    ]:
        sp = sub.add_parser(name, help=helptext)
        _add_common(sp)
        sp.set_defaults(func=cmd_m1_stub)

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
