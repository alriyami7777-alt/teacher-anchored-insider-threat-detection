"""Fail-closed path and protocol guards for EDITOR-006B.

No r6.2 predictive access. No r5.2 TEST tensor. No training entry points.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = Path(__file__).resolve().parents[1]
FREEZE_DIR = REPO_ROOT / "review" / "editor006a_preinference_freeze"
OUTPUT_DIR_DEFAULT = REPO_ROOT / "review" / "editor006b_harness"

FEAS_SCRIPTS = Path(r"C:\PhD\07_Projects\cert-r42-feasibility\scripts")
LOCKED_SCRIPTS = Path(r"C:\PhD\07_Projects\cert-r52-locked-baselines\scripts")
TRAIN_NPZ = Path(
    r"C:\PhD\07_Projects\cert-r42-feasibility\data\processed\r5.2\tensors\r52_T20_s1_train.npz"
)
VAL_NPZ = Path(
    r"C:\PhD\07_Projects\cert-r42-feasibility\data\processed\r5.2\tensors\r52_T20_s1_validation.npz"
)
DENSE_PARQUET = Path(
    r"C:\PhD\07_Projects\cert-r42-feasibility\data\processed\r5.2\interval_level\r52_user_day_intervals_dense.parquet"
)

EXPECTED_SCALER_SHA256 = "6a092df8275e15b6e05c685b306f48de72ab55fb1e88ede5ed5899ecd63f3488"
EXPECTED_TRAIN_NPZ_SHA256 = "b268328d3bf2e98f712d1145958dabe175ce2c07a7c390da4b84a663317ebc2e"
EXPECTED_TRAIN_X_RAW_SHA256 = "f3eb0ccec75eea247713473bc9e31c5ea6753a1e3fedb126d3651fd3439373b3"
EXPECTED_VAL_X_RAW_SHA256 = "73192caa4bfbbaee88e755912768c39b3f39d404686c97eb487756964ba7b292"
EXPECTED_AGGREGATOR_SHA256 = "dd47330f82791bc7c56d3d6019ce80bcd6ca31f497b9fffeabc9165f35b1b2f9"
EXPECTED_ARCHITECTURE_SHA256 = "9867b0c266f3b735d138e2d8d53f0d3f5c5c644e25302c10c25e2f4677560abd"
EXPECTED_ODST_SHA256 = "95764ce80a7c80529108d8d6b72f6bd06896c39d065f7e475c12dce8421417bb"
EXPECTED_SEQUENCE_ENSEMBLE_SHA256 = "43f16bce9c09305c7578d319dadf4c23c6c18cbe70fd7dcc1fda0114c86d6475"
FUTURE_EXTERNAL_DATASET_ID = "CERT r6.2"
C2_SEED62_THRESHOLD = 0.6544522184133537

EXPECTED_FAMILIES = (
    "teacher_frozen_odst",
    "C2",
    "C5_original_paper",
    "attention_linear",
    "RF_40",
    "XGBoost_40",
)
SEEDS = (42, 52, 62)
T_WINDOW = 20
N_FEATURES = 13
N_AGG_FEATURES = 40
BATCH_SIZE_FROZEN = 1024
BOOTSTRAP_SEED = 2026
BOOTSTRAP_VALID_RESAMPLES = 2000
DEV_SUBSET_N = 256
DEV_SUBSET_RULE = "first_n_validation_sequences_index_order"
SYNTHETIC_RNG_SEED = 2026

COMMON_13_FEATURES = [
    "total_events",
    "logon_count",
    "device_count",
    "file_count",
    "email_count",
    "http_count",
    "active_duration_minutes",
    "has_logon_activity",
    "has_device_activity",
    "has_file_activity",
    "has_email_activity",
    "has_http_activity",
    "is_active_day",
]

SCORE_STEM = {
    "teacher_frozen_odst": "teacher",
    "C2": "c2",
    "C5_original_paper": "c5",
    "attention_linear": "attention_linear",
    "RF_40": "rf",
    "XGBoost_40": "xgb",
}

CHECKPOINT_STATE_KEY = "model_state_dict"

R62_MARKERS = (
    "r6.2",
    "r62",
    "processed/r6.2",
    "processed\\r6.2",
    "raw/r6.2",
    "raw\\r6.2",
    "cert r6.2",
    "dataset_id=cert r6.2",
)
R52_TEST_MARKERS = (
    "r52_t20_s1_test",
    "r5.2_t20_s1_test",
    "r52_t20_s1_test.npz",
)


class HarnessProtocolError(RuntimeError):
    """Fail-closed harness violation."""


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


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _norm(text: str) -> str:
    return text.replace("\\", "/").lower()


def path_looks_like_r62(path: str | Path) -> bool:
    text = _norm(str(path))
    return any(marker in text for marker in R62_MARKERS)


def path_looks_like_r52_test(path: str | Path) -> bool:
    text = _norm(str(path))
    name = Path(path).name.lower()
    if name == "r52_t20_s1_test.npz":
        return True
    return any(marker in text for marker in R52_TEST_MARKERS)


def refuse_r52_test(path: str | Path) -> None:
    if path_looks_like_r52_test(path):
        raise HarnessProtocolError(f"REFUSED: r5.2 TEST tensor path: {path}")


def refuse_r62_without_auth(path: str | Path, *, authorised: bool) -> None:
    if path_looks_like_r62(path) and not authorised:
        raise HarnessProtocolError(
            f"REFUSED: CERT r6.2 path without valid external authorisation: {path}"
        )


def refuse_dataset_id_r62(dataset_id: str, *, authorised: bool) -> None:
    token = (dataset_id or "").strip().lower().replace("_", " ")
    if token in {"cert r6.2", "r6.2", "r62", "cert-r6.2"} and not authorised:
        raise HarnessProtocolError(
            f"REFUSED: dataset_id={dataset_id!r} without valid external authorisation"
        )


def assert_not_test_split(split: str) -> None:
    if str(split).strip().lower() == "test":
        raise HarnessProtocolError("REFUSED: split=test")


class OpenedPathRegister:
    """Record every path the harness opens."""

    def __init__(self) -> None:
        self.opened: list[dict[str, str]] = []
        self.models_loaded: list[str] = []
        self.fixture_files: list[str] = []
        self.outputs_created: list[str] = []

    def note(self, path: Path | str, role: str) -> Path:
        p = Path(path)
        refuse_r52_test(p)
        self.opened.append({"path": str(p), "role": role, "utc": utc_now()})
        if role.startswith("model"):
            self.models_loaded.append(str(p))
        if role.startswith("fixture"):
            self.fixture_files.append(str(p))
        if role.startswith("output"):
            self.outputs_created.append(str(p))
        return p


REGISTER = OpenedPathRegister()


def hash_harness_sources() -> str:
    files = sorted((Path(__file__).resolve().parent).glob("*.py"))
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()
