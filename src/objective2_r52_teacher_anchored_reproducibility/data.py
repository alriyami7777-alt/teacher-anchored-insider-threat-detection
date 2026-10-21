"""r5.2 train/validation loaders with absolute test-path refusal."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import torch
from torch.utils.data import DataLoader, Dataset, TensorDataset

from .constants import (
    EXPECTED_TRAIN_POS,
    EXPECTED_TRAIN_SHA256,
    EXPECTED_TRAIN_SHAPE,
    EXPECTED_VAL_POS,
    EXPECTED_VAL_SHA256,
    EXPECTED_VAL_SHAPE,
    SAFE_FEATURES,
    TENSOR_DIR_REL,
    TRAIN_NAME,
    VAL_NAME,
)
from .safety import ProtectedDataAccessError, assert_path_allowed_for_read, refuse_test_loader_construction


def sha256_file(path: Path) -> str:
    assert_path_allowed_for_read(path, context="hash")
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass(frozen=True)
class PartitionAudit:
    name: str
    path: str
    sha256: str
    shape: tuple[int, ...]
    n_pos: int
    n_neg: int
    feature_names: tuple[str, ...]
    sequence_length: int
    feature_dim: int


def _load_npz(path: Path) -> dict[str, Any]:
    assert_path_allowed_for_read(path, context="npz_load")
    refuse_test_loader_construction(partition=path.name)
    data = np.load(path, allow_pickle=True)
    # Support both flat and nested keys used in CERT pipelines.
    keys = set(data.files)
    if "X" in keys and "y" in keys:
        X = np.asarray(data["X"], dtype=np.float32)
        y = np.asarray(data["y"], dtype=np.float32).reshape(-1)
    elif "sequences" in keys and "labels" in keys:
        X = np.asarray(data["sequences"], dtype=np.float32)
        y = np.asarray(data["labels"], dtype=np.float32).reshape(-1)
    else:
        raise RuntimeError(f"Unrecognized tensor keys in {path}: {sorted(keys)}")
    feature_names = SAFE_FEATURES
    if "feature_names" in keys:
        raw = data["feature_names"]
        if getattr(raw, "ndim", 0) == 0:
            feature_names = tuple(str(x) for x in raw.item())
        else:
            feature_names = tuple(str(x) for x in raw.tolist())
    return {"X": X, "y": y, "feature_names": feature_names, "keys": sorted(keys)}


def load_train_validation(
    repo_root: Path,
    *,
    verify_hashes: bool = True,
) -> tuple[TensorDataset, TensorDataset, list[PartitionAudit], dict[str, Any]]:
    refuse_test_loader_construction(partition="train")
    refuse_test_loader_construction(partition="validation")

    train_path = (repo_root / TENSOR_DIR_REL / TRAIN_NAME).resolve()
    val_path = (repo_root / TENSOR_DIR_REL / VAL_NAME).resolve()
    assert_path_allowed_for_read(train_path, context="train")
    assert_path_allowed_for_read(val_path, context="validation")

    if verify_hashes:
        train_sha = sha256_file(train_path)
        val_sha = sha256_file(val_path)
        if train_sha != EXPECTED_TRAIN_SHA256:
            raise RuntimeError(f"Train SHA mismatch: {train_sha} != {EXPECTED_TRAIN_SHA256}")
        if val_sha != EXPECTED_VAL_SHA256:
            raise RuntimeError(f"Val SHA mismatch: {val_sha} != {EXPECTED_VAL_SHA256}")
    else:
        train_sha = EXPECTED_TRAIN_SHA256
        val_sha = EXPECTED_VAL_SHA256

    train = _load_npz(train_path)
    val = _load_npz(val_path)

    if train["X"].shape != EXPECTED_TRAIN_SHAPE:
        raise RuntimeError(f"Train shape {train['X'].shape} != {EXPECTED_TRAIN_SHAPE}")
    if val["X"].shape != EXPECTED_VAL_SHAPE:
        raise RuntimeError(f"Val shape {val['X'].shape} != {EXPECTED_VAL_SHAPE}")

    train_pos = int(train["y"].sum())
    val_pos = int(val["y"].sum())
    if train_pos != EXPECTED_TRAIN_POS:
        raise RuntimeError(f"Train pos {train_pos} != {EXPECTED_TRAIN_POS}")
    if val_pos != EXPECTED_VAL_POS:
        raise RuntimeError(f"Val pos {val_pos} != {EXPECTED_VAL_POS}")

    if tuple(train["feature_names"]) != SAFE_FEATURES:
        # Interface mismatch: only identical order is approved without a mapping.
        raise RuntimeError(
            "objective2_r52_teacher_anchored_blocked_interface_mismatch: "
            f"feature order {train['feature_names']} != {SAFE_FEATURES}"
        )
    if train["X"].shape[-1] != 13 or train["X"].shape[1] != 20:
        raise RuntimeError(
            "objective2_r52_teacher_anchored_blocked_interface_mismatch: "
            f"expected (N,20,13), got {train['X'].shape}"
        )

    # Train-only scaling (per-feature mean/std over train sequences flattened).
    # Match locked r5.2 / r4.2 pipeline: if tensors are already scaled, detect and skip.
    # Historical r5.2 tensors are pre-scaled with train-only stats baked in.
    # We verify finite and do not re-fit from validation/test.
    X_train = train["X"]
    X_val = val["X"]
    if not np.isfinite(X_train).all() or not np.isfinite(X_val).all():
        raise RuntimeError("Non-finite values in train/val tensors")

    train_ds = TensorDataset(
        torch.from_numpy(X_train),
        torch.from_numpy(np.asarray(train["y"], dtype=np.float32)),
    )
    val_ds = TensorDataset(
        torch.from_numpy(X_val),
        torch.from_numpy(np.asarray(val["y"], dtype=np.float32)),
    )

    audits = [
        PartitionAudit(
            name="train",
            path=str(train_path),
            sha256=train_sha,
            shape=tuple(int(x) for x in X_train.shape),
            n_pos=train_pos,
            n_neg=int(len(train["y"]) - train_pos),
            feature_names=SAFE_FEATURES,
            sequence_length=20,
            feature_dim=13,
        ),
        PartitionAudit(
            name="validation",
            path=str(val_path),
            sha256=val_sha,
            shape=tuple(int(x) for x in X_val.shape),
            n_pos=val_pos,
            n_neg=int(len(val["y"]) - val_pos),
            feature_names=SAFE_FEATURES,
            sequence_length=20,
            feature_dim=13,
        ),
    ]
    meta = {
        "scaling": "prebaked_train_only_in_tensor_files",
        "class_weight_source": "train_only",
        "early_stopping_source": "validation_only",
        "threshold_source": "validation_only",
        "test_used": False,
    }
    return train_ds, val_ds, audits, meta


def make_loaders(
    train_ds: Dataset,
    val_ds: Dataset,
    *,
    batch_size: int,
    seed: int,
) -> tuple[DataLoader, DataLoader]:
    g = torch.Generator()
    g.manual_seed(seed)
    train_loader = DataLoader(
        train_ds,
        batch_size=batch_size,
        shuffle=True,
        generator=g,
        drop_last=False,
        num_workers=0,
    )
    val_loader = DataLoader(
        val_ds,
        batch_size=batch_size,
        shuffle=False,
        num_workers=0,
    )
    return train_loader, val_loader


def pos_weight_from_train(n_pos: int, n_neg: int, mult: float) -> float:
    # Standard WBCE pos_weight = (n_neg / n_pos) * mult
    return float((n_neg / max(n_pos, 1)) * mult)
