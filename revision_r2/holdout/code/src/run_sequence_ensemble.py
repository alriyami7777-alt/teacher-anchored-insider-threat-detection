#!/usr/bin/env python3
"""
Stage 1 / 1.1 Objective 2: differentiable sequence–ensemble model.

Bi-LSTM temporal encoder + attention/last aggregation + soft-forest/linear head
on CERT r4.2 T=20 stride=1 tensors.

Independent of standalone Bi-LSTM / Soft Forest artefacts. Does not modify
optimisation scripts or their outputs. Smoke / diagnostic results are not
appended to Chapter 4 notes or the official results manifest.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
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

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from models.sequence_ensemble import (  # noqa: E402
    SequenceEnsembleModel,
    assert_component_gradients,
    assert_model_outputs,
    component_grad_norms,
    compute_validation_diagnostics,
    load_encoder_checkpoint,
)

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

SEQ_LEN = 20
INPUT_DIM = 13
GRAD_CLIP_NORM = 1.0
DEFAULT_SEED = 42
DEFAULT_HIDDEN = 64
DEFAULT_DROPOUT = 0.2
DEFAULT_ATTENTION_DIM = 64
DEFAULT_N_TREES = 5
DEFAULT_TREE_DEPTH = 4
DEFAULT_LR = 1e-3
DEFAULT_WEIGHT_DECAY = 0.0
DEFAULT_BATCH = 1024
DEFAULT_MAX_EPOCHS = 20
DEFAULT_PATIENCE = 4
DEFAULT_POS_WEIGHT_MULT = 1.0


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def resolve(root: Path, p: str | Path) -> Path:
    path = Path(p)
    return path if path.is_absolute() else (root / path).resolve()


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def select_device(choice: str) -> torch.device:
    if choice == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if choice == "cuda":
        if not torch.cuda.is_available():
            raise SystemExit("CUDA requested but torch.cuda.is_available() is False")
        return torch.device("cuda")
    return torch.device("cpu")


class NpzSequenceDataset(Dataset):
    """NPZ loader with optional memory-map; can materialise arrays for shuffle speed."""

    def __init__(self, npz_path: Path, mmap: bool = True, materialize: bool = False) -> None:
        self.path = npz_path
        z = np.load(npz_path, allow_pickle=True, mmap_mode="r" if mmap else None)
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


def validate_tensors(datasets: dict[str, NpzSequenceDataset], feature_list: list[str]) -> list[str]:
    messages: list[str] = []
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

    messages.append("PASS: train-only scaling (scaler stats artefact fitted_on_train_only)")
    messages.append(
        "PASS: test unused for training / early stopping / threshold / tuning (by protocol)"
    )
    return messages


def choose_threshold_f1(y_true: np.ndarray, probs: np.ndarray) -> tuple[float, float]:
    candidates = set(np.linspace(0.01, 0.99, 99).tolist())
    candidates.update(float(q) for q in np.quantile(probs, np.linspace(0.01, 0.99, 50)))
    best_t, best_f1 = 0.5, -1.0
    for t in sorted(candidates):
        f1 = f1_score(y_true, (probs >= t).astype(int), zero_division=0)
        if f1 > best_f1:
            best_f1 = float(f1)
            best_t = float(t)
    return best_t, best_f1


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


@torch.no_grad()
def predict_proba(model: SequenceEnsembleModel, loader: DataLoader, device: torch.device) -> np.ndarray:
    model.eval()
    outs: list[np.ndarray] = []
    for xb, _ in loader:
        logits, _ = model(xb.to(device))
        outs.append(torch.sigmoid(logits).cpu().numpy())
    return np.concatenate(outs, axis=0)


def train_one_epoch(
    model: SequenceEnsembleModel,
    loader: DataLoader,
    optimizer: torch.optim.Optimizer,
    criterion: nn.Module,
    device: torch.device,
) -> tuple[float, dict[str, float]]:
    """Train one epoch; return mean loss and grad norms from the final batch."""
    model.train()
    total = 0.0
    n = 0
    last_grad_norms: dict[str, float] = {}
    for xb, yb in loader:
        xb = xb.to(device)
        yb = yb.to(device)
        optimizer.zero_grad(set_to_none=True)
        logits, _ = model(xb)
        loss = criterion(logits, yb)
        loss.backward()
        last_grad_norms = component_grad_norms(model)
        torch.nn.utils.clip_grad_norm_(model.parameters(), GRAD_CLIP_NORM)
        optimizer.step()
        bs = xb.size(0)
        total += float(loss.item()) * bs
        n += bs
    return total / max(n, 1), last_grad_norms


@torch.no_grad()
def eval_loss(
    model: SequenceEnsembleModel,
    loader: DataLoader,
    criterion: nn.Module,
    device: torch.device,
) -> float:
    model.eval()
    total = 0.0
    n = 0
    for xb, yb in loader:
        xb = xb.to(device)
        yb = yb.to(device)
        logits, _ = model(xb)
        loss = criterion(logits, yb)
        bs = xb.size(0)
        total += float(loss.item()) * bs
        n += bs
    return total / max(n, 1)


@torch.no_grad()
def collect_validation_pass(
    model: SequenceEnsembleModel,
    loader: DataLoader,
    device: torch.device,
    grad_norms: dict[str, float] | None = None,
) -> tuple[np.ndarray, np.ndarray, dict]:
    """Full validation forward: probabilities, labels, and aggregated diagnostics."""
    model.eval()
    logit_chunks: list[torch.Tensor] = []
    y_chunks: list[torch.Tensor] = []
    attn_chunks: list[torch.Tensor] = []
    routing_acc: list[list[torch.Tensor]] | None = None

    for xb, yb in loader:
        xb = xb.to(device)
        logits, extras = model(xb)
        logit_chunks.append(logits.detach().cpu())
        y_chunks.append(yb.detach().cpu())
        attn_chunks.append(extras["attention_weights"].detach().cpu())
        routing = extras.get("routing") or []
        if routing:
            if routing_acc is None:
                routing_acc = [[] for _ in routing]
            for i, route in enumerate(routing):
                routing_acc[i].append(route["leaf_probs"].detach().cpu())

    logits_all = torch.cat(logit_chunks, dim=0)
    y_all = torch.cat(y_chunks, dim=0)
    attn_all = torch.cat(attn_chunks, dim=0)
    routing_extras: list[dict] = []
    if routing_acc is not None:
        for leaf_list in routing_acc:
            leaf = torch.cat(leaf_list, dim=0)
            routing_extras.append(
                {
                    "leaf_probs": leaf,
                    "p_left": torch.ones(1),  # placeholders unused by diagnostics leaf path
                    "p_right": torch.ones(1),
                    "tree_logit": torch.ones(1),
                }
            )

    extras = {
        "attention_weights": attn_all,
        "routing": routing_extras,
        "classification_head": model.classification_head,
        "temporal_aggregation": model.temporal_aggregation,
    }
    # Recompute proper routing diagnostics when soft forest is active via a
    # second lightweight pass is expensive; leaf_probs alone suffice for util/entropy.
    diag = compute_validation_diagnostics(
        model, logits_all, extras, y_all, grad_norms=grad_norms
    )
    probs = torch.sigmoid(logits_all).numpy()
    return probs, y_all.numpy(), diag


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


def collect_rng_states() -> dict:
    return {
        "python_random_state": random.getstate(),
        "numpy_random_state": np.random.get_state(),
        "torch_cpu_rng_state": torch.get_rng_state(),
        "torch_cuda_rng_state": (
            torch.cuda.get_rng_state_all() if torch.cuda.is_available() else None
        ),
    }


def build_checkpoint(
    model: SequenceEnsembleModel,
    optimizer: torch.optim.Optimizer,
    scheduler: torch.optim.lr_scheduler._LRScheduler | None,
    epoch: int,
    best_epoch: int,
    best_val_pr: float,
    patience_left: int,
    config: dict,
    history: list[dict],
    diagnostics: list[dict],
) -> dict:
    return {
        "model_state_dict": {k: v.detach().cpu().clone() for k, v in model.state_dict().items()},
        "optimizer_state_dict": optimizer.state_dict(),
        "scheduler_state_dict": scheduler.state_dict() if scheduler is not None else None,
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
        "validation_diagnostics": diagnostics,
        "rng_states": collect_rng_states(),
    }


def run_gradient_check(
    model: SequenceEnsembleModel,
    loader: DataLoader,
    criterion: nn.Module,
    device: torch.device,
) -> list[str]:
    model.train()
    xb, yb = next(iter(loader))
    xb = xb.to(device)
    yb = yb.to(device)
    model.zero_grad(set_to_none=True)
    logits, extras = model(xb)
    msgs = assert_model_outputs(logits, extras, batch_size=xb.size(0), seq_len=SEQ_LEN)
    loss = criterion(logits, yb)
    loss.backward()
    msgs.extend(assert_component_gradients(model))
    model.zero_grad(set_to_none=True)
    return msgs


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


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Stage 1/1.1 sequence–ensemble with validation-only diagnostic ablations."
    )
    p.add_argument("--tensor-dir", default="data/processed/tensors")
    p.add_argument("--output-dir", default="outputs/baselines/sequence_ensemble")
    p.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"])
    p.add_argument("--batch-size", type=int, default=DEFAULT_BATCH)
    p.add_argument("--max-epochs", type=int, default=DEFAULT_MAX_EPOCHS)
    p.add_argument("--smoke", action="store_true")
    p.add_argument("--smoke-n", type=int, default=4000)
    p.add_argument("--seed", type=int, default=DEFAULT_SEED)
    p.add_argument("--hidden-size", type=int, default=DEFAULT_HIDDEN)
    p.add_argument("--dropout", type=float, default=DEFAULT_DROPOUT)
    p.add_argument("--attention-dim", type=int, default=DEFAULT_ATTENTION_DIM)
    p.add_argument("--n-trees", type=int, default=DEFAULT_N_TREES)
    p.add_argument("--tree-depth", type=int, default=DEFAULT_TREE_DEPTH)
    p.add_argument("--learning-rate", type=float, default=DEFAULT_LR)
    p.add_argument("--weight-decay", type=float, default=DEFAULT_WEIGHT_DECAY)
    p.add_argument("--patience", type=int, default=DEFAULT_PATIENCE)
    p.add_argument(
        "--classification-head",
        default="soft_forest",
        choices=["soft_forest", "linear"],
        help="soft_forest: proposed head; linear: diagnostic linear ablation.",
    )
    p.add_argument(
        "--temporal-aggregation",
        default="attention",
        choices=["attention", "last"],
        help="attention: proposed aggregation; last: final Bi-LSTM state ablation.",
    )
    p.add_argument(
        "--pos-weight-mult",
        type=float,
        default=DEFAULT_POS_WEIGHT_MULT,
        help="effective pos_weight = train imbalance ratio × multiplier (default 1.0).",
    )
    p.add_argument(
        "--encoder-checkpoint",
        default=None,
        help="Optional standalone Bi-LSTM checkpoint for encoder weight initialisation.",
    )
    p.add_argument("--resume", action="store_true", help="Resume from last.pt in output-dir.")
    p.add_argument(
        "--evaluate-test",
        action="store_true",
        help="Apply validation-selected threshold to the test set once (disabled by default).",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    root = repo_root()
    tensor_dir = resolve(root, args.tensor_dir)
    out_dir = resolve(root, args.output_dir)
    # Nest under smoke/ only for the default output root so custom diagnostic dirs stay intact.
    if args.smoke and out_dir.name == "sequence_ensemble":
        out_dir = out_dir / "smoke"
    out_dir.mkdir(parents=True, exist_ok=True)

    set_seed(args.seed)
    device = select_device(args.device)

    print("=" * 72)
    print("CERT r4.2 sequence–ensemble Stage 1.1 (T=20, stride=1)")
    print("=" * 72)
    print(f"Device: {device}")
    print(f"Output: {out_dir}")
    print(f"Head: {args.classification_head} | Aggregation: {args.temporal_aggregation}")
    print(f"pos_weight_mult: {args.pos_weight_mult}")
    print(f"Evaluate test: {bool(args.evaluate_test)}")
    if args.smoke:
        print("Mode: SMOKE (stratified subsets; 2 epochs; no test evaluation)")

    feature_list_path = root / "outputs" / "tensors" / "r42_T20_s1_tensor_feature_list.csv"
    scaler_path = root / "outputs" / "tensors" / "r42_T20_s1_train_scaler_stats.json"
    feats_df = pd.read_csv(feature_list_path)
    feature_list = feats_df["feature_name"].tolist()
    scaler = json.loads(scaler_path.read_text(encoding="utf-8"))
    if not scaler.get("fitted_on_train_only", False):
        raise SystemExit("Scaler not marked as train-only.")

    datasets = {
        "train": NpzSequenceDataset(
            tensor_dir / "r42_T20_s1_train.npz", mmap=True, materialize=not args.smoke
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

    y_train_full = np.asarray(datasets["train"].y).astype(np.float64)
    max_epochs = args.max_epochs
    if args.smoke:
        rng = np.random.default_rng(args.seed)
        train_idx = stratified_smoke_indices(y_train_full, args.smoke_n, rng)
        y_val_full = np.asarray(datasets["validation"].y).astype(np.float64)
        val_idx = stratified_smoke_indices(
            y_val_full, min(args.smoke_n // 2, len(y_val_full)), rng
        )
        y_train = y_train_full[train_idx]
        max_epochs = 2
        print(f"\nSMOKE subsets: train_n={len(train_idx)}, val_n={len(val_idx)}, epochs={max_epochs}")
        if args.evaluate_test:
            print("  NOTE: --evaluate-test ignored during smoke mode (test not evaluated).")
    else:
        train_idx = None
        val_idx = None
        y_train = y_train_full

    n_pos = float((y_train == 1).sum())
    n_neg = float((y_train == 0).sum())
    base_pos_weight = n_neg / max(n_pos, 1.0)
    effective_pos_weight = base_pos_weight * float(args.pos_weight_mult)
    pos_weight = torch.tensor([effective_pos_weight], dtype=torch.float32, device=device)
    print(
        f"\npos_weight: base={base_pos_weight:.4f}, "
        f"mult={args.pos_weight_mult:.4f}, effective={effective_pos_weight:.4f}"
    )

    model = SequenceEnsembleModel(
        input_dim=INPUT_DIM,
        hidden_size=args.hidden_size,
        dropout=args.dropout,
        attention_dim=args.attention_dim,
        n_trees=args.n_trees,
        tree_depth=args.tree_depth,
        classification_head=args.classification_head,
        temporal_aggregation=args.temporal_aggregation,
    ).to(device)

    encoder_report = None
    if args.encoder_checkpoint:
        enc_path = resolve(root, args.encoder_checkpoint)
        encoder_report = load_encoder_checkpoint(model, enc_path)
        print("\nEncoder checkpoint load report:")
        print(f"  path: {encoder_report['checkpoint']}")
        print(f"  loaded ({encoder_report['n_loaded']}): {encoder_report['loaded']}")
        print(f"  missing: {encoder_report['missing']}")
        print(f"  incompatible: {encoder_report['incompatible']}")
        print(f"  skipped standalone head: {encoder_report['skipped_standalone_head']}")
        print(f"  encoder_frozen: {encoder_report['encoder_frozen']}")
        (out_dir / "encoder_load_report.json").write_text(
            json.dumps(encoder_report, indent=2), encoding="utf-8"
        )

    counts = model.component_parameter_counts()
    print("\nParameter counts:")
    for k, v in counts.items():
        print(f"  {k}: {v:,}")

    train_loader = make_loader(datasets["train"], args.batch_size, shuffle=True, indices=train_idx)
    val_loader = make_loader(
        datasets["validation"], args.batch_size, shuffle=False, indices=val_idx
    )

    criterion = nn.BCEWithLogitsLoss(pos_weight=pos_weight)
    optimizer = torch.optim.Adam(
        model.parameters(), lr=args.learning_rate, weight_decay=args.weight_decay
    )
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimizer, mode="max", factor=0.5, patience=max(1, args.patience // 2), min_lr=1e-5
    )

    config = {
        "architecture": "SequenceEnsembleModel",
        "stage": "1.1",
        "input_shape": [None, SEQ_LEN, INPUT_DIM],
        "classification_head": args.classification_head,
        "temporal_aggregation": args.temporal_aggregation,
        "hidden_size": args.hidden_size,
        "dropout": args.dropout,
        "attention_dim": args.attention_dim,
        "n_trees": args.n_trees,
        "tree_depth": args.tree_depth,
        "learning_rate": args.learning_rate,
        "weight_decay": args.weight_decay,
        "batch_size": args.batch_size,
        "max_epochs": max_epochs,
        "patience": args.patience,
        "seed": args.seed,
        "device": str(device),
        "base_pos_weight": base_pos_weight,
        "pos_weight_multiplier": float(args.pos_weight_mult),
        "effective_pos_weight": effective_pos_weight,
        "encoder_checkpoint": str(resolve(root, args.encoder_checkpoint))
        if args.encoder_checkpoint
        else None,
        "grad_clip_norm": GRAD_CLIP_NORM,
        "early_stopping_metric": "validation_pr_auc",
        "threshold_selection": "maximum_validation_f1",
        "features": feature_list,
        "parameter_counts": counts,
        "smoke": bool(args.smoke),
        "evaluate_test": bool(args.evaluate_test) and not args.smoke,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }

    history: list[dict] = []
    diagnostics_rows: list[dict] = []
    best_val_pr = -1.0
    best_epoch = 0
    patience_left = args.patience
    start_epoch = 1
    ckpt_last = out_dir / "last.pt"
    ckpt_best = out_dir / "best.pt"

    if args.resume and ckpt_last.exists():
        payload = torch.load(ckpt_last, map_location="cpu", weights_only=False)
        model.load_state_dict(payload["model_state_dict"])
        optimizer.load_state_dict(payload["optimizer_state_dict"])
        if payload.get("scheduler_state_dict") and scheduler is not None:
            scheduler.load_state_dict(payload["scheduler_state_dict"])
        history = list(payload.get("history", []))
        diagnostics_rows = list(payload.get("validation_diagnostics", []))
        best_val_pr = float(payload.get("best_val_pr_auc", -1.0))
        best_epoch = int(payload.get("best_epoch", 0))
        patience_left = int(payload.get("early_stopping", {}).get("patience_left", args.patience))
        start_epoch = int(payload.get("epoch", 0)) + 1
        print(f"Resumed from {ckpt_last} at epoch {start_epoch}")

    print("\nNumerical / gradient checks (one batch):")
    for msg in run_gradient_check(model, train_loader, criterion, device):
        print(f"  {msg}")

    print(
        f"\nTraining: params={counts['total']:,}, batch={args.batch_size}, "
        f"lr={args.learning_rate}, weight_decay={args.weight_decay}, "
        f"effective_pos_weight={effective_pos_weight:.4f}"
    )
    t0 = time.perf_counter()
    for epoch in range(start_epoch, max_epochs + 1):
        ep_t0 = time.perf_counter()
        train_loss, grad_norms = train_one_epoch(
            model, train_loader, optimizer, criterion, device
        )
        val_loss = eval_loss(model, val_loader, criterion, device)
        val_probs, y_val_np, diag = collect_validation_pass(
            model, val_loader, device, grad_norms=grad_norms
        )
        val_pr = pr_auc_safe(y_val_np, val_probs)
        if np.isfinite(val_pr):
            scheduler.step(val_pr)
        ep_sec = time.perf_counter() - ep_t0

        hist_row = {
            "epoch": epoch,
            "train_loss": train_loss,
            "val_loss": val_loss,
            "val_pr_auc": val_pr,
            "lr": float(optimizer.param_groups[0]["lr"]),
            "epoch_time_sec": ep_sec,
        }
        history.append(hist_row)
        diag_row = {"epoch": epoch, **diag}
        diagnostics_rows.append(diag_row)

        print(
            f"  epoch {epoch:02d}: train_loss={train_loss:.6f} "
            f"val_loss={val_loss:.6f} val_pr_auc={val_pr:.6f} "
            f"attn_H={diag['attention_mean_entropy']:.4f} ({ep_sec:.1f}s)"
        )

        improved = np.isfinite(val_pr) and (val_pr > best_val_pr + 1e-6)
        if improved:
            best_val_pr = float(val_pr)
            best_epoch = epoch
            patience_left = args.patience
        else:
            patience_left -= 1

        ckpt = build_checkpoint(
            model,
            optimizer,
            scheduler,
            epoch,
            best_epoch,
            best_val_pr,
            patience_left,
            config,
            history,
            diagnostics_rows,
        )
        torch.save(ckpt, ckpt_last)
        if improved:
            torch.save(ckpt, ckpt_best)

        # Persist diagnostics incrementally (validation-only).
        pd.DataFrame(diagnostics_rows).to_csv(out_dir / "validation_diagnostics.csv", index=False)
        pd.DataFrame(history).to_csv(out_dir / "training_history.csv", index=False)

        if patience_left <= 0 and not args.smoke:
            print(f"  Early stopping at epoch {epoch} (best={best_epoch})")
            break

    train_time = time.perf_counter() - t0

    if ckpt_best.exists():
        best_payload = torch.load(ckpt_best, map_location="cpu", weights_only=False)
        model.load_state_dict(best_payload["model_state_dict"])
        model.to(device)

    val_probs, y_val_np, _ = collect_validation_pass(model, val_loader, device)
    thr, thr_f1 = choose_threshold_f1(y_val_np, val_probs)
    val_metrics = metrics_at_threshold(y_val_np, val_probs, thr)

    (out_dir / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    pd.DataFrame(history).to_csv(out_dir / "training_history.csv", index=False)
    pd.DataFrame(diagnostics_rows).to_csv(out_dir / "validation_diagnostics.csv", index=False)
    thr_payload = {
        "selected_threshold": thr,
        "selection_rule": "maximum validation F1; test unused for selection",
        "validation_f1_at_selected": thr_f1,
        "validation_metrics": val_metrics,
        "best_epoch": best_epoch,
        "best_val_pr_auc": best_val_pr,
        "test_not_used_for_selection": True,
    }
    (out_dir / "threshold.json").write_text(json.dumps(thr_payload, indent=2), encoding="utf-8")
    save_predictions(
        out_dir / "validation_predictions.parquet",
        "validation",
        y_val_np,
        val_probs,
        thr,
        datasets["validation"],
        val_idx,
    )
    pd.DataFrame(
        [
            {
                "model": "sequence_ensemble",
                "split": "validation",
                "threshold_rule": "selected_val_f1",
                **val_metrics,
            }
        ]
    ).to_csv(out_dir / "validation_metrics.csv", index=False)

    test_metrics = None
    if args.evaluate_test and not args.smoke:
        test_loader = make_loader(datasets["test"], args.batch_size, shuffle=False, indices=None)
        test_probs = predict_proba(model, test_loader, device)
        y_test = np.asarray(datasets["test"].y)
        test_metrics = metrics_at_threshold(y_test, test_probs, thr)
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
                    "model": "sequence_ensemble",
                    "split": "test",
                    "threshold_rule": "selected_val_f1",
                    **test_metrics,
                }
            ]
        ).to_csv(out_dir / "test_metrics.csv", index=False)

    required = [
        ckpt_best,
        ckpt_last,
        out_dir / "config.json",
        out_dir / "training_history.csv",
        out_dir / "validation_diagnostics.csv",
        out_dir / "threshold.json",
        out_dir / "validation_predictions.parquet",
        out_dir / "validation_metrics.csv",
    ]
    missing = [str(p) for p in required if not p.exists()]
    if missing:
        raise SystemExit(f"Missing required outputs: {missing}")

    print("\n" + "=" * 72)
    print("SEQUENCE–ENSEMBLE STAGE 1.1 SUMMARY")
    print("=" * 72)
    print(f"Head={args.classification_head}  Aggregation={args.temporal_aggregation}")
    print(
        f"pos_weight base={base_pos_weight:.4f} mult={args.pos_weight_mult:.4f} "
        f"effective={effective_pos_weight:.4f}"
    )
    print(f"Best epoch: {best_epoch}  validation PR-AUC: {best_val_pr:.6f}")
    print(f"Validation-selected threshold (max F1): {thr:.4f}")
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

    if args.smoke:
        print("SMOKE TEST PASSED")


if __name__ == "__main__":
    main()
