"""Fail-closed path guards. Never open r5.2 TEST, r5.1, or r6.2."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
REVIEW_ROOT = REPO_ROOT / "review" / "editor009_c2_c5_odst_rescue"
OUTPUT_ROOT = REPO_ROOT / "outputs" / "editor009_c2_c5_odst_rescue"

FEAS_SCRIPTS = Path(r"C:\PhD\07_Projects\cert-r42-feasibility\scripts")
TRAIN_NPZ = Path(
    r"C:\PhD\07_Projects\cert-r42-feasibility\data\processed\r5.2\tensors\r52_T20_s1_train.npz"
)
VAL_NPZ = Path(
    r"C:\PhD\07_Projects\cert-r42-feasibility\data\processed\r5.2\tensors\r52_T20_s1_validation.npz"
)

EXPECTED_TRAIN_SHA256 = "b268328d3bf2e98f712d1145958dabe175ce2c07a7c390da4b84a663317ebc2e"
EXPECTED_VAL_SHA256 = "5ac2e7e8fbd50eb62638cdb8c9d444464e02ff2ea20ba55989c36926dd751a5c"
EXPECTED_ARCHITECTURE_SHA256 = "9867b0c266f3b735d138e2d8d53f0d3f5c5c644e25302c10c25e2f4677560abd"
EXPECTED_ODST_SHA256 = "95764ce80a7c80529108d8d6b72f6bd06896c39d065f7e475c12dce8421417bb"
EXPECTED_SEQUENCE_ENSEMBLE_SHA256 = "43f16bce9c09305c7578d319dadf4c23c6c18cbe70fd7dcc1fda0114c86d6475"
EXPECTED_SCALER_SHA256 = "6a092df8275e15b6e05c685b306f48de72ab55fb1e88ede5ed5899ecd63f3488"

C5_DENY_HASHES = {
    "a5a08dc24a89014fd1bb92c6c6342ed50511b33804e95246e480e90c4692b214",
    "3203455562ec6ff4018cc5cb3299bc2530bc8eff95aa523e6b7746f43731d971",
    "54f879d6b163185073ea586fa50a68edf89b603c269c6208c8b48156dccd4e22",
}

HISTORICAL_READONLY_MARKERS = (
    "review/editor006",
    "review/editor007",
    "review/editor008",
    "review\\editor006",
    "review\\editor007",
    "review\\editor008",
)

R52_TEST_MARKERS = (
    "r52_t20_s1_test",
    "r5.2_t20_s1_test",
    "r52_t20_s1_test.npz",
)
R51_MARKERS = ("r5.1", "r51", "processed/r5.1", "processed\\r5.1")
R62_MARKERS = ("r6.2", "r62", "processed/r6.2", "processed\\r6.2", "raw/r6.2")


class Editor009ProtocolError(RuntimeError):
    """Fail-closed EDITOR-009 violation."""


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


def _norm(text: str) -> str:
    return text.replace("\\", "/").lower()


def refuse_r52_test(path: str | Path) -> None:
    text = _norm(str(path))
    name = Path(path).name.lower()
    if name == "r52_t20_s1_test.npz" or any(m in text for m in R52_TEST_MARKERS):
        raise Editor009ProtocolError(f"REFUSED: r5.2 TEST path: {path}")


def refuse_r51(path: str | Path) -> None:
    text = _norm(str(path))
    if any(m in text for m in ("processed/r5.1", "processed/r51", "raw/r5.1", "tensors/r51")):
        raise Editor009ProtocolError(f"REFUSED: r5.1 path: {path}")


def refuse_r62(path: str | Path) -> None:
    text = _norm(str(path))
    if any(m in text for m in R62_MARKERS):
        raise Editor009ProtocolError(f"REFUSED: r6.2 path: {path}")


def refuse_historical_write(path: str | Path) -> None:
    text = _norm(str(path))
    for marker in ("review/editor006", "review/editor007", "review/editor008"):
        if marker in text:
            raise Editor009ProtocolError(f"REFUSED: historical frozen write: {path}")


def assert_split_allowed(split: str) -> None:
    token = str(split).strip().lower()
    if token in {"test", "later-development", "later_development", "r62", "r6.2", "r51", "r5.1"}:
        raise Editor009ProtocolError(f"REFUSED: split={split!r}")


def note_open(path: Path | str, *, role: str) -> Path:
    p = Path(path)
    refuse_r52_test(p)
    refuse_r51(p)
    refuse_r62(p)
    return p


def assert_not_deny_c5(sha256: str) -> None:
    if sha256 in C5_DENY_HASHES:
        raise Editor009ProtocolError(
            f"HASH GATE ABORT: deny-listed ablation C5 sha={sha256}"
        )


def require_hash(path: Path, expected: str, *, role: str) -> str:
    note_open(path, role=role)
    if not path.is_file():
        raise Editor009ProtocolError(f"missing {role}: {path}")
    observed = sha256_file(path)
    if observed != expected:
        raise Editor009ProtocolError(
            f"HASH MISMATCH {role}: expected={expected} observed={observed} path={path}"
        )
    return observed
