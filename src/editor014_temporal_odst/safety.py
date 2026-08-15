"""Fail-closed path guards. Never open r5.2 TEST, r5.1, or r6.2."""

from __future__ import annotations

from pathlib import Path

from editor012_rescue.safety import (
    EXPECTED_ARCHITECTURE_SHA256,
    EXPECTED_ODST_SHA256,
    EXPECTED_SCALER_SHA256,
    EXPECTED_SEQUENCE_ENSEMBLE_SHA256,
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
    "editor009_c2_c5_odst_rescue",
    "editor010_capacity_objective_teacher_rescue",
    "editor011_matched_route_confirmation",
    "editor012_teacher_anchor_rescue",
    "editor013_odst_value_proof",
)

_INNER_PHASE = False
_PROMOTION_FROZEN = False


class Editor014ProtocolError(RuntimeError):
    """Fail-closed EDITOR-014 violation."""


class Editor014Blocked(Editor014ProtocolError):
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


def _norm(text: str) -> str:
    return text.replace("\\", "/").lower()


def refuse_historical_write(path: str | Path) -> None:
    text = _norm(str(path))
    if "editor014_temporal_odst_value" in text:
        return
    for marker in HISTORICAL_WRITE_MARKERS:
        if marker in text:
            raise Editor014ProtocolError(f"REFUSED: historical frozen write: {path}")


def refuse_official_validation_during_inner(path: str | Path) -> None:
    if not _INNER_PHASE:
        return
    text = _norm(str(path))
    name = Path(path).name.lower()
    if name == "r52_t20_s1_validation.npz" or "r52_t20_s1_validation" in text:
        raise Editor014Blocked("inner search cannot read official validation")


def refuse_validation_before_promotion(path: str | Path) -> None:
    if _PROMOTION_FROZEN or _INNER_PHASE:
        return
    text = _norm(str(path))
    name = Path(path).name.lower()
    if "02_validation_confirmation" in text or name == "r52_t20_s1_validation.npz":
        raise Editor014Blocked("promotion freeze precedes validation evaluation")


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
        raise Editor014ProtocolError(f"REFUSED: split={split!r}")
    if _INNER_PHASE and token in {"validation", "val", "official_validation"}:
        raise Editor014Blocked("inner search cannot read official validation")
