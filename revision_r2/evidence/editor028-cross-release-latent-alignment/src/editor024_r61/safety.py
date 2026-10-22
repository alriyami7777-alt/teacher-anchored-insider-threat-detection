"""Fail-closed EDITOR-024 guards. No r6.1 content before protocol freeze."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from editor012_rescue.safety import refuse_r51, refuse_r52_test, refuse_r62, sha256_bytes, utc_now

from .constants import (
    OUTPUT_REL,
    PROTOCOL_FREEZE_SUBJECT,
    RAW_R61_ROOT,
    REVIEW_REL,
    repo_root,
)

REPO_ROOT = repo_root()
REVIEW_ROOT = REPO_ROOT / REVIEW_REL
OUTPUT_ROOT = REPO_ROOT / OUTPUT_REL

HISTORICAL_WRITE_MARKERS = tuple(
    item
    for n in range(1, 24)
    for item in (
        f"review/editor{n:03d}",
        f"outputs/editor{n:03d}",
        f"review/editor{n}",
        f"outputs/editor{n}",
    )
) + (
    "editor006a_preinference_freeze",
    "editor006b_harness",
    "editor006c_r62_input_bundle",
    "editor006d_external_runner",
    "editor006e_authorisation",
    "editor007a_post006e_diagnostics",
    "editor007b_r51_secondary_stress",
    "editor007c_r51_authorisation",
    "editor007d_cross_version_synthesis",
    "editor008_cross_version_portability_protocol",
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
    "editor023_positive_architecture_value",
)


class Editor024ProtocolError(RuntimeError):
    """Fail-closed EDITOR-024 violation."""


class Editor024Blocked(Editor024ProtocolError):
    """Hard block that invalidates the campaign."""


def _norm(text: str) -> str:
    return text.replace("\\", "/").lower()


def path_looks_like_r61_content(path: Path | str) -> bool:
    """True only for CERT r6.1 raw/answer content, never for editor024_r61 source paths."""
    p = Path(path)
    text = _norm(str(p.resolve() if p.exists() else p))
    name = p.name.lower()
    if name.startswith("r6.1-") and name.endswith(".csv"):
        return True
    if "06_datasets/r6.1" in text:
        return True
    raw = _norm(str(RAW_R61_ROOT))
    if raw and raw in text:
        return True
    return False


def protocol_freeze_commit() -> str | None:
    out = subprocess.check_output(
        ["git", "log", "-1", "--grep", PROTOCOL_FREEZE_SUBJECT, "--format=%H"],
        cwd=str(REPO_ROOT),
        text=True,
    ).strip()
    return out or None


def protocol_is_frozen() -> bool:
    return protocol_freeze_commit() is not None


def require_protocol_frozen(*, action: str) -> str:
    sha = protocol_freeze_commit()
    if not sha:
        raise Editor024Blocked(
            f"EDITOR024_PRE_FREEZE_PROHIBITION: {action} is forbidden before the protocol freeze commit"
        )
    return sha


def refuse_r61_content_before_freeze(path: Path | str, *, action: str) -> None:
    if path_looks_like_r61_content(path) and not protocol_is_frozen():
        raise Editor024Blocked(
            f"EDITOR024_PRE_FREEZE_PROHIBITION: {action} of r6.1 content is forbidden: {path}"
        )


def sha256_file(path: Path | str, chunk_size: int = 8 * 1024 * 1024) -> str:
    p = Path(path)
    refuse_r61_content_before_freeze(p, action="hash")
    digest = hashlib.sha256()
    with p.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def open_text_file(path: Path | str, **kwargs: object):
    p = Path(path)
    refuse_r61_content_before_freeze(p, action="open")
    return p.open("r", **kwargs)  # type: ignore[arg-type]


def refuse_historical_write(path: Path | str) -> None:
    text = _norm(str(path))
    if "editor024_r61" in text or "editor024_r61_final_confirmation" in text:
        return
    for marker in HISTORICAL_WRITE_MARKERS:
        if marker.replace("\\", "/") in text:
            raise Editor024ProtocolError(f"REFUSED: historical EDITOR-001..023 write: {path}")


def refuse_training() -> None:
    raise Editor024Blocked("EDITOR024_TRAINING_GATE = FAIL: training is prohibited")


def refuse_target_threshold_search() -> None:
    raise Editor024Blocked("TARGET_THRESHOLD_SEARCH = YES is prohibited")


def refuse_target_calibration_fit() -> None:
    raise Editor024Blocked("TARGET_CALIBRATION_FIT = YES is prohibited")


def refuse_target_feature_selection() -> None:
    raise Editor024Blocked("TARGET_FEATURE_SELECTION = YES is prohibited")


def refuse_r51_rerun(path: Path | str | None = None) -> None:
    if path is not None:
        refuse_r51(path)
    raise Editor024Blocked("R51_RERUN is prohibited in EDITOR-024")


def refuse_r62_rerun(path: Path | str | None = None) -> None:
    if path is not None:
        refuse_r62(path)
    raise Editor024Blocked("R62_RERUN is prohibited in EDITOR-024")


def note_open(path: Path | str, *, role: str) -> Path:
    p = Path(path)
    refuse_r52_test(p)
    refuse_r61_content_before_freeze(p, action=f"open:{role}")
    return p


__all__ = [
    "Editor024Blocked",
    "Editor024ProtocolError",
    "REPO_ROOT",
    "REVIEW_ROOT",
    "OUTPUT_ROOT",
    "sha256_file",
    "sha256_bytes",
    "utc_now",
    "protocol_is_frozen",
    "require_protocol_frozen",
    "refuse_historical_write",
    "refuse_training",
    "path_looks_like_r61_content",
]
