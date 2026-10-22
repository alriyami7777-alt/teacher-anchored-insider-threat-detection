"""Fail-closed EDITOR-023 guards. Frozen checkpoints only. No TEST / r5.1 / r6.2."""

from __future__ import annotations

from pathlib import Path

from editor012_rescue.safety import (
    TRAIN_NPZ,
    VAL_NPZ,
    refuse_r51,
    refuse_r52_test,
    refuse_r62,
    require_hash,
    sha256_bytes,
    sha256_file,
    utc_now,
)

from .constants import OUTPUT_REL, REVIEW_REL

REPO_ROOT = Path(__file__).resolve().parents[2]
REVIEW_ROOT = REPO_ROOT / REVIEW_REL
OUTPUT_ROOT = REPO_ROOT / OUTPUT_REL

HISTORICAL_WRITE_MARKERS = (
    "review/editor006",
    "review/editor007",
    "review/editor008",
    "review/editor009",
    "review/editor010",
    "review/editor011",
    "review/editor012",
    "review/editor013",
    "review/editor014",
    "review/editor015",
    "review/editor016",
    "review/editor017",
    "review/editor018",
    "review/editor019",
    "review/editor020",
    "review/editor021",
    "review/editor022",
    "outputs/editor006",
    "outputs/editor007",
    "outputs/editor008",
    "outputs/editor009",
    "outputs/editor010",
    "outputs/editor011",
    "outputs/editor012",
    "outputs/editor013",
    "outputs/editor014",
    "outputs/editor015",
    "outputs/editor016",
    "outputs/editor017",
    "outputs/editor018",
    "outputs/editor019",
    "outputs/editor020",
    "outputs/editor021",
    "outputs/editor022",
    "editor012_teacher_anchor_rescue",
    "editor013_odst_value_proof",
    "editor014_temporal_odst_value",
    "editor015_residual_complementarity",
    "editor016_uncertainty_routed_odst",
    "editor017_explanation_robustness",
    "editor018_cross_view_tree_rescue",
    "editor019_oblique_boosted_tree_rescue",
    "editor020_teacher_degraded_consistency",
    "editor021_clean_function_representation_robustness",
    "editor022_sequential_clean_optimum_robustness",
)


class Editor023ProtocolError(RuntimeError):
    """Fail-closed EDITOR-023 violation."""


class Editor023Blocked(Editor023ProtocolError):
    """Hard block that invalidates the campaign."""


def _norm(text: str) -> str:
    return text.replace("\\", "/").lower()


def refuse_historical_write(path: Path | str) -> None:
    text = _norm(str(path))
    if "editor023_positive_architecture_value" in text or "editor023_architecture_value" in text:
        return
    for marker in HISTORICAL_WRITE_MARKERS:
        if marker in text:
            raise Editor023ProtocolError(f"REFUSED: historical frozen write: {path}")


def refuse_training() -> None:
    raise Editor023Blocked("EDITOR023_TRAINING_GATE = FAIL: training is prohibited")


def refuse_threshold_retune() -> None:
    raise Editor023Blocked("EDITOR-023 forbids threshold retuning on degraded inputs")


def refuse_calibration_refit() -> None:
    raise Editor023Blocked("EDITOR-023 forbids calibration refit")


def assert_split_allowed(split: str) -> None:
    token = str(split).strip().lower()
    if token in {"test", "later-development", "later_development", "r62", "r6.2", "r51", "r5.1"}:
        raise Editor023ProtocolError(f"REFUSED: split={split!r}")


def note_open(path: Path | str, *, role: str) -> Path:
    p = Path(path)
    refuse_r52_test(p)
    refuse_r51(p)
    refuse_r62(p)
    return p


__all__ = [
    "Editor023Blocked",
    "Editor023ProtocolError",
    "REPO_ROOT",
    "REVIEW_ROOT",
    "OUTPUT_ROOT",
    "refuse_historical_write",
    "refuse_training",
    "sha256_file",
    "sha256_bytes",
    "utc_now",
    "note_open",
    "TRAIN_NPZ",
    "VAL_NPZ",
    "require_hash",
]
