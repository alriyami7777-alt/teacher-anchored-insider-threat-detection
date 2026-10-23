"""Bounded micro-run training with gradient/routing/drift diagnostics."""

from __future__ import annotations

from typing import Any

import numpy as np
import torch
import torch.nn as nn
from sklearn.metrics import brier_score_loss, log_loss
from torch.utils.data import DataLoader, Subset

from prototype_v3_node.diagnostics import leaf_utilization_stats
from prototype_v3_node.train import choose_threshold_f1, metrics_at_threshold

from .schedules import apply_schedule, assert_frozen_have_no_grad, build_optimizer


def _component_grad_norm(params) -> float:
    sq = 0.0
    n = 0
    for p in params:
        if p.grad is None:
            continue
        g = p.grad.detach()
        sq += float(g.pow(2).sum().item())
        n += 1
    return float(np.sqrt(sq)) if n else 0.0


def collect_grad_stats(model) -> dict[str, float]:
    g_lstm = _component_grad_norm(model.lstm.parameters())
    g_attn = _component_grad_norm(model.attention.parameters())
    g_odst = _component_grad_norm(model.node_head.parameters())
    return {
        "grad_lstm_l2": g_lstm,
        "grad_attention_l2": g_attn,
        "grad_odst_l2": g_odst,
        "grad_encoder_to_odst_ratio": (g_lstm / g_odst) if g_odst > 1e-12 else float("nan"),
        "grad_attention_to_odst_ratio": (g_attn / g_odst) if g_odst > 1e-12 else float("nan"),
    }


def routing_leaf_metrics(extras: dict[str, Any]) -> dict[str, float]:
    leaf = extras.get("leaf_probs")
    if leaf is None:
        return {
            "routing_entropy_mean": float("nan"),
            "unused_leaves_pct": float("nan"),
            "unused_leaves_count": float("nan"),
            "n_leaves_total": float("nan"),
            "active_leaves": float("nan"),
        }
    stats = leaf_utilization_stats(leaf)
    # Also concentration / dominant leaf
    mean_mass = leaf.mean(dim=0)  # (T, L)
    dom_freq = float((mean_mass.argmax(dim=-1)).float().mean().item()) if mean_mass.numel() else float("nan")
    # tree output correlation if available
    tree_logits = extras.get("layer_tree_logits")
    tree_corr = float("nan")
    tree_var = float("nan")
    if tree_logits is not None and isinstance(tree_logits, (list, tuple)) and tree_logits:
        # use first layer tree logits if tensor
        t0 = tree_logits[0]
        if torch.is_tensor(t0) and t0.dim() >= 2:
            flat = t0.detach().float().reshape(t0.size(0), -1)
            tree_var = float(flat.var(unbiased=False).item())
            if flat.size(1) >= 2:
                c = torch.corrcoef(flat.T)
                # mean off-diagonal
                m = c.numel()
                tree_corr = float(((c.sum() - c.diag().sum()) / max(m - c.size(0), 1)).item())
    # sparsemax active dims from feature selection if present
    fsp = extras.get("feature_selection_probs")
    sparse_active = float("nan")
    if torch.is_tensor(fsp):
        sparse_active = float((fsp > 1e-3).float().sum(dim=-1).mean().item())
    return {
        "routing_entropy_mean": float(stats["routing_entropy_mean"]),
        "unused_leaves_pct": float(stats["unused_leaves_frac"] * 100.0),
        "unused_leaves_count": float(stats["unused_leaves_count"]),
        "n_leaves_total": float(stats["n_leaves_total"]),
        "active_leaves": float(stats["n_leaves_total"] - stats["unused_leaves_count"]),
        "dominant_leaf_frequency": dom_freq,
        "tree_output_correlation": tree_corr,
        "tree_output_variance": tree_var,
        "sparsemax_active_dim_count": sparse_active,
        "mean_routing_concentration": float(1.0 / max(stats["routing_entropy_mean"], 1e-6)),
    }


@torch.no_grad()
def evaluate_model(model, loader, device, criterion) -> dict[str, Any]:
    model.eval()
    losses = []
    logits_all = []
    y_all = []
    last_extras = None
    for xb, yb in loader:
        xb = xb.to(device)
        yb = yb.to(device)
        logits, extras = model(xb)
        loss = criterion(logits, yb)
        losses.append(float(loss.item()) * int(yb.size(0)))
        logits_all.append(logits.detach().cpu().numpy())
        y_all.append(yb.detach().cpu().numpy())
        last_extras = extras
    logits = np.concatenate(logits_all)
    y = np.concatenate(y_all).astype(int)
    probs = 1.0 / (1.0 + np.exp(-logits))
    thr, _ = choose_threshold_f1(y, probs)
    met = metrics_at_threshold(y, probs, thr)
    met.update(
        {
            "val_loss": float(sum(losses) / max(len(y), 1)),
            "brier": float(brier_score_loss(y, probs)),
            "log_loss": float(log_loss(y, np.clip(probs, 1e-7, 1 - 1e-7))),
            "pos_score_mean": float(probs[y == 1].mean()) if (y == 1).any() else float("nan"),
            "neg_score_mean": float(probs[y == 0].mean()) if (y == 0).any() else float("nan"),
        }
    )
    if last_extras is not None:
        met.update(routing_leaf_metrics(last_extras))
    met["probs"] = probs
    met["y_true"] = y
    met["logits"] = logits
    return met


def representation_drift(
    model,
    initial_state: dict[str, torch.Tensor],
    diag_loader: DataLoader,
    device: torch.device,
    initial_pooled: torch.Tensor | None,
    initial_attn: torch.Tensor | None,
) -> dict[str, float]:
    # parameter distance for encoder
    dist = 0.0
    for k, v0 in initial_state.items():
        if not (k.startswith("lstm.") or k.startswith("attention.")):
            continue
        v1 = model.state_dict()[k].detach().cpu()
        dist += float((v1 - v0.cpu()).pow(2).sum().item())
    dist = float(np.sqrt(dist))

    model.eval()
    with torch.no_grad():
        xb, _ = next(iter(diag_loader))
        xb = xb.to(device)
        h, extras = model.encode_attention_h(xb)
        attn = extras["attention_weights"]
    cos_h = float("nan")
    attn_change = float("nan")
    pooled_change = float("nan")
    if initial_pooled is not None:
        a = initial_pooled.to(device)
        cos_h = float(torch.nn.functional.cosine_similarity(h, a, dim=-1).mean().item())
        pooled_change = float((h - a).norm(dim=-1).mean().item())
    if initial_attn is not None:
        attn_change = float((attn - initial_attn.to(device)).abs().mean().item())
    return {
        "encoder_param_distance": dist,
        "pooled_cosine_similarity": cos_h,
        "attention_vector_change": attn_change,
        "pooled_representation_change": pooled_change,
    }


def train_micro_run(
    model,
    *,
    condition: str,
    train_loader: DataLoader,
    val_loader: DataLoader,
    diag_loader: DataLoader,
    device: torch.device,
    pos_weight: torch.Tensor,
    max_epochs: int = 5,
    grad_clip: float | None = None,
    initial_state: dict[str, torch.Tensor] | None = None,
) -> dict[str, Any]:
    criterion = nn.BCEWithLogitsLoss(pos_weight=pos_weight.to(device))
    had_nan = False
    grad_explosion = False
    routing_collapse = False

    # Fixed diagnostic representations at start
    model.eval()
    with torch.no_grad():
        xb0, _ = next(iter(diag_loader))
        xb0 = xb0.to(device)
        h0, ex0 = model.encode_attention_h(xb0)
        attn0 = ex0["attention_weights"].detach().cpu()
        h0_cpu = h0.detach().cpu()

    epoch_rows = []
    grad_rows = []
    routing_rows = []
    drift_rows = []
    best = {"pr_auc": -1.0, "epoch": 0, "f1": -1.0, "metrics": None}
    batch_grad_lstm = []
    batch_grad_attn = []
    batch_grad_odst = []

    for epoch in range(1, max_epochs + 1):
        flags = apply_schedule(model, condition, epoch)
        opt, lrs = build_optimizer(model, condition)
        model.train()
        # Keep dropout deterministic-ish on encoder when frozen
        if not flags["lstm"]:
            model.lstm.eval()
            model.dropout.eval()
        if not flags["attention"]:
            model.attention.eval()
        model.linear_head.eval()

        train_loss_sum = 0.0
        n_obs = 0
        for xb, yb in train_loader:
            xb = xb.to(device)
            yb = yb.to(device)
            opt.zero_grad(set_to_none=True)
            logits, extras = model(xb)
            if not torch.isfinite(logits).all():
                had_nan = True
                break
            loss = criterion(logits, yb)
            if not torch.isfinite(loss):
                had_nan = True
                break
            loss.backward()
            assert_frozen_have_no_grad(model)
            gstat = collect_grad_stats(model)
            batch_grad_lstm.append(gstat["grad_lstm_l2"])
            batch_grad_attn.append(gstat["grad_attention_l2"])
            batch_grad_odst.append(gstat["grad_odst_l2"])
            if max(gstat["grad_lstm_l2"], gstat["grad_attention_l2"], gstat["grad_odst_l2"]) > 1e3:
                grad_explosion = True
            unclipped = gstat["grad_odst_l2"]
            clipped_norm = None
            if grad_clip is not None:
                clipped_norm = float(
                    torch.nn.utils.clip_grad_norm_(
                        [p for p in model.parameters() if p.requires_grad], grad_clip
                    ).item()
                )
            opt.step()
            bs = int(yb.size(0))
            train_loss_sum += float(loss.item()) * bs
            n_obs += bs
            grad_rows.append(
                {
                    "condition": condition,
                    "epoch": epoch,
                    **gstat,
                    "grad_clip": grad_clip,
                    "grad_norm_unclipped_odst": unclipped,
                    "grad_norm_clipped": clipped_norm,
                    **flags,
                    **lrs,
                }
            )
        if had_nan:
            break

        val = evaluate_model(model, val_loader, device, criterion)
        if val.get("unused_leaves_pct", 0) >= 99.0 and val.get("routing_entropy_mean", 1) < 1e-3:
            routing_collapse = True
        train_loss = train_loss_sum / max(n_obs, 1)
        row = {
            "condition": condition,
            "epoch": epoch,
            "train_loss": train_loss,
            "validation_loss": val["val_loss"],
            "validation_pr_auc": val["pr_auc"],
            "brier": val["brier"],
            "log_loss": val["log_loss"],
            "threshold": val["threshold"],
            "precision": val["precision"],
            "recall": val["recall"],
            "f1": val["f1"],
            "fp": val["fp"],
            "fn": val["fn"],
            "pos_score_mean": val["pos_score_mean"],
            "neg_score_mean": val["neg_score_mean"],
            **{k: flags[k] for k in flags},
        }
        epoch_rows.append(row)
        routing_rows.append(
            {
                "condition": condition,
                "epoch": epoch,
                "routing_entropy_mean": val.get("routing_entropy_mean"),
                "unused_leaves_pct": val.get("unused_leaves_pct"),
                "unused_leaves_count": val.get("unused_leaves_count"),
                "active_leaves": val.get("active_leaves"),
                "dominant_leaf_frequency": val.get("dominant_leaf_frequency"),
                "tree_output_correlation": val.get("tree_output_correlation"),
                "tree_output_variance": val.get("tree_output_variance"),
                "sparsemax_active_dim_count": val.get("sparsemax_active_dim_count"),
                "mean_routing_concentration": val.get("mean_routing_concentration"),
            }
        )
        if condition in {"T1", "T2", "T3"} and initial_state is not None:
            drift = representation_drift(model, initial_state, diag_loader, device, h0_cpu, attn0)
            drift_rows.append({"condition": condition, "epoch": epoch, **drift})
        if val["pr_auc"] > best["pr_auc"]:
            best = {
                "pr_auc": val["pr_auc"],
                "epoch": epoch,
                "f1": val["f1"],
                "metrics": {k: v for k, v in val.items() if k not in {"probs", "y_true", "logits"}},
                "probs": val["probs"],
                "y_true": val["y_true"],
            }

    def _iqr(xs):
        if not xs:
            return float("nan"), float("nan"), float("nan"), float("nan"), float("nan")
        a = np.asarray(xs, dtype=np.float64)
        return (
            float(np.median(a)),
            float(np.percentile(a, 75) - np.percentile(a, 25)),
            float(a.min()),
            float(a.max()),
            float(a.mean()),
        )

    med_l, iqr_l, min_l, max_l, _ = _iqr(batch_grad_lstm)
    med_a, iqr_a, min_a, max_a, _ = _iqr(batch_grad_attn)
    med_o, iqr_o, min_o, max_o, _ = _iqr(batch_grad_odst)
    final = epoch_rows[-1] if epoch_rows else {}
    summary = {
        "condition": condition,
        "best_pr_auc": float(best["pr_auc"]),
        "best_epoch": int(best["epoch"]),
        "best_f1": float(best["f1"]),
        "final_pr_auc": float(final.get("validation_pr_auc", float("nan"))),
        "final_f1": float(final.get("f1", float("nan"))),
        "unused_leaves_pct": float((best["metrics"] or {}).get("unused_leaves_pct", float("nan"))),
        "routing_entropy_mean": float((best["metrics"] or {}).get("routing_entropy_mean", float("nan"))),
        "brier_best": float((best["metrics"] or {}).get("brier", float("nan"))),
        "fp_at_best": float((best["metrics"] or {}).get("fp", float("nan"))),
        "recall_at_best": float((best["metrics"] or {}).get("recall", float("nan"))),
        "had_nan_or_inf": had_nan,
        "gradient_explosion": grad_explosion,
        "routing_collapse": routing_collapse,
        "protected_access": False,
        "grad_lstm_median": med_l,
        "grad_lstm_iqr": iqr_l,
        "grad_attention_median": med_a,
        "grad_attention_iqr": iqr_a,
        "grad_odst_median": med_o,
        "grad_odst_iqr": iqr_o,
        "grad_lstm_min": min_l,
        "grad_lstm_max": max_l,
        "grad_attention_min": min_a,
        "grad_attention_max": max_a,
        "grad_odst_min": min_o,
        "grad_odst_max": max_o,
        "encoder_to_odst_ratio_median": (med_l / med_o) if med_o and med_o > 1e-12 else float("nan"),
        "attention_to_odst_ratio_median": (med_a / med_o) if med_o and med_o > 1e-12 else float("nan"),
        "grad_instability": float(iqr_o),
        "stable_gradients": (not grad_explosion) and (iqr_o < 50.0 if np.isfinite(iqr_o) else False),
        "epoch_rows": epoch_rows,
        "grad_rows": grad_rows,
        "routing_rows": routing_rows,
        "drift_rows": drift_rows,
        "best_probs": best.get("probs"),
        "best_y_true": best.get("y_true"),
    }
    return summary


def make_diagnostic_subset(val_dataset, size: int, seed: int) -> Subset:
    rng = np.random.default_rng(seed)
    n = len(val_dataset)
    idx = rng.choice(n, size=min(size, n), replace=False)
    idx = np.sort(idx.astype(int))
    return Subset(val_dataset, idx.tolist())
