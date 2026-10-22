"""Fail-closed path guards. Never open r5.2 TEST, r5.1, or r6.2. Never write EDITOR-021 history."""

from __future__ import annotations

from pathlib import Path

from editor012_rescue.safety import (
    TRAIN_NPZ,
    VAL_NPZ,
    refuse_r51,
    refuse_r52_test,
    refuse_r62,
    sha256_bytes,
    sha256_file,
    utc_now,
)

from .constants import EDITOR021_OUTPUT_REL, EDITOR021_REVIEW_REL, OUTPUT_REL, REVIEW_REL

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
    "editor021_clean_function_representation_robustness",
    "editor021_cfpr",
    "editor020_teacher_degraded_consistency",
    "editor017_explanation_robustness",
)

_INNER_PHASE = False
_PROMOTION_FROZEN = False
_PREDICTIVE_STARTED = False


class Editor022ProtocolError(RuntimeError):
    """Fail-closed EDITOR-022 violation."""


class Editor022Blocked(Editor022ProtocolError):
    """Hard block that invalidates the campaign."""


def enter_inner_phase() -> None:
    global _INNER_PHASE
    _INNER_PHASE = True


def exit_inner_phase() -> None:
    global _INNER_PHASE
    _INNER_PHASE = False


def inner_phase_active() -> bool:
    return bool(_INNER_PHASE)


def mark_promotion_frozen() -> None:
    global _PROMOTION_FROZEN
    _PROMOTION_FROZEN = True


def promotion_frozen() -> bool:
    return bool(_PROMOTION_FROZEN)


def mark_predictive_started() -> None:
    global _PREDICTIVE_STARTED
    _PREDICTIVE_STARTED = True


def predictive_started() -> bool:
    return bool(_PREDICTIVE_STARTED)


def _norm(text: str) -> str:
    return text.replace("\\", "/").lower()


def refuse_historical_write(path: str | Path) -> None:
    text = _norm(str(path))
    allowed = (
        _norm(str(REVIEW_REL)),
        _norm(str(OUTPUT_REL)),
        "src/editor022_sequential_robustness",
        "tests/test_editor022_sequential_robustness.py",
    )
    if any(marker in text for marker in allowed):
        if "editor021_clean_function_representation_robustness" in text:
            raise Editor022ProtocolError(f"REFUSED: historical EDITOR-021 write: {path}")
        return
    if _norm(str(EDITOR021_REVIEW_REL)) in text or _norm(str(EDITOR021_OUTPUT_REL)) in text:
        raise Editor022ProtocolError(f"REFUSED: historical EDITOR-021 write: {path}")
    for marker in HISTORICAL_WRITE_MARKERS:
        if marker in text:
            raise Editor022ProtocolError(f"REFUSED: historical frozen write: {path}")


def refuse_editor021_review_write(path: str | Path) -> None:
    text = _norm(str(path))
    if "review/editor021_clean_function_representation_robustness" in text:
        raise Editor022ProtocolError(f"REFUSED: historical EDITOR-021 review write: {path}")


def refuse_editor021_output_write(path: str | Path) -> None:
    text = _norm(str(path))
    if "outputs/editor021_clean_function_representation_robustness" in text:
        raise Editor022ProtocolError(f"REFUSED: historical EDITOR-021 output write: {path}")


def refuse_official_validation_during_inner(path: str | Path) -> None:
    if not _INNER_PHASE:
        return
    text = _norm(str(path))
    name = Path(path).name.lower()
    if name == "r52_t20_s1_validation.npz" or "r52_t20_s1_validation" in text:
        raise Editor022Blocked("inner search cannot read official validation")


def note_open(path: Path | str, *, role: str) -> Path:
    p = Path(path)
    refuse_r52_test(p)
    refuse_r51(p)
    refuse_r62(p)
    refuse_official_validation_during_inner(p)
    return p


def assert_split_allowed(split: str) -> None:
    token = str(split).strip().lower()
    if token in {"test", "later-development", "later_development", "r62", "r6.2", "r51", "r5.1"}:
        raise Editor022ProtocolError(f"REFUSED: split={split!r}")
    if _INNER_PHASE and token in {"validation", "val", "official_validation"}:
        raise Editor022Blocked("inner search cannot read official validation")


def assert_frozen_coefficients() -> None:
    from .constants import LAMBDA_FP, LAMBDA_HISTORICAL_SINGLE_TEACHER_LOGIT, LAMBDA_ROUTE, LAMBDA_TEACHER

    if LAMBDA_HISTORICAL_SINGLE_TEACHER_LOGIT != 0.0:
        raise Editor022Blocked("historical single-teacher logit anchor must remain retired")
    if abs(float(LAMBDA_TEACHER) - 0.5) > 1e-15:
        raise Editor022Blocked("lambda teacher must stay exactly 0.5")
    if abs(float(LAMBDA_ROUTE) - 0.5) > 1e-15:
        raise Editor022Blocked("lambda route must stay exactly 0.5")
    if abs(float(LAMBDA_FP) - 1.0) > 1e-15:
        raise Editor022Blocked("lambda_fp must stay exactly 1.0")


def refuse_validation_threshold_search(*, split: str, threshold: float | None) -> None:
    token = str(split).strip().lower()
    if token in {"validation", "val", "official_validation"} and threshold is None:
        raise Editor022Blocked("No validation threshold search exists")
