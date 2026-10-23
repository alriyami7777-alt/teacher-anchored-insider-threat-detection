"""Safety for read-only latency audit."""

from __future__ import annotations

import hashlib
import json
import platform
import sys
from pathlib import Path
from typing import Any

from .constants import FORBIDDEN_PATH_MARKERS, OUTPUT_REL


class ProtectedDataAccessError(RuntimeError):
    pass


class StudyBlockedError(RuntimeError):
    def __init__(self, status: str, message: str = "") -> None:
        self.status = status
        super().__init__(message or status)


def _norm(p: Path | str) -> str:
    return Path(p).as_posix().replace("\\", "/").lower()


def assert_path_allowed_for_read(path: Path | str, *, context: str = "") -> Path:
    p = Path(path)
    s = _norm(p)
    for marker in FORBIDDEN_PATH_MARKERS:
        if marker in s:
            raise ProtectedDataAccessError(f"Blocked ({context}): {p} matched '{marker}'")
    if "test.npz" in s:
        raise ProtectedDataAccessError(f"Blocked test artefact ({context}): {p}")
    return p


def assert_output_namespace(path: Path | str) -> Path:
    p = Path(path).resolve()
    if "r52_component_latency_audit_v1" not in _norm(p):
        raise ProtectedDataAccessError(f"Write outside namespace: {p}")
    return p


def refuse_training() -> None:
    raise ProtectedDataAccessError("Latency audit forbids training")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json_atomic(path: Path, payload: Any) -> None:
    assert_output_namespace(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def write_text_atomic(path: Path, text: str) -> None:
    assert_output_namespace(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def environment_metadata() -> dict[str, Any]:
    import numpy as np
    import pandas as pd
    import torch

    return {
        "python": sys.version,
        "platform": platform.platform(),
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "torch": torch.__version__,
        "cuda": bool(torch.cuda.is_available()),
        "training": False,
        "profiling_only": True,
        "study": "r52_component_latency_audit_v1",
        "output_rel": str(OUTPUT_REL),
    }
