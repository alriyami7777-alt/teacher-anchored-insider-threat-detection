"""Training / evaluation helpers for Prototype V3 NODE (validation-only)."""

from __future__ import annotations

import random
from typing import Any

import numpy as np
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
from torch.utils.data import DataLoader

from .architecture import AttentionNodeEnsemble
from .diagnostics import compute_v3_diagnostics, gradient_norm_report
from .losses import v3_total_loss

GRAD_CLIP_NORM = 1.0


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
    return {
        "threshold": float(threshold),
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "f1": float(f1_score(y_true, y_pred, zero_division=0)),
        "pr_auc": float(average_precision_score(y_true, probs)),
        "roc_auc": float(roc_auc_score(y_true, probs)),
        "tn": int(tn),
        "fp": int(fp),
        "fn": int(fn),
        "tp": int(tp),
    }


def rebuild_optimizer_frozen(
    model: AttentionNodeEnsemble,
    lr: float,
) -> tuple[torch.optim.Optimizer, dict[str, float]]:
    groups = model.trainable_parameter_groups()
    params: list[nn.Parameter] = []
    lrs: dict[str, float] = {}
    for name, plist in groups.items():
        if not plist:
            continue
        params.extend(plist)
        lrs[f"lr_{name}"] = float(lr)
    if not params:
        raise RuntimeError("No trainable parameters for frozen V3 NODE optimizer")
    return torch.optim.Adam(params, lr=lr), lrs


def train_one_epoch(
    model: AttentionNodeEnsemble,
    loader: DataLoader,
    optimizer: torch.optim.Optimizer,
    criterion: nn.Module,
    device: torch.device,
    *,
    node_aux_weight: float = 0.0,
    linear_aux_weight: float = 0.0,
    residual_penalty_weight: float = 1e-3,
    anti_collapse_weight: float = 1e-3,
) -> tuple[float, dict[str, float]]:
    model.train()
    # Keep dropout inactive on frozen backbone features.
    model.lstm.eval()
    model.attention.eval()
    model.linear_head.eval()
    model.dropout.eval()

    total = 0.0
    n = 0
    last_parts: dict[str, float] = {}
    last_grad_report: dict[str, float] = {}
    for xb, yb in loader:
        xb = xb.to(device)
        yb = yb.to(device)
        optimizer.zero_grad(set_to_none=True)
        logits, extras = model(xb)
        if not torch.isfinite(logits).all():
            raise RuntimeError("Non-finite logits during V3 NODE training")
        loss, parts = v3_total_loss(
            logits,
            yb,
            extras,
            criterion,
            node_aux_weight=node_aux_weight,
            linear_aux_weight=linear_aux_weight,
            residual_penalty_weight=residual_penalty_weight,
            anti_collapse_weight=anti_collapse_weight,
        )
        if not torch.isfinite(loss):
            raise RuntimeError(f"Non-finite loss detected: {float(loss.detach())}")
        loss.backward()
        for name, param in model.named_parameters():
            if not param.requires_grad and param.grad is not None:
                raise RuntimeError(f"Unexpected gradient on frozen parameter {name}")
        last_grad_report = gradient_norm_report(model)
        torch.nn.utils.clip_grad_norm_(
            [p for p in model.parameters() if p.requires_grad], GRAD_CLIP_NORM
        )
        optimizer.step()
        bs = int(yb.size(0))
        total += float(loss.detach().item()) * bs
        n += bs
        last_parts = parts
    last_parts.update(last_grad_report)
    return total / max(n, 1), last_parts


@torch.no_grad()
def predict_with_extras(
    model: AttentionNodeEnsemble,
    loader: DataLoader,
    device: torch.device,
) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    model.eval()
    probs: list[np.ndarray] = []
    bags: dict[str, list[np.ndarray]] = {
        "gate": [],
        "linear_logit": [],
        "node_logit": [],
        "node_bounded": [],
        "effective_residual": [],
        "final_logit": [],
        "alpha": [],
    }
    for xb, _ in loader:
        logits, extras = model(xb.to(device))
        probs.append(torch.sigmoid(logits).cpu().numpy())
        bags["gate"].append(extras["gate"].detach().cpu().numpy())
        bags["linear_logit"].append(extras["linear_logit"].detach().cpu().numpy())
        bags["node_logit"].append(extras["node_logit"].detach().cpu().numpy())
        bags["node_bounded"].append(extras["node_bounded"].detach().cpu().numpy())
        bags["effective_residual"].append(
            extras["effective_residual"].detach().cpu().numpy()
        )
        bags["final_logit"].append(extras["final_logit"].detach().cpu().numpy())
        alpha = extras["alpha"]
        if alpha.ndim == 0:
            alpha = alpha.expand_as(logits)
        bags["alpha"].append(alpha.detach().cpu().numpy())
    return np.concatenate(probs, axis=0), {k: np.concatenate(v, axis=0) for k, v in bags.items()}


@torch.no_grad()
def evaluate_loader_diagnostics(
    model: AttentionNodeEnsemble,
    loader: DataLoader,
    y_true: np.ndarray,
    device: torch.device,
    fixed_threshold: float | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    model.eval()
    all_logits: list[torch.Tensor] = []
    # Aggregate ODST diagnostics over full loader (first layer leaf/feature stats).
    leaf_bags: list[torch.Tensor] = []
    feature_sel: torch.Tensor | None = None
    thresholds: torch.Tensor | None = None
    last_extras: dict[str, Any] | None = None

    for xb, _ in loader:
        logits, extras = model(xb.to(device))
        all_logits.append(logits.detach().cpu())
        last_extras = {
            k: (v.detach().cpu() if torch.is_tensor(v) else v) for k, v in extras.items()
        }
        if torch.is_tensor(extras.get("leaf_probs")):
            leaf_bags.append(extras["leaf_probs"].detach().cpu())
        if feature_sel is None and torch.is_tensor(extras.get("feature_selection_probs")):
            feature_sel = extras["feature_selection_probs"].detach().cpu()
        if thresholds is None and torch.is_tensor(extras.get("thresholds")):
            thresholds = extras["thresholds"].detach().cpu()

    logits_cat = torch.cat(all_logits, dim=0)
    assert last_extras is not None
    probs, parts = predict_with_extras(model, loader, device)
    for key in (
        "gate",
        "linear_logit",
        "node_logit",
        "node_bounded",
        "effective_residual",
        "final_logit",
        "alpha",
    ):
        last_extras[key] = torch.from_numpy(parts[key])
    if leaf_bags:
        last_extras["leaf_probs"] = torch.cat(leaf_bags, dim=0)
    if feature_sel is not None:
        last_extras["feature_selection_probs"] = feature_sel
    if thresholds is not None:
        last_extras["thresholds"] = thresholds

    diag = compute_v3_diagnostics(
        logits_cat,
        last_extras,
        torch.from_numpy(y_true.astype(np.float32)),
    )
    if fixed_threshold is None:
        thr, _ = choose_threshold_f1(y_true, probs)
    else:
        thr = float(fixed_threshold)
    metrics = metrics_at_threshold(y_true, probs, thr)
    for k in (
        "linear_head_pr_auc",
        "linear_head_f1",
        "node_head_pr_auc",
        "node_head_f1",
        "final_fused_pr_auc",
        "final_fused_f1",
    ):
        metrics[k] = diag.get(k)
    return metrics, diag
