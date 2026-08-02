"""Path guards for the r5.2 teacher-anchoring ablation namespace."""

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
    s = _norm(p)
    if "r52_teacher_anchoring_ablation_v1" not in s:
        raise ProtectedDataAccessError(
            f"Write outside allowed namespace: {p} (need {OUTPUT_REL})"
        )
    for prefix in FORBIDDEN_WRITE_PREFIXES:
        if f"/{prefix.rstrip('/').lower()}/" in f"/{s}/":
            raise ProtectedDataAccessError(f"Forbidden write prefix: {p}")
    return p


def refuse_test_loader_construction(*, partition: str) -> None:
    if partition.lower() in {"test", "later-development", "later_development", "r62", "r6.2"}:
        raise ProtectedDataAccessError(
            f"Test/protected loader construction refused for partition={partition!r}"
        )
