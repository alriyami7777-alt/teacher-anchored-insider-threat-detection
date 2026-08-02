"""Train/validation-only data loading for Prototype V2 (r4.2)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import torch
from torch.utils.data import DataLoader, Dataset, Subset

from .safety import R42TestAccessError, assert_no_r42_test_access, path_looks_like_r42_test

SAFE_FEATURES = [
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

EXPECTED_SHAPES = {
    "train": (381_000, 20, 13),
    "validation": (31_000, 20, 13),
}
EXPECTED_POS = {"train": 2_775, "validation": 252}

ALLOWED_SPLITS = ("train", "validation")


class NpzSequenceDataset(Dataset):
    """NPZ loader with optional memory-map; refuses r4.2 test paths."""

    def __init__(self, npz_path: Path, mmap: bool = True, materialize: bool = False) -> None:
        if path_looks_like_r42_test(npz_path):
            raise R42TestAccessError(
                f"REFUSED: V2 must not load r4.2 test tensor: {npz_path}"
            )
        self.path = Path(npz_path)
        z = np.load(self.path, allow_pickle=True, mmap_mode="r" if mmap else None)
        x = z["X"]
        y = z["y"]
        if materialize:
            self.X = np.array(x, dtype=np.float32, copy=True)
            self.y = np.array(y, copy=True)
            self._z = None
        else:
            self.X = x
            self.y = y
            self._z = z
        self.sequence_id = z["sequence_id"] if "sequence_id" in z.files else None
        self.user = z["user"] if "user" in z.files else None
        self.start_date = z["start_date"] if "start_date" in z.files else None
        self.end_date = z["end_date"] if "end_date" in z.files else None

    def __len__(self) -> int:
        return int(self.X.shape[0])

    def __getitem__(self, idx: int):
        x = np.asarray(self.X[idx], dtype=np.float32)
        y = np.float32(self.y[idx])
        return torch.from_numpy(x.copy() if not x.flags.writeable else x), torch.tensor(
            y, dtype=torch.float32
        )


def load_train_validation_datasets(
    tensor_dir: Path,
    *,
    materialize_train: bool = True,
) -> dict[str, NpzSequenceDataset]:
    """Load only r4.2 train and validation tensors."""
    train_path = tensor_dir / "r42_T20_s1_train.npz"
    val_path = tensor_dir / "r42_T20_s1_validation.npz"
    assert_no_r42_test_access([train_path, val_path])
    # Explicitly refuse if a caller swapped in the test file under an alias.
    for p in (train_path, val_path):
        if not p.exists():
            raise FileNotFoundError(p)
    return {
        "train": NpzSequenceDataset(train_path, mmap=True, materialize=materialize_train),
        "validation": NpzSequenceDataset(val_path, mmap=True, materialize=False),
    }


def validate_train_val_tensors(
    datasets: dict[str, NpzSequenceDataset],
    feature_list: list[str],
) -> list[str]:
    messages: list[str] = []
    if set(datasets.keys()) - set(ALLOWED_SPLITS):
        raise R42TestAccessError(
            f"REFUSED: unexpected splits {sorted(datasets)}; only {ALLOWED_SPLITS} allowed"
        )
    if "test" in datasets:
        raise R42TestAccessError("REFUSED: test split present in V2 datasets dict")
    if feature_list != SAFE_FEATURES:
        raise SystemExit(f"Feature list mismatch: {feature_list}")
    messages.append(f"PASS: exact 13 safe features confirmed: {SAFE_FEATURES}")

    for split, ds in datasets.items():
        exp = EXPECTED_SHAPES[split]
        if tuple(ds.X.shape) != exp:
            raise SystemExit(f"{split} shape {ds.X.shape} != {exp}")
        if ds.X.dtype != np.float32:
            raise SystemExit(f"{split} X dtype {ds.X.dtype} != float32")
        y = np.asarray(ds.y)
        pos = int(y.sum())
        if pos != EXPECTED_POS[split]:
            raise SystemExit(f"{split} pos {pos} != {EXPECTED_POS[split]}")
        x_arr = np.asarray(ds.X)
        if not np.isfinite(x_arr).all():
            raise SystemExit(f"{split} has non-finite X values")
        messages.append(
            f"PASS: {split} shape={ds.X.shape}, dtype={ds.X.dtype}, "
            f"pos={pos}, neg={len(y) - pos}, finite=True"
        )
    messages.append("PASS: r4.2 test tensor not loaded (V2 development default)")
    return messages


def load_feature_list_and_scaler(root: Path) -> tuple[list[str], dict[str, Any]]:
    feature_list_path = root / "outputs" / "tensors" / "r42_T20_s1_tensor_feature_list.csv"
    scaler_path = root / "outputs" / "tensors" / "r42_T20_s1_train_scaler_stats.json"
    feats_df = pd.read_csv(feature_list_path)
    feature_list = feats_df["feature_name"].tolist()
    scaler = json.loads(scaler_path.read_text(encoding="utf-8"))
    if not scaler.get("fitted_on_train_only", False):
        raise SystemExit("Scaler not marked as train-only.")
    return feature_list, scaler


def stratified_smoke_indices(
    y: np.ndarray, n: int, rng: np.random.Generator
) -> np.ndarray:
    y = np.asarray(y).astype(int)
    pos = np.where(y == 1)[0]
    neg = np.where(y == 0)[0]
    n = min(n, len(y))
    n_pos = min(len(pos), max(1, int(round(n * (len(pos) / max(len(y), 1))))))
    n_neg = min(len(neg), n - n_pos)
    if n_pos + n_neg < n and len(neg) > n_neg:
        n_neg = min(len(neg), n - n_pos)
    choose_pos = rng.choice(pos, size=n_pos, replace=False) if n_pos else np.array([], dtype=int)
    choose_neg = rng.choice(neg, size=n_neg, replace=False) if n_neg else np.array([], dtype=int)
    idx = np.concatenate([choose_pos, choose_neg])
    rng.shuffle(idx)
    return idx


def make_loader(
    dataset: Dataset,
    batch_size: int,
    shuffle: bool,
    indices: np.ndarray | None = None,
) -> DataLoader:
    ds: Dataset = dataset if indices is None else Subset(dataset, indices.tolist())
    return DataLoader(
        ds,
        batch_size=batch_size,
        shuffle=shuffle,
        num_workers=0,
        pin_memory=torch.cuda.is_available(),
    )
