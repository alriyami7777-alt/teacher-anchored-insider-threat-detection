"""Fail-closed path guards. Never open r5.2 TEST, r5.1, or r6.2."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
REVIEW_ROOT = REPO_ROOT / "review" / "editor011_matched_route_confirmation"
OUTPUT_ROOT = REPO_ROOT / "outputs" / "editor011_matched_route_confirmation"

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

R52_TEST_MARKERS = (
    "r52_t20_s1_test",
    "r5.2_t20_s1_test",
    "r52_t20_s1_test.npz",
)
R51_MARKERS = ("processed/r5.1", "processed/r51", "raw/r5.1", "tensors/r51")
R62_MARKERS = ("processed/r6.2", "processed/r62", "raw/r6.2", "tensors/r62")

HISTORICAL_WRITE_MARKERS = (
    "review/editor006",
    "review/editor007",
    "review/editor008",
    "review/editor009",
    "review/editor010",
    "editor009_c2_c5_odst_rescue",
    "editor010_capacity_objective_teacher_rescue",
)


class Editor011ProtocolError(RuntimeError):
    """Fail-closed EDITOR-011 violation."""


class Editor011Blocked(Editor011ProtocolError):
    """Hard block that invalidates the matched comparison."""


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


def _norm(text: str) -> str:
    return text.replace("\\", "/").lower()


def refuse_r52_test(path: str | Path) -> None:
    text = _norm(str(path))
    name = Path(path).name.lower()
    if name == "r52_t20_s1_test.npz" or any(m in text for m in R52_TEST_MARKERS):
        raise Editor011ProtocolError(f"REFUSED: r5.2 TEST path: {path}")


def refuse_r51(path: str | Path) -> None:
    text = _norm(str(path))
    if any(m in text for m in R51_MARKERS):
        raise Editor011ProtocolError(f"REFUSED: r5.1 path: {path}")


def refuse_r62(path: str | Path) -> None:
    text = _norm(str(path))
    if any(m in text for m in R62_MARKERS):
        raise Editor011ProtocolError(f"REFUSED: r6.2 path: {path}")


def refuse_historical_write(path: str | Path) -> None:
    text = _norm(str(path))
    if "editor011_matched_route_confirmation" in text:
        return
    for marker in HISTORICAL_WRITE_MARKERS:
        if marker in text:
            raise Editor011ProtocolError(f"REFUSED: historical frozen write: {path}")


def assert_split_allowed(split: str) -> None:
    token = str(split).strip().lower()
    if token in {"test", "later-development", "later_development", "r62", "r6.2", "r51", "r5.1"}:
        raise Editor011ProtocolError(f"REFUSED: split={split!r}")


def note_open(path: Path | str, *, role: str) -> Path:
    p = Path(path)
    refuse_r52_test(p)
    refuse_r51(p)
    refuse_r62(p)
    return p


def require_hash(path: Path, expected: str, *, role: str) -> str:
    note_open(path, role=role)
    if not path.is_file():
        raise Editor011ProtocolError(f"missing {role}: {path}")
    observed = sha256_file(path)
    if observed != expected:
        raise Editor011ProtocolError(
            f"HASH MISMATCH {role}: expected={expected} observed={observed} path={path}"
        )
    return observed
