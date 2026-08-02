"""CLI entry: python -m objective2_r52_calibration_alert_burden"""

from __future__ import annotations

import argparse
from pathlib import Path

from .pipeline import run


def main() -> None:
    p = argparse.ArgumentParser(
        description="r5.2 grouped calibration + operational alert-burden audit"
    )
    p.add_argument("--repo-root", type=Path, default=None)
    args = p.parse_args()
    run(repo_root=args.repo_root)


if __name__ == "__main__":
    main()
