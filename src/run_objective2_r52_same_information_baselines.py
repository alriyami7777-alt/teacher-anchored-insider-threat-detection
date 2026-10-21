#!/usr/bin/env python
"""Run locked same-information baseline comparison for CERT r5.2 (Objective 2)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
ROOT = Path(__file__).resolve().parents[1]
# repo root is parent of scripts/
REPO_ROOT = Path(__file__).resolve().parents[1]
if REPO_ROOT.name == "scripts":
    REPO_ROOT = REPO_ROOT.parent
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

from objective2_r52_same_information_baselines.pipeline import run_pipeline  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=REPO_ROOT,
        help="Repository / worktree root",
    )
    parser.add_argument(
        "--force-cpu-mlp",
        action="store_true",
        help="Force MLP onto CPU even if CUDA is available",
    )
    args = parser.parse_args()
    result = run_pipeline(args.repo_root.resolve(), force_cpu_mlp=args.force_cpu_mlp)
    print(json_dumps(result))
    return 0 if "complete" in result["status"] else 2


def json_dumps(obj: object) -> str:
    import json

    return json.dumps(obj, indent=2, default=str)


if __name__ == "__main__":
    raise SystemExit(main())
