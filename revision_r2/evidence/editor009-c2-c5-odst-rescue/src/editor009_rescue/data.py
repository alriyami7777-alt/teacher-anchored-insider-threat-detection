"""r5.2 TRAIN/VALIDATION loaders. TEST construction is refused."""

from __future__ import annotations

from typing import Any

import numpy as np
import torch
from torch.utils.data import DataLoader, TensorDataset

from .safety import (
    EXPECTED_TRAIN_SHA256,
    EXPECTED_VAL_SHA256,
    TRAIN_NPZ,
    VAL_NPZ,
    Editor009ProtocolError,
    assert_split_allowed,
    note_open,
    require_hash,
    sha256_file,
)

EXPECTED_TRAIN_SHAPE = (788000, 20, 13)
EXPECTED_VAL_SHAPE = (64000, 20, 13)
EXPECTED_TRAIN_POS = 3957
EXPECTED_VAL_POS = 728
POS_WEIGHT_MULT = 0.25
BATCH_SIZE = 1024


def _load_split(path, expected_sha: str, expected_shape: tuple[int, ...], expected_pos: int, role: str) -> dict[str, Any]:
    note_open(path, role=role)
    require_hash(path, expected_sha, role=role)
    data = np.load(path, allow_pickle=True)
    keys = set(data.files)
    if "X" in keys and "y" in keys:
        X = np.asarray(data["X"], dtype=np.float32)
        y = np.asarray(data["y"], dtype=np.float32).reshape(-1)
    elif "sequences" in keys and "labels" in keys:
        X = np.asarray(data["sequences"], dtype=np.float32)
        y = np.asarray(data["labels"], dtype=np.float32).reshape(-1)
    else:
        raise Editor009ProtocolError(f"unrecognized tensor keys {sorted(keys)} in {path}")
    if tuple(X.shape) != expected_shape:
        raise Editor009ProtocolError(f"{role} shape {X.shape} != {expected_shape}")
    n_pos = int(y.sum())
    if n_pos != expected_pos:
        raise Editor009ProtocolError(f"{role} pos {n_pos} != {expected_pos}")
    extras: dict[str, Any] = {"npz_keys": sorted(keys)}
    for cand in ("user_id", "user_ids", "sequence_id", "sequence_ids", "uid"):
        if cand in keys:
            extras[cand] = np.asarray(data[cand])
    return {"X": X, "y": y, **extras}


def load_train_validation() -> dict[str, Any]:
    assert_split_allowed("train")
    assert_split_allowed("validation")
    train = _load_split(TRAIN_NPZ, EXPECTED_TRAIN_SHA256, EXPECTED_TRAIN_SHAPE, EXPECTED_TRAIN_POS, "train")
    val = _load_split(VAL_NPZ, EXPECTED_VAL_SHA256, EXPECTED_VAL_SHAPE, EXPECTED_VAL_POS, "validation")
    if not np.isfinite(train["X"]).all() or not np.isfinite(val["X"]).all():
        raise Editor009ProtocolError("non-finite values in train/val tensors")
    n_neg = int(len(train["y"]) - EXPECTED_TRAIN_POS)
    pos_weight = float((n_neg / max(EXPECTED_TRAIN_POS, 1)) * POS_WEIGHT_MULT)
    return {
        "train": train,
        "val": val,
        "n_train": int(len(train["y"])),
        "n_val": int(len(val["y"])),
        "n_train_pos": EXPECTED_TRAIN_POS,
        "n_train_neg": n_neg,
        "n_val_pos": EXPECTED_VAL_POS,
        "pos_weight": pos_weight,
        "prevalence_train": EXPECTED_TRAIN_POS / float(len(train["y"])),
        "train_sha256": EXPECTED_TRAIN_SHA256,
        "val_sha256": EXPECTED_VAL_SHA256,
        "test_used": False,
    }


def make_loaders(
    bundle: dict[str, Any], *, seed: int, batch_size: int = BATCH_SIZE
) -> tuple[DataLoader, DataLoader]:
    train_ds = TensorDataset(
        torch.from_numpy(bundle["train"]["X"]),
        torch.from_numpy(np.asarray(bundle["train"]["y"], dtype=np.float32)),
    )
    val_ds = TensorDataset(
        torch.from_numpy(bundle["val"]["X"]),
        torch.from_numpy(np.asarray(bundle["val"]["y"], dtype=np.float32)),
    )
    g = torch.Generator()
    g.manual_seed(int(seed))
    train_loader = DataLoader(
        train_ds, batch_size=batch_size, shuffle=True, generator=g, drop_last=False, num_workers=0
    )
    val_loader = DataLoader(val_ds, batch_size=batch_size, shuffle=False, num_workers=0)
    return train_loader, val_loader
