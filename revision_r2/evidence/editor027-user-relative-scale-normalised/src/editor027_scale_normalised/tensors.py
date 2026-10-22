"""Build user-relative daily panels and frozen-window tensors. Labels never enter the transform."""

from __future__ import annotations

from typing import Any

import numpy as np
import pyarrow.parquet as pq

from editor006b_harness.safety import EXPECTED_TRAIN_NPZ_SHA256
from editor012_rescue.constants import EXPECTED_VAL_SHA256
from editor024_r61.scaler import load_r52_train_scaler
from editor025_r61_autopsy.feature_shift import inverse_scale

from .constants import (
    EXPECTED_TRAIN_POS,
    EXPECTED_TRAIN_SHAPE,
    EXPECTED_VAL_POS,
    EXPECTED_VAL_SHAPE,
    FEATURE_ORDER,
    R52_DENSE_PARQUET,
    R52_TRAIN_NPZ,
    R52_VAL_NPZ,
    SEQUENCE_LENGTH_LOCKED,
)
from .representation import causal_scale_normalised_daily, causal_scale_normalised_panel
from .safety import Editor027Blocked, sha256_file
from .scaler import ScaleNetworkScaler
from .windows import gather_windows, r61_gather_windows, split_notes


def _floors_vec(scale_floors: Any) -> np.ndarray:
    if scale_floors is None:
        raise Editor027Blocked("SCALE floors must be derived from r5.2 TRAIN before transform")
    if isinstance(scale_floors, dict) and "floor_vector" in scale_floors:
        return np.asarray(scale_floors["floor_vector"], dtype=np.float64)
    return np.asarray(scale_floors, dtype=np.float64)


def _load_npz(path, expected_sha: str, expected_shape: tuple[int, ...], expected_pos: int, role: str) -> dict[str, np.ndarray]:
    sha = sha256_file(path)
    if sha != expected_sha:
        raise Editor027Blocked(f"{role} npz hash mismatch {sha}")
    with np.load(path, allow_pickle=True) as z:
        x = np.asarray(z["X"], dtype=np.float32)
        y = np.asarray(z["y"]).astype(np.int8).ravel()
        user = np.asarray(z["user"]).astype(str)
        seq = np.asarray(z["sequence_id"]).astype(str)
        start = np.asarray(z["start_date"]).astype(str)
        end = np.asarray(z["end_date"]).astype(str)
    if tuple(x.shape) != expected_shape:
        raise Editor027Blocked(f"{role} shape {x.shape} != {expected_shape}")
    if int(y.sum()) != expected_pos:
        raise Editor027Blocked(f"{role} pos {int(y.sum())} != {expected_pos}")
    return {"X": x, "y": y, "user": user, "sequence_id": seq, "start_date": start, "end_date": end, "sha256": sha}


def load_frozen_r52_splits() -> dict[str, Any]:
    train = _load_npz(R52_TRAIN_NPZ, EXPECTED_TRAIN_NPZ_SHA256, EXPECTED_TRAIN_SHAPE, EXPECTED_TRAIN_POS, "train")
    val = _load_npz(R52_VAL_NPZ, EXPECTED_VAL_SHA256, EXPECTED_VAL_SHAPE, EXPECTED_VAL_POS, "validation")
    return {"train": train, "val": val}


def load_r52_dense_raw() -> dict[str, Any]:
    cols = ["user", "interval_date", *FEATURE_ORDER]
    table = pq.read_table(R52_DENSE_PARQUET, columns=cols)
    df = table.to_pandas()
    df["user"] = df["user"].astype(str)
    df["interval_date"] = df["interval_date"].astype(str).str.slice(0, 10)
    df = df.sort_values(["user", "interval_date"], kind="mergesort").reset_index(drop=True)
    raw_by_user: dict[str, np.ndarray] = {}
    dates_by_user: dict[str, np.ndarray] = {}
    for u, grp in df.groupby("user", sort=False):
        dates_by_user[str(u)] = grp["interval_date"].to_numpy()
        raw_by_user[str(u)] = grp.loc[:, list(FEATURE_ORDER)].to_numpy(dtype=np.float64)
    return {
        "raw_by_user": raw_by_user,
        "dates_by_user": dates_by_user,
        "n_users": len(raw_by_user),
        "n_rows": int(len(df)),
        "path": str(R52_DENSE_PARQUET),
    }


def transform_r52_scale(dense: dict[str, Any], scale_floors: Any) -> dict[str, np.ndarray]:
    floors = _floors_vec(scale_floors)
    ur: dict[str, np.ndarray] = {}
    for u, raw in dense["raw_by_user"].items():
        ur[u] = causal_scale_normalised_daily(
            raw, dense["dates_by_user"][u], scale_floors=floors
        )
    return ur


def train_calendar_mask(dates: np.ndarray, train_start: str, train_end: str) -> np.ndarray:
    d = np.asarray(dates).astype(str)
    return (d >= train_start[:10]) & (d <= train_end[:10])


def fit_scale_scaler(
    ur_by_user: dict[str, np.ndarray],
    dates_by_user: dict[str, np.ndarray],
    train_start: str,
    train_end: str,
) -> ScaleNetworkScaler:
    blocks = []
    for u, arr in ur_by_user.items():
        mask = train_calendar_mask(dates_by_user[u], train_start, train_end)
        if mask.any():
            blocks.append(arr[mask])
    if not blocks:
        raise Editor027Blocked("no r5.2 TRAIN user-relative daily rows")
    scaler = ScaleNetworkScaler()
    scaler.fit(np.concatenate(blocks, axis=0), source="CERT r5.2 TRAIN ONLY")
    return scaler


def scale_by_user(ur_by_user: dict[str, np.ndarray], scaler: ScaleNetworkScaler) -> dict[str, np.ndarray]:
    return {u: scaler.transform(arr) for u, arr in ur_by_user.items()}


def build_r52_scale_windows(
    *,
    scaled_by_user: dict[str, np.ndarray],
    dates_by_user: dict[str, np.ndarray],
    split: dict[str, np.ndarray],
) -> np.ndarray:
    return gather_windows(
        scaled_by_user=scaled_by_user,
        dates_by_user=dates_by_user,
        users=split["user"],
        start_dates=split["start_date"],
        sequence_length=SEQUENCE_LENGTH_LOCKED,
    )


def load_r61_bundle_raw() -> dict[str, Any]:
    from pathlib import Path
    from .constants import EDITOR024_OUTPUT_REL, repo_root

    b = repo_root() / EDITOR024_OUTPUT_REL / "bundle"
    scaled = np.load(b / "scaled_dense_daily.npy", mmap_mode="r")
    orig = load_r52_train_scaler()
    raw = inverse_scale(np.asarray(scaled), orig["mean"], orig["scale"])
    return {
        "raw": raw,
        "y": np.load(b / "completed_window_labels.npy"),
        "user_idx": np.load(b / "window_user_index.npy"),
        "start_idx": np.load(b / "window_start_index.npy"),
        "user_ids_sorted": np.load(b / "user_ids_sorted.npy", allow_pickle=True).astype(str),
        "user_ids_windows": np.load(b / "user_ids_windows.npy", allow_pickle=True).astype(str),
        "sequence_ids": np.load(b / "sequence_ids.npy", allow_pickle=True).astype(str),
        "calendar_dates": np.load(b / "calendar_dates.npy", allow_pickle=True).astype(str),
        "original_scaler_sha256": orig["sha256"],
    }


def build_r61_scale(
    bundle: dict[str, Any],
    scaler: ScaleNetworkScaler,
    scale_floors: Any,
) -> dict[str, np.ndarray]:
    floors = _floors_vec(scale_floors)
    ur_raw = causal_scale_normalised_panel(
        bundle["raw"], dates=bundle["calendar_dates"], scale_floors=floors
    )
    ur_scaled = scaler.transform(ur_raw)
    x = r61_gather_windows(
        scaled_panel=ur_scaled,
        user_index=bundle["user_idx"],
        start_index=bundle["start_idx"],
    )
    return {"ur_raw": ur_raw, "ur_scaled_daily": ur_scaled, "X": x}


def r61_pos_weight_notes() -> dict[str, Any]:
    return {
        **split_notes(),
        "r61_used_for_scaler_fit": False,
        "r61_used_for_model_training": False,
    }
