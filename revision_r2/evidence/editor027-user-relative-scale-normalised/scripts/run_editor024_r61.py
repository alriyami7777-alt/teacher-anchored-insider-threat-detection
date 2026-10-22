"""CLI entry for EDITOR-024 r6.1 final confirmation."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from editor024_r61.campaign import run_campaign  # noqa: E402
from editor024_r61.protocol import freeze_protocol  # noqa: E402
from editor024_r61.training_gate import assert_no_training  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("protocol", "evaluate"), default="evaluate")
    args = parser.parse_args()
    assert_no_training()
    if args.phase == "protocol":
        freeze_protocol()
        return
    payload = run_campaign()
    print(Path("review/editor024_r61_final_confirmation/EDITOR024_TERMINAL_BLOCK.txt").read_text(encoding="utf-8"))
    print(f"SHA_MANIFEST_VERIFICATION = {payload['SHA_MANIFEST_VERIFICATION']}")


if __name__ == "__main__":
    main()
