"""Fail-closed EDITOR-029 guards. Historical EDITOR-001–028 files remain immutable."""

from __future__ import annotations

import hashlib
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from editor012_rescue.safety import refuse_r51, refuse_r52_test, refuse_r62

from .constants import (
    ENDPOINT_MODEL_FREEZE_SUBJECT,
    OUTPUT_REL,
    PROTOCOL_FREEZE_SUBJECT,
    REVIEW_REL,
    repo_root,
)

REPO_ROOT = repo_root()
REVIEW_ROOT = REPO_ROOT / REVIEW_REL
OUTPUT_ROOT = REPO_ROOT / OUTPUT_REL

HISTORICAL_WRITE_MARKERS = tuple(
    item
    for n in range(1, 29)
    for item in (
        f"review/editor{n:03d}",
        f"outputs/editor{n:03d}",
        f"src/editor{n:03d}",
        f"src/editor{n}",
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
    "editor024_r61_final_confirmation",
    "editor025_r61_failure_autopsy",
    "editor026_user_relative",
    "editor027_scale_normalised",
    "editor028_latent_alignment",
    "src/editor024_r61",
    "src/editor025_r61_autopsy",
    "src/editor026_user_relative",
    "src/editor027_scale_normalised",
    "src/editor028_latent_alignment",
    "scripts/run_editor024_r61.py",
    "scripts/run_editor025_r61_autopsy.py",
    "scripts/run_editor026_user_relative.py",
    "scripts/run_editor027_scale_normalised.py",
    "scripts/run_editor028_latent_alignment.py",
    "tests/test_editor024_r61.py",
    "tests/test_editor025_r61_autopsy.py",
    "tests/test_editor026_user_relative.py",
    "tests/test_editor027_scale_normalised.py",
    "tests/test_editor028_latent_alignment.py",
)

R61_MARKERS = ("processed/r6.1", "processed/r61", "raw/r6.1", "tensors/r61")
EDITOR030_MARKERS = ("editor030", "EDITOR-030", "EDITOR030")


class Editor029ProtocolError(RuntimeError):
    """Fail-closed EDITOR-029 violation."""


class Editor029Blocked(Editor029ProtocolError):
    """Hard block that invalidates the campaign."""


class Editor029EngineeringBlockedAfterResult(Editor029Blocked):
    """Prediction-affecting defect after first new result. Do not patch-and-rerun."""


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def _norm(text: str) -> str:
    return text.replace("\\", "/").lower()


def refuse_historical_write(path: str | Path) -> None:
    text = _norm(str(path))
    try:
        rel = _norm(str(Path(path).resolve().relative_to(REPO_ROOT.resolve())))
    except (ValueError, OSError):
        rel = text
    if "editor029" in rel:
        return
    for marker in HISTORICAL_WRITE_MARKERS:
        if _norm(marker) in rel:
            raise Editor029ProtocolError(f"REFUSED: historical write {path}")


def refuse_r61(path: str | Path) -> None:
    text = _norm(str(path))
    if any(m in text for m in R61_MARKERS):
        raise Editor029ProtocolError(f"REFUSED: r6.1 path: {path}")


def refuse_r51_r61_r62_test(path: str | Path) -> None:
    refuse_r51(path)
    refuse_r61(path)
    refuse_r62(path)
    refuse_r52_test(path)


def refuse_editor030(text: str) -> None:
    blob = str(text)
    for marker in EDITOR030_MARKERS:
        if marker in blob:
            raise Editor029Blocked("REFUSED: EDITOR-030 must not be launched automatically")


def protocol_freeze_commit() -> str | None:
    out = subprocess.check_output(
        ["git", "log", "-1", "--grep", PROTOCOL_FREEZE_SUBJECT, "--format=%H"],
        cwd=str(REPO_ROOT),
        text=True,
    ).strip()
    return out or None


def endpoint_model_freeze_commit() -> str | None:
    out = subprocess.check_output(
        ["git", "log", "-1", "--grep", ENDPOINT_MODEL_FREEZE_SUBJECT, "--format=%H"],
        cwd=str(REPO_ROOT),
        text=True,
    ).strip()
    return out or None


def require_protocol_frozen(*, action: str) -> str:
    sha = protocol_freeze_commit()
    if not sha:
        raise Editor029Blocked(f"EDITOR029 protocol is not frozen; refused: {action}")
    return sha


def require_endpoint_model_frozen(*, action: str) -> str:
    sha = endpoint_model_freeze_commit()
    if not sha:
        raise Editor029Blocked(f"endpoint model freeze missing; refused: {action}")
    freeze = REVIEW_ROOT / "EDITOR029_ENDPOINT_MODEL_FREEZE.json"
    if not freeze.is_file():
        raise Editor029Blocked(f"EDITOR029_ENDPOINT_MODEL_FREEZE.json missing; refused: {action}")
    return sha
