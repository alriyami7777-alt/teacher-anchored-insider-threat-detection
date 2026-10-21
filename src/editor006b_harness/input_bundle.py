"""Input-bundle schema, synthetic fixtures, window gather, scaler closed-loop.

Does not materialise a CERT r6.2 bundle. Does not open r5.2 TEST.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterator

import numpy as np

from .safety import (
    COMMON_13_FEATURES,
    DENSE_PARQUET,
    DEV_SUBSET_N,
    DEV_SUBSET_RULE,
    EXPECTED_SCALER_SHA256,
    EXPECTED_TRAIN_NPZ_SHA256,
    EXPECTED_TRAIN_X_RAW_SHA256,
    EXPECTED_VAL_X_RAW_SHA256,
    FREEZE_DIR,
    N_FEATURES,
    REGISTER,
    SYNTHETIC_RNG_SEED,
    T_WINDOW,
    TRAIN_NPZ,
    VAL_NPZ,
    HarnessProtocolError,
    refuse_r52_test,
    sha256_file,
    sha256_bytes,
)


@dataclass(frozen=True)
class SequenceIdentifiers:
    sequence_id: str
    user_id: str
    window_start_date: str
    window_end_date: str
    decision_date: str
    completed_window_label: int
    endpoint_label: int
    deoverlap_offset0_flag: int
    official_insider_flag: int
    official_incident_id: str | None
    answer_scenario_ids: tuple[int, ...]
    endpoint_answer_scenario_ids: tuple[int, ...]
    user_index: int
    start_index: int


FUTURE_METADATA_FIELDS = (
    "sequence_id",
    "user_id",
    "window_start_date",
    "window_end_date",
    "decision_date",
    "completed_window_label",
    "endpoint_label",
    "deoverlap_offset0_flag",
    "official_insider_flag",
    "official_incident_id",
    "answer_scenario_ids",
    "endpoint_answer_scenario_ids",
)


def metadata_schema() -> dict[str, Any]:
    return {
        "schema_name": "EDITOR006B1_SEQUENCE_METADATA",
        "label_rule": "R52_LABEL_RULE_EVENT_LEVEL_ANSWER_MATCH",
        "distinction": "official_incident_id != contextual scenario evidence",
        "official_incident_id": {
            "nullable": True,
            "derives_from": "official insiders/scenario mapping only",
            "not_assigned_from": "contextual answer-event scenario membership",
        },
        "answer_scenario_ids": {
            "meaning": "scenario IDs whose matched answer events occur within the user's T=20 window",
            "cardinality": "zero, one, or more",
            "representation": "sorted unique tuple of ints",
        },
        "endpoint_answer_scenario_ids": {
            "meaning": "scenario IDs of matched events on decision day d",
            "cardinality": "zero, one, or more",
        },
        "required_fields": list(FUTURE_METADATA_FIELDS),
    }


def union_scenario_ids(day_ids: list[tuple[int, ...]]) -> tuple[int, ...]:
    acc: set[int] = set()
    for item in day_ids:
        acc.update(int(v) for v in item)
    return tuple(sorted(acc))


def window_answer_scenario_ids(day_ids: list[tuple[int, ...]], start: int, t: int = T_WINDOW) -> tuple[int, ...]:
    return union_scenario_ids(day_ids[start : start + t])


def endpoint_answer_scenario_ids(day_ids: list[tuple[int, ...]], start: int, t: int = T_WINDOW) -> tuple[int, ...]:
    return tuple(sorted({int(v) for v in day_ids[start + t - 1]}))


@dataclass
class DenseBundle:
    """Memory-mappable dense daily design. Not an r6.2 bundle."""

    scaled_dense_daily: np.ndarray
    malicious_day_labels: np.ndarray
    user_ids: list[str]
    calendar_dates: list[str]
    official_insider_flags: np.ndarray
    official_incident_ids: list[str | None]
    day_answer_scenario_ids: list[list[tuple[int, ...]]]
    dataset_id: str
    source: str

    def __post_init__(self) -> None:
        x = self.scaled_dense_daily
        if x.ndim != 3 or x.shape[2] != N_FEATURES or x.dtype != np.float32:
            raise HarnessProtocolError(f"Bad dense shape/dtype: {x.shape} {x.dtype}")
        if self.malicious_day_labels.shape != x.shape[:2]:
            raise HarnessProtocolError("Label matrix shape mismatch")


def load_persisted_scaler(scaler_path: Path | None = None) -> dict[str, Any]:
    path = Path(scaler_path) if scaler_path is not None else FREEZE_DIR / "EDITOR006A_SCALER.json"
    REGISTER.note(path, "scaler")
    sha = sha256_file(path)
    if sha != EXPECTED_SCALER_SHA256:
        raise HarnessProtocolError(f"Scaler SHA mismatch at load: {sha}")
    obj = json.loads(path.read_text(encoding="utf-8"))
    mean = np.asarray(obj["mean"], dtype=np.float64)
    scale = np.asarray(obj["scale"], dtype=np.float64)
    if mean.shape != (13,) or scale.shape != (13,):
        raise HarnessProtocolError("Scaler vectors must be length 13")
    if list(obj["features"]) != COMMON_13_FEATURES:
        raise HarnessProtocolError("Scaler features != common-13")
    return {"obj": obj, "mean": mean, "scale": scale, "sha256": sha, "path": str(path)}


def apply_persisted_scaler(raw: np.ndarray, mean: np.ndarray, scale: np.ndarray) -> np.ndarray:
    """Transform only. Never fit."""
    return ((raw.astype(np.float64) - mean) / scale).astype(np.float32)


def raw_array_sha(x: np.ndarray) -> str:
    return sha256_bytes(np.ascontiguousarray(x).tobytes())


def closed_loop_train_scaler(*, include_parquet_reconstruction: bool = True) -> dict[str, Any]:
    """EDITOR-003C closed-loop on r5.2 TRAIN only. Never opens TEST."""
    refuse_r52_test(TRAIN_NPZ)
    REGISTER.note(TRAIN_NPZ, "fixture_train_npz")
    npz_sha = sha256_file(TRAIN_NPZ)
    if npz_sha != EXPECTED_TRAIN_NPZ_SHA256:
        raise HarnessProtocolError(f"Train NPZ container SHA mismatch: {npz_sha}")
    with np.load(TRAIN_NPZ, allow_pickle=True, mmap_mode="r") as z:
        x = np.asarray(z["X"], dtype=np.float32)
        users = np.asarray(z["user"]).astype(str)
        starts = np.asarray(z["start_date"]).astype(str)
        feature_names = [str(v) for v in z["feature_names"].tolist()]
    if feature_names != COMMON_13_FEATURES:
        raise HarnessProtocolError("Train NPZ feature names != common-13")
    if tuple(x.shape) != (788000, 20, 13):
        raise HarnessProtocolError(f"Unexpected train X shape {x.shape}")
    x_sha = raw_array_sha(x)
    if x_sha != EXPECTED_TRAIN_X_RAW_SHA256:
        raise HarnessProtocolError(f"Train raw-X SHA mismatch: {x_sha}")

    scaler = load_persisted_scaler()
    mean, scale = scaler["mean"], scaler["scale"]
    implied_raw = x.astype(np.float64) * scale.reshape(1, 1, 13) + mean.reshape(1, 1, 13)
    rescaled = apply_persisted_scaler(implied_raw, mean, scale)
    unequal = int(np.sum(rescaled != x))
    max_abs = float(np.max(np.abs(rescaled.astype(np.float64) - x.astype(np.float64))))
    exact = bool(np.array_equal(rescaled, x))
    if not exact or unequal != 0 or max_abs != 0.0:
        raise HarnessProtocolError(
            f"Scaler inverse-retransform failed unequal={unequal} max_abs={max_abs}"
        )

    parquet_report: dict[str, Any] = {"performed": False}
    if include_parquet_reconstruction:
        parquet_report = _reconstruct_train_from_parquet(x, users, starts, mean, scale)

    val_report: dict[str, Any] = {"performed": False}
    refuse_r52_test(VAL_NPZ)
    REGISTER.note(VAL_NPZ, "fixture_val_npz_hash_only")
    with np.load(VAL_NPZ, allow_pickle=True, mmap_mode="r") as vz:
        vx = np.asarray(vz["X"], dtype=np.float32)
    val_x_sha = raw_array_sha(vx)
    val_report = {
        "performed": True,
        "shape": list(vx.shape),
        "raw_x_sha256": val_x_sha,
        "expected_raw_x_sha256": EXPECTED_VAL_X_RAW_SHA256,
        "match": val_x_sha == EXPECTED_VAL_X_RAW_SHA256,
    }
    if not val_report["match"]:
        raise HarnessProtocolError("Validation raw-X SHA mismatch")

    return {
        "status": "PASS",
        "dataset_fitted_on": "CERT r5.2 TRAIN ONLY",
        "n_train_daily_rows_recorded": 826000,
        "ddof": 0,
        "output_dtype": "float32",
        "no_external_data_fit": True,
        "train_npz_path": str(TRAIN_NPZ),
        "train_npz_sha256": npz_sha,
        "train_x_raw_sha256": x_sha,
        "unequal_elements": unequal,
        "max_abs_difference": max_abs,
        "exact_equality": exact,
        "parquet_reconstruction": parquet_report,
        "validation_array_check": val_report,
        "r52_test_opened": False,
        "scaler_sha256": scaler["sha256"],
    }


def _reconstruct_train_from_parquet(
    x_frozen: np.ndarray,
    users: np.ndarray,
    starts: np.ndarray,
    mean: np.ndarray,
    scale: np.ndarray,
) -> dict[str, Any]:
    import pandas as pd
    import pyarrow.parquet as pq

    REGISTER.note(DENSE_PARQUET, "fixture_dense_parquet_trainonly")
    cols = ["user", "interval_date", *COMMON_13_FEATURES]
    dense = pq.read_table(DENSE_PARQUET, columns=cols).to_pandas()
    dense["user"] = dense["user"].astype(str)
    dense["interval_date"] = pd.to_datetime(dense["interval_date"]).dt.strftime("%Y-%m-%d")
    dense = dense.sort_values(["user", "interval_date"], kind="mergesort")
    scaled_by_user: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for user, grp in dense.groupby("user", sort=False):
        dates = grp["interval_date"].to_numpy()
        raw = grp[COMMON_13_FEATURES].to_numpy(dtype=np.float64)
        scaled_by_user[str(user)] = (dates, apply_persisted_scaler(raw, mean, scale))

    reconstructed = np.empty_like(x_frozen)
    n = len(users)
    order = np.arange(n)
    # Vectorised gather per user (producing pipeline grouping).
    for user in np.unique(users):
        sel = users == user
        positions = order[sel]
        dates, feats = scaled_by_user[str(user)]
        start_vals = starts[sel]
        start_idxs = np.searchsorted(dates, start_vals).astype(np.int64)
        if np.any(start_idxs + T_WINDOW > len(feats)):
            raise HarnessProtocolError(f"Train reconstruction window out of range user={user}")
        if np.any(dates[start_idxs] != start_vals):
            raise HarnessProtocolError(f"Train reconstruction start-date miss user={user}")
        gather = start_idxs[:, None] + np.arange(T_WINDOW, dtype=np.int64)[None, :]
        reconstructed[positions] = feats[gather]
    unequal = int(np.sum(reconstructed != x_frozen))
    max_abs = float(np.max(np.abs(reconstructed.astype(np.float64) - x_frozen.astype(np.float64))))
    exact = bool(np.array_equal(reconstructed, x_frozen))
    if not exact:
        raise HarnessProtocolError(
            f"Parquet reconstruction != frozen TRAIN X unequal={unequal} max_abs={max_abs}"
        )
    return {
        "performed": True,
        "unequal_elements": unequal,
        "max_abs_difference": max_abs,
        "exact_equality": exact,
        "n_windows": int(n),
    }


def gather_windows(
    dense: np.ndarray,
    user_index: np.ndarray,
    start_index: np.ndarray,
) -> np.ndarray:
    """Gather B windows of shape (B,20,13). Callers must pass one batch, not all r6.2 windows."""
    if dense.ndim != 3 or dense.shape[2] != N_FEATURES:
        raise HarnessProtocolError(f"dense must be (U,D,13); got {dense.shape}")
    n = int(len(user_index))
    out = np.empty((n, T_WINDOW, N_FEATURES), dtype=np.float32)
    for i in range(n):
        u = int(user_index[i])
        s = int(start_index[i])
        out[i] = dense[u, s : s + T_WINDOW]
    return out


def iter_window_batches(
    user_index: np.ndarray,
    start_index: np.ndarray,
    batch_size: int,
) -> Iterator[tuple[int, int, np.ndarray, np.ndarray]]:
    n = int(len(user_index))
    if batch_size < 1:
        raise HarnessProtocolError("batch_size must be >= 1")
    for lo in range(0, n, batch_size):
        hi = min(n, lo + batch_size)
        yield lo, hi, user_index[lo:hi], start_index[lo:hi]


class DenseDailyWindowProvider:
    """Memmap-backed batchwise window gather. Never materialises (N,20,13)."""

    def __init__(
        self,
        dense: np.ndarray,
        user_index: np.ndarray,
        start_index: np.ndarray,
        batch_size: int,
    ) -> None:
        if dense.ndim != 3 or dense.shape[2] != N_FEATURES:
            raise HarnessProtocolError(f"dense must be (U,D,13); got {dense.shape}")
        if dense.dtype != np.float32:
            raise HarnessProtocolError(f"dense dtype must be float32; got {dense.dtype}")
        if batch_size < 1:
            raise HarnessProtocolError("batch_size must be >= 1")
        self.dense = dense
        self.user_index = np.asarray(user_index, dtype=np.int64)
        self.start_index = np.asarray(start_index, dtype=np.int64)
        if self.user_index.shape != self.start_index.shape:
            raise HarnessProtocolError("user_index/start_index length mismatch")
        self.batch_size = int(batch_size)
        self.n_sequences = int(len(self.user_index))
        self.batch_shapes: list[tuple[int, ...]] = []
        self.n_batches_yielded = 0

    def __iter__(self) -> Iterator[tuple[int, int, np.ndarray]]:
        self.batch_shapes = []
        self.n_batches_yielded = 0
        for lo, hi, ui, si in iter_window_batches(self.user_index, self.start_index, self.batch_size):
            batch = gather_windows(self.dense, ui, si)
            if batch.shape[0] > self.batch_size:
                raise HarnessProtocolError("Window provider yielded more than one batch")
            if batch.shape != (hi - lo, T_WINDOW, N_FEATURES):
                raise HarnessProtocolError(f"Bad gathered batch shape {batch.shape}")
            self.batch_shapes.append(tuple(batch.shape))
            self.n_batches_yielded += 1
            yield lo, hi, batch

    def assert_never_full_sequence_tensor(self) -> None:
        n = self.n_sequences
        for shape in self.batch_shapes:
            if shape == (n, T_WINDOW, N_FEATURES) and n > self.batch_size:
                raise HarnessProtocolError("Full (N,20,13) tensor was materialised")
            if shape[0] > self.batch_size:
                raise HarnessProtocolError("Batch exceeded frozen batch size")


def make_sequence_table(
    *,
    user_ids: list[str],
    calendar_dates: list[str],
    user_index: np.ndarray,
    start_index: np.ndarray,
    completed_labels: np.ndarray,
    endpoint_labels: np.ndarray,
    official_insider_flags: np.ndarray,
    official_incident_ids: list[str | None],
    day_answer_scenario_ids: list[list[tuple[int, ...]]],
) -> list[SequenceIdentifiers]:
    rows: list[SequenceIdentifiers] = []
    n_days = len(calendar_dates)
    for i in range(len(user_index)):
        u = int(user_index[i])
        s = int(start_index[i])
        e = s + T_WINDOW - 1
        if e >= n_days:
            raise HarnessProtocolError("window overruns calendar")
        official_flag = int(official_insider_flags[u])
        official_incident = official_incident_ids[u]
        if official_flag != 1:
            official_incident = None
        elif official_incident is None or str(official_incident).strip() == "":
            raise HarnessProtocolError("Official insider missing official_incident_id")
        ans = window_answer_scenario_ids(day_answer_scenario_ids[u], s)
        end_ans = endpoint_answer_scenario_ids(day_answer_scenario_ids[u], s)
        rows.append(
            SequenceIdentifiers(
                sequence_id=f"seq_{i:08d}",
                user_id=str(user_ids[u]),
                window_start_date=calendar_dates[s],
                window_end_date=calendar_dates[e],
                decision_date=calendar_dates[e],
                completed_window_label=int(completed_labels[i]),
                endpoint_label=int(endpoint_labels[i]),
                deoverlap_offset0_flag=int(s % T_WINDOW == 0),
                official_insider_flag=official_flag,
                official_incident_id=None if official_incident is None else str(official_incident),
                answer_scenario_ids=ans,
                endpoint_answer_scenario_ids=end_ans,
                user_index=u,
                start_index=s,
            )
        )
    return rows


def identifiers_sha(rows: list[SequenceIdentifiers]) -> str:
    blob = json.dumps([asdict(r) for r in rows], separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return sha256_bytes(blob)


def build_synthetic_bundle(*, n_users: int = 4, n_days: int = 40, rng_seed: int = SYNTHETIC_RNG_SEED) -> dict[str, Any]:
    rng = np.random.default_rng(rng_seed)
    dense = rng.normal(size=(n_users, n_days, N_FEATURES)).astype(np.float32)
    labels = np.zeros((n_users, n_days), dtype=np.int8)
    labels[0, 25:28] = 1
    labels[1, 10] = 1
    if n_users >= 4:
        labels[3, 15] = 1
        labels[3, 16] = 1
    user_ids = [f"SYN{u:04d}" for u in range(n_users)]
    start = date(2010, 1, 2)
    calendar = [(start + timedelta(days=i)).isoformat() for i in range(n_days)]
    official = np.zeros(n_users, dtype=np.int8)
    official[0] = 1
    official_incident_ids: list[str | None] = [None] * n_users
    official_incident_ids[0] = "rSYN-1"
    day_answer: list[list[tuple[int, ...]]] = [[() for _ in range(n_days)] for _ in range(n_users)]
    for d in range(25, 28):
        day_answer[0][d] = (1,)
    day_answer[1][10] = (2,)
    if n_users >= 4:
        day_answer[3][15] = (1,)
        day_answer[3][16] = (4,)
    ui: list[int] = []
    si: list[int] = []
    completed: list[int] = []
    endpoint: list[int] = []
    for u in range(n_users):
        for s in range(0, n_days - T_WINDOW + 1):
            ui.append(u)
            si.append(s)
            completed.append(int(labels[u, s : s + T_WINDOW].max()))
            endpoint.append(int(labels[u, s + T_WINDOW - 1]))
    user_index = np.asarray(ui, dtype=np.int64)
    start_index = np.asarray(si, dtype=np.int64)
    rows = make_sequence_table(
        user_ids=user_ids,
        calendar_dates=calendar,
        user_index=user_index,
        start_index=start_index,
        completed_labels=np.asarray(completed, dtype=np.int8),
        endpoint_labels=np.asarray(endpoint, dtype=np.int8),
        official_insider_flags=official,
        official_incident_ids=official_incident_ids,
        day_answer_scenario_ids=day_answer,
    )
    bundle = DenseBundle(
        scaled_dense_daily=dense,
        malicious_day_labels=labels,
        user_ids=user_ids,
        calendar_dates=calendar,
        official_insider_flags=official,
        official_incident_ids=official_incident_ids,
        day_answer_scenario_ids=day_answer,
        dataset_id="SYNTHETIC_EDITOR006B",
        source="deterministic_synthetic_fixture",
    )
    return {
        "bundle": bundle,
        "user_index": user_index,
        "start_index": start_index,
        "identifiers": rows,
        "identifiers_sha256": identifiers_sha(rows),
        "n_sequences": len(rows),
        "rng_seed": rng_seed,
        "scientific_interpretation_forbidden": True,
    }


def load_validation_development_fixture(*, n: int = DEV_SUBSET_N) -> dict[str, Any]:
    refuse_r52_test(VAL_NPZ)
    REGISTER.note(VAL_NPZ, "fixture_validation_npz")
    sha = sha256_file(VAL_NPZ)
    with np.load(VAL_NPZ, allow_pickle=True, mmap_mode="r") as z:
        x = np.asarray(z["X"][:n], dtype=np.float32)
        y = np.asarray(z["y"][:n])
        seq = np.asarray(z["sequence_id"][:n]).astype(str)
        users = np.asarray(z["user"][:n]).astype(str)
        starts = np.asarray(z["start_date"][:n]).astype(str)
        ends = np.asarray(z["end_date"][:n]).astype(str)
    indices = list(range(n))
    idx_sha = sha256_bytes(json.dumps(indices, separators=(",", ":")).encode("utf-8"))
    rows = []
    for i in range(n):
        rows.append(
            SequenceIdentifiers(
                sequence_id=str(seq[i]),
                user_id=str(users[i]),
                window_start_date=str(starts[i]),
                window_end_date=str(ends[i]),
                decision_date=str(ends[i]),
                completed_window_label=int(y[i]),
                endpoint_label=-1,
                deoverlap_offset0_flag=-1,
                official_insider_flag=-1,
                official_incident_id=None,
                answer_scenario_ids=(),
                endpoint_answer_scenario_ids=(),
                user_index=-1,
                start_index=i,
            )
        )
    return {
        "path": str(VAL_NPZ),
        "source_tensor_sha256": sha,
        "subset_rule": DEV_SUBSET_RULE,
        "subset_n": n,
        "subset_indices": indices,
        "subset_indices_sha256": idx_sha,
        "X": x,
        "y_completed_from_npz": y,
        "identifiers": rows,
        "identifiers_sha256": identifiers_sha(rows),
        "scientific_interpretation_forbidden": True,
        "r52_test_opened": False,
    }


def completed_and_endpoint_from_days(mal: np.ndarray, start: int) -> tuple[int, int]:
    window = mal[start : start + T_WINDOW]
    return int(window.max()), int(window[-1])
