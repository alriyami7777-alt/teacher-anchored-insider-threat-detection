"""Train/validation loading, flattening, and partition parity."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .constants import (
    EXPECTED_TRAIN_POS,
    EXPECTED_TRAIN_SHA256,
    EXPECTED_TRAIN_SHAPE,
    EXPECTED_VAL_POS,
    EXPECTED_VAL_SHA256,
    EXPECTED_VAL_SHAPE,
    FLAT_DIM,
    N_FEATURES,
    SAFE_FEATURES,
    SEQ_LEN,
    STATUS_FEATURE_MISMATCH,
    STATUS_PARTITION_MISMATCH,
    TENSOR_DIR_REL,
    TRAIN_NAME,
    VAL_NAME,
)
from .safety import (
    ComparisonBlockedError,
    ProtectedDataAccessError,
    assert_path_allowed_for_read,
    refuse_test_loader_construction,
    sha256_array,
    sha256_bytes,
    sha256_file,
)


def sha256_ids(ids: np.ndarray) -> str:
    payload = "\n".join(str(x) for x in np.asarray(ids).tolist()).encode("utf-8")
    return sha256_bytes(payload)


@dataclass(frozen=True)
class PartitionBundle:
    name: str
    path: Path
    X_seq: np.ndarray
    X_flat: np.ndarray
    y: np.ndarray
    sequence_id: np.ndarray
    user: np.ndarray
    feature_names: tuple[str, ...]
    sha256: str
    seq_hash: str
    flat_hash: str
    id_hash: str
    label_hash: str
    n_pos: int
    n_neg: int


def flatten_mapping(feature_names: tuple[str, ...] = SAFE_FEATURES) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for t in range(SEQ_LEN):
        for f, name in enumerate(feature_names):
            col = t * N_FEATURES + f
            rows.append(
                {
                    "flat_column_index": col,
                    "time_step_index": t,
                    "day_number_1based": t + 1,
                    "feature_index": f,
                    "feature_name": name,
                    "mapping": f"day{t + 1}__{name}",
                }
            )
    if len(rows) != FLAT_DIM:
        raise RuntimeError(f"Expected {FLAT_DIM} flatten columns; got {len(rows)}")
    return rows


def flatten_sequences(X: np.ndarray) -> np.ndarray:
    if X.ndim != 3 or X.shape[1] != SEQ_LEN or X.shape[2] != N_FEATURES:
        raise ComparisonBlockedError(
            STATUS_FEATURE_MISMATCH,
            f"objective2_same_information_comparison_blocked_feature_mismatch: shape {X.shape}",
        )
    flat = np.ascontiguousarray(X.reshape(X.shape[0], FLAT_DIM))
    # Exact value parity: first/last sample round-trip
    if not np.array_equal(flat.reshape(-1, SEQ_LEN, N_FEATURES), X):
        raise ComparisonBlockedError(
            STATUS_FEATURE_MISMATCH,
            "objective2_same_information_comparison_blocked_feature_mismatch: reshape parity failed",
        )
    return flat.astype(np.float32, copy=False)


def _load_npz(path: Path) -> dict[str, Any]:
    assert_path_allowed_for_read(path, context="npz_load")
    refuse_test_loader_construction(partition=path.name)
    data = np.load(path, allow_pickle=True)
    keys = set(data.files)
    if "X" not in keys or "y" not in keys:
        raise RuntimeError(f"Unrecognized tensor keys in {path}: {sorted(keys)}")
    X = np.asarray(data["X"], dtype=np.float32)
    y = np.asarray(data["y"]).astype(np.int32).ravel()
    feature_names = SAFE_FEATURES
    if "feature_names" in keys:
        raw = data["feature_names"]
        feature_names = tuple(str(x) for x in (raw.tolist() if getattr(raw, "ndim", 0) else raw.item()))
    sequence_id = (
        np.asarray(data["sequence_id"]).astype(str)
        if "sequence_id" in keys
        else np.arange(len(y)).astype(str)
    )
    user = (
        np.asarray(data["user"]).astype(str)
        if "user" in keys
        else np.array(["unknown"] * len(y), dtype=str)
    )
    return {
        "X": X,
        "y": y,
        "feature_names": feature_names,
        "sequence_id": sequence_id,
        "user": user,
        "keys": sorted(keys),
    }


def load_train_validation(repo_root: Path, *, verify_hashes: bool = True) -> dict[str, Any]:
    refuse_test_loader_construction(partition="train")
    refuse_test_loader_construction(partition="validation")

    train_path = (repo_root / TENSOR_DIR_REL / TRAIN_NAME).resolve()
    val_path = (repo_root / TENSOR_DIR_REL / VAL_NAME).resolve()
    assert_path_allowed_for_read(train_path, context="train")
    assert_path_allowed_for_read(val_path, context="validation")

    # Explicitly refuse constructing a test loader path as a usable target.
    test_probe = repo_root / TENSOR_DIR_REL / "r52_T20_s1_test.npz"
    try:
        assert_path_allowed_for_read(test_probe, context="test_probe")
        raise ProtectedDataAccessError("Test path unexpectedly passed guard")
    except ProtectedDataAccessError:
        pass

    train_sha = sha256_file(train_path) if verify_hashes else EXPECTED_TRAIN_SHA256
    val_sha = sha256_file(val_path) if verify_hashes else EXPECTED_VAL_SHA256
    if verify_hashes:
        if train_sha != EXPECTED_TRAIN_SHA256:
            raise RuntimeError(f"Train SHA mismatch: {train_sha}")
        if val_sha != EXPECTED_VAL_SHA256:
            raise RuntimeError(f"Val SHA mismatch: {val_sha}")

    train_raw = _load_npz(train_path)
    val_raw = _load_npz(val_path)

    if train_raw["X"].shape != EXPECTED_TRAIN_SHAPE:
        raise ComparisonBlockedError(
            STATUS_PARTITION_MISMATCH,
            f"Train shape {train_raw['X'].shape} != {EXPECTED_TRAIN_SHAPE}",
        )
    if val_raw["X"].shape != EXPECTED_VAL_SHAPE:
        raise ComparisonBlockedError(
            STATUS_PARTITION_MISMATCH,
            f"Val shape {val_raw['X'].shape} != {EXPECTED_VAL_SHAPE}",
        )
    if int(train_raw["y"].sum()) != EXPECTED_TRAIN_POS or int(val_raw["y"].sum()) != EXPECTED_VAL_POS:
        raise ComparisonBlockedError(
            STATUS_PARTITION_MISMATCH,
            "objective2_same_information_comparison_blocked_partition_mismatch: label counts",
        )
    if tuple(train_raw["feature_names"]) != SAFE_FEATURES:
        raise ComparisonBlockedError(
            STATUS_FEATURE_MISMATCH,
            f"Feature order mismatch: {train_raw['feature_names']}",
        )

    train_flat = flatten_sequences(train_raw["X"])
    val_flat = flatten_sequences(val_raw["X"])

    # Sample-for-sample correspondence: flat[i] == seq[i].ravel()
    if not np.array_equal(train_flat[0], train_raw["X"][0].reshape(-1)):
        raise ComparisonBlockedError(STATUS_FEATURE_MISMATCH, "train flat/seq mismatch sample 0")
    if not np.array_equal(val_flat[-1], val_raw["X"][-1].reshape(-1)):
        raise ComparisonBlockedError(STATUS_FEATURE_MISMATCH, "val flat/seq mismatch last sample")

    train_ids = set(train_raw["sequence_id"].tolist())
    val_ids = set(val_raw["sequence_id"].tolist())
    if train_ids & val_ids:
        raise ComparisonBlockedError(
            STATUS_PARTITION_MISMATCH,
            "objective2_same_information_comparison_blocked_partition_mismatch: train/val id overlap",
        )

    def _bundle(name: str, path: Path, raw: dict[str, Any], flat: np.ndarray, sha: str) -> PartitionBundle:
        y = raw["y"]
        n_pos = int(y.sum())
        return PartitionBundle(
            name=name,
            path=path,
            X_seq=raw["X"],
            X_flat=flat,
            y=y,
            sequence_id=raw["sequence_id"],
            user=raw["user"],
            feature_names=SAFE_FEATURES,
            sha256=sha,
            seq_hash=sha256_array(raw["X"]),
            flat_hash=sha256_array(flat),
            id_hash=sha256_ids(raw["sequence_id"]),
            label_hash=sha256_array(y.astype(np.int32)),
            n_pos=n_pos,
            n_neg=int(len(y) - n_pos),
        )

    train = _bundle("train", train_path, train_raw, train_flat, train_sha)
    val = _bundle("validation", val_path, val_raw, val_flat, val_sha)

    mapping = flatten_mapping()
    return {
        "train": train,
        "validation": val,
        "flatten_mapping": mapping,
        "meta": {
            "scaling_in_tensors": "prebaked_train_only_in_tensor_files",
            "flat_dim": FLAT_DIM,
            "no_engineered_features_added": True,
            "test_used": False,
        },
    }


def parity_tables(bundle: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    train: PartitionBundle = bundle["train"]
    val: PartitionBundle = bundle["validation"]
    mapping = pd.DataFrame(bundle["flatten_mapping"])

    partition = pd.DataFrame(
        [
            {
                "partition": train.name,
                "n_samples": len(train.y),
                "n_pos": train.n_pos,
                "n_neg": train.n_neg,
                "shape_seq": str(train.X_seq.shape),
                "shape_flat": str(train.X_flat.shape),
                "file_sha256": train.sha256,
                "sequence_tensor_sha256": train.seq_hash,
                "flat_matrix_sha256": train.flat_hash,
                "sample_id_sha256": train.id_hash,
                "label_sha256": train.label_hash,
                "n_unique_sequence_ids": int(len(set(train.sequence_id.tolist()))),
                "n_unique_users": int(len(set(train.user.tolist()))),
            },
            {
                "partition": val.name,
                "n_samples": len(val.y),
                "n_pos": val.n_pos,
                "n_neg": val.n_neg,
                "shape_seq": str(val.X_seq.shape),
                "shape_flat": str(val.X_flat.shape),
                "file_sha256": val.sha256,
                "sequence_tensor_sha256": val.seq_hash,
                "flat_matrix_sha256": val.flat_hash,
                "sample_id_sha256": val.id_hash,
                "label_sha256": val.label_hash,
                "n_unique_sequence_ids": int(len(set(val.sequence_id.tolist()))),
                "n_unique_users": int(len(set(val.user.tolist()))),
            },
        ]
    )

    label = pd.DataFrame(
        [
            {
                "check": "train_pos",
                "observed": train.n_pos,
                "expected": EXPECTED_TRAIN_POS,
                "ok": train.n_pos == EXPECTED_TRAIN_POS,
            },
            {
                "check": "val_pos",
                "observed": val.n_pos,
                "expected": EXPECTED_VAL_POS,
                "ok": val.n_pos == EXPECTED_VAL_POS,
            },
            {
                "check": "train_label_hash_nonempty",
                "observed": train.label_hash[:16],
                "expected": "nonempty",
                "ok": bool(train.label_hash),
            },
            {
                "check": "val_label_hash_nonempty",
                "observed": val.label_hash[:16],
                "expected": "nonempty",
                "ok": bool(val.label_hash),
            },
            {
                "check": "train_val_id_disjoint",
                "observed": len(set(train.sequence_id.tolist()) & set(val.sequence_id.tolist())),
                "expected": 0,
                "ok": len(set(train.sequence_id.tolist()) & set(val.sequence_id.tolist())) == 0,
            },
        ]
    )

    feature_audit = mapping.copy()
    feature_audit["n_flat_columns"] = FLAT_DIM
    feature_audit["engineered_feature_created"] = False
    feature_audit["order_deterministic"] = True
    feature_audit["source_values"] = "identical_to_sequence_tensor_C_order_ravel"

    return partition, label, feature_audit, mapping
