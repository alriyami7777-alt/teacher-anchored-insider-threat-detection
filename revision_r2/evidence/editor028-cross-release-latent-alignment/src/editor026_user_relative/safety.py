"""Fail-closed EDITOR-026 guards. Historical EDITOR files remain immutable."""

from __future__ import annotations

import hashlib
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from editor012_rescue.safety import refuse_r51, refuse_r52_test, refuse_r62

from .constants import (
    OUTPUT_REL,
    PROTOCOL_FREEZE_SUBJECT,
    R52_MODEL_FREEZE_SUBJECT,
    REVIEW_REL,
    repo_root,
)

REPO_ROOT = repo_root()
REVIEW_ROOT = REPO_ROOT / REVIEW_REL
OUTPUT_ROOT = REPO_ROOT / OUTPUT_REL

HISTORICAL_WRITE_MARKERS = tuple(
    item
    for n in range(1, 26)
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
    "src/editor024_r61",
    "src/editor025_r61_autopsy",
    "scripts/run_editor024_r61.py",
    "scripts/run_editor025_r61_autopsy.py",
    "tests/test_editor024_r61.py",
    "tests/test_editor025_r61_autopsy.py",
)

FUTURE_TARGET_MARKERS = (
    "untouched_target_search",
    "select_new_untouched",
    "future_confirmation_release",
    "r6.2",
    "r62",
    "r5.1",
    "r51",
)


class Editor026ProtocolError(RuntimeError):
    """Fail-closed EDITOR-026 violation."""


class Editor026Blocked(Editor026ProtocolError):
    """Hard block that invalidates the campaign."""


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
    rel = _norm(str(Path(path)))
    try:
        rel = _norm(str(Path(path).resolve().relative_to(REPO_ROOT.resolve())))
    except (ValueError, OSError):
        rel = text
    if "editor026" in rel:
        return
    for marker in HISTORICAL_WRITE_MARKERS:
        if _norm(marker) in rel:
            raise Editor026ProtocolError(f"REFUSED: historical write {path}")


def refuse_r51_r62(path: str | Path) -> None:
    refuse_r51(path)
    refuse_r62(path)
    refuse_r52_test(path)


def protocol_freeze_commit() -> str | None:
    out = subprocess.check_output(
        ["git", "log", "-1", "--grep", PROTOCOL_FREEZE_SUBJECT, "--format=%H"],
        cwd=str(REPO_ROOT),
        text=True,
    ).strip()
    return out or None


def r52_model_freeze_commit() -> str | None:
    out = subprocess.check_output(
        ["git", "log", "-1", "--grep", R52_MODEL_FREEZE_SUBJECT, "--format=%H"],
        cwd=str(REPO_ROOT),
        text=True,
    ).strip()
    return out or None


def protocol_is_frozen() -> bool:
    return protocol_freeze_commit() is not None


def require_protocol_frozen(*, action: str) -> str:
    sha = protocol_freeze_commit()
    if not sha:
        raise Editor026Blocked(f"EDITOR026 protocol is not frozen; refused: {action}")
    return sha


def require_stage0_pass(*, action: str) -> dict:
    path = REVIEW_ROOT / "EDITOR026_STAGE0_GATE.json"
    if not path.is_file():
        raise Editor026Blocked(f"Stage-0 gate missing; refused: {action}")
    import json

    rec = json.loads(path.read_text(encoding="utf-8"))
    if rec.get("EDITOR026_REPRESENTATION_DISTRIBUTION_GATE") != "PASS":
        raise Editor026Blocked(f"distribution gate failed; refused: {action}")
    if rec.get("EDITOR026_INPUT_SIGNAL_GATE") != "PASS":
        raise Editor026Blocked(f"input-signal gate failed; refused: {action}")
    if rec.get("EDITOR026_TRAINING_AUTHORISED") != "YES":
        raise Editor026Blocked(f"training not authorised; refused: {action}")
    return rec


def require_r52_model_frozen(*, action: str) -> str:
    sha = r52_model_freeze_commit()
    if not sha:
        raise Editor026Blocked(f"r5.2 model freeze missing; refused: {action}")
    freeze = REVIEW_ROOT / "EDITOR026_R52_MODEL_FREEZE.json"
    if not freeze.is_file():
        raise Editor026Blocked(f"EDITOR026_R52_MODEL_FREEZE.json missing; refused: {action}")
    return sha
