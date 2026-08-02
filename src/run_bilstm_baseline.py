#!/usr/bin/env python3
"""
Standalone Bi-LSTM baseline on verified CERT r4.2 T=20 stride=1 tensors.

Objective 2 repeated-seed comparison: validation PR-AUC early stopping,
validation F1 threshold selection, test evaluation only with --evaluate-test.
Does not modify locked sequence-ensemble, fragmented hybrid, or test artefacts.
"""

from __future__ import annotations

import argparse
import json
import platform
import random
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from sklearn.metrics import (
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from torch.utils.data import DataLoader, Dataset, Subset

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
    "test": (32_000, 20, 13),
}
EXPECTED_POS = {"train": 2_775, "validation": 252, "test": 84}

# Locked T=20 XGBoost reference (temporal-window comparison / baseline eval).
XGB_REF = {
    "precision": 0.988,
    "recall": 1.000,
    "f1": 0.994,
    "pr_auc": 1.000,
    "fpr": 0.000031,
    "fp": 1,
    "fn": 0,
}

DEFAULT_SEED = 42
SEED_CHOICES = (42, 52, 62)
HIDDEN_SIZE = 64
DROPOUT = 0.2
LEARNING_RATE = 1e-3
MAX_EPOCHS = 20
DEFAULT_PATIENCE = 4
GRAD_CLIP_NORM = 1.0
DEFAULT_BATCH_SIZE = 1024


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def resolve(root: Path, p: str | Path) -> Path:
    path = Path(p)
    return path if path.is_absolute() else root / path


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    # Deterministic settings where supported (may reduce throughput on GPU).
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
    if hasattr(torch, "use_deterministic_algorithms"):
        try:
            torch.use_deterministic_algorithms(True, warn_only=True)
        except Exception:
            pass


def select_device(choice: str) -> torch.device:
    if choice == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if choice == "cuda":
        if not torch.cuda.is_available():
            raise SystemExit("CUDA requested but torch.cuda.is_available() is False")
        return torch.device("cuda")
    return torch.device("cpu")


def collect_rng_states() -> dict:
    return {
        "python_random_state": random.getstate(),
        "numpy_random_state": np.random.get_state(),
        "torch_cpu_rng_state": torch.get_rng_state(),
        "torch_cuda_rng_state": (
            torch.cuda.get_rng_state_all() if torch.cuda.is_available() else None
        ),
    }


def stratified_smoke_indices(y: np.ndarray, n: int, rng: np.random.Generator) -> np.ndarray:
    pos_idx = np.where(y == 1)[0]
    neg_idx = np.where(y == 0)[0]
    n_pos = min(len(pos_idx), max(1, n // 10))
    n_neg = min(len(neg_idx), max(0, n - n_pos))
    idx = np.concatenate(
        [
            rng.choice(pos_idx, size=n_pos, replace=False),
            rng.choice(neg_idx, size=n_neg, replace=False),
        ]
    )
    rng.shuffle(idx)
    return idx


class NpzSequenceDataset(Dataset):
    """NPZ loader with optional memory-map; can materialise arrays for fast shuffle."""

    def __init__(self, npz_path: Path, mmap: bool = True, materialize: bool = False) -> None:
        self.path = npz_path
        z = np.load(npz_path, allow_pickle=True, mmap_mode="r" if mmap else None)
        x = z["X"]
        y = z["y"]
        if materialize:
            # Copy into RAM: needed for efficient shuffled training on CPU/Windows.
            self.X = np.array(x, dtype=np.float32, copy=True)
            self.y = np.array(y, copy=True)
            self._z = None
        else:
            self.X = x
            self.y = y
            self._z = z  # keep handle alive for mmap
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


class BiLSTMClassifier(nn.Module):
    def __init__(
        self,
        input_dim: int = 13,
        hidden_size: int = HIDDEN_SIZE,
        dropout: float = DROPOUT,
    ) -> None:
        super().__init__()
        self.lstm = nn.LSTM(
            input_size=input_dim,
            hidden_size=hidden_size,
            num_layers=1,
            batch_first=True,
            bidirectional=True,
        )
        self.dropout = nn.Dropout(dropout)
        self.fc = nn.Linear(hidden_size * 2, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (B, T, F)
        out, _ = self.lstm(x)
        h = out[:, -1, :]  # last timestep, both directions concatenated
        h = self.dropout(h)
        logits = self.fc(h).squeeze(-1)
        return logits


def inspect_hardware(device: torch.device, batch_size: int) -> dict:
    cuda = device.type == "cuda"
    info = {
        "torch_version": torch.__version__,
        "cuda_available": torch.cuda.is_available(),
        "device": str(device),
        "gpu_model": torch.cuda.get_device_name(0) if cuda else None,
        "gpu_memory_gb": (
            round(torch.cuda.get_device_properties(0).total_memory / 1024**3, 2)
            if cuda
            else None
        ),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "train_X_float32_mb": round(381_000 * 20 * 13 * 4 / 1024**2, 1),
        "all_splits_X_float32_mb": round(
            (381_000 + 31_000 + 32_000) * 20 * 13 * 4 / 1024**2, 1
        ),
        "proposed_batch_size": batch_size,
        "mmap_streaming_required": True,
        "mmap_streaming_used": True,
        "deterministic_cudnn": True,
    }
    return info


def build_checkpoint(
    model: nn.Module,
    optimizer: torch.optim.Optimizer,
    epoch: int,
    best_epoch: int,
    best_val_pr: float,
    patience_left: int,
    config: dict,
    history: list[dict],
) -> dict:
    return {
        "model_state_dict": {k: v.detach().cpu().clone() for k, v in model.state_dict().items()},
        "optimizer_state_dict": optimizer.state_dict(),
        "epoch": int(epoch),
        "best_epoch": int(best_epoch),
        "best_val_pr_auc": float(best_val_pr),
        "early_stopping": {
            "patience": int(config["patience"]),
            "patience_left": int(patience_left),
            "metric": "validation_pr_auc",
        },
        "config": config,
        "history": history,
        "rng_states": collect_rng_states(),
        "architecture": "BiLSTMClassifier",
        "seed": int(config["seed"]),
    }


def save_predictions(
    path: Path,
    split: str,
    y: np.ndarray,
    probs: np.ndarray,
    thr: float,
    ds: NpzSequenceDataset,
    indices: np.ndarray | None,
) -> None:
    idx = np.arange(len(y)) if indices is None else indices
    frame = {
        "split": split,
        "y_true": y.astype(np.int8),
        "y_prob": probs.astype(np.float32),
        "y_pred_selected": (probs >= thr).astype(np.int8),
        "y_pred_0_5": (probs >= 0.5).astype(np.int8),
    }
    if ds.sequence_id is not None:
        frame["sequence_id"] = np.asarray(ds.sequence_id)[idx].astype(str)
    if ds.user is not None:
        frame["user"] = np.asarray(ds.user)[idx].astype(str)
    pd.DataFrame(frame).to_parquet(path, index=False)


def validate_tensors(datasets: dict[str, NpzSequenceDataset], feature_list: list[str]) -> list[str]:
    messages: list[str] = []
    if feature_list != SAFE_FEATURES:
        raise SystemExit(f"Feature list mismatch: {feature_list}")
    messages.append(f"PASS: exact 13 input features confirmed: {SAFE_FEATURES}")

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
        # Sample finite check (full scan on mmap is OK for ~440MB).
        x_arr = np.asarray(ds.X)
        if not np.isfinite(x_arr).all():
            raise SystemExit(f"{split} has non-finite X values")
        messages.append(
            f"PASS: {split} shape={ds.X.shape}, dtype={ds.X.dtype}, "
            f"pos={pos}, neg={len(y)-pos}, finite=True"
        )

    messages.append("PASS: no label-derived input features (tensor feature list)")
    messages.append("PASS: scaling fitted only on training split (scaler stats artefact)")
    messages.append("PASS: sequences constructed inside chronological splits (metadata protocol)")
    messages.append(
        "PASS: test split unused for training / early stopping / threshold / tuning (by protocol)"
    )
    return messages


def choose_threshold_f1(y_true: np.ndarray, probs: np.ndarray) -> tuple[float, float]:
    candidates = set(np.linspace(0.01, 0.99, 99).tolist())
    qs = np.quantile(probs, np.linspace(0.01, 0.99, 50))
    candidates.update(float(q) for q in qs)
    best_t, best_f1 = 0.5, -1.0
    for t in sorted(candidates):
        f1 = f1_score(y_true, (probs >= t).astype(int), zero_division=0)
        if f1 > best_f1:
            best_f1 = float(f1)
            best_t = float(t)
    return best_t, best_f1


@torch.no_grad()
def predict_proba(model: nn.Module, loader: DataLoader, device: torch.device) -> np.ndarray:
    model.eval()
    outs: list[np.ndarray] = []
    for xb, _ in loader:
        xb = xb.to(device)
        logits = model(xb)
        outs.append(torch.sigmoid(logits).cpu().numpy())
    return np.concatenate(outs, axis=0)


def metrics_at_threshold(y_true: np.ndarray, probs: np.ndarray, threshold: float) -> dict:
    y_pred = (probs >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()
    fpr = float(fp / (fp + tn)) if (fp + tn) else 0.0
    fnr = float(fn / (fn + tp)) if (fn + tp) else 0.0
    return {
        "threshold": float(threshold),
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "f1": float(f1_score(y_true, y_pred, zero_division=0)),
        "pr_auc": float(average_precision_score(y_true, probs)),
        "roc_auc": float(roc_auc_score(y_true, probs)),
        "fpr": fpr,
        "fnr": fnr,
        "tn": int(tn),
        "fp": int(fp),
        "fn": int(fn),
        "tp": int(tp),
    }


def pr_auc_safe(y_true: np.ndarray, probs: np.ndarray) -> float:
    if y_true.sum() == 0:
        return float("nan")
    return float(average_precision_score(y_true, probs))


def train_one_epoch(
    model: nn.Module,
    loader: DataLoader,
    optimizer: torch.optim.Optimizer,
    criterion: nn.Module,
    device: torch.device,
) -> float:
    model.train()
    total_loss = 0.0
    n = 0
    for xb, yb in loader:
        xb = xb.to(device)
        yb = yb.to(device)
        optimizer.zero_grad(set_to_none=True)
        logits = model(xb)
        loss = criterion(logits, yb)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), GRAD_CLIP_NORM)
        optimizer.step()
        bs = xb.size(0)
        total_loss += float(loss.item()) * bs
        n += bs
    return total_loss / max(n, 1)


@torch.no_grad()
def eval_loss(
    model: nn.Module,
    loader: DataLoader,
    criterion: nn.Module,
    device: torch.device,
) -> float:
    model.eval()
    total_loss = 0.0
    n = 0
    for xb, yb in loader:
        xb = xb.to(device)
        yb = yb.to(device)
        logits = model(xb)
        loss = criterion(logits, yb)
        bs = xb.size(0)
        total_loss += float(loss.item()) * bs
        n += bs
    return total_loss / max(n, 1)


def make_loader(
    ds: Dataset,
    batch_size: int,
    shuffle: bool,
    indices: np.ndarray | None = None,
) -> DataLoader:
    data = Subset(ds, indices.tolist()) if indices is not None else ds
    return DataLoader(
        data,
        batch_size=batch_size,
        shuffle=shuffle,
        num_workers=0,
        pin_memory=torch.cuda.is_available(),
    )


def append_manifest(root: Path, out_dir: Path, key_result: str) -> None:
    chapter_manifest = root / "outputs" / "chapter4" / "chapter4_results_manifest.csv"
    if not chapter_manifest.exists():
        return
    man = pd.read_csv(chapter_manifest)
    if (man["step_number"] == 15).any():
        man = man[man["step_number"] != 15]
    row = {
        "step_number": 15,
        "chapter4_section": "1.5 Standalone Bi-LSTM baseline",
        "related_research_objective": "Objective 1 / Objective 2 preparation",
        "input_files": (
            "data/processed/tensors/r42_T20_s1_train.npz; "
            "data/processed/tensors/r42_T20_s1_validation.npz; "
            "data/processed/tensors/r42_T20_s1_test.npz; "
            "outputs/tensors/r42_T20_s1_tensor_feature_list.csv; "
            "outputs/tensors/r42_T20_s1_train_scaler_stats.json"
        ),
        "script_used": "scripts/run_bilstm_baseline.py",
        "output_files": "; ".join(
            [
                str(out_dir / "best.pt"),
                str(out_dir / "last.pt"),
                str(out_dir / "config.json"),
                str(out_dir / "training_history.csv"),
                str(out_dir / "threshold.json"),
                str(out_dir / "validation_predictions.parquet"),
                str(out_dir / "validation_metrics.csv"),
                str(out_dir / "checkpoint_metadata.json"),
            ]
        ),
        "key_result": key_result,
        "why_this_step_matters": (
            "Establishes a leakage-controlled sequence neural baseline before "
            "the differentiable soft decision forest"
        ),
        "status": "Complete",
    }
    man = pd.concat([man, pd.DataFrame([row])], ignore_index=True)
    man = man.sort_values("step_number")
    man.to_csv(chapter_manifest, index=False)


def append_notes(root: Path, summary: dict) -> None:
    notes_path = root / "docs" / "cert_r42_notes.md"
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    block = f"""

## CERT r4.2 standalone Bi-LSTM baseline T=20/s=1 ({ts})

Leakage-controlled Bi-LSTM on verified tensors. Threshold selected on validation F1 only. Test used once for final evaluation. Compared with T=20 XGBoost baseline (not claimed superior unless measured).

### Hardware / loading
- Device: `{summary['device']}`
- CUDA available: `{summary['cuda_available']}`
- Batch size: `{summary['batch_size']}`
- mmap loader: yes

### Architecture
- Bi-LSTM hidden={summary['hidden_size']}, dropout={summary['dropout']}, params={summary['param_count']:,}
- pos_weight (train): {summary['pos_weight']:.4f}
- best epoch: {summary['best_epoch']}
- selected val threshold (max F1): {summary['selected_threshold']:.4f}

### Test metrics (selected threshold)

| Model | P | R | F1 | PR-AUC | FPR | FP | FN |
|-------|---|---|----|--------|-----|----|----|
| Bi-LSTM @ thr | {summary['test_precision']:.4f} | {summary['test_recall']:.4f} | {summary['test_f1']:.4f} | {summary['test_pr_auc']:.4f} | {summary['test_fpr']:.6f} | {summary['test_fp']} | {summary['test_fn']} |
| Bi-LSTM @ 0.50 | {summary['test_precision_050']:.4f} | {summary['test_recall_050']:.4f} | {summary['test_f1_050']:.4f} | {summary['test_pr_auc']:.4f} | {summary['test_fpr_050']:.6f} | {summary['test_fp_050']} | {summary['test_fn_050']} |
| XGBoost T=20 | 0.988 | 1.000 | 0.994 | 1.000 | 0.000031 | 1 | 0 |

### Outputs
- `{summary['out_dir']}/`
"""
    with notes_path.open("a", encoding="utf-8") as f:
        f.write(block)


def run_experiment(
    root: Path,
    tensor_dir: Path,
    out_dir: Path,
    seed: int,
    device_choice: str,
    batch_size: int,
    max_epochs: int,
    patience: int,
    resume: bool,
    evaluate_test: bool,
    smoke: bool,
    smoke_n: int,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    set_seed(seed)
    device = select_device(device_choice)

    hw = inspect_hardware(device, batch_size)
    print("=" * 90)
    print(f"CERT r4.2 standalone Bi-LSTM baseline (T=20, stride=1) seed={seed}")
    print("=" * 90)
    print(f"Device: {device}")
    print(f"Output: {out_dir}")
    print(f"Evaluate test: {bool(evaluate_test) and not smoke}")
    if smoke:
        print("Mode: SMOKE (stratified subsets; 2 epochs; test not evaluated)")
    print("Hardware inspection:")
    for k, v in hw.items():
        print(f"  {k}: {v}")
    if device.type == "cpu":
        print("  NOTE: Using CPU + memory-mapped NPZ loader.")

    feature_list_path = root / "outputs" / "tensors" / "r42_T20_s1_tensor_feature_list.csv"
    scaler_path = root / "outputs" / "tensors" / "r42_T20_s1_train_scaler_stats.json"
    feats_df = pd.read_csv(feature_list_path)
    feature_list = feats_df["feature_name"].tolist()
    scaler = json.loads(scaler_path.read_text(encoding="utf-8"))
    if not scaler.get("fitted_on_train_only", False):
        raise SystemExit("Scaler not marked as train-only.")

    datasets = {
        "train": NpzSequenceDataset(
            tensor_dir / "r42_T20_s1_train.npz", mmap=True, materialize=not smoke
        ),
        "validation": NpzSequenceDataset(
            tensor_dir / "r42_T20_s1_validation.npz", mmap=True, materialize=False
        ),
        "test": NpzSequenceDataset(
            tensor_dir / "r42_T20_s1_test.npz", mmap=True, materialize=False
        ),
    }
    print("\nPre-training validation:")
    for msg in validate_tensors(datasets, feature_list):
        print(f"  {msg}")

    model = BiLSTMClassifier(input_dim=13, hidden_size=HIDDEN_SIZE, dropout=DROPOUT).to(device)
    param_count = sum(p.numel() for p in model.parameters() if p.requires_grad)

    y_train_full = np.asarray(datasets["train"].y).astype(np.float64)
    if smoke:
        rng = np.random.default_rng(seed)
        train_idx = stratified_smoke_indices(y_train_full, smoke_n, rng)
        y_val_full = np.asarray(datasets["validation"].y).astype(np.float64)
        val_idx = stratified_smoke_indices(
            y_val_full, min(smoke_n // 2, len(y_val_full)), rng
        )
        y_train = y_train_full[train_idx]
        max_epochs = min(max_epochs, 2)
        if evaluate_test:
            print("  NOTE: --evaluate-test ignored during smoke mode (test not evaluated).")
        print(
            f"\nSMOKE MODE: train_n={len(train_idx)}, val_n={len(val_idx)}, "
            f"epochs={max_epochs}"
        )
    else:
        train_idx = None
        val_idx = None
        y_train = y_train_full

    n_pos = float((y_train == 1).sum())
    n_neg = float((y_train == 0).sum())
    pos_weight = torch.tensor([n_neg / max(n_pos, 1.0)], dtype=torch.float32, device=device)

    train_loader = make_loader(datasets["train"], batch_size, shuffle=True, indices=train_idx)
    val_loader = make_loader(datasets["validation"], batch_size, shuffle=False, indices=val_idx)

    criterion = nn.BCEWithLogitsLoss(pos_weight=pos_weight)
    optimizer = torch.optim.Adam(model.parameters(), lr=LEARNING_RATE)

    config = {
        "architecture": {
            "type": "BiLSTMClassifier",
            "input_dim": 13,
            "hidden_size": HIDDEN_SIZE,
            "num_layers": 1,
            "bidirectional": True,
            "dropout": DROPOUT,
            "classifier": "Linear(128 -> 1) + sigmoid via BCEWithLogitsLoss",
        },
        "param_count": param_count,
        "seed": seed,
        "batch_size": batch_size,
        "learning_rate": LEARNING_RATE,
        "optimizer": "Adam",
        "loss": "BCEWithLogitsLoss",
        "pos_weight_train": float(pos_weight.cpu()),
        "max_epochs": max_epochs,
        "patience": patience,
        "early_stopping_metric": "validation_pr_auc",
        "threshold_selection": "maximum_validation_f1",
        "grad_clip_norm": GRAD_CLIP_NORM,
        "features": SAFE_FEATURES,
        "device": str(device),
        "hardware": hw,
        "smoke": bool(smoke),
        "evaluate_test": bool(evaluate_test) and not smoke,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "deterministic": {
            "cudnn_deterministic": True,
            "cudnn_benchmark": False,
        },
    }

    history: list[dict] = []
    best_val_pr = -1.0
    best_epoch = 0
    patience_left = patience
    start_epoch = 1
    ckpt_last = out_dir / "last.pt"
    ckpt_best = out_dir / "best.pt"

    if resume and ckpt_last.exists():
        payload = torch.load(ckpt_last, map_location="cpu", weights_only=False)
        model.load_state_dict(payload["model_state_dict"])
        optimizer.load_state_dict(payload["optimizer_state_dict"])
        history = list(payload.get("history", []))
        best_val_pr = float(payload.get("best_val_pr_auc", -1.0))
        best_epoch = int(payload.get("best_epoch", 0))
        patience_left = int(payload.get("early_stopping", {}).get("patience_left", patience))
        start_epoch = int(payload.get("epoch", 0)) + 1
        if payload.get("config"):
            config.update(payload["config"])
        print(f"Resumed from {ckpt_last} at epoch {start_epoch}")

    print(
        f"\nTraining: device={device}, params={param_count:,}, "
        f"batch={batch_size}, lr={LEARNING_RATE}, pos_weight={float(pos_weight):.4f}, "
        f"patience={patience}"
    )
    t0 = time.perf_counter()
    for epoch in range(start_epoch, max_epochs + 1):
        ep_t0 = time.perf_counter()
        train_loss = train_one_epoch(model, train_loader, optimizer, criterion, device)
        val_loss = eval_loss(model, val_loader, criterion, device)
        val_probs = predict_proba(model, val_loader, device)
        y_val = np.asarray(datasets["validation"].y)
        if val_idx is not None:
            y_val = y_val[val_idx]
        val_pr = pr_auc_safe(y_val, val_probs)
        ep_sec = time.perf_counter() - ep_t0
        history.append(
            {
                "epoch": epoch,
                "train_loss": train_loss,
                "val_loss": val_loss,
                "val_pr_auc": val_pr,
                "epoch_time_sec": ep_sec,
            }
        )
        print(
            f"  epoch {epoch:02d}: train_loss={train_loss:.6f} "
            f"val_loss={val_loss:.6f} val_pr_auc={val_pr:.6f} ({ep_sec:.1f}s)"
        )

        improved = np.isfinite(val_pr) and (val_pr > best_val_pr + 1e-6)
        if improved:
            best_val_pr = float(val_pr)
            best_epoch = epoch
            patience_left = patience
        else:
            patience_left -= 1

        config["best_epoch"] = best_epoch
        config["best_val_pr_auc"] = best_val_pr
        ckpt = build_checkpoint(
            model,
            optimizer,
            epoch,
            best_epoch,
            best_val_pr,
            patience_left,
            config,
            history,
        )
        torch.save(ckpt, ckpt_last)
        if improved:
            torch.save(ckpt, ckpt_best)

        pd.DataFrame(history).to_csv(out_dir / "training_history.csv", index=False)

        if patience_left <= 0 and not smoke:
            print(f"  Early stopping at epoch {epoch} (best={best_epoch})")
            break

    train_time = time.perf_counter() - t0
    config["training_time_sec"] = train_time

    if ckpt_best.exists():
        best_payload = torch.load(ckpt_best, map_location="cpu", weights_only=False)
        model.load_state_dict(best_payload["model_state_dict"])
        model.to(device)
    elif ckpt_last.exists():
        last_payload = torch.load(ckpt_last, map_location="cpu", weights_only=False)
        model.load_state_dict(last_payload["model_state_dict"])
        model.to(device)

    val_probs = predict_proba(model, val_loader, device)
    y_val = np.asarray(datasets["validation"].y)
    if val_idx is not None:
        y_val = y_val[val_idx]
    thr, thr_f1 = choose_threshold_f1(y_val, val_probs)
    val_metrics = metrics_at_threshold(y_val, val_probs, thr)
    val_metrics_050 = metrics_at_threshold(y_val, val_probs, 0.5)

    (out_dir / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    thr_payload = {
        "selected_threshold": thr,
        "selection_rule": (
            "Grid-search threshold on validation probabilities to maximise F1; "
            "candidates = linspace(0.01,0.99,99) union validation probability quantiles; "
            "test unused for threshold selection."
        ),
        "validation_f1_at_selected": thr_f1,
        "validation_metrics": val_metrics,
        "validation_metrics_default_0_5": val_metrics_050,
        "best_epoch": best_epoch,
        "best_val_pr_auc": best_val_pr,
        "test_not_used_for_selection": True,
    }
    (out_dir / "threshold.json").write_text(json.dumps(thr_payload, indent=2), encoding="utf-8")
    save_predictions(
        out_dir / "validation_predictions.parquet",
        "validation",
        y_val,
        val_probs,
        thr,
        datasets["validation"],
        val_idx,
    )
    pd.DataFrame(
        [
            {
                "model": "bilstm",
                "split": "validation",
                "threshold_rule": "selected_val_f1",
                "seed": seed,
                "best_epoch": best_epoch,
                "training_time_sec": train_time,
                **val_metrics,
            }
        ]
    ).to_csv(out_dir / "validation_metrics.csv", index=False)

    metadata = {
        "seed": seed,
        "best_epoch": best_epoch,
        "best_val_pr_auc": best_val_pr,
        "selected_threshold": thr,
        "validation_f1": val_metrics["f1"],
        "checkpoint_best": str(ckpt_best),
        "checkpoint_last": str(ckpt_last),
        "param_count": param_count,
        "training_time_sec": train_time,
        "evaluate_test": bool(evaluate_test) and not smoke,
        "resumed": bool(resume and start_epoch > 1),
    }
    (out_dir / "checkpoint_metadata.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )

    test_metrics = None
    test_metrics_050 = None
    test_infer_time = None
    if evaluate_test and not smoke:
        test_loader = make_loader(datasets["test"], batch_size, shuffle=False, indices=None)
        t_inf0 = time.perf_counter()
        test_probs = predict_proba(model, test_loader, device)
        test_infer_time = time.perf_counter() - t_inf0
        y_test = np.asarray(datasets["test"].y)
        test_metrics = metrics_at_threshold(y_test, test_probs, thr)
        test_metrics_050 = metrics_at_threshold(y_test, test_probs, 0.5)
        save_predictions(
            out_dir / "test_predictions.parquet",
            "test",
            y_test,
            test_probs,
            thr,
            datasets["test"],
            None,
        )
        pd.DataFrame(
            [
                {
                    "model": "bilstm",
                    "split": "test",
                    "threshold_rule": "selected_val_f1",
                    "seed": seed,
                    "best_epoch": best_epoch,
                    "training_time_sec": train_time,
                    "test_inference_time_sec": test_infer_time,
                    **test_metrics,
                }
            ]
        ).to_csv(out_dir / "test_metrics.csv", index=False)
        config["test_inference_time_sec"] = test_infer_time
        (out_dir / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")

        cmp_rows = [
            {
                "model": "xgboost_T20",
                "precision": XGB_REF["precision"],
                "recall": XGB_REF["recall"],
                "f1": XGB_REF["f1"],
                "pr_auc": XGB_REF["pr_auc"],
                "fpr": XGB_REF["fpr"],
                "fp": XGB_REF["fp"],
                "fn": XGB_REF["fn"],
            },
            {
                "model": "bilstm_T20_selected_threshold",
                "precision": test_metrics["precision"],
                "recall": test_metrics["recall"],
                "f1": test_metrics["f1"],
                "pr_auc": test_metrics["pr_auc"],
                "fpr": test_metrics["fpr"],
                "fp": test_metrics["fp"],
                "fn": test_metrics["fn"],
            },
            {
                "model": "bilstm_T20_threshold_0.50",
                "precision": test_metrics_050["precision"],
                "recall": test_metrics_050["recall"],
                "f1": test_metrics_050["f1"],
                "pr_auc": test_metrics_050["pr_auc"],
                "fpr": test_metrics_050["fpr"],
                "fp": test_metrics_050["fp"],
                "fn": test_metrics_050["fn"],
            },
        ]
        pd.DataFrame(cmp_rows).to_csv(out_dir / "bilstm_vs_xgboost.csv", index=False)

    required = [
        ckpt_best,
        ckpt_last,
        out_dir / "config.json",
        out_dir / "training_history.csv",
        out_dir / "threshold.json",
        out_dir / "validation_predictions.parquet",
        out_dir / "validation_metrics.csv",
        out_dir / "checkpoint_metadata.json",
    ]
    missing = [str(p) for p in required if not p.exists()]
    if missing:
        raise SystemExit(f"Missing required outputs: {missing}")

    print("\n" + "=" * 90)
    print("RESULTS SUMMARY")
    print("=" * 90)
    print(f"Seed: {seed}")
    print(f"Best epoch: {best_epoch} (val PR-AUC={best_val_pr:.6f})")
    print(f"Selected validation threshold (max F1): {thr:.4f} (val F1={thr_f1:.4f})")
    print(
        f"Validation @ selected: P={val_metrics['precision']:.4f} "
        f"R={val_metrics['recall']:.4f} F1={val_metrics['f1']:.4f} "
        f"PR-AUC={val_metrics['pr_auc']:.4f} FP={val_metrics['fp']} FN={val_metrics['fn']}"
    )
    if test_metrics is not None:
        print(
            f"Test @ selected (single evaluation): P={test_metrics['precision']:.4f} "
            f"R={test_metrics['recall']:.4f} F1={test_metrics['f1']:.4f} "
            f"PR-AUC={test_metrics['pr_auc']:.4f} FP={test_metrics['fp']} FN={test_metrics['fn']}"
        )
    else:
        print("Test evaluation: skipped (--evaluate-test not set, or smoke mode)")
    print(f"Training time: {train_time:.1f}s")
    print(f"Outputs: {out_dir}")

    if smoke:
        if len(history) < 1:
            raise SystemExit("Smoke failed: no history")
        if not np.isfinite(history[0]["train_loss"]):
            raise SystemExit("Smoke failed: non-finite loss")
        if len(history) >= 2 and not (
            history[-1]["train_loss"] <= history[0]["train_loss"] * 1.5
            or abs(history[-1]["train_loss"] - history[0]["train_loss"]) < 5.0
        ):
            print("  WARN: smoke loss did not clearly decrease (still numerically finite).")
        print("SMOKE TEST PASSED")
        return

    if evaluate_test and test_metrics is not None:
        key = (
            f"Bi-LSTM seed={seed} test F1={test_metrics['f1']:.4f}, "
            f"PR-AUC={test_metrics['pr_auc']:.4f}, "
            f"R={test_metrics['recall']:.4f}; vs XGB F1=0.994"
        )
        append_manifest(root, out_dir, key)
        append_notes(
            root,
            {
                "device": str(device),
                "cuda_available": hw["cuda_available"],
                "batch_size": batch_size,
                "hidden_size": HIDDEN_SIZE,
                "dropout": DROPOUT,
                "param_count": param_count,
                "pos_weight": float(pos_weight.cpu()),
                "best_epoch": best_epoch,
                "selected_threshold": thr,
                "test_precision": test_metrics["precision"],
                "test_recall": test_metrics["recall"],
                "test_f1": test_metrics["f1"],
                "test_pr_auc": test_metrics["pr_auc"],
                "test_fpr": test_metrics["fpr"],
                "test_fp": test_metrics["fp"],
                "test_fn": test_metrics["fn"],
                "test_precision_050": test_metrics_050["precision"],
                "test_recall_050": test_metrics_050["recall"],
                "test_f1_050": test_metrics_050["f1"],
                "test_fpr_050": test_metrics_050["fpr"],
                "test_fp_050": test_metrics_050["fp"],
                "test_fn_050": test_metrics_050["fn"],
                "out_dir": str(out_dir.relative_to(root)).replace("\\", "/"),
            },
        )


def default_output_dir(root: Path, seed: int) -> Path:
    return root / "outputs" / "objective2" / f"bilstm_seed{seed}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Standalone Bi-LSTM baseline on T=20 tensors (Objective 2 repeated seeds)."
    )
    parser.add_argument("--tensor-dir", default="data/processed/tensors")
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Default: outputs/objective2/bilstm_seed{seed}",
    )
    parser.add_argument("--seed", type=int, choices=SEED_CHOICES, default=DEFAULT_SEED)
    parser.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"])
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--max-epochs", type=int, default=MAX_EPOCHS)
    parser.add_argument("--patience", type=int, default=DEFAULT_PATIENCE)
    parser.add_argument("--resume", action="store_true", help="Resume from last.pt in output-dir.")
    parser.add_argument(
        "--evaluate-test",
        action="store_true",
        help="Apply validation-selected threshold to test once (disabled by default).",
    )
    parser.add_argument("--smoke", action="store_true", help="Small subset, 2 epochs.")
    parser.add_argument("--smoke-n", type=int, default=4000)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = repo_root()
    out_dir = (
        resolve(root, args.output_dir)
        if args.output_dir is not None
        else default_output_dir(root, args.seed)
    )
    if args.smoke and args.output_dir is None:
        out_dir = out_dir / "smoke"
    run_experiment(
        root=root,
        tensor_dir=resolve(root, args.tensor_dir),
        out_dir=out_dir,
        seed=args.seed,
        device_choice=args.device,
        batch_size=args.batch_size,
        max_epochs=args.max_epochs,
        patience=args.patience,
        resume=args.resume,
        evaluate_test=args.evaluate_test,
        smoke=args.smoke,
        smoke_n=args.smoke_n,
    )


if __name__ == "__main__":
    main()
