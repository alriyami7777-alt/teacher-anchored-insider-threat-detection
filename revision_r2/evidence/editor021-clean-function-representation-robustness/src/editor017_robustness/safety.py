"""Fail-closed EDITOR-017 guards. Frozen checkpoints only. No TEST / r5.1 / r6.2."""

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
    "editor009_c2_c5_odst_rescue",
    "editor010_capacity_objective_teacher_rescue",
    "editor011_matched_route_confirmation",
    "editor012_teacher_anchor_rescue",
    "editor013_odst_value_proof",
    "editor014_temporal_odst_value",
    "editor015_residual_complementarity",
    "editor016_uncertainty_routed_odst",
)


class Editor017ProtocolError(RuntimeError):
    """Fail-closed EDITOR-017 violation."""


class Editor017Blocked(Editor017ProtocolError):
    """Hard block that invalidates the campaign."""


def _norm(text: str) -> str:
    return text.replace("\\", "/").lower()


def refuse_historical_write(path: Path | str) -> None:
    text = _norm(str(path))
    if "editor017_explanation_robustness" in text or "editor017_robustness" in text:
        return
    for marker in HISTORICAL_WRITE_MARKERS:
        if marker in text:
            raise Editor017ProtocolError(f"REFUSED: historical frozen write: {path}")


def refuse_training() -> None:
    raise Editor017Blocked("EDITOR-017 evaluates frozen checkpoints only; training is refused")


def refuse_threshold_retune() -> None:
    raise Editor017Blocked("EDITOR-017 forbids threshold retuning on degraded inputs")


def refuse_validation_derived_perturbation() -> None:
    raise Editor017Blocked("EDITOR-017 forbids validation-derived noise or source selection")


def assert_split_allowed(split: str) -> None:
    token = str(split).strip().lower()
    if token in {"test", "later-development", "later_development", "r62", "r6.2", "r51", "r5.1"}:
        raise Editor017ProtocolError(f"REFUSED: split={split!r}")


def note_open(path: Path | str, *, role: str) -> Path:
    p = Path(path)
    refuse_r52_test(p)
    refuse_r51(p)
    refuse_r62(p)
    return p
