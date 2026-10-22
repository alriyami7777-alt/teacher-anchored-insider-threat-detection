"""Authorised r5.2 TRAIN/VALIDATION loaders. TEST construction is fail-closed."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import torch
from torch.utils.data import DataLoader, TensorDataset

from .constants import (
    EXPECTED_TRAIN_POS,
    EXPECTED_TRAIN_SHA256,
    EXPECTED_TRAIN_SHAPE,
    EXPECTED_VAL_POS,
    EXPECTED_VAL_SHA256,
    EXPECTED_VAL_SHAPE,
    SAFE_FEATURES,
    TENSOR_CANDIDATE_ROOTS,
    TRAIN_NAME,
    VAL_NAME,
)
from .hashes import sha256_file
from .safety import assert_path_allowed_for_read, refuse_test_loader_construction


@dataclass(frozen=True)
class SequenceBundle:
    X: np.ndarray
    y: np.ndarray
    user: np.ndarray
    sequence_id: np.ndarray
    start_date: np.ndarray
    end_date: np.ndarray
    path: Path
    sha256: str
    name: str


def resolve_tensor(name: str) -> Path:
    refuse_test_loader_construction(partition=name)
    for root in TENSOR_CANDIDATE_ROOTS:
        cand = root / name
        if cand.exists():
            return assert_path_allowed_for_read(cand, context=name)
    raise FileNotFoundError(f"Authorised tensor not found: {name}")


def _load_npz(path: Path, *, expected_sha: str, expected_shape: tuple[int, ...], expected_pos: int, name: str) -> SequenceBundle:
    refuse_test_loader_construction(partition=path.name)
    path = assert_path_allowed_for_read(path, context=name)
    digest = sha256_file(path)
    if digest != expected_sha:
        raise RuntimeError(f"{name} SHA mismatch: {digest} != {expected_sha}")
    payload = np.load(path, allow_pickle=True)
    keys = set(payload.files)
    if "X" not in keys or "y" not in keys:
        raise RuntimeError(f"Unrecognized tensor keys in {path}: {sorted(keys)}")
    X = np.asarray(payload["X"], dtype=np.float32)
    y = np.asarray(payload["y"]).reshape(-1)
    if tuple(X.shape) != expected_shape:
        raise RuntimeError(f"{name} shape {X.shape} != {expected_shape}")
    if int(y.sum()) != expected_pos:
        raise RuntimeError(f"{name} positives {int(y.sum())} != {expected_pos}")
    if "feature_names" in keys:
        raw = payload["feature_names"]
        names = tuple(str(x) for x in (raw.tolist() if getattr(raw, "ndim", 1) else raw.item()))
        if names != SAFE_FEATURES:
            raise RuntimeError(f"{name} feature names {names} != {SAFE_FEATURES}")
    user = np.asarray(payload["user"]).astype(str) if "user" in keys else np.array(["NA"] * len(y))
    sequence_id = np.asarray(payload["sequence_id"]).astype(str) if "sequence_id" in keys else np.array([str(i) for i in range(len(y))])
    start_date = np.asarray(payload["start_date"]).astype(str) if "start_date" in keys else np.array([""] * len(y))
    end_date = np.asarray(payload["end_date"]).astype(str) if "end_date" in keys else np.array([""] * len(y))
    if not np.isfinite(X).all():
        raise RuntimeError(f"Non-finite values in {name}")
    return SequenceBundle(
        X=X,
        y=y.astype(np.float32),
        user=user,
        sequence_id=sequence_id,
        start_date=start_date,
        end_date=end_date,
        path=path,
        sha256=digest,
        name=name,
    )


def load_train() -> SequenceBundle:
    refuse_test_loader_construction(partition="train")
    return _load_npz(
        resolve_tensor(TRAIN_NAME),
        expected_sha=EXPECTED_TRAIN_SHA256,
        expected_shape=EXPECTED_TRAIN_SHAPE,
        expected_pos=EXPECTED_TRAIN_POS,
        name="train",
    )


def load_validation() -> SequenceBundle:
    refuse_test_loader_construction(partition="validation")
    return _load_npz(
        resolve_tensor(VAL_NAME),
        expected_sha=EXPECTED_VAL_SHA256,
        expected_shape=EXPECTED_VAL_SHAPE,
        expected_pos=EXPECTED_VAL_POS,
        name="validation",
    )


def subset_bundle(bundle: SequenceBundle, mask: np.ndarray, name: str) -> SequenceBundle:
    refuse_test_loader_construction(partition=name)
    mask = np.asarray(mask, dtype=bool)
    return SequenceBundle(
        X=bundle.X[mask],
        y=bundle.y[mask],
        user=bundle.user[mask],
        sequence_id=bundle.sequence_id[mask],
        start_date=bundle.start_date[mask],
        end_date=bundle.end_date[mask],
        path=bundle.path,
        sha256=bundle.sha256,
        name=name,
    )


def make_xy_loader(
    X: np.ndarray,
    y: np.ndarray,
    *,
    batch_size: int,
    seed: int,
    shuffle: bool,
) -> DataLoader:
    ds = TensorDataset(
        torch.from_numpy(np.asarray(X, dtype=np.float32)),
        torch.from_numpy(np.asarray(y, dtype=np.float32).reshape(-1)),
    )
    generator = torch.Generator()
    generator.manual_seed(int(seed))
    return DataLoader(
        ds,
        batch_size=batch_size,
        shuffle=shuffle,
        generator=generator if shuffle else None,
        drop_last=False,
        num_workers=0,
    )


def pos_weight(n_pos: int, n_neg: int, mult: float) -> float:
    return float((n_neg / max(n_pos, 1)) * mult)
