#!/usr/bin/env python3
"""Diagnostics and safeguards for Prototype V2 residual-gated fusion."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import torch
from sklearn.metrics import average_precision_score, f1_score


def _entropy(p: torch.Tensor, dim: int = -1, eps: float = 1e-8) -> torch.Tensor:
    p = p.clamp_min(eps)
    return -(p * p.log()).sum(dim=dim)


def _safe_corr(a: np.ndarray, b: np.ndarray) -> float:
    a = np.asarray(a, dtype=np.float64).ravel()
    b = np.asarray(b, dtype=np.float64).ravel()
    if a.size < 2 or b.size < 2:
        return float("nan")
    if float(np.std(a)) < 1e-12 or float(np.std(b)) < 1e-12:
        return float("nan")
    return float(np.corrcoef(a, b)[0, 1])


def head_pr_auc_f1(
    y_true: np.ndarray,
    logits: np.ndarray,
    threshold: float | None = None,
) -> dict[str, float]:
    """PR-AUC and F1 for one head (choose F1-max threshold if none given)."""
    y = np.asarray(y_true).astype(int)
    probs = 1.0 / (1.0 + np.exp(-np.asarray(logits, dtype=np.float64)))
    pr_auc = float(average_precision_score(y, probs)) if y.sum() > 0 else float("nan")
    if threshold is None:
        candidates = np.linspace(0.01, 0.99, 99)
        best_t, best_f1 = 0.5, -1.0
        for t in candidates:
            f1 = float(f1_score(y, (probs >= t).astype(int), zero_division=0))
            if f1 > best_f1:
                best_f1 = f1
                best_t = float(t)
        threshold = best_t
        f1 = best_f1
    else:
        f1 = float(f1_score(y, (probs >= threshold).astype(int), zero_division=0))
    return {
        "pr_auc": pr_auc,
        "f1": float(f1),
        "threshold": float(threshold),
    }


@torch.no_grad()
def compute_v2_diagnostics(
    logits: torch.Tensor,
    extras: dict[str, Any],
    y_true: torch.Tensor,
    grad_norms: dict[str, float] | None = None,
    unused_leaf_threshold: float = 1e-3,
    gate_collapse_low: float = 0.05,
    gate_collapse_high: float = 0.95,
    inactive_forest_abs: float = 1e-4,
    gate_near_eps: float = 0.05,
    help_eps: float = 1e-6,
) -> dict[str, Any]:
    """Finite diagnostics for attention, routing, gates, correction, and logits."""
    attn = extras["attention_weights"]
    gate = extras["gate"]
    linear_logit = extras["linear_logit"]
    forest_logit = extras["forest_logit"]
    forest_correction = extras["forest_correction"]
    final_logit = extras.get("final_logit", logits)
    probs = torch.sigmoid(logits)
    linear_probs = torch.sigmoid(linear_logit)
    y = y_true.float()

    attn_entropy = _entropy(attn, dim=1)
    gate_np = gate.detach().cpu().numpy()
    corr_np = forest_correction.detach().cpu().numpy()
    y_np = y.detach().cpu().numpy()

    # Helped / harmed vs linear-only probabilities.
    linear_err = (linear_probs - y).abs()
    final_err = (probs - y).abs()
    helped = (final_err < (linear_err - help_eps)).float()
    harmed = (final_err > (linear_err + help_eps)).float()

    gate_mal = gate[y > 0.5]
    gate_ben = gate[y <= 0.5]

    n_leaves_total = 0
    unused_total = 0
    routing_entropies: list[float] = []
    leaf_utils: list[float] = []
    routing = extras.get("routing") or []
    for i, route in enumerate(routing):
        leaf = route["leaf_probs"]
        util = leaf.mean(dim=0)
        ent = _entropy(leaf, dim=1).mean()
        unused = int((util < unused_leaf_threshold).sum().item())
        n_leaves = int(util.numel())
        n_leaves_total += n_leaves
        unused_total += unused
        routing_entropies.append(float(ent.item()))
        leaf_utils.append(float(util.mean().item()))

    diag: dict[str, Any] = {
        "attention_mean_entropy": float(attn_entropy.mean().item()),
        "attention_mean_max_weight": float(attn.max(dim=1).values.mean().item()),
        "attention_entropy": float(attn_entropy.mean().item()),
        "logit_mean": float(logits.mean().item()),
        "logit_std": float(logits.std(unbiased=False).item()) if logits.numel() > 1 else 0.0,
        "linear_logit_mean": float(linear_logit.mean().item()),
        "forest_logit_mean": float(forest_logit.mean().item()),
        "forest_correction_mean": float(forest_correction.mean().item()),
        "forest_correction_abs_mean": float(forest_correction.abs().mean().item()),
        "forest_correction_magnitude": float(forest_correction.abs().mean().item()),
        "gate_mean": float(gate.mean().item()),
        "gate_std": float(gate.std(unbiased=False).item()) if gate.numel() > 1 else 0.0,
        "gate_min": float(gate.min().item()),
        "gate_max": float(gate.max().item()),
        "gate_mean_malicious": float(gate_mal.mean().item()) if gate_mal.numel() else float("nan"),
        "gate_mean_benign": float(gate_ben.mean().item()) if gate_ben.numel() else float("nan"),
        "gate_std_malicious": float(gate_mal.std(unbiased=False).item())
        if gate_mal.numel() > 1
        else (0.0 if gate_mal.numel() == 1 else float("nan")),
        "gate_std_benign": float(gate_ben.std(unbiased=False).item())
        if gate_ben.numel() > 1
        else (0.0 if gate_ben.numel() == 1 else float("nan")),
        "pct_gates_near_0": float((gate < gate_near_eps).float().mean().item() * 100.0),
        "pct_gates_near_1": float((gate > (1.0 - gate_near_eps)).float().mean().item() * 100.0),
        "corr_gate_vs_correction": _safe_corr(gate_np, corr_np),
        "corr_gate_vs_abs_correction": _safe_corr(gate_np, np.abs(corr_np)),
        "pct_sequences_helped_by_correction": float(helped.mean().item() * 100.0),
        "pct_sequences_harmed_by_correction": float(harmed.mean().item() * 100.0),
        "mean_prob_positive": float(probs[y > 0.5].mean().item())
        if (y > 0.5).any()
        else float("nan"),
        "mean_prob_negative": float(probs[y <= 0.5].mean().item())
        if (y <= 0.5).any()
        else float("nan"),
        "fusion_variant": extras.get("fusion_variant"),
        "routing_entropy": (
            float(sum(routing_entropies) / len(routing_entropies))
            if routing_entropies
            else float("nan")
        ),
        "mean_routing_entropy": (
            float(sum(routing_entropies) / len(routing_entropies))
            if routing_entropies
            else float("nan")
        ),
        "leaf_utilisation_mean": (
            float(sum(leaf_utils) / len(leaf_utils)) if leaf_utils else float("nan")
        ),
        "n_unused_leaves_total": unused_total,
        "n_leaves_total": n_leaves_total,
        "unused_leaf_percentage": (
            float(100.0 * unused_total / n_leaves_total) if n_leaves_total else float("nan")
        ),
        "n_trees_reported": len(routing),
    }

    pos_mean = attn.mean(dim=0)
    for t in range(attn.size(1)):
        diag[f"attention_pos{t:02d}_mean"] = float(pos_mean[t].item())

    for i, route in enumerate(routing):
        leaf = route["leaf_probs"]
        util = leaf.mean(dim=0)
        ent = _entropy(leaf, dim=1).mean()
        unused = int((util < unused_leaf_threshold).sum().item())
        diag[f"tree{i}_routing_entropy"] = float(ent.item())
        diag[f"tree{i}_mean_leaf_utilisation"] = float(util.mean().item())
        diag[f"tree{i}_unused_leaves"] = unused

    # Head-level PR-AUC / F1 (validation diagnostics).
    try:
        lin_m = head_pr_auc_f1(y_np, linear_logit.detach().cpu().numpy())
        for_m = head_pr_auc_f1(y_np, forest_logit.detach().cpu().numpy())
        fin_m = head_pr_auc_f1(y_np, final_logit.detach().cpu().numpy())
        diag["linear_head_pr_auc"] = lin_m["pr_auc"]
        diag["linear_head_f1"] = lin_m["f1"]
        diag["forest_head_pr_auc"] = for_m["pr_auc"]
        diag["forest_head_f1"] = for_m["f1"]
        diag["final_fused_pr_auc"] = fin_m["pr_auc"]
        diag["final_fused_f1"] = fin_m["f1"]
    except Exception as exc:  # pragma: no cover - defensive
        diag["head_metrics_error"] = str(exc)

    safeguards = evaluate_gate_safeguards(
        gate=gate,
        forest_correction=forest_correction,
        unused_leaves_total=unused_total,
        n_leaves_total=n_leaves_total,
        gate_collapse_low=gate_collapse_low,
        gate_collapse_high=gate_collapse_high,
        inactive_forest_abs=inactive_forest_abs,
    )
    diag.update(safeguards)

    if grad_norms:
        diag.update(grad_norms)
        nonfinite_grads = [
            k for k, v in grad_norms.items() if isinstance(v, float) and not math.isfinite(v)
        ]
        diag["nonfinite_grad_norms"] = nonfinite_grads
        diag["flag_nonfinite_gradients"] = bool(nonfinite_grads)

    if not torch.isfinite(logits).all():
        diag["flag_nonfinite_loss_or_logits"] = True
    else:
        diag["flag_nonfinite_loss_or_logits"] = False

    for k, v in diag.items():
        if isinstance(v, float):
            if math.isnan(v):
                continue
            if not math.isfinite(v):
                raise AssertionError(f"Non-finite diagnostic: {k}={v}")
    return diag


def evaluate_gate_safeguards(
    gate: torch.Tensor,
    forest_correction: torch.Tensor,
    unused_leaves_total: int,
    n_leaves_total: int = 0,
    gate_collapse_low: float = 0.05,
    gate_collapse_high: float = 0.95,
    inactive_forest_abs: float = 1e-4,
    nearly_all_frac: float = 0.95,
) -> dict[str, Any]:
    """Flags for gate collapse, inactive forest correction, unused leaves."""
    g_mean = float(gate.mean().item())
    g_std = float(gate.std(unbiased=False).item()) if gate.numel() > 1 else 0.0
    corr_abs = float(forest_correction.abs().mean().item())
    frac_low = float((gate < gate_collapse_low).float().mean().item())
    frac_high = float((gate > gate_collapse_high).float().mean().item())

    collapse_low = frac_low >= nearly_all_frac or (g_mean < gate_collapse_low and g_std < 0.02)
    collapse_high = frac_high >= nearly_all_frac or (
        g_mean > gate_collapse_high and g_std < 0.02
    )
    inactive_forest = corr_abs < inactive_forest_abs
    unused_pct = (
        float(100.0 * unused_leaves_total / n_leaves_total) if n_leaves_total else float("nan")
    )

    return {
        "flag_gate_collapse_low": bool(collapse_low),
        "flag_gate_collapse_high": bool(collapse_high),
        "flag_gate_collapse": bool(collapse_low or collapse_high),
        "flag_inactive_forest_correction": bool(inactive_forest),
        "flag_unused_leaves": bool(unused_leaves_total > 0),
        "frac_gates_below_low": frac_low,
        "frac_gates_above_high": frac_high,
        "unused_leaf_percentage": unused_pct,
        "safeguard_gate_collapse_low_thresh": gate_collapse_low,
        "safeguard_gate_collapse_high_thresh": gate_collapse_high,
        "safeguard_inactive_forest_abs": inactive_forest_abs,
    }


def threshold_stability(
    thresholds: list[float],
    max_range: float = 0.25,
) -> dict[str, Any]:
    """Detect unstable validation thresholds across seeds / epochs."""
    if not thresholds:
        return {
            "threshold_n": 0,
            "threshold_min": float("nan"),
            "threshold_max": float("nan"),
            "threshold_range": float("nan"),
            "flag_threshold_instability": False,
        }
    tmin = float(min(thresholds))
    tmax = float(max(thresholds))
    trange = tmax - tmin
    return {
        "threshold_n": len(thresholds),
        "threshold_min": tmin,
        "threshold_max": tmax,
        "threshold_range": trange,
        "flag_threshold_instability": bool(trange > max_range),
        "threshold_stability_max_range": max_range,
    }
