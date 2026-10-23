#!/usr/bin/env python3
"""Prepare CERT common-13 event / daily / T=20 sequence artefacts.

Default target is CERT r5.2 (primary confirmatory release). Preparation only:
  - no model training
  - no test-set evaluation
  - no writes into raw folders
  - does not modify locked r4.2 / Objective 2 / Objective 3 artefacts

Examples:
  python scripts/prepare_cert_common13_pipeline.py --dataset-version 5.2 --smoke
  python scripts/prepare_cert_common13_pipeline.py --dataset-version 5.2
  python scripts/prepare_cert_common13_pipeline.py --dataset-version 5.2 \\
      --stages match,label_events
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

# Line-buffered logs when redirected to files.
try:
    sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
    sys.stderr.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
except Exception:
    pass

from cert_common13_pipeline import (  # noqa: E402
    ALL_STAGES,
    COMMON_13_FEATURES,
    PipelinePaths,
    run_pipeline,
)
from dataset_registry import (  # noqa: E402
    DatasetVersionError,
    add_dataset_path_arguments,
    assert_raw_is_readonly_target,
    normalize_dataset_version,
    print_resolved_paths,
    refuse_mixed_versions,
    resolve_dataset_paths,
)

TRAINING_FLAGS = (
    "train",
    "fit",
    "evaluate_test",
    "evaluate-test",
    "retrain",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare event-labelled, daily behavioural, and T=20 sequence artefacts "
            "using the verified common 13-feature schema."
        )
    )
    add_dataset_path_arguments(parser, default_version="5.2")
    parser.add_argument(
        "--stages",
        default=",".join(ALL_STAGES),
        help=f"Comma-separated stages to run. Allowed: {','.join(ALL_STAGES)}",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Row-capped plumbing run (not for confirmatory modelling).",
    )
    parser.add_argument(
        "--max-scan-rows-per-file",
        type=int,
        default=None,
        help="Cap raw rows scanned during malicious-ID matching.",
    )
    parser.add_argument(
        "--max-rows-per-log",
        type=int,
        default=None,
        help="Cap rows labelled per activity log (smoke / debug).",
    )
    for flag in TRAINING_FLAGS:
        parser.add_argument(
            f"--{flag}",
            action="store_true",
            default=False,
            help=argparse.SUPPRESS,
        )
    return parser


def _refuse_training(args: argparse.Namespace) -> None:
    for name in TRAINING_FLAGS:
        attr = name.replace("-", "_")
        if getattr(args, attr, False):
            raise SystemExit(
                f"REFUSED: preparation must not perform '{name}'. "
                "training_started=false, test_evaluated=false."
            )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _refuse_training(args)

    version = normalize_dataset_version(args.dataset_version)
    paths = resolve_dataset_paths(
        version,
        raw_dir=args.raw_dir,
        answers_dir=args.answers_dir,
        processed_dir=args.processed_dir,
        output_dir=args.output_dir,
    )
    print_resolved_paths(paths)
    assert_raw_is_readonly_target(paths.raw_dir)
    refuse_mixed_versions(version, paths.raw_dir)

    # When --output-dir is passed to resolve_dataset_paths it becomes readiness
    # output; for this pipeline treat explicit --output-dir as the report root.
    report_root = None
    if args.output_dir is not None:
        report_root = Path(args.output_dir)
        if not report_root.is_absolute():
            report_root = (Path(__file__).resolve().parents[1] / report_root).resolve()

    pipe = PipelinePaths.from_resolved(paths, output_dir=report_root)
    # Keep processed under the registry default unless overridden.
    if args.processed_dir is not None:
        pipe.processed_dir = paths.processed_dir

    stages = tuple(s.strip() for s in args.stages.split(",") if s.strip())
    print("=" * 72)
    print(f"CERT {version} common-13 preparation pipeline")
    print("=" * 72)
    print(f"Stages             : {', '.join(stages)}")
    print(f"Common-13 features : {len(COMMON_13_FEATURES)}")
    print(f"Processed dir      : {pipe.processed_dir}")
    print(f"Report dir         : {pipe.output_dir}")
    print(f"Smoke              : {args.smoke}")
    print()

    try:
        manifest = run_pipeline(
            pipe,
            stages=stages,
            smoke=bool(args.smoke),
            max_scan_rows_per_file=args.max_scan_rows_per_file,
            max_rows_per_log=args.max_rows_per_log,
        )
    except DatasetVersionError as exc:
        raise SystemExit(f"REFUSED: {exc}") from exc

    print()
    print("=" * 72)
    print("PIPELINE COMPLETE")
    print("=" * 72)
    print(f"Manifest           : {pipe.manifest_json}")
    print(f"Stages completed   : {', '.join(manifest['stages_completed'])}")
    print(f"training_started   : {manifest['training_started']}")
    print(f"test_evaluated     : {manifest['test_evaluated']}")
    if args.smoke:
        print(
            "NOTE: smoke artefacts are plumbing-only; do not use for confirmatory evaluation."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
