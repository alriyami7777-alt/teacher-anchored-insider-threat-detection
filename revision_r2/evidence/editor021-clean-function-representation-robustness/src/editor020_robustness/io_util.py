"""JSON/CSV writers confined to the EDITOR-020 namespace."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .safety import refuse_historical_write


def write_json(path: Path, obj: Any) -> None:
    refuse_historical_write(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, default=str), encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    refuse_historical_write(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        if fieldnames:
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
        else:
            path.write_text("", encoding="utf-8")
        return
    keys = fieldnames or list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in keys})
