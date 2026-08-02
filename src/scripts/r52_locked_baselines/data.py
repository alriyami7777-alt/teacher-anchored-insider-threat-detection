"""r5.2 train/validation loading and locked 40-feature aggregation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from . import BINARY_FEATURES, COMMON_13_FEATURES, NUMERIC_FEATURES
from .safety import (
    ProtocolAccessError,
    assert_path_allowed,
    path_looks_like_test,
    refuse_test_loader,
    sha256_file,
)

EXPECTED_SHAPES = {"train": (788_000, 20, 13), "validation": (64_000, 20, 13)}
EXPECTED_POS = {"train": 3_957, "validation": 728}
LOCKED_AGG_FEATURES = [
    f"{c}_{a}" for c in NUMERIC_FEATURES for a in ("sum", "mean", "max", "std")
] + [
    f"{c}_{a}" for c in BINARY_FEATURES for a in ("active_days", "active_proportion")
]


def load_split_npz(tensor_dir: Path, split: str) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    if split == "test" or "test" in str(split).lower():
        refuse_test_loader(split=str(split), path=Path(tensor_dir) / f"r52_T20_s1_{split}.npz")
    if split not in {"train", "validation"}:
        raise ProtocolAccessError(f"REFUSED split={split}; only train/validation allowed")
    path = Path(tensor_dir) / f"r52_T20_s1_{split}.npz"
    assert_path_allowed(path, role=f"{split}_tensor")
    if path_looks_like_test(path) or "test" in path.name.lower():
        refuse_test_loader(split=split, path=path)
    z = np.load(path, allow_pickle=True, mmap_mode="r")
    X = np.asarray(z["X"], dtype=np.float32)
    y = np.asarray(z["y"])
    meta = {
        "path": str(path),
        "sha256": sha256_file(path),
        "files": list(z.files),
        "feature_names": (
            [str(v) for v in z["feature_names"].tolist()] if "feature_names" in z.files else None
        ),
        "user": z["user"] if "user" in z.files else None,
        "sequence_id": z["sequence_id"] if "sequence_id" in z.files else None,
        "start_date": z["start_date"] if "start_date" in z.files else None,
        "end_date": z["end_date"] if "end_date" in z.files else None,
    }
    return X, y, meta


def aggregate_common13_windows(X: np.ndarray) -> tuple[np.ndarray, list[str]]:
    """Deterministic locked r4.2 aggregation: T×F → 40 features."""
    if X.ndim != 3 or X.shape[1] != 20 or X.shape[2] != 13:
        raise ProtocolAccessError(f"Expected (N,20,13); got {X.shape}")
    cols: list[np.ndarray] = []
    names: list[str] = []
    for j, col in enumerate(NUMERIC_FEATURES):
        vals = X[:, :, j]
        for agg, arr in (
            ("sum", vals.sum(axis=1)),
            ("mean", vals.mean(axis=1)),
            ("max", vals.max(axis=1)),
            ("std", vals.std(axis=1)),
        ):
            cols.append(arr.astype(np.float32, copy=False))
            names.append(f"{col}_{agg}")
    for j, col in enumerate(BINARY_FEATURES):
        vals = X[:, :, 7 + j]
        cols.append(vals.sum(axis=1).astype(np.float32, copy=False))
        names.append(f"{col}_active_days")
        cols.append(vals.mean(axis=1).astype(np.float32, copy=False))
        names.append(f"{col}_active_proportion")
    feat = np.stack(cols, axis=1)
    if names != LOCKED_AGG_FEATURES:
        raise ProtocolAccessError("Aggregated feature order mismatch vs locked schema")
    if feat.shape[1] != 40:
        raise ProtocolAccessError(f"Expected 40 features; got {feat.shape[1]}")
    return feat, names


def audit_r52_tensors(
    tensor_dir: Path, root: Path
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    feature_list_path = root / "outputs/r5.2/tensors/r52_T20_s1_tensor_feature_list.csv"
    assert_path_allowed(feature_list_path, role="feature_list")
    feats = pd.read_csv(feature_list_path)["feature_name"].tolist()
    if feats != COMMON_13_FEATURES:
        raise ProtocolAccessError(f"Feature schema mismatch: {feats}")

    # Refuse constructing test path as a loader target.
    sibling_test = Path(tensor_dir) / "r52_T20_s1_test.npz"
    if sibling_test.exists() and path_looks_like_test(sibling_test):
        pass  # presence on disk allowed; never opened

    datasets: dict[str, dict[str, Any]] = {}
    for split in ("train", "validation"):
        X, y, meta = load_split_npz(tensor_dir, split)
        if tuple(X.shape) != EXPECTED_SHAPES[split]:
            raise ProtocolAccessError(f"{split} shape {X.shape} != {EXPECTED_SHAPES[split]}")
        pos = int(y.sum())
        if pos != EXPECTED_POS[split]:
            raise ProtocolAccessError(f"{split} pos {pos} != {EXPECTED_POS[split]}")
        if meta["feature_names"] is not None and meta["feature_names"] != COMMON_13_FEATURES:
            raise ProtocolAccessError(f"{split} embedded feature names mismatch")
        datasets[split] = {"X": X, "y": y, "meta": meta}

    train_ids = set(map(str, np.asarray(datasets["train"]["meta"]["sequence_id"]).tolist()))
    val_ids = set(map(str, np.asarray(datasets["validation"]["meta"]["sequence_id"]).tolist()))
    id_overlap = train_ids & val_ids

    train_ud = {
        f"{u}|{d}"
        for u, d in zip(
            np.asarray(datasets["train"]["meta"]["user"]).tolist(),
            np.asarray(datasets["train"]["meta"]["start_date"]).tolist(),
            strict=True,
        )
    }
    val_ud = {
        f"{u}|{d}"
        for u, d in zip(
            np.asarray(datasets["validation"]["meta"]["user"]).tolist(),
            np.asarray(datasets["validation"]["meta"]["start_date"]).tolist(),
            strict=True,
        )
    }
    ud_overlap = train_ud & val_ud

    train_end = max(map(str, np.asarray(datasets["train"]["meta"]["end_date"]).tolist()))
    val_start = min(map(str, np.asarray(datasets["validation"]["meta"]["start_date"]).tolist()))
    val_end = max(map(str, np.asarray(datasets["validation"]["meta"]["end_date"]).tolist()))
    chronological = train_end < val_start
    if train_end > "2011-02-18":
        raise ProtocolAccessError(f"Train boundary too late: {train_end}")
    if not (val_start >= "2011-02-19" and val_end <= "2011-04-10"):
        raise ProtocolAccessError(f"Validation window mismatch: {val_start}..{val_end}")
    if id_overlap or ud_overlap or not chronological:
        raise ProtocolAccessError("Split audit failed")

    users = set(map(str, np.asarray(datasets["train"]["meta"]["user"]).tolist())) | set(
        map(str, np.asarray(datasets["validation"]["meta"]["user"]).tolist())
    )
    if len(users) != 2000:
        raise ProtocolAccessError(f"Expected 2000 users; got {len(users)}")

    data_manifest = {
        "release": "CERT r5.2",
        "sequence_length_T": 20,
        "feature_dim_F": 13,
        "feature_names": COMMON_13_FEATURES,
        "users": 2000,
        "train_sequences": 788000,
        "train_positives": 3957,
        "validation_sequences": 64000,
        "validation_positives": 728,
        "train_end_date_max": train_end,
        "validation_start_date_min": val_start,
        "validation_end_date_max": val_end,
        "test_partition_accessed": False,
        "r62_accessed": False,
        "train_tensor_sha256": datasets["train"]["meta"]["sha256"],
        "validation_tensor_sha256": datasets["validation"]["meta"]["sha256"],
        "aggregation": {
            "method": "locked_r42_window_aggregates",
            "input": "T×F=20×13 common-13 sequences",
            "output_dim": 40,
            "feature_names": LOCKED_AGG_FEATURES,
            "source_script": "scripts/run_baseline_evaluation.py + run_validation_audit.py aggregation",
        },
    }
    split_audit = {
        "n_users_train_or_val": len(users),
        "sequence_id_overlap_count": 0,
        "user_start_date_overlap_count": 0,
        "chronological_train_before_validation": True,
        "test_loaded": False,
        "r62_accessed": False,
        "pass_no_sequence_overlap": True,
        "pass_no_user_date_overlap": True,
        "pass_chronological": True,
        "pass_expected_counts": True,
    }
    return data_manifest, split_audit, datasets
