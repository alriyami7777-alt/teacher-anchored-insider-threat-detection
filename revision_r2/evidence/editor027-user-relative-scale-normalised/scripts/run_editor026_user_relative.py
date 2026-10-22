"""CLI for EDITOR-026 user-relative representation rescue."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from editor026_user_relative.campaign import run_campaign  # noqa: E402
from editor026_user_relative.protocol import freeze_protocol  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--phase",
        choices=("protocol", "stage0", "train", "evaluate", "all"),
        default="all",
    )
    args = parser.parse_args()
    if args.phase == "protocol":
        freeze_protocol()
        print("EDITOR026 protocol written")
        return
    payload = run_campaign(phase=args.phase)
    term = ROOT / "review" / "editor026_user_relative_representation" / "EDITOR026_TERMINAL_BLOCK.txt"
    if term.is_file():
        print(term.read_text(encoding="utf-8"))
    print(f"SHA_MANIFEST_VERIFICATION = {payload.get('SHA_MANIFEST_VERIFICATION', 'N/A')}")


if __name__ == "__main__":
    main()
