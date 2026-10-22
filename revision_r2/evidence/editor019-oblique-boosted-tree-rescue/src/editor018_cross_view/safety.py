"""Fail-closed path guards. Never open r5.2 TEST, r5.1, or r6.2."""

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
    "editor009_c2_c5_odst_rescue",
    "editor010_capacity_objective_teacher_rescue",
    "editor011_matched_route_confirmation",
    "editor012_teacher_anchor_rescue",
    "editor013_odst_value_proof",
    "editor014_temporal_odst_value",
    "editor015_residual_complementarity",
    "editor016_uncertainty_routed_odst",
    "editor017_explanation_robustness",
)

_INNER_PHASE = False
_PROMOTION_FROZEN = False


class Editor018ProtocolError(RuntimeError):
    """Fail-closed EDITOR-018 violation."""


class Editor018Blocked(Editor018ProtocolError):
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
    if "editor018_cross_view_tree_rescue" in text:
        return
    for marker in HISTORICAL_WRITE_MARKERS:
        if marker in text:
            raise Editor018ProtocolError(f"REFUSED: historical frozen write: {path}")


def refuse_official_validation_during_inner(path: str | Path) -> None:
    if not _INNER_PHASE:
        return
    text = _norm(str(path))
    name = Path(path).name.lower()
    if name == "r52_t20_s1_validation.npz" or "r52_t20_s1_validation" in text:
        raise Editor018Blocked("inner search cannot read official validation")


def refuse_validation_before_promotion(path: str | Path) -> None:
    if _PROMOTION_FROZEN:
        return
    text = _norm(str(path))
    if "02_validation_confirmation" in text:
        raise Editor018Blocked("promotion freeze precedes validation evaluation")


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
        raise Editor018ProtocolError(f"REFUSED: split={split!r}")
    if _INNER_PHASE and token in {"validation", "val", "official_validation"}:
        raise Editor018Blocked("inner search cannot read official validation")


__all__ = [
    "Editor018Blocked",
    "Editor018ProtocolError",
    "REPO_ROOT",
    "REVIEW_ROOT",
    "OUTPUT_ROOT",
    "TRAIN_NPZ",
    "VAL_NPZ",
    "sha256_file",
    "sha256_bytes",
    "utc_now",
    "require_hash",
    "refuse_historical_write",
    "note_open",
]
