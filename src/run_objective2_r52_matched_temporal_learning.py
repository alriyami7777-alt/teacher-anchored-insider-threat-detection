#!/usr/bin/env python
"""Matched temporal-learning comparison Stage 2 (forward-pass only)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if REPO_ROOT.name == "scripts":
    REPO_ROOT = REPO_ROOT.parent
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

from objective2_r52_matched_temporal_learning.pipeline import run_pipeline  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    args = parser.parse_args()
    result = run_pipeline(args.repo_root.resolve())
    print(json.dumps(result, indent=2, default=str))
    ok = result["status"] in {
        "objective2_matched_temporal_learning_complete",
        "objective2_matched_temporal_learning_complete_with_limits",
    }
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
