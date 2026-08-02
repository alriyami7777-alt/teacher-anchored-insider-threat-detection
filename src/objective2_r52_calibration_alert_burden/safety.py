"""Safety guards for calibration + alert-burden audit."""

from __future__ import annotations

import hashlib
import json
import platform
import sys
from pathlib import Path
from typing import Any

from .constants import FORBIDDEN_PATH_MARKERS, FORBIDDEN_WRITE_PREFIXES, OUTPUT_REL


class ProtectedDataAccessError(RuntimeError):
    pass


class AuditBlockedError(RuntimeError):
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
    if p.name.lower().endswith("_test.npz") or "test_predictions" in p.name.lower():
        raise ProtectedDataAccessError(f"Blocked test artefact ({context}): {p}")
    return p


def assert_output_namespace(path: Path | str) -> Path:
    p = Path(path).resolve()
    s = _norm(p)
    if "r52_calibration_alert_burden_v1" not in s:
        raise ProtectedDataAccessError(f"Write outside allowed namespace: {p}")
    for prefix in FORBIDDEN_WRITE_PREFIXES:
        pref = prefix.rstrip("/").lower()
        if f"/{pref}/" in f"/{s}/" and "r52_calibration_alert_burden_v1" not in s:
            raise ProtectedDataAccessError(f"Forbidden write prefix: {p}")
    return p


def refuse_test_loader(partition: str) -> None:
    if partition.lower() in {"test", "later-development", "later_development", "r62", "r6.2"}:
        raise ProtectedDataAccessError(f"Test/protected loader refused: {partition!r}")


def refuse_training() -> None:
    raise ProtectedDataAccessError(
        "Calibration audit forbids neural training, optimisers, and backward passes"
    )


def refuse_teacher_load(path: Path | str | None = None) -> None:
    raise ProtectedDataAccessError(
        f"Teacher checkpoint loading is forbidden{f': {path}' if path else ''}"
    )


def sha256_file(path: Path) -> str:
    assert_path_allowed_for_read(path, context="hash")
    h = hashlib.sha256()
    with path.open("rb") as f:
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


def write_csv_atomic(path: Path, df) -> None:
    assert_output_namespace(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    df.to_csv(tmp, index=False)
    tmp.replace(path)


def environment_metadata() -> dict[str, Any]:
    import numpy as np
    import pandas as pd
    import sklearn

    meta: dict[str, Any] = {
        "python": sys.version,
        "platform": platform.platform(),
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "sklearn": sklearn.__version__,
        "executable": sys.executable,
        "stage": "objective2_r52_calibration_alert_burden",
        "training": False,
        "test_used": False,
        "teacher_loaded": False,
        "output_rel": str(OUTPUT_REL),
    }
    try:
        import torch

        meta["torch"] = torch.__version__
        meta["cuda_available"] = bool(torch.cuda.is_available())
    except Exception:
        meta["torch"] = None
        meta["cuda_available"] = False
    try:
        import scipy

        meta["scipy"] = scipy.__version__
    except Exception:
        meta["scipy"] = None
    return meta


class OpenedFilesRegister:
    def __init__(self) -> None:
        self.rows: list[dict[str, str]] = []

    def record(self, path: Path, purpose: str, columns: str = "") -> Path:
        assert_path_allowed_for_read(path, context=purpose)
        self.rows.append(
            {"path": str(path.resolve()), "purpose": purpose, "columns": columns}
        )
        return path

    def to_dataframe(self):
        import pandas as pd

        return pd.DataFrame(self.rows)
