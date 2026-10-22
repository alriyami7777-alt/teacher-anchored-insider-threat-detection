"""CLI entry for EDITOR-017 explanation and degraded-input robustness."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from editor012_rescue.data import load_train_validation  # noqa: E402
from editor017_robustness.campaign import run_campaign  # noqa: E402
from editor017_robustness.protocol import freeze_protocol  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("protocol", "evaluate"), default="evaluate")
    args = parser.parse_args()
    if args.phase == "protocol":
        bundle = load_train_validation()
        freeze_protocol(y_val=bundle["val"].y)
        return
    run_campaign()


if __name__ == "__main__":
    main()
