"""Fail-closed path guards for EDITOR-010. r5.2 TEST and non-r5.2 releases are denied."""

from __future__ import annotations

from pathlib import Path

class Editor010SafetyError(RuntimeError):
    """Raised when a blocked path or partition would be used."""


FORBIDDEN_PATH_MARKERS = (
    "r52_t20_s1_test",
    "r5.2_test",
    "r52_test",
    "/test.npz",
    "\\test.npz",
    "r42_t20_s1_test",
    "processed/r5.1",
    "processed\\r5.1",
    "r51_t20",
    "cert r5.1",
    "cert-r5.1",
    "processed/r6.2",
    "processed\\r6.2",
    "r62_t20",
    "cert r6.2",
    "processed/r4.1",
    "processed\\r4.1",
    "r41_t20",
    "processed/r6.1",
    "processed\\r6.1",
    "r61_t20",
    "later-development",
    "later_development",
)

FORBIDDEN_WRITE_MARKERS = (
    "r52_odst_confirmation",
    "r52_teacher_anchoring_ablation_v1",
    "r52_teacher_anchored_reproducibility_v1",
    "r52_locked_baselines",
    "editor009_c2_c5_odst_rescue",
)

ALLOWED_WRITE_MARKERS = (
    "editor010_capacity_objective_teacher_rescue",
    "outputs/editor010",
    "outputs\\editor010",
)

TEST_PARTITION_NAMES = {"test", "later-development", "later_development", "r5.1", "r51", "r6.2", "r62", "r4.1", "r6.1"}


def _norm(path: Path | str) -> str:
    return Path(path).as_posix().replace("\\", "/").lower()


def assert_path_allowed_for_read(path: Path | str, *, context: str = "") -> Path:
    p = Path(path)
    s = _norm(p)
    for marker in FORBIDDEN_PATH_MARKERS:
        if marker.lower() in s:
            raise Editor010SafetyError(
                f"EDITOR-010 blocked protected-path access ({context}): {p} matched {marker!r}"
            )
    return p


def assert_output_namespace(path: Path | str) -> Path:
    p = Path(path)
    s = _norm(p)
    if not any(m.lower().replace("\\", "/") in s for m in ALLOWED_WRITE_MARKERS):
        raise Editor010SafetyError(f"EDITOR-010 write outside allowed namespace: {p}")
    for marker in FORBIDDEN_WRITE_MARKERS:
        if marker.lower() in s and "editor010" not in s:
            raise Editor010SafetyError(f"EDITOR-010 refused write into historical packet: {p}")
    return p


def refuse_test_loader_construction(*, partition: str) -> None:
    name = str(partition).strip().lower()
    if name in TEST_PARTITION_NAMES or "test" in name:
        raise Editor010SafetyError(
            f"EDITOR-010 refused loader construction for partition={partition!r}"
        )


def assert_not_historical_write(path: Path | str) -> Path:
    return assert_output_namespace(path)
