"""CLI entry for EDITOR-014 temporal ODST value proof."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from editor014_temporal_odst.campaign import main  # noqa: E402


if __name__ == "__main__":
    main()
