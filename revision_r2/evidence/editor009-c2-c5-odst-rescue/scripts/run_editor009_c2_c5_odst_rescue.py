#!/usr/bin/env python
"""EDITOR-009 DEVELOPMENT RESCUE campaign runner."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from editor009_rescue.campaign import run_campaign  # noqa: E402
from editor009_rescue.safety import Editor009ProtocolError  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description="EDITOR-009 C2/C5/ODST rescue campaign")
    p.add_argument("--screening-seed", type=int, default=42)
    p.add_argument("--max-epochs", type=int, default=None, help="Override locked 15 only for smoke tests")
    args = p.parse_args()
    try:
        out = run_campaign(screening_seed=args.screening_seed, max_epochs=args.max_epochs)
    except Editor009ProtocolError as exc:
        print(f"EDITOR-009 HARD BLOCK: {exc}", flush=True)
        return 2
    print("EDITOR009_OVERNIGHT_RESCUE_COMPLETE", flush=True)
    print(f"GATE={out['gate']} BEST={out['best']} PROMOTED={out['promoted']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
