"""JSON/CSV/NPY writers confined to the EDITOR-029 namespace."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import numpy as np

from .safety import refuse_historical_write


def write_json(path: Path, obj: Any) -> None:
    refuse_historical_write(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, default=str) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    refuse_historical_write(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    keys = fieldnames or list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in keys})


def write_npy(path: Path, array: np.ndarray) -> None:
    refuse_historical_write(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    np.save(path, np.asarray(array))


def write_npz(path: Path, **arrays: np.ndarray) -> None:
    refuse_historical_write(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, **arrays)


def write_text(path: Path, text: str) -> None:
    refuse_historical_write(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
