"""Diagnostics for Prototype V3 NODE / ODST."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import torch
from sklearn.metrics import average_precision_score, f1_score


def _entropy(p: torch.Tensor, dim: int = -1, eps: float = 1e-8) -> torch.Tensor:
    p = p.clamp_min(eps)
    return -(p * p.log()).sum(dim=dim)


def _binary_entropy_np(p: np.ndarray, eps: float = 1e-8) -> float:
    p = np.clip(np.asarray(p, dtype=np.float64), eps, 1.0 - eps)
    return float(np.mean(-(p * np.log(p) + (1.0 - p) * np.log(1.0 - p))))


def head_pr_auc_f1(y_true: np.ndarray, logits: np.ndarray) -> dict[str, float]:
    y = np.asarray(y_true).astype(int)
    probs = 1.0 / (1.0 + np.exp(-np.asarray(logits, dtype=np.float64)))
    pr_auc = float(average_precision_score(y, probs)) if y.sum() > 0 else float("nan")
    candidates = np.linspace(0.01, 0.99, 99)
    best_t, best_f1 = 0.5, -1.0
    for t in candidates:
        f1 = float(f1_score(y, (probs >= t).astype(int), zero_division=0))
        if f1 > best_f1:
            best_f1 = f1
            best_t = float(t)
    return {"pr_auc": pr_auc, "f1": float(best_f1), "threshold": best_t}


def leaf_utilization_stats(leaf_probs: torch.Tensor, unused_eps: float = 1e-4) -> dict[str, Any]:
    """leaf_probs: (B, T, L) → utilisation / unused-leaf / routing entropy."""
    # Mean mass per leaf across batch: (T, L)
    mean_mass = leaf_probs.mean(dim=0)
    unused = (mean_mass < unused_eps).float()
    # Routing entropy per sample/tree then mean
    ent = _entropy(leaf_probs, dim=-1)  # (B, T)
    return {
        "leaf_utilization_mean": float(mean_mass.mean().item()),
        "leaf_utilization_max": float(mean_mass.max().item()),
        "unused_leaves_frac": float(unused.mean().item()),
        "unused_leaves_count": int(unused.sum().item()),
        "n_leaves_total": int(mean_mass.numel()),
        "routing_entropy_mean": float(ent.mean().item()),
        "routing_entropy_std": float(ent.std(unbiased=False).item())
        if ent.numel() > 1
        else 0.0,
    }


def feature_selection_stats(feature_probs: torch.Tensor) -> dict[str, Any]:
    """feature_probs: (T, D, d)."""
    # Effective support size per (T, D)
    support = (feature_probs > 1e-3).float().sum(dim=-1)
    ent = _entropy(feature_probs, dim=-1)
    return {
        "feature_selection_support_mean": float(support.mean().item()),
        "feature_selection_support_max": float(support.max().item()),
        "feature_selection_entropy_mean": float(ent.mean().item()),
        "feature_selection_max_prob_mean": float(feature_probs.max(dim=-1).values.mean().item()),
    }


def threshold_distribution_stats(thresholds: torch.Tensor) -> dict[str, Any]:
    t = thresholds.detach().float().reshape(-1)
    return {
        "threshold_mean": float(t.mean().item()),
        "threshold_std": float(t.std(unbiased=False).item()) if t.numel() > 1 else 0.0,
        "threshold_min": float(t.min().item()),
        "threshold_max": float(t.max().item()),
        "threshold_abs_mean": float(t.abs().mean().item()),
    }


def temperature_distribution_stats(temperatures: torch.Tensor) -> dict[str, Any]:
    t = temperatures.detach().float().reshape(-1)
    return {
        "temperature_mean": float(t.mean().item()),
        "temperature_std": float(t.std(unbiased=False).item()) if t.numel() > 1 else 0.0,
        "temperature_min": float(t.min().item()),
        "temperature_max": float(t.max().item()),
    }


def split_probability_stats(choice: torch.Tensor) -> dict[str, Any]:
    c = choice.detach().float()
    return {
        "split_prob_mean": float(c.mean().item()),
        "split_prob_std": float(c.std(unbiased=False).item()) if c.numel() > 1 else 0.0,
        "pct_split_below_0_01": float((c < 0.01).float().mean().item() * 100.0),
        "pct_split_above_0_99": float((c > 0.99).float().mean().item() * 100.0),
    }


@torch.no_grad()
def compute_v3_diagnostics(
    logits: torch.Tensor,
    extras: dict[str, Any],
    y_true: torch.Tensor,
    help_eps: float = 1e-6,
) -> dict[str, Any]:
    gate = extras["gate"]
    linear_logit = extras["linear_logit"]
    node_logit = extras["node_logit"]
    node_bounded = extras.get("node_bounded", torch.tanh(node_logit))
    effective = extras.get("effective_residual")
    if effective is None:
        effective = logits.new_zeros(logits.shape)

    probs = torch.sigmoid(logits)
    linear_probs = torch.sigmoid(linear_logit)
    y = y_true.float()
    y_np = y.detach().cpu().numpy()

    linear_err = (linear_probs - y).abs()
    final_err = (probs - y).abs()
    helped = (final_err < (linear_err - help_eps)).float()
    harmed = (final_err > (linear_err + help_eps)).float()

    attn = extras["attention_weights"]
    attn_entropy = _entropy(attn, dim=1)

    diag: dict[str, Any] = {
        "attention_mean_entropy": float(attn_entropy.mean().item()),
        "gate_mean": float(gate.mean().item()),
        "gate_std": float(gate.std(unbiased=False).item()) if gate.numel() > 1 else 0.0,
        "gate_min": float(gate.min().item()),
        "gate_max": float(gate.max().item()),
        "gate_entropy": _binary_entropy_np(gate.detach().cpu().numpy()),
        "alpha_scalar": float(extras.get("alpha_scalar", float("nan"))),
        "max_residual_scale": float(extras.get("max_residual_scale", float("nan"))),
        "node_logit_mean": float(node_logit.mean().item()),
        "node_logit_std": float(node_logit.std(unbiased=False).item())
        if node_logit.numel() > 1
        else 0.0,
        "node_bounded_mean": float(node_bounded.mean().item()),
        "linear_logit_mean": float(linear_logit.mean().item()),
        "final_logit_mean": float(logits.mean().item()),
        "effective_residual_mean": float(effective.mean().item()),
        "effective_residual_abs_mean": float(effective.abs().mean().item()),
        "pct_sequences_helped_by_correction": float(helped.mean().item() * 100.0),
        "pct_sequences_harmed_by_correction": float(harmed.mean().item() * 100.0),
        "node_num_layers": int(extras.get("node_num_layers", -1)),
        "node_n_trees": int(extras.get("node_n_trees", -1)),
        "node_depth": int(extras.get("node_depth", -1)),
        "fusion_variant": extras.get("fusion_variant"),
        "mechanism": extras.get("mechanism"),
    }

    fs = extras.get("feature_selection_probs")
    if torch.is_tensor(fs):
        diag.update(feature_selection_stats(fs))
    thr = extras.get("thresholds")
    if torch.is_tensor(thr):
        diag.update(threshold_distribution_stats(thr))
    temps = extras.get("temperatures")
    if torch.is_tensor(temps):
        diag.update(temperature_distribution_stats(temps))
    choice = extras.get("choice")
    if torch.is_tensor(choice):
        diag.update(split_probability_stats(choice))
    lp = extras.get("leaf_probs")
    if torch.is_tensor(lp):
        diag.update(leaf_utilization_stats(lp))

    diag["choice_function"] = extras.get("choice_function")
    diag["readout"] = extras.get("readout")
    diag["is_canonical_node"] = extras.get("is_canonical_node")

    try:
        lin_m = head_pr_auc_f1(y_np, linear_logit.detach().cpu().numpy())
        node_m = head_pr_auc_f1(y_np, node_logit.detach().cpu().numpy())
        fin_m = head_pr_auc_f1(y_np, logits.detach().cpu().numpy())
        diag["linear_head_pr_auc"] = lin_m["pr_auc"]
        diag["linear_head_f1"] = lin_m["f1"]
        diag["node_head_pr_auc"] = node_m["pr_auc"]
        diag["node_head_f1"] = node_m["f1"]
        diag["final_fused_pr_auc"] = fin_m["pr_auc"]
        diag["final_fused_f1"] = fin_m["f1"]
    except Exception as exc:  # pragma: no cover
        diag["head_metrics_error"] = str(exc)

    for k, v in diag.items():
        if isinstance(v, float) and not math.isnan(v) and not math.isfinite(v):
            raise AssertionError(f"Non-finite diagnostic: {k}={v}")
    return diag


def gradient_norm_report(model: torch.nn.Module) -> dict[str, float]:
    """L2 gradient norms by component after a backward pass."""
    buckets: dict[str, list[torch.Tensor]] = {
        "encoder": [],
        "attention": [],
        "linear_head": [],
        "node_head": [],
        "residual_scale": [],
        "gate": [],
        "other": [],
    }
    for name, param in model.named_parameters():
        if param.grad is None:
            continue
        g = param.grad.detach()
        if name.startswith("lstm."):
            buckets["encoder"].append(g)
        elif name.startswith("attention."):
            buckets["attention"].append(g)
        elif name.startswith("linear_head."):
            buckets["linear_head"].append(g)
        elif name.startswith("node_head."):
            buckets["node_head"].append(g)
        elif name.startswith("residual_scale"):
            buckets["residual_scale"].append(g)
        elif name.startswith("sample_gate."):
            buckets["gate"].append(g)
        else:
            buckets["other"].append(g)

    def _norm(tensors: list[torch.Tensor]) -> float:
        if not tensors:
            return 0.0
        flat = torch.cat([t.reshape(-1) for t in tensors])
        return float(torch.linalg.vector_norm(flat).item())

    return {f"grad_norm_{k}": _norm(v) for k, v in buckets.items()}
