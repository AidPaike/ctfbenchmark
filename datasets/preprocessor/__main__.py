"""CLI entry point for the dataset preprocessor.

Usage::

    # Single challenge
    python -m datasets.preprocessor single --raw-path /data/raw/XBEN-001 --output-dir datasets/drafts

    # Batch — all challenges in a directory
    python -m datasets.preprocessor batch --raw-path /data/raw/xbow --output-dir datasets/xbow

    # Batch multi — multiple datasets from a JSON spec
    python -m datasets.preprocessor batch-multi specs.json --overwrite
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .base import BatchRunner
from .xbow import XbowPreprocessor


# ---------------------------------------------------------------------------
# Preprocessor registry — add new dataset types here
# ---------------------------------------------------------------------------

def _default_runner() -> BatchRunner:
    return BatchRunner(preprocessors=[XbowPreprocessor()])


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert raw CTF challenge directories into Droplet draft datasets.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # -- single --
    p_single = sub.add_parser("single", help="Process one raw challenge directory.")
    p_single.add_argument("--raw-path", required=True, type=Path)
    p_single.add_argument("--output-dir", required=True, type=Path)
    p_single.add_argument("--challenge-id", help="Override challenge id.")
    p_single.add_argument("--dataset-id", help="Override dataset suite id.")
    p_single.add_argument("--type", dest="dataset_type", default="xbow")
    p_single.add_argument("--overwrite", action="store_true")

    # -- batch --
    p_batch = sub.add_parser("batch", help="Process all challenges in a raw dataset directory.")
    p_batch.add_argument("--raw-path", required=True, type=Path)
    p_batch.add_argument("--output-dir", required=True, type=Path)
    p_batch.add_argument("--dataset-id", help="Override dataset suite id.")
    p_batch.add_argument("--type", dest="dataset_type", default="xbow")
    p_batch.add_argument("--overwrite", action="store_true")

    # -- batch-multi --
    p_multi = sub.add_parser("batch-multi", help="Process multiple datasets from a JSON spec file.")
    p_multi.add_argument("spec", type=Path, help="JSON: array of {type, raw_path, output_dir, dataset_id?}")
    p_multi.add_argument("--overwrite", action="store_true")

    return parser


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

def cmd_single(args: argparse.Namespace) -> int:
    preprocessor = _default_runner().get(args.dataset_type)
    result = preprocessor.process_one(
        args.raw_path, args.output_dir,
        challenge_id=args.challenge_id, dataset_id=args.dataset_id,
        overwrite=args.overwrite,
    )
    print(json.dumps({
        "challenge_id": result.challenge_id,
        "output_dir": str(result.output_dir),
        "name": result.metadata.name,
        "tags": result.metadata.tags,
    }, indent=2, ensure_ascii=False))
    return 0


def cmd_batch(args: argparse.Namespace) -> int:
    preprocessor = _default_runner().get(args.dataset_type)
    result = preprocessor.process_batch(
        args.raw_path, args.output_dir,
        dataset_id=args.dataset_id, overwrite=args.overwrite,
    )
    print(result.summary())
    return 0 if result.failed == 0 else 1


def cmd_batch_multi(args: argparse.Namespace) -> int:
    specs = json.loads(args.spec.read_text(encoding="utf-8"))
    results = _default_runner().run(specs, overwrite=args.overwrite)
    for r in results:
        print(r.summary())
        print()
    return 0 if sum(r.failed for r in results) == 0 else 1


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handler = {"single": cmd_single, "batch": cmd_batch, "batch-multi": cmd_batch_multi}
    return handler[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
