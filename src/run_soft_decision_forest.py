#!/usr/bin/env python3
"""Standalone differentiable soft decision forest on T=20 aggregated features."""

from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.nn.functional as F
from sklearn.metrics import (
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from torch.utils.data import DataLoader, TensorDataset

META_COLS = {
    "sequence_id",
    "user",
    "split",
    "start_date",
    "end_date",
    "window_length",
    "stride",
    "y",
    "n_active_days",
}
FORBIDDEN_RE = re.compile(
    r"(^y$|is_malicious|malicious|label|insider|scenario|answer|ground_truth|attack)",
    re.IGNORECASE,
)

N_TREES = 5
TREE_DEPTH = 4
LEARNING_RATE = 1e-3
MAX_EPOCHS = 80
EARLY_STOP_PATIENCE = 10
GRAD_CLIP_NORM = 1.0
BATCH_SIZE = 4096
DEFAULT_SEED = 42
SEEDS = [42, 52, 62]

XGB_REF = {
    "precision": 0.988,
    "recall": 1.000,
    "f1": 0.994,
    "pr_auc": 1.000,
    "fp": 1,
    "fn": 0,
}
BILSTM_REF = {
    "precision": 0.514,
    "recall": 0.893,
    "f1": 0.652,
    "pr_auc": 0.879,
    "fp": 71,
    "fn": 9,
}


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def resolve(root: Path, p: str | Path) -> Path:
    path = Path(p)
    return path if path.is_absolute() else (root / path).resolve()


def model_feature_columns(columns: list[str]) -> list[str]:
    feats = [c for c in columns if c not in META_COLS and not FORBIDDEN_RE.search(c)]
    return sorted(feats)


def set_seed(seed: int) -> None:
    np.random.seed(seed)
    torch.manual_seed(seed)


def choose_threshold(y_val: np.ndarray, p_val: np.ndarray) -> tuple[float, float]:
    candidates = set(np.linspace(0.01, 0.99, 99).tolist())
    candidates.update(float(q) for q in np.quantile(p_val, np.linspace(0.01, 0.99, 50)))
    best_t, best_f1 = 0.5, -1.0
    for t in sorted(candidates):
        f1 = f1_score(y_val, (p_val >= t).astype(int), zero_division=0)
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


class SoftDecisionTree(nn.Module):
    """Differentiable soft binary decision tree with probabilistic routing."""

    def __init__(self, in_dim: int, depth: int) -> None:
        super().__init__()
        if depth < 1:
            raise ValueError("depth must be >= 1")
        self.depth = depth
        self.n_internal = (2**depth) - 1
        self.n_leaves = 2**depth
        self.node_weight = nn.Parameter(torch.empty(self.n_internal, in_dim))
        self.node_bias = nn.Parameter(torch.zeros(self.n_internal))
        # Learnable malicious-class logit per leaf.
        self.leaf_logit = nn.Parameter(torch.empty(self.n_leaves))
        nn.init.xavier_uniform_(self.node_weight)
        nn.init.zeros_(self.node_bias)
        # Diverse leaf starts: half mildly positive, half mildly negative.
        with torch.no_grad():
            self.leaf_logit.uniform_(-0.5, 0.5)

        # Precompute path templates: for each leaf, sequence of (node_index, go_right).
        paths: list[list[tuple[int, int]]] = []
        for leaf in range(self.n_leaves):
            node = 0
            path: list[tuple[int, int]] = []
            for d in range(self.depth):
                go_right = (leaf >> (self.depth - 1 - d)) & 1
                path.append((node, go_right))
                node = 2 * node + (2 if go_right else 1)
            paths.append(path)
        self._paths = paths

    def routing(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """Return p_left, p_right, leaf_path_probs."""
        # x: (B, F)
        logits = F.linear(x, self.node_weight, self.node_bias)  # (B, n_internal)
        p_left = torch.sigmoid(logits)
        p_right = 1.0 - p_left

        batch = x.size(0)
        leaf_probs = x.new_ones(batch, self.n_leaves)
        for leaf, path in enumerate(self._paths):
            prob = x.new_ones(batch)
            for node, go_right in path:
                prob = prob * (p_right[:, node] if go_right else p_left[:, node])
            leaf_probs[:, leaf] = prob
        return p_left, p_right, leaf_probs

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, dict[str, torch.Tensor]]:
        p_left, p_right, leaf_probs = self.routing(x)
        # Probability-weighted combination of leaf logits.
        tree_logit = (leaf_probs * self.leaf_logit.unsqueeze(0)).sum(dim=1)
        extras = {
            "p_left": p_left,
            "p_right": p_right,
            "leaf_probs": leaf_probs,
            "tree_logit": tree_logit,
        }
        return tree_logit, extras


class SoftDecisionForest(nn.Module):
    def __init__(self, in_dim: int, n_trees: int = N_TREES, depth: int = TREE_DEPTH) -> None:
        super().__init__()
        self.trees = nn.ModuleList(
            [SoftDecisionTree(in_dim, depth) for _ in range(n_trees)]
        )
        self.n_trees = n_trees
        self.depth = depth
        self.in_dim = in_dim

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, list[dict[str, torch.Tensor]]]:
        tree_logits = []
        extras_list = []
        for tree in self.trees:
            logit, extras = tree(x)
            tree_logits.append(logit)
            extras_list.append(extras)
        # Average tree outputs in probability space for stable forest probability,
        # but train with mean logit for BCEWithLogitsLoss consistency.
        stacked = torch.stack(tree_logits, dim=1)  # (B, n_trees)
        forest_logit = stacked.mean(dim=1)
        return forest_logit, extras_list


def assert_numerical_validity(
    forest_logit: torch.Tensor,
    extras_list: list[dict[str, torch.Tensor]],
    model: SoftDecisionForest,
) -> list[str]:
    messages: list[str] = []
    for i, extras in enumerate(extras_list):
        p_left = extras["p_left"]
        p_right = extras["p_right"]
        leaf_probs = extras["leaf_probs"]
        if not torch.isfinite(p_left).all() or not torch.isfinite(p_right).all():
            raise SystemExit(f"Non-finite routing probabilities in tree {i}")
        if (p_left < 0).any() or (p_left > 1).any() or (p_right < 0).any() or (p_right > 1).any():
            raise SystemExit(f"Routing probabilities outside [0,1] in tree {i}")
        if not torch.allclose(p_left + p_right, torch.ones_like(p_left), atol=1e-5):
            raise SystemExit(f"p_left + p_right != 1 in tree {i}")
        if not torch.isfinite(leaf_probs).all():
            raise SystemExit(f"Non-finite leaf-path probabilities in tree {i}")
        leaf_sum = leaf_probs.sum(dim=1)
        if not torch.allclose(leaf_sum, torch.ones_like(leaf_sum), atol=1e-4):
            raise SystemExit(
                f"Leaf-path probabilities do not sum to 1 in tree {i}: "
                f"min={float(leaf_sum.min()):.6f} max={float(leaf_sum.max()):.6f}"
            )
    probs = torch.sigmoid(forest_logit)
    if (probs < 0).any() or (probs > 1).any() or not torch.isfinite(probs).all():
        raise SystemExit("Forest output probabilities invalid")
    messages.append(
        "PASS: routing in [0,1]; p_left+p_right~=1; leaf paths sum~=1; forest probs valid"
    )
    return messages


def check_gradients(model: SoftDecisionForest) -> None:
    missing = []
    for name, p in model.named_parameters():
        if p.grad is None:
            missing.append(name)
        elif not torch.isfinite(p.grad).all():
            raise SystemExit(f"Non-finite gradients for {name}")
    if missing:
        raise SystemExit(f"Missing gradients for: {missing}")


@torch.no_grad()
def predict_proba(model: SoftDecisionForest, loader: DataLoader, device: torch.device) -> np.ndarray:
    model.eval()
    outs = []
    for xb, _ in loader:
        logit, _ = model(xb.to(device))
        outs.append(torch.sigmoid(logit).cpu().numpy())
    return np.concatenate(outs, axis=0)


def train_one_epoch(
    model: SoftDecisionForest,
    loader: DataLoader,
    optimizer: torch.optim.Optimizer,
    pos_weight: torch.Tensor,
    device: torch.device,
    validate_numerics: bool = False,
) -> float:
    model.train()
    total = 0.0
    n = 0
    for xb, yb in loader:
        xb = xb.to(device)
        yb = yb.to(device)
        optimizer.zero_grad(set_to_none=True)
        logit, extras = model(xb)
        if validate_numerics:
            assert_numerical_validity(logit, extras, model)
        loss = F.binary_cross_entropy_with_logits(logit, yb, pos_weight=pos_weight)
        if not torch.isfinite(loss):
            raise SystemExit("Non-finite training loss")
        loss.backward()
        if validate_numerics:
            check_gradients(model)
        torch.nn.utils.clip_grad_norm_(model.parameters(), GRAD_CLIP_NORM)
        optimizer.step()
        bs = xb.size(0)
        total += float(loss.item()) * bs
        n += bs
    return total / max(n, 1)


@torch.no_grad()
def eval_loss(
    model: SoftDecisionForest,
    loader: DataLoader,
    pos_weight: torch.Tensor,
    device: torch.device,
) -> float:
    model.eval()
    total = 0.0
    n = 0
    for xb, yb in loader:
        xb = xb.to(device)
        yb = yb.to(device)
        logit, _ = model(xb)
        loss = F.binary_cross_entropy_with_logits(logit, yb, pos_weight=pos_weight)
        bs = xb.size(0)
        total += float(loss.item()) * bs
        n += bs
    return total / max(n, 1)


def verify_inputs(feat: pd.DataFrame, feature_cols: list[str]) -> dict:
    report = {
        "n_model_features": len(feature_cols),
        "feature_list": feature_cols,
        "scaling_required": True,
        "scaling_fitted_on_train_only": True,
        "splits": {},
    }
    print("\nInput verification:")
    print(f"  n_model_features: {len(feature_cols)}")
    print("  feature_list:")
    for i, c in enumerate(feature_cols):
        print(f"    {i:02d}: {c}")
    if any(FORBIDDEN_RE.search(c) for c in feature_cols) or any(c in META_COLS for c in feature_cols):
        raise SystemExit("Leakage-prone / metadata columns in model features")
    for split in ("train", "validation", "test"):
        part = feat.loc[feat["split"] == split]
        x = part[feature_cols].to_numpy(dtype=np.float32)
        y = part["y"].to_numpy(dtype=np.int8)
        info = {
            "n": int(len(part)),
            "x_shape": list(x.shape),
            "y_shape": list(y.shape),
            "dtype_x": str(x.dtype),
            "dtype_y": str(y.dtype),
            "malicious": int((y == 1).sum()),
            "benign": int((y == 0).sum()),
            "missing": int(np.isnan(x).sum()),
            "infinite": int(np.isinf(x).sum()),
        }
        report["splits"][split] = info
        print(
            f"  {split}: X{info['x_shape']} dtype={info['dtype_x']}; "
            f"mal={info['malicious']} ben={info['benign']}; "
            f"missing={info['missing']} inf={info['infinite']}"
        )
        if info["missing"] or info["infinite"]:
            raise SystemExit(f"Non-finite values in {split}")
    print("  scaling: train-only z-score (required for tabular soft forest)")
    return report


def prepare_arrays(
    feat: pd.DataFrame, feature_cols: list[str]
) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray], np.ndarray, np.ndarray]:
    arrays_x: dict[str, np.ndarray] = {}
    arrays_y: dict[str, np.ndarray] = {}
    train = feat.loc[feat["split"] == "train"]
    x_train = train[feature_cols].to_numpy(dtype=np.float32)
    mean = x_train.mean(axis=0)
    scale = x_train.std(axis=0, ddof=0)
    scale[scale == 0] = 1.0
    for split in ("train", "validation", "test"):
        part = feat.loc[feat["split"] == split]
        x = part[feature_cols].to_numpy(dtype=np.float32)
        arrays_x[split] = ((x - mean) / scale).astype(np.float32)
        arrays_y[split] = part["y"].to_numpy(dtype=np.float32)
    return arrays_x, arrays_y, mean, scale


def make_loader(x: np.ndarray, y: np.ndarray, batch_size: int, shuffle: bool) -> DataLoader:
    ds = TensorDataset(torch.from_numpy(x), torch.from_numpy(y))
    return DataLoader(ds, batch_size=batch_size, shuffle=shuffle, num_workers=0)


def run_training(
    arrays_x: dict[str, np.ndarray],
    arrays_y: dict[str, np.ndarray],
    feature_cols: list[str],
    out_dir: Path,
    seed: int,
    max_epochs: int,
    batch_size: int,
    smoke: bool,
    smoke_n: int,
    device: torch.device,
) -> dict:
    set_seed(seed)
    mode = "smoke" if smoke else "full"
    run_dir = out_dir if not smoke else out_dir / "smoke"
    run_dir.mkdir(parents=True, exist_ok=True)

    x_train, y_train = arrays_x["train"], arrays_y["train"]
    x_val, y_val = arrays_x["validation"], arrays_y["validation"]
    x_test, y_test = arrays_x["test"], arrays_y["test"]

    if smoke:
        rng = np.random.default_rng(seed)
        def stratified(x, y, n):
            pos = np.flatnonzero(y == 1)
            neg = np.flatnonzero(y == 0)
            n_pos = min(len(pos), max(50, n // 10))
            n_neg = min(len(neg), n - n_pos)
            idx = np.concatenate(
                [rng.choice(pos, n_pos, replace=False), rng.choice(neg, n_neg, replace=False)]
            )
            rng.shuffle(idx)
            return x[idx], y[idx]

        x_train, y_train = stratified(x_train, y_train, smoke_n)
        x_val, y_val = stratified(x_val, y_val, max(500, smoke_n // 4))
        x_test, y_test = stratified(x_test, y_test, max(500, smoke_n // 4))
        max_epochs = min(max_epochs, 2)
        print(
            f"\nSMOKE: train={len(y_train)} val={len(y_val)} test={len(y_test)} epochs={max_epochs}"
        )

    n_pos = float((y_train == 1).sum())
    n_neg = float((y_train == 0).sum())
    pos_weight_val = n_neg / max(n_pos, 1.0)
    pos_weight = torch.tensor([pos_weight_val], dtype=torch.float32, device=device)

    model = SoftDecisionForest(in_dim=len(feature_cols), n_trees=N_TREES, depth=TREE_DEPTH).to(device)
    param_count = sum(p.numel() for p in model.parameters() if p.requires_grad)
    optimizer = torch.optim.Adam(model.parameters(), lr=LEARNING_RATE)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimizer, mode="max", factor=0.5, patience=4, min_lr=1e-5
    )

    train_loader = make_loader(x_train, y_train, batch_size, shuffle=True)
    val_loader = make_loader(x_val, y_val, batch_size, shuffle=False)
    test_loader = make_loader(x_test, y_test, batch_size, shuffle=False)

    print(
        f"\nTraining soft forest seed={seed}: trees={N_TREES}, depth={TREE_DEPTH}, "
        f"params={param_count:,}, pos_weight={pos_weight_val:.4f}, device={device}"
    )

    history: list[dict] = []
    best_pr = -1.0
    best_epoch = 0
    best_state = None
    patience = EARLY_STOP_PATIENCE
    t0 = time.perf_counter()

    for epoch in range(1, max_epochs + 1):
        validate_numerics = smoke or epoch == 1
        train_loss = train_one_epoch(
            model,
            train_loader,
            optimizer,
            pos_weight,
            device,
            validate_numerics=validate_numerics,
        )
        val_loss = eval_loss(model, val_loader, pos_weight, device)
        p_val = predict_proba(model, val_loader, device)
        val_pr = float(average_precision_score(y_val, p_val)) if y_val.sum() else float("nan")
        if np.isfinite(val_pr):
            scheduler.step(val_pr)
        history.append(
            {
                "epoch": epoch,
                "train_loss": train_loss,
                "val_loss": val_loss,
                "val_pr_auc": val_pr,
                "lr": float(optimizer.param_groups[0]["lr"]),
            }
        )
        print(
            f"  epoch {epoch:02d}: train_loss={train_loss:.6f} "
            f"val_loss={val_loss:.6f} val_pr_auc={val_pr:.6f} "
            f"lr={optimizer.param_groups[0]['lr']:.1e}"
        )
        improved = np.isfinite(val_pr) and (val_pr > best_pr + 1e-6)
        if improved:
            best_pr = val_pr
            best_epoch = epoch
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
            patience = EARLY_STOP_PATIENCE
            torch.save(
                {
                    "model_state_dict": best_state,
                    "epoch": best_epoch,
                    "val_pr_auc": best_pr,
                    "seed": seed,
                    "n_trees": N_TREES,
                    "depth": TREE_DEPTH,
                },
                run_dir / "sdf_T20_s1_checkpoint.pt",
            )
        else:
            patience -= 1
            if patience <= 0 and not smoke:
                print(f"  Early stopping at epoch {epoch} (best={best_epoch})")
                break

    train_time = time.perf_counter() - t0
    if best_state is None:
        best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
        best_epoch = max_epochs
        torch.save(
            {
                "model_state_dict": best_state,
                "epoch": best_epoch,
                "val_pr_auc": best_pr,
                "seed": seed,
            },
            run_dir / "sdf_T20_s1_checkpoint.pt",
        )

    model.load_state_dict(best_state)
    model.to(device)

    # Final numeric check on a batch
    xb, yb = next(iter(val_loader))
    model.eval()
    with torch.no_grad():
        logit, extras = model(xb.to(device))
        num_msgs = assert_numerical_validity(logit, extras, model)
    for m in num_msgs:
        print(f"  {m}")

    p_val = predict_proba(model, val_loader, device)
    thr, thr_f1 = choose_threshold(y_val, p_val)
    val_sel = metrics_at_threshold(y_val, p_val, thr)
    val_050 = metrics_at_threshold(y_val, p_val, 0.5)

    t_inf = time.perf_counter()
    p_test = predict_proba(model, test_loader, device)
    infer_time = time.perf_counter() - t_inf
    test_sel = metrics_at_threshold(y_test, p_test, thr)
    test_050 = metrics_at_threshold(y_test, p_test, 0.5)

    pd.DataFrame(history).to_csv(run_dir / "sdf_T20_s1_training_history.csv", index=False)

    config = {
        "mode": mode,
        "architecture": {
            "type": "SoftDecisionForest",
            "n_trees": N_TREES,
            "tree_depth": TREE_DEPTH,
            "internal_nodes_per_tree": (2**TREE_DEPTH) - 1,
            "leaves_per_tree": 2**TREE_DEPTH,
            "routing": "p_left=sigmoid(w^T x + b); p_right=1-p_left",
            "leaf": "learnable malicious logit; tree output = sum(path_prob * leaf_logit)",
            "forest_output": "mean of tree logits -> sigmoid",
        },
        "param_count": param_count,
        "seed": seed,
        "batch_size": batch_size,
        "learning_rate": LEARNING_RATE,
        "optimizer": "Adam",
        "loss": "BCEWithLogitsLoss",
        "pos_weight_train": pos_weight_val,
        "max_epochs": max_epochs,
        "early_stopping_patience": EARLY_STOP_PATIENCE,
        "early_stopping_metric": "validation_pr_auc",
        "grad_clip_norm": GRAD_CLIP_NORM,
        "n_features": len(feature_cols),
        "features": feature_cols,
        "device": str(device),
        "best_epoch": best_epoch,
        "best_val_pr_auc": best_pr,
        "training_time_sec": train_time,
        "test_inference_time_sec": infer_time,
        "threshold_selection_rule": (
            "Grid-search threshold on validation probabilities to maximise F1; "
            "candidates = linspace(0.01,0.99,99) union validation probability quantiles; "
            "test unused for threshold selection."
        ),
    }
    (run_dir / "sdf_T20_s1_config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    pd.Series(feature_cols, name="feature").to_csv(
        run_dir / "sdf_T20_s1_feature_list.csv", index_label="feature_index"
    )

    thr_payload = {
        "selected_threshold": thr,
        "selection_rule": config["threshold_selection_rule"],
        "validation_f1_at_selected": thr_f1,
        "validation_metrics_selected": val_sel,
        "validation_metrics_default_0_5": val_050,
        "test_not_used_for_selection": True,
    }
    (run_dir / "sdf_T20_s1_threshold.json").write_text(
        json.dumps(thr_payload, indent=2), encoding="utf-8"
    )

    # Predictions with metadata from original frame indices when not smoke
    def save_preds(split_name: str, y: np.ndarray, p: np.ndarray, path: Path, meta: pd.DataFrame | None):
        df = pd.DataFrame(
            {
                "split": split_name,
                "y_true": y.astype(np.int8),
                "y_prob": p.astype(np.float32),
                "y_pred_selected": (p >= thr).astype(np.int8),
                "y_pred_0_5": (p >= 0.5).astype(np.int8),
            }
        )
        if meta is not None and len(meta) == len(df):
            for col in ("sequence_id", "user", "start_date", "end_date"):
                if col in meta.columns:
                    df[col] = meta[col].to_numpy()
        df.to_parquet(path, index=False)

    return {
        "mode": mode,
        "seed": seed,
        "run_dir": run_dir,
        "param_count": param_count,
        "pos_weight": pos_weight_val,
        "best_epoch": best_epoch,
        "best_val_pr_auc": best_pr,
        "selected_threshold": thr,
        "train_time": train_time,
        "infer_time": infer_time,
        "test_sel": test_sel,
        "test_050": test_050,
        "val_sel": val_sel,
        "y_val": y_val,
        "p_val": p_val,
        "y_test": y_test,
        "p_test": p_test,
        "config": config,
        "save_preds": save_preds,
        "history": history,
    }


def append_docs(root: Path, out_dir: Path, result: dict, multi: list[dict] | None) -> None:
    chapter = root / "outputs" / "chapter4" / "chapter4_results_manifest.csv"
    if chapter.exists():
        man = pd.read_csv(chapter)
        man = man[man["step_number"] != 17]
        ts = result["test_sel"]
        row = {
            "step_number": 17,
            "chapter4_section": "1.5 Standalone soft decision forest baseline",
            "related_research_objective": "Objective 1 / Objective 2 preparation",
            "input_files": "data/processed/sequences/r42_T20_s1_sequence_feature_table.parquet",
            "script_used": "scripts/run_soft_decision_forest.py",
            "output_files": str(out_dir),
            "key_result": (
                f"SDF test F1={ts['f1']:.4f}, PR-AUC={ts['pr_auc']:.4f}, "
                f"R={ts['recall']:.4f}, FP={ts['fp']}, FN={ts['fn']}"
            ),
            "why_this_step_matters": (
                "Establishes standalone differentiable soft-tree performance before "
                "Bi-LSTM + soft forest integration"
            ),
            "status": "Complete",
        }
        man = pd.concat([man, pd.DataFrame([row])], ignore_index=True).sort_values("step_number")
        man.to_csv(chapter, index=False)

    notes = root / "docs" / "cert_r42_notes.md"
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    m = result["test_sel"]
    m05 = result["test_050"]
    multi_txt = ""
    if multi and len(multi) > 1:
        f1s = [r["test_sel"]["f1"] for r in multi]
        multi_txt = (
            f"\n### Multi-seed stability\n\n"
            f"- Seeds: {[r['seed'] for r in multi]}\n"
            f"- F1 mean±std: {np.mean(f1s):.4f} ± {np.std(f1s):.4f}\n"
        )
    block = f"""

## CERT r4.2 standalone soft decision forest baseline T=20/s=1 ({ts})

Differentiable soft decision forest on the verified aggregated sequence feature table (same 40 features as XGBoost). Probabilistic routing: `p_left = sigmoid(w^T x + b)`, path products to leaves, forest = mean of tree logits. Threshold selected on validation F1 only.

### Architecture / training
- Trees: {N_TREES}; depth: {TREE_DEPTH}; params: {result['param_count']:,}
- pos_weight (train): {result['pos_weight']:.4f}
- best epoch: {result['best_epoch']}; selected threshold: {result['selected_threshold']:.4f}

### Test metrics

| Model | P | R | F1 | PR-AUC | FP | FN |
|-------|---|---|----|--------|----|----|
| Soft forest @ selected | {m['precision']:.4f} | {m['recall']:.4f} | {m['f1']:.4f} | {m['pr_auc']:.4f} | {m['fp']} | {m['fn']} |
| Soft forest @ 0.50 | {m05['precision']:.4f} | {m05['recall']:.4f} | {m05['f1']:.4f} | {m05['pr_auc']:.4f} | {m05['fp']} | {m05['fn']} |
| XGBoost T=20 | 0.988 | 1.000 | 0.994 | 1.000 | 1 | 0 |
| Bi-LSTM T=20 | 0.514 | 0.893 | 0.652 | 0.879 | 71 | 9 |
{multi_txt}
### Outputs
- `{out_dir.as_posix().replace(str(root).replace(chr(92), '/') + '/', '')}/`
"""
    with notes.open("a", encoding="utf-8") as f:
        f.write(block)


def main() -> None:
    parser = argparse.ArgumentParser(description="Standalone soft decision forest baseline.")
    parser.add_argument(
        "--features",
        default="data/processed/sequences/r42_T20_s1_sequence_feature_table.parquet",
    )
    parser.add_argument("--output-dir", default="outputs/baselines/soft_decision_forest")
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    parser.add_argument("--max-epochs", type=int, default=MAX_EPOCHS)
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--smoke-n", type=int, default=4000)
    parser.add_argument("--multi-seed", action="store_true", help="Run seeds 42,52,62")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args()

    root = repo_root()
    out_dir = resolve(root, args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    print("=" * 90)
    print("CERT r4.2 standalone soft decision forest (T=20, stride=1)")
    print("=" * 90)
    print(f"Device: {device}")

    feat_path = resolve(root, args.features)
    feat = pd.read_parquet(feat_path)
    feature_cols = model_feature_columns(list(feat.columns))
    if len(feature_cols) != 40:
        raise SystemExit(f"Expected 40 features (XGBoost parity); got {len(feature_cols)}")

    input_report = verify_inputs(feat, feature_cols)
    arrays_x, arrays_y, mean, scale = prepare_arrays(feat, feature_cols)

    if args.smoke:
        result = run_training(
            arrays_x,
            arrays_y,
            feature_cols,
            out_dir,
            seed=args.seed,
            max_epochs=2,
            batch_size=min(args.batch_size, 1024),
            smoke=True,
            smoke_n=args.smoke_n,
            device=device,
        )
        assert (result["run_dir"] / "sdf_T20_s1_checkpoint.pt").exists()
        assert (result["run_dir"] / "sdf_T20_s1_training_history.csv").exists()
        print("SMOKE TEST PASSED")
        return

    seeds = SEEDS if args.multi_seed else [args.seed]
    multi_results: list[dict] = []
    primary = None

    for seed in seeds:
        seed_out = out_dir if seed == seeds[0] and len(seeds) == 1 else out_dir / f"seed_{seed}"
        if len(seeds) == 1:
            seed_out = out_dir
        result = run_training(
            arrays_x,
            arrays_y,
            feature_cols,
            seed_out,
            seed=seed,
            max_epochs=args.max_epochs,
            batch_size=args.batch_size,
            smoke=False,
            smoke_n=args.smoke_n,
            device=device,
        )
        # Save predictions with metadata for primary / each seed
        meta_val = feat.loc[feat["split"] == "validation"].reset_index(drop=True)
        meta_test = feat.loc[feat["split"] == "test"].reset_index(drop=True)
        result["save_preds"](
            "validation",
            result["y_val"],
            result["p_val"],
            result["run_dir"] / "sdf_T20_s1_val_predictions.parquet",
            meta_val,
        )
        result["save_preds"](
            "test",
            result["y_test"],
            result["p_test"],
            result["run_dir"] / "sdf_T20_s1_test_predictions.parquet",
            meta_test,
        )

        metric_rows = [
            {"model": "soft_decision_forest", "split": "validation", "threshold_rule": "selected_val_f1", **result["val_sel"]},
            {
                "model": "soft_decision_forest",
                "split": "test",
                "threshold_rule": "selected_val_f1",
                **result["test_sel"],
                "training_time_sec": result["train_time"],
                "test_inference_time_sec": result["infer_time"],
                "best_epoch": result["best_epoch"],
                "seed": seed,
            },
            {
                "model": "soft_decision_forest",
                "split": "test",
                "threshold_rule": "default_0.5",
                **result["test_050"],
                "seed": seed,
            },
        ]
        pd.DataFrame(metric_rows).to_csv(result["run_dir"] / "sdf_T20_s1_metrics.csv", index=False)
        cm_rows = [
            {
                "split_setting": "test_selected",
                "threshold": result["test_sel"]["threshold"],
                "tn": result["test_sel"]["tn"],
                "fp": result["test_sel"]["fp"],
                "fn": result["test_sel"]["fn"],
                "tp": result["test_sel"]["tp"],
                "seed": seed,
            },
            {
                "split_setting": "test_0.50",
                "threshold": 0.5,
                "tn": result["test_050"]["tn"],
                "fp": result["test_050"]["fp"],
                "fn": result["test_050"]["fn"],
                "tp": result["test_050"]["tp"],
                "seed": seed,
            },
        ]
        pd.DataFrame(cm_rows).to_csv(result["run_dir"] / "sdf_T20_s1_confusion_matrices.csv", index=False)

        multi_results.append(result)
        if primary is None:
            primary = result

    assert primary is not None
    # Promote seed 42 / first result artefacts into out_dir root if multi-seed wrote subdirs
    if len(seeds) > 1:
        # Copy primary (seed 42) key files to root out_dir for the required filenames
        import shutil

        src = primary["run_dir"]
        for name in [
            "sdf_T20_s1_checkpoint.pt",
            "sdf_T20_s1_config.json",
            "sdf_T20_s1_feature_list.csv",
            "sdf_T20_s1_training_history.csv",
            "sdf_T20_s1_threshold.json",
            "sdf_T20_s1_val_predictions.parquet",
            "sdf_T20_s1_test_predictions.parquet",
            "sdf_T20_s1_metrics.csv",
            "sdf_T20_s1_confusion_matrices.csv",
        ]:
            if (src / name).exists():
                shutil.copy2(src / name, out_dir / name)

        seed_rows = []
        for r in multi_results:
            seed_rows.append(
                {
                    "model": "soft_decision_forest",
                    "seed": r["seed"],
                    "test_precision": r["test_sel"]["precision"],
                    "test_recall": r["test_sel"]["recall"],
                    "test_f1": r["test_sel"]["f1"],
                    "test_pr_auc": r["test_sel"]["pr_auc"],
                    "test_fpr": r["test_sel"]["fpr"],
                    "test_fp": r["test_sel"]["fp"],
                    "test_fn": r["test_sel"]["fn"],
                    "selected_threshold": r["selected_threshold"],
                    "best_epoch": r["best_epoch"],
                    "training_time_sec": r["train_time"],
                }
            )
        seed_df = pd.DataFrame(seed_rows)
        seed_df.to_csv(out_dir / "sdf_T20_s1_repeated_seed_results.csv", index=False)
        summary = []
        for metric in ["precision", "recall", "f1", "pr_auc", "fpr", "fp", "fn"]:
            vals = seed_df[f"test_{metric}"].to_numpy(dtype=float)
            summary.append(
                {
                    "metric": metric,
                    "mean": float(vals.mean()),
                    "std": float(vals.std(ddof=0)),
                    "min": float(vals.min()),
                    "max": float(vals.max()),
                    "n_seeds": len(vals),
                }
            )
        pd.DataFrame(summary).to_csv(out_dir / "sdf_T20_s1_repeated_seed_summary.csv", index=False)

    m = primary["test_sel"]
    cmp_rows = [
        {"model": "xgboost_T20", **XGB_REF},
        {"model": "bilstm_T20", **BILSTM_REF},
        {
            "model": "soft_decision_forest_T20_selected",
            "precision": m["precision"],
            "recall": m["recall"],
            "f1": m["f1"],
            "pr_auc": m["pr_auc"],
            "fp": m["fp"],
            "fn": m["fn"],
        },
        {
            "model": "soft_decision_forest_T20_threshold_0.50",
            "precision": primary["test_050"]["precision"],
            "recall": primary["test_050"]["recall"],
            "f1": primary["test_050"]["f1"],
            "pr_auc": primary["test_050"]["pr_auc"],
            "fp": primary["test_050"]["fp"],
            "fn": primary["test_050"]["fn"],
        },
    ]
    pd.DataFrame(cmp_rows).to_csv(out_dir / "sdf_T20_s1_vs_baselines.csv", index=False)

    # Closeness: Euclidean distance on (f1, pr_auc) normalized roughly
    def dist(ref):
        return abs(m["f1"] - ref["f1"]) + abs(m["pr_auc"] - ref["pr_auc"])

    closer = "xgboost" if dist(XGB_REF) < dist(BILSTM_REF) else "bilstm"
    routing_stable = True  # validated by assertions during/after training
    detected = m["tp"] > 0
    # Integration is justified if the forest learns stable routing and a usable ranking
    # signal (not if it matches XGBoost). Standalone soft trees are expected to lag hard trees.
    justify = bool(routing_stable and detected and m["pr_auc"] >= 0.50 and m["recall"] >= 0.50)

    manifest = {
        "experiment": "standalone_soft_decision_forest_T20_s1",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "inputs": {"feature_table": str(feat_path)},
        "input_verification": input_report,
        "scaler": {
            "type": "train_only_zscore",
            "mean": mean.tolist(),
            "scale": scale.tolist(),
            "fitted_on_train_only": True,
        },
        "outputs_dir": str(out_dir),
        "primary_seed": primary["seed"],
        "seeds": seeds,
        "test_metrics_selected": m,
        "test_metrics_0_5": primary["test_050"],
        "comparisons": cmp_rows,
        "closer_to": closer,
        "justify_bilstm_integration": justify,
        "assertions": [
            "no leakage-prone fields in model inputs",
            "scaling fitted on train only",
            "threshold selected on validation only",
            "test unused for tuning",
            "routing/leaf/forest numerical validity checks passed",
        ],
    }
    (out_dir / "sdf_T20_s1_experiment_manifest.json").write_text(
        json.dumps(manifest, indent=2, default=str), encoding="utf-8"
    )
    # Also store scaler alongside config
    (out_dir / "sdf_T20_s1_scaler.json").write_text(
        json.dumps(manifest["scaler"], indent=2), encoding="utf-8"
    )

    append_docs(root, out_dir, primary, multi_results if len(multi_results) > 1 else None)

    print("\n" + "=" * 90)
    print("SOFT DECISION FOREST SUMMARY")
    print("=" * 90)
    print(f"Stable routing: {'YES' if routing_stable else 'NO'} (numerical assertions passed)")
    print(f"Detected malicious sequences: {'YES' if detected else 'NO'} (TP={m['tp']})")
    print(
        f"Test @ selected thr={primary['selected_threshold']:.3f}: "
        f"P={m['precision']:.4f} R={m['recall']:.4f} F1={m['f1']:.4f} "
        f"PR-AUC={m['pr_auc']:.4f} FP={m['fp']} FN={m['fn']}"
    )
    print(
        f"Test @ 0.50: P={primary['test_050']['precision']:.4f} "
        f"R={primary['test_050']['recall']:.4f} F1={primary['test_050']['f1']:.4f} "
        f"FP={primary['test_050']['fp']} FN={primary['test_050']['fn']}"
    )
    print("XGBoost : P=0.988 R=1.000 F1=0.994 PR-AUC=1.000 FP=1 FN=0")
    print("Bi-LSTM : P=0.514 R=0.893 F1=0.652 PR-AUC=0.879 FP=71 FN=9")
    print(f"Closer to: {closer}")
    if len(multi_results) > 1:
        f1s = [r["test_sel"]["f1"] for r in multi_results]
        print(f"Multi-seed F1: mean={np.mean(f1s):.4f} std={np.std(f1s):.4f}")
    print(
        f"Justify Bi-LSTM integration: {'YES' if justify else 'NO'} — "
        + (
            "stable routing and usable ranking/detection signal support hybridisation "
            "(standalone remains below XGBoost, as expected for soft trees)"
            if justify
            else "standalone forest signal is too weak to justify encoder integration yet"
        )
    )
    print(f"Outputs: {out_dir}")


if __name__ == "__main__":
    main()
