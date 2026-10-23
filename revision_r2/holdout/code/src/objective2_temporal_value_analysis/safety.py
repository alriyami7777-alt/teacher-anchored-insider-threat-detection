"""Path guards for temporal-value analysis (forward-pass only)."""

from __future__ import annotations

from pathlib import Path

from .constants import FORBIDDEN_PATH_MARKERS, OUTPUT_REL


class ProtectedDataAccessError(RuntimeError):
    pass


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
    p = Path(path)
    s = _norm(p)
    if "temporal_value_analysis_v1" not in s:
        raise ProtectedDataAccessError(f"Write outside allowed namespace: {p} (need {OUTPUT_REL})")
    return p


def refuse_test_loader(partition: str) -> None:
    if partition.lower() in {"test", "later-development", "later_development", "r62", "r6.2"}:
        raise ProtectedDataAccessError(f"Test/protected loader refused: {partition!r}")
