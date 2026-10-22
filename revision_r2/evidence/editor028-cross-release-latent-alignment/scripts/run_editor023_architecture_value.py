"""CLI entry for EDITOR-023 positive architecture-value confirmation."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from editor012_rescue.data import load_train_validation  # noqa: E402
from editor023_architecture_value.campaign import run_campaign  # noqa: E402
from editor023_architecture_value.protocol import freeze_protocol  # noqa: E402
from editor023_architecture_value.training_gate import assert_no_training  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("protocol", "evaluate"), default="evaluate")
    args = parser.parse_args()
    assert_no_training()
    if args.phase == "protocol":
        bundle = load_train_validation()
        freeze_protocol(y_val=bundle["val"].y)
        return
    run_campaign()


if __name__ == "__main__":
    main()
