"""Path guards for matched temporal-learning (forward-pass only)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .constants import FORBIDDEN_PATH_MARKERS, FORBIDDEN_WRITE_PREFIXES, OUTPUT_REL


class ProtectedDataAccessError(RuntimeError):
    pass


class TemporalBlockedError(RuntimeError):
    def __init__(self, status: str, message: str = "") -> None:
        self.status = status
        super().__init__(message or status)


def _norm(p: Path | str) -> str:
    return Path(p).as_posix().replace("\\", "/").lower()


def assert_path_allowed_for_read(path: Path | str, *, context: str = "") -> Path:
    p = Path(path)
    s = _norm(p)
    for marker in FORBIDDEN_PATH_MARKERS:
        if marker.lower() in s:
            raise ProtectedDataAccessError(
                f"Blocked protected-path access ({context}): {p} matched '{marker}'"
            )
    return p


def assert_output_namespace(path: Path | str) -> Path:
    p = Path(path).resolve()
    s = _norm(p)
    if "r52_matched_temporal_learning_v1" not in s:
        raise ProtectedDataAccessError(f"Write outside allowed namespace: {p}")
    for prefix in FORBIDDEN_WRITE_PREFIXES:
        pref = prefix.rstrip("/").lower()
        if f"/{pref}/" in f"/{s}/" and "r52_matched_temporal_learning_v1" not in s:
            raise ProtectedDataAccessError(f"Forbidden write prefix: {p}")
    return p


def refuse_test_loader(partition: str) -> None:
    if partition.lower() in {"test", "later-development", "later_development", "r62", "r6.2"}:
        raise ProtectedDataAccessError(f"Test/protected loader refused: {partition!r}")


def sha256_file(path: Path) -> str:
    assert_path_allowed_for_read(path, context="hash")
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_array(arr: Any) -> str:
    import numpy as np

    a = np.ascontiguousarray(arr)
    return hashlib.sha256(a.tobytes()).hexdigest()


def write_json_atomic(path: Path, payload: Any) -> None:
    assert_output_namespace(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)
