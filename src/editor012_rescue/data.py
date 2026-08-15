"""r5.2 TRAIN/VALIDATION loaders. TEST construction is refused."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import torch
from torch.utils.data import DataLoader, TensorDataset

from .constants import (
    BATCH_SIZE,
    EXPECTED_TRAIN_POS,
    EXPECTED_TRAIN_SHA256,
    EXPECTED_TRAIN_SHAPE,
    EXPECTED_VAL_POS,
    EXPECTED_VAL_SHA256,
    EXPECTED_VAL_SHAPE,
    POS_WEIGHT_MULT,
    SAFE_FEATURES,
)
from .safety import (
    TRAIN_NPZ,
    VAL_NPZ,
    Editor012ProtocolError,
    assert_split_allowed,
    note_open,
    require_hash,
)


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


def _load_split(
    path: Path, expected_sha: str, expected_shape: tuple[int, ...], expected_pos: int, role: str
) -> SequenceBundle:
    note_open(path, role=role)
    require_hash(path, expected_sha, role=role)
    data = np.load(path, allow_pickle=True)
    keys = set(data.files)
    if "X" not in keys or "y" not in keys:
        raise Editor012ProtocolError(f"unrecognized tensor keys {sorted(keys)} in {path}")
    X = np.asarray(data["X"], dtype=np.float32)
    y = np.asarray(data["y"], dtype=np.float32).reshape(-1)
    if tuple(X.shape) != expected_shape:
        raise Editor012ProtocolError(f"{role} shape {X.shape} != {expected_shape}")
    n_pos = int(y.sum())
    if n_pos != expected_pos:
        raise Editor012ProtocolError(f"{role} pos {n_pos} != {expected_pos}")
    if "feature_names" in keys:
        raw = data["feature_names"]
        names = tuple(str(x) for x in (raw.tolist() if getattr(raw, "ndim", 1) else raw.item()))
        if names != SAFE_FEATURES:
            raise Editor012ProtocolError(f"{role} feature names {names} != {SAFE_FEATURES}")
    user = np.asarray(data["user"]).astype(str) if "user" in keys else np.array(["NA"] * len(y))
    sequence_id = (
        np.asarray(data["sequence_id"]).astype(str)
        if "sequence_id" in keys
        else np.array([str(i) for i in range(len(y))])
    )
    start_date = np.asarray(data["start_date"]).astype(str) if "start_date" in keys else np.array([""] * len(y))
    end_date = np.asarray(data["end_date"]).astype(str) if "end_date" in keys else np.array([""] * len(y))
    if not np.isfinite(X).all():
        raise Editor012ProtocolError(f"non-finite values in {role}")
    return SequenceBundle(
        X=X,
        y=y,
        user=user,
        sequence_id=sequence_id,
        start_date=start_date,
        end_date=end_date,
        path=path,
        sha256=expected_sha,
        name=role,
    )


def load_train_validation() -> dict[str, Any]:
    assert_split_allowed("train")
    assert_split_allowed("validation")
    train = _load_split(TRAIN_NPZ, EXPECTED_TRAIN_SHA256, EXPECTED_TRAIN_SHAPE, EXPECTED_TRAIN_POS, "train")
    val = _load_split(VAL_NPZ, EXPECTED_VAL_SHA256, EXPECTED_VAL_SHAPE, EXPECTED_VAL_POS, "validation")
    n_neg = int(len(train.y) - EXPECTED_TRAIN_POS)
    pos_weight = float((n_neg / max(EXPECTED_TRAIN_POS, 1)) * POS_WEIGHT_MULT)
    return {
        "train": train,
        "val": val,
        "n_train": int(len(train.y)),
        "n_val": int(len(val.y)),
        "n_train_pos": EXPECTED_TRAIN_POS,
        "n_train_neg": n_neg,
        "n_val_pos": EXPECTED_VAL_POS,
        "pos_weight": pos_weight,
        "train_sha256": EXPECTED_TRAIN_SHA256,
        "val_sha256": EXPECTED_VAL_SHA256,
        "test_used": False,
    }


def subset_bundle(bundle: SequenceBundle, mask: np.ndarray, name: str) -> SequenceBundle:
    assert_split_allowed(name)
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
    seed: int,
    batch_size: int = BATCH_SIZE,
    shuffle: bool = False,
    extras: list[np.ndarray] | None = None,
) -> DataLoader:
    tensors = [
        torch.from_numpy(np.asarray(X, dtype=np.float32)),
        torch.from_numpy(np.asarray(y, dtype=np.float32).reshape(-1)),
    ]
    if extras:
        for arr in extras:
            tensors.append(torch.from_numpy(np.asarray(arr, dtype=np.float32)))
    ds = TensorDataset(*tensors)
    g = torch.Generator()
    g.manual_seed(int(seed))
    return DataLoader(
        ds,
        batch_size=batch_size,
        shuffle=shuffle,
        generator=g if shuffle else None,
        drop_last=False,
        num_workers=0,
    )
