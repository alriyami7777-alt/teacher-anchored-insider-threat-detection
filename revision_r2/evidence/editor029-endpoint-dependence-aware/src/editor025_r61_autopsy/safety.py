"""Fail-closed EDITOR-025 guards. Historical EDITOR-024 remains immutable."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from editor012_rescue.safety import refuse_r51, refuse_r52_test, refuse_r62, sha256_bytes, utc_now

from .constants import (
    EDITOR024_OUTPUT_REL,
    EDITOR024_REVIEW_REL,
    OUTPUT_REL,
    PROTOCOL_FREEZE_SUBJECT,
    REVIEW_REL,
    repo_root,
)

REPO_ROOT = repo_root()
REVIEW_ROOT = REPO_ROOT / REVIEW_REL
OUTPUT_ROOT = REPO_ROOT / OUTPUT_REL
EDITOR024_REVIEW_ROOT = REPO_ROOT / EDITOR024_REVIEW_REL
EDITOR024_OUTPUT_ROOT = REPO_ROOT / EDITOR024_OUTPUT_REL

HISTORICAL_WRITE_MARKERS = tuple(
    item
    for n in range(1, 25)
    for item in (
        f"review/editor{n:03d}",
        f"outputs/editor{n:03d}",
        f"review/editor{n}",
        f"outputs/editor{n}",
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
    "src/editor024_r61",
    "scripts/run_editor024_r61.py",
    "tests/test_editor024_r61.py",
)


class Editor025ProtocolError(RuntimeError):
    """Fail-closed EDITOR-025 violation."""


class Editor025Blocked(Editor025ProtocolError):
    """Hard block that invalidates the autopsy."""


def _norm(text: str) -> str:
    return text.replace("\\", "/").lower()


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
        raise Editor025Blocked(
            f"EDITOR025_PRE_FREEZE_PROHIBITION: {action} is forbidden before the protocol freeze commit"
        )
    return sha


def sha256_file(path: Path | str, chunk_size: int = 8 * 1024 * 1024) -> str:
    p = Path(path)
    digest = hashlib.sha256()
    with p.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def refuse_historical_write(path: Path | str) -> None:
    text = _norm(str(path))
    if "editor025_r61" in text or "editor025_r61_failure_autopsy" in text:
        return
    for marker in HISTORICAL_WRITE_MARKERS:
        if marker.replace("\\", "/").lower() in text:
            raise Editor025ProtocolError(f"REFUSED: historical EDITOR-001..024 write: {path}")


def refuse_training() -> None:
    raise Editor025Blocked("EDITOR025_TRAINING_GATE = FAIL: training is prohibited")


def refuse_r51_rerun(path: Path | str | None = None) -> None:
    if path is not None:
        refuse_r51(path)
    raise Editor025Blocked("R51_RERUN is prohibited in EDITOR-025")


def refuse_r62_rerun(path: Path | str | None = None) -> None:
    if path is not None:
        refuse_r62(path)
    raise Editor025Blocked("R62_RERUN is prohibited in EDITOR-025")


def refuse_r52_test_access(path: Path | str | None = None) -> None:
    if path is not None:
        refuse_r52_test(path)
    else:
        refuse_r52_test(Path("r52_T20_s1_test.npz"))


def path_is_editor024(path: Path | str) -> bool:
    text = _norm(str(path))
    return "editor024" in text and "editor025" not in text


__all__ = [
    "Editor025Blocked",
    "Editor025ProtocolError",
    "REPO_ROOT",
    "REVIEW_ROOT",
    "OUTPUT_ROOT",
    "sha256_file",
    "sha256_bytes",
    "sha256_text",
    "utc_now",
    "protocol_is_frozen",
    "require_protocol_frozen",
    "refuse_historical_write",
    "refuse_training",
]
