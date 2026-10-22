"""Frozen-checkpoint scoring. Thresholds are never retuned on degraded inputs."""

from __future__ import annotations

from typing import Any

import numpy as np
import torch
from torch.utils.data import DataLoader

from editor012_rescue.metrics import metrics_from_logits, sigmoid
from editor012_rescue.models import student_forward
from editor013_odst_value.models import editor013_forward

from .safety import Editor017Blocked


@torch.no_grad()
def score_odst_full(model: torch.nn.Module, loader: DataLoader, device: torch.device) -> dict[str, np.ndarray]:
    model.eval()
    logits, choices, trees, leaves, zs, attn = [], [], [], [], [], []
    ys = []
    for batch in loader:
        xb = batch[0].to(device)
        yb = batch[1]
        out = student_forward(model, xb)
        logits.append(out["logit"].detach().cpu().numpy())
        choices.append(out["choices"].detach().cpu().numpy())
        trees.append(out["tree_outputs"].detach().cpu().numpy())
        leaves.append(out["leaf_probs_all"].detach().cpu().numpy())
        zs.append(out["z"].detach().cpu().numpy())
        attn.append(out["attention_weights"].detach().cpu().numpy())
        ys.append(np.asarray(yb).reshape(-1))
    return {
        "logits": np.concatenate(logits),
        "choices": np.concatenate(choices),
        "tree_outputs": np.concatenate(trees),
        "leaf_probs_all": np.concatenate(leaves),
        "z": np.concatenate(zs),
        "attention_weights": np.concatenate(attn),
        "y": np.concatenate(ys).reshape(-1),
    }


@torch.no_grad()
def score_l1_full(
    student: torch.nn.Module,
    modules: torch.nn.Module,
    loader: DataLoader,
    device: torch.device,
) -> dict[str, np.ndarray]:
    student.eval()
    modules.eval()
    logits, zs, attn = [], [], []
    ys = []
    for batch in loader:
        xb = batch[0].to(device)
        yb = batch[1]
        out = editor013_forward(student, xb, modules)
        logits.append(out["logit"].detach().cpu().numpy())
        zs.append(out["z"].detach().cpu().numpy())
        attn.append(out["attention_weights"].detach().cpu().numpy())
        ys.append(np.asarray(yb).reshape(-1))
    return {
        "logits": np.concatenate(logits),
        "z": np.concatenate(zs),
        "attention_weights": np.concatenate(attn),
        "y": np.concatenate(ys).reshape(-1),
    }


def metrics_at_frozen_threshold(
    y: np.ndarray,
    logits: np.ndarray,
    threshold: float,
) -> dict[str, Any]:
    if threshold is None:
        raise Editor017Blocked("degraded-input scoring requires a frozen clean threshold")
    met = metrics_from_logits(y, logits, threshold=float(threshold))
    return {k: v for k, v in met.items() if k not in {"probs", "pred"}}


def paired_score_stats(
    y: np.ndarray,
    clean_logits: np.ndarray,
    degraded_logits: np.ndarray,
    threshold: float,
) -> dict[str, float]:
    from scipy.stats import spearmanr

    clean_p = sigmoid(clean_logits)
    deg_p = sigmoid(degraded_logits)
    clean_pred = (clean_p >= threshold).astype(int)
    deg_pred = (deg_p >= threshold).astype(int)
    rho, _ = spearmanr(clean_p, deg_p)
    return {
        "score_spearman_vs_clean": float(rho) if np.isfinite(rho) else float("nan"),
        "prediction_flip_rate": float(np.mean(clean_pred != deg_pred)),
    }


def ols_slope(levels: np.ndarray, values: np.ndarray) -> float:
    x = np.asarray(levels, dtype=np.float64)
    y = np.asarray(values, dtype=np.float64)
    if x.size < 2 or np.unique(x).size < 2:
        return float("nan")
    return float(np.polyfit(x, y, 1)[0])
