"""Path guards and compute-protection helpers."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from .constants import FORBIDDEN_PATH_MARKERS, FORBIDDEN_WRITE_PREFIXES, OUTPUT_REL


class ProtectedDataAccessError(RuntimeError):
    """Raised when a blocked test/protected path would be opened or written."""


class ComparisonBlockedError(RuntimeError):
    """Raised for declared comparison stop statuses."""

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
    if "r52_same_information_baselines_v1" not in s:
        raise ProtectedDataAccessError(
            f"Write outside allowed namespace: {p} (need {OUTPUT_REL})"
        )
    for prefix in FORBIDDEN_WRITE_PREFIXES:
        pref = prefix.rstrip("/").lower()
        if f"/{pref}/" in f"/{s}/" and "r52_same_information_baselines_v1" not in s:
            raise ProtectedDataAccessError(f"Forbidden write prefix: {p}")
    return p


def refuse_test_loader_construction(*, partition: str) -> None:
    if partition.lower() in {"test", "later-development", "later_development", "r62", "r6.2"}:
        raise ProtectedDataAccessError(
            f"Test/protected loader construction refused for partition={partition!r}"
        )


def refuse_overwrite(path: Path) -> None:
    if path.exists():
        raise ProtectedDataAccessError(f"Refuse overwrite of existing artefact: {path}")


def sha256_file(path: Path) -> str:
    assert_path_allowed_for_read(path, context="hash")
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_array(arr: Any) -> str:
    import numpy as np

    a = np.ascontiguousarray(arr)
    return hashlib.sha256(a.tobytes()).hexdigest()


def write_json_atomic(path: Path, payload: Any) -> None:
    assert_output_namespace(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=False, default=str), encoding="utf-8")
    tmp.replace(path)


def software_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for name in ("numpy", "pandas", "sklearn", "xgboost", "torch", "joblib", "matplotlib"):
        try:
            mod = __import__(name if name != "sklearn" else "sklearn")
            versions[name] = getattr(mod, "__version__", "unknown")
        except Exception:
            versions[name] = "unavailable"
    return versions


def nvidia_smi_text() -> str:
    try:
        r = subprocess.run(
            ["nvidia-smi"],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        return (r.stdout or "") + (r.stderr or "")
    except Exception as exc:  # noqa: BLE001
        return f"nvidia-smi_unavailable: {exc}"


def gpu_busy_with_protected_jobs(nvidia_text: str) -> bool:
    lower = nvidia_text.lower()
    if "no running processes found" in lower:
        return False
    lines = [ln for ln in nvidia_text.splitlines() if "python" in ln.lower()]
    return len(lines) > 0


def list_python_processes() -> list[dict[str, Any]]:
    try:
        r = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
                "Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        raw = (r.stdout or "").strip()
        if not raw:
            return []
        data = json.loads(raw)
        if isinstance(data, dict):
            return [data]
        return list(data)
    except Exception:  # noqa: BLE001
        return []
