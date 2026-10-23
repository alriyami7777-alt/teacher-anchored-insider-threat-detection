"""Path guards and safety checks for r5.2 teacher-anchored reproducibility."""

from __future__ import annotations

from pathlib import Path

from .constants import FORBIDDEN_PATH_MARKERS, FORBIDDEN_WRITE_PREFIXES, OUTPUT_REL


class ProtectedDataAccessError(RuntimeError):
    """Raised when a blocked test/protected path would be opened or written."""


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
    # Must live under the allowed output namespace (relative check via parts).
    s = _norm(p)
    allowed = _norm(OUTPUT_REL)
    if allowed not in s and not s.endswith(allowed.rstrip("/")):
        # Also accept absolute paths that contain the namespace segment.
        if "r52_teacher_anchored_reproducibility_v1" not in s:
            raise ProtectedDataAccessError(
                f"Write outside allowed namespace: {p} (need {OUTPUT_REL})"
            )
    for prefix in FORBIDDEN_WRITE_PREFIXES:
        # Disallow writing into forbidden trees even if somehow nested.
        if f"/{prefix.rstrip('/').lower()}/" in f"/{s}/" and "r52_teacher_anchored_reproducibility_v1" not in s:
            raise ProtectedDataAccessError(f"Forbidden write prefix: {p}")
    return p


def refuse_test_loader_construction(*, partition: str) -> None:
    if partition.lower() in {"test", "later-development", "later_development", "r62", "r6.2"}:
        raise ProtectedDataAccessError(
            f"Test/protected loader construction refused for partition={partition!r}"
        )


def gpu_busy_with_protected_jobs(nvidia_smi_text: str) -> bool:
    """Heuristic: non-idle compute processes that look like protected experiments."""
    lower = nvidia_smi_text.lower()
    markers = (
        "python",
        "objective",
        "train",
        "torch",
    )
    # If Processes section shows only No running processes, GPU is free.
    if "no running processes found" in lower:
        return False
    # Cursor/shell alone are OK; competing python training is not.
    if "python" in lower and ("cuda" in lower or "c" in lower):
        # Conservative: if any python GPU process exists, treat as blocked for launch decision upstream.
        lines = [ln for ln in nvidia_smi_text.splitlines() if "python" in ln.lower()]
        return len(lines) > 0
    return False
