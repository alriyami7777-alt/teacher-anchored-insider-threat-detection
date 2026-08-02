"""Training, parity, and evaluation for teacher-anchored ODST."""

from __future__ import annotations

from typing import Any

import numpy as np
import torch
import torch.nn as nn
from scipy.stats import pearsonr, spearmanr
from torch.utils.data import DataLoader

from prototype_v3_node.architecture import AttentionNodeEnsemble
from prototype_v3_node.diagnostics import leaf_utilization_stats
from prototype_v3_node.train import choose_threshold_f1, metrics_at_threshold

from .config import (
    GRAD_CLIP_NORM,
    LOGIT_CONSISTENCY_WEIGHT,
    LR_ATTENTION,
    LR_ENCODER,
    LR_ODST,
    MAX_EPOCHS,
    PARITY_ATOL,
    PARITY_RTOL,
    PATIENCE,
    ROUTE_CONSISTENCY_WEIGHT,
)
from .models import (
    assert_teacher_not_in_optimizer,
    build_student_optimizer,
    enable_all_student_components,
    logit_consistency_loss,
    route_consistency_loss,
    student_forward_with_routing,
    teacher_forward_with_routing,
    total_loss,
)


def _corr(a: np.ndarray, b: np.ndarray, kind: str = "pearson") -> float:
    try:
        fn = pearsonr if kind == "pearson" else spearmanr
        r = fn(a, b)
        return float(getattr(r, "statistic", r[0]))
    except Exception:
        return float("nan")


def _grad_l2(params) -> float:
    sq = 0.0
    n = 0
    for p in params:
        if p.grad is None:
            continue
        sq += float(p.grad.detach().pow(2).sum().item())
        n += 1
    return float(np.sqrt(sq)) if n else 0.0


def _iqr_stats(xs: list[float]) -> dict[str, float]:
    if not xs:
        return {"median": float("nan"), "iqr": float("nan"), "min": float("nan"), "max": float("nan")}
    a = np.asarray(xs, dtype=np.float64)
    return {
        "median": float(np.median(a)),
        "iqr": float(np.percentile(a, 75) - np.percentile(a, 25)),
        "min": float(a.min()),
        "max": float(a.max()),
    }


def _param_dist(a: dict[str, torch.Tensor], b: dict[str, torch.Tensor], prefix: str) -> float:
    d = 0.0
    for k, v0 in a.items():
        if k.startswith(prefix):
            d += float((b[k].cpu() - v0.cpu()).pow(2).sum().item())
    return float(np.sqrt(d))


@torch.no_grad()
def parity_check(
    teacher: AttentionNodeEnsemble,
    student: AttentionNodeEnsemble,
    loader: DataLoader,
    device: torch.device,
    indices: list[int],
) -> dict[str, Any]:
    teacher.eval()
    student.eval()
    t_z, s_z, t_l, s_l, t_c, s_c, t_leaf, s_leaf = [], [], [], [], [], [], [], []
    for xb, _ in loader:
        xb = xb.to(device)
        tr = teacher_forward_with_routing(teacher, xb)
        sr = student_forward_with_routing(student, xb)
        t_z.append(tr["z"].cpu())
        s_z.append(sr["z"].cpu())
        t_l.append(tr["logit"].cpu())
        s_l.append(sr["logit"].cpu())
        t_c.append(tr["choices"].cpu())
        s_c.append(sr["choices"].cpu())
        t_leaf.append(tr["leaf_probs"].cpu())
        s_leaf.append(sr["leaf_probs"].cpu())
    tz = torch.cat(t_z)
    sz = torch.cat(s_z)
    tl = torch.cat(t_l)
    sl = torch.cat(s_l)
    tc = torch.cat(t_c)
    sc = torch.cat(s_c)
    tlp = torch.cat(t_leaf)
    slp = torch.cat(s_leaf)
    tp = torch.sigmoid(tl)
    sp = torch.sigmoid(sl)
    thr = 0.5
    t_pred = (tp >= thr).int()
    s_pred = (sp >= thr).int()
    z_ok = bool(torch.allclose(tz, sz, atol=PARITY_ATOL, rtol=PARITY_RTOL))
    logit_ok = bool(torch.allclose(tl, sl, atol=PARITY_ATOL, rtol=PARITY_RTOL))
    prob_ok = bool(torch.allclose(tp, sp, atol=PARITY_ATOL, rtol=PARITY_RTOL))
    route_ok = bool(torch.allclose(tc, sc, atol=PARITY_ATOL, rtol=PARITY_RTOL))
    leaf_ok = bool(torch.allclose(tlp, slp, atol=PARITY_ATOL, rtol=PARITY_RTOL))
    pred_ok = bool(torch.equal(t_pred, s_pred))
    return {
        "z_match": z_ok,
        "logits_match": logit_ok,
        "probs_match": prob_ok,
        "routes_match": route_ok,
        "leaf_probs_match": leaf_ok,
        "predictions_match": pred_ok,
        "max_abs_z_diff": float((tz - sz).abs().max().item()),
        "max_abs_logit_diff": float((tl - sl).abs().max().item()),
        "max_abs_prob_diff": float((tp - sp).abs().max().item()),
        "max_abs_route_diff": float((tc - sc).abs().max().item()),
        "parity_atol": PARITY_ATOL,
        "parity_rtol": PARITY_RTOL,
        "n_samples": int(tl.numel()),
        "parity_indices": indices,
        "initial_parity_ok": bool(z_ok and logit_ok and prob_ok and route_ok and leaf_ok and pred_ok),
    }


@torch.no_grad()
def evaluate_pair(
    teacher: AttentionNodeEnsemble,
    student: AttentionNodeEnsemble,
    loader: DataLoader,
    y_true: np.ndarray,
    device: torch.device,
    criterion: nn.Module,
) -> dict[str, Any]:
    teacher.eval()
    student.eval()
    s_logits, t_logits = [], []
    s_leaves, t_leaves = [], []
    s_choices, t_choices = [], []
    s_z, t_z = [], []
    losses = []
    n = 0
    last_attn = None
    for xb, yb in loader:
        xb = xb.to(device)
        yb = yb.to(device)
        tr = teacher_forward_with_routing(teacher, xb)
        sr = student_forward_with_routing(student, xb)
        loss = criterion(sr["logit"], yb)
        losses.append(float(loss.item()) * int(yb.size(0)))
        n += int(yb.size(0))
        s_logits.append(sr["logit"].cpu().numpy())
        t_logits.append(tr["logit"].cpu().numpy())
        s_leaves.append(sr["leaf_probs"].cpu())
        t_leaves.append(tr["leaf_probs"].cpu())
        s_choices.append(sr["choices"].cpu())
        t_choices.append(tr["choices"].cpu())
        s_z.append(sr["z"].cpu())
        t_z.append(tr["z"].cpu())
        last_attn = sr["attention_weights"].cpu()
    sl = np.concatenate(s_logits)
    tl = np.concatenate(t_logits)
    sp = 1.0 / (1.0 + np.exp(-sl))
    tp = 1.0 / (1.0 + np.exp(-tl))
    y = np.asarray(y_true).astype(int)
    thr_s, _ = choose_threshold_f1(y, sp)
    thr_t, _ = choose_threshold_f1(y, tp)
    met_s = metrics_at_threshold(y, sp, thr_s)
    met_t = metrics_at_threshold(y, tp, thr_t)
    s_leaf = torch.cat(s_leaves)
    t_leaf = torch.cat(t_leaves)
    s_stats = leaf_utilization_stats(s_leaf)
    t_stats = leaf_utilization_stats(t_leaf)
    sc = torch.cat(s_choices)
    tc = torch.cat(t_choices)
    route_div = float(
        (
            tc * torch.log((tc + 1e-6) / (sc + 1e-6))
            + (1 - tc) * torch.log((1 - tc + 1e-6) / (1 - sc + 1e-6))
        )
        .mean()
        .item()
    )
    sz = torch.cat(s_z)
    tz = torch.cat(t_z)
    cos = float(torch.nn.functional.cosine_similarity(sz, tz, dim=-1).mean().item())
    pred_s = (sp >= thr_s).astype(int)
    pred_t = (tp >= thr_t).astype(int)
    # Agreement at student's threshold for change analysis vs teacher scores at same thr
    pred_t_at_s = (tp >= thr_s).astype(int)
    changed = pred_s != pred_t_at_s
    pos = y == 1
    neg = y == 0
    attn_ent = float("nan")
    if last_attn is not None:
        p = last_attn.clamp_min(1e-8)
        attn_ent = float((-(p * p.log()).sum(dim=-1)).mean().item())
    return {
        "student": {
            **met_s,
            "val_loss": float(sum(losses) / max(n, 1)),
            "routing_entropy_mean": float(s_stats["routing_entropy_mean"]),
            "unused_leaves_pct": float(s_stats["unused_leaves_frac"] * 100.0),
            "active_leaves": int(s_stats["n_leaves_total"] - s_stats["unused_leaves_count"]),
            "logits": sl,
            "probs": sp,
        },
        "teacher": {
            **met_t,
            "routing_entropy_mean": float(t_stats["routing_entropy_mean"]),
            "unused_leaves_pct": float(t_stats["unused_leaves_frac"] * 100.0),
            "active_leaves": int(t_stats["n_leaves_total"] - t_stats["unused_leaves_count"]),
            "logits": tl,
            "probs": tp,
        },
        "pooled_cosine_similarity": cos,
        "routing_divergence": route_div,
        "pearson_logits": _corr(sl, tl, "pearson"),
        "spearman_logits": _corr(sl, tl, "spearman"),
        "student_logit_mean_abs": float(np.abs(sl).mean()),
        "teacher_logit_mean_abs": float(np.abs(tl).mean()),
        "pct_predictions_changed": float(changed.mean() * 100.0),
        "pct_predictions_changed_positive": float(changed[pos].mean() * 100.0) if pos.any() else float("nan"),
        "pct_predictions_changed_negative": float(changed[neg].mean() * 100.0) if neg.any() else float("nan"),
        "prediction_agreement": float((pred_s == pred_t_at_s).mean()),
        "attention_entropy": attn_ent,
        "y_true": y,
        "student_threshold": thr_s,
        "teacher_threshold": thr_t,
    }


def train_teacher_anchored(
    *,
    teacher: AttentionNodeEnsemble,
    student: AttentionNodeEnsemble,
    train_loader: DataLoader,
    val_loader: DataLoader,
    diag_loader: DataLoader,
    y_val: np.ndarray,
    device: torch.device,
    pos_weight: torch.Tensor,
    seed: int,
    teacher_initial_state: dict[str, torch.Tensor],
    student_initial_state: dict[str, torch.Tensor],
) -> dict[str, Any]:
    criterion = nn.BCEWithLogitsLoss(pos_weight=pos_weight.to(device))
    enable_all_student_components(student)
    assert all(not p.requires_grad for p in teacher.parameters())
    opt, used_lrs = build_student_optimizer(
        student, {"lr_encoder": LR_ENCODER, "lr_attention": LR_ATTENTION, "lr_odst": LR_ODST}
    )
    assert_teacher_not_in_optimizer(teacher, opt)

    epoch_rows, loss_rows, grad_rows, param_rows, routing_rows = [], [], [], [], []
    best_pr = -1.0
    best_epoch = 0
    best_metrics = None
    best_state = None
    final_state = None
    patience_left = PATIENCE
    had_nan = False
    grad_explosion = False
    encoder_updated = attention_updated = odst_updated = False
    nonzero = {"lstm": False, "attention": False, "odst": False}
    teacher_unchanged = True

    for epoch in range(1, MAX_EPOCHS + 1):
        enable_all_student_components(student)
        student.train()
        teacher.eval()
        opt.zero_grad(set_to_none=True)

        train_tot = train_cls = train_logit = train_route = 0.0
        n_obs = 0
        batch_g = {"lstm": [], "attention": [], "odst": []}

        for xb, yb in train_loader:
            xb = xb.to(device)
            yb = yb.to(device)
            opt.zero_grad(set_to_none=True)
            with torch.no_grad():
                tr = teacher_forward_with_routing(teacher, xb)
            sr = student_forward_with_routing(student, xb)
            if not torch.isfinite(sr["logit"]).all():
                had_nan = True
                break
            l_class = criterion(sr["logit"], yb)
            l_logit = logit_consistency_loss(sr["logit"], tr["logit"])
            l_route = route_consistency_loss(sr["choices"], tr["choices"])
            loss = total_loss(
                class_loss=l_class,
                logit_loss=l_logit,
                route_loss=l_route,
                w_logit=LOGIT_CONSISTENCY_WEIGHT,
                w_route=ROUTE_CONSISTENCY_WEIGHT,
            )
            if not torch.isfinite(loss):
                had_nan = True
                break
            loss.backward()
            for p in teacher.parameters():
                if p.grad is not None:
                    raise RuntimeError("Teacher received gradients")
            g_l = _grad_l2(student.lstm.parameters())
            g_a = _grad_l2(student.attention.parameters())
            g_o = _grad_l2(student.node_head.parameters())
            batch_g["lstm"].append(g_l)
            batch_g["attention"].append(g_a)
            batch_g["odst"].append(g_o)
            if max(g_l, g_a, g_o) > 1e3:
                grad_explosion = True
            if g_l > 0:
                nonzero["lstm"] = True
            if g_a > 0:
                nonzero["attention"] = True
            if g_o > 0:
                nonzero["odst"] = True
            torch.nn.utils.clip_grad_norm_([p for p in student.parameters() if p.requires_grad], GRAD_CLIP_NORM)
            opt.step()
            bs = int(yb.size(0))
            train_tot += float(loss.item()) * bs
            train_cls += float(l_class.item()) * bs
            train_logit += float(l_logit.item()) * bs
            train_route += float(l_route.item()) * bs
            n_obs += bs
        if had_nan:
            break

        # teacher integrity
        if _param_dist(teacher_initial_state, teacher.state_dict(), "") > 1e-12:
            teacher_unchanged = False
            raise RuntimeError("Teacher parameters changed during training")

        cur = student.state_dict()
        if _param_dist(student_initial_state, cur, "lstm.") > 1e-12:
            encoder_updated = True
        if _param_dist(student_initial_state, cur, "attention.") > 1e-12:
            attention_updated = True
        if _param_dist(student_initial_state, cur, "node_head.") > 1e-12:
            odst_updated = True

        val = evaluate_pair(teacher, student, val_loader, y_val, device, criterion)
        s = val["student"]
        t = val["teacher"]
        g_l = _iqr_stats(batch_g["lstm"])
        g_a = _iqr_stats(batch_g["attention"])
        g_o = _iqr_stats(batch_g["odst"])
        enc_ratio = g_l["median"] / g_o["median"] if g_o["median"] and g_o["median"] > 1e-12 else float("nan")

        row = {
            "seed": seed,
            "epoch": epoch,
            "joint": True,
            "train_total_loss": train_tot / max(n_obs, 1),
            "train_class_loss": train_cls / max(n_obs, 1),
            "train_logit_consistency_loss": train_logit / max(n_obs, 1),
            "train_route_consistency_loss": train_route / max(n_obs, 1),
            "validation_loss": s["val_loss"],
            "validation_pr_auc": s["pr_auc"],
            "validation_precision": s["precision"],
            "validation_recall": s["recall"],
            "validation_f1": s["f1"],
            "validation_fp": s["fp"],
            "validation_fn": s["fn"],
            "validation_threshold": s["threshold"],
            "teacher_val_pr_auc": t["pr_auc"],
            "attention_entropy": val["attention_entropy"],
            "student_routing_entropy": s["routing_entropy_mean"],
            "teacher_routing_entropy": t["routing_entropy_mean"],
            "routing_divergence": val["routing_divergence"],
            "student_unused_leaves_pct": s["unused_leaves_pct"],
            "teacher_unused_leaves_pct": t["unused_leaves_pct"],
            "student_active_leaves": s["active_leaves"],
            "teacher_active_leaves": t["active_leaves"],
            "pooled_cosine_similarity": val["pooled_cosine_similarity"],
            "pearson_teacher_student_logits": val["pearson_logits"],
            "spearman_teacher_student_logits": val["spearman_logits"],
            "student_logit_mean_abs": val["student_logit_mean_abs"],
            "teacher_logit_mean_abs": val["teacher_logit_mean_abs"],
            "pct_predictions_changed": val["pct_predictions_changed"],
            "pct_predictions_changed_positive": val["pct_predictions_changed_positive"],
            "pct_predictions_changed_negative": val["pct_predictions_changed_negative"],
            "lr_encoder": used_lrs.get("lr_encoder", 0.0),
            "lr_attention": used_lrs.get("lr_attention", 0.0),
            "lr_odst": used_lrs.get("lr_odst", 0.0),
            "grad_lstm_median": g_l["median"],
            "grad_lstm_iqr": g_l["iqr"],
            "grad_attention_median": g_a["median"],
            "grad_attention_iqr": g_a["iqr"],
            "grad_odst_median": g_o["median"],
            "grad_odst_iqr": g_o["iqr"],
            "encoder_to_odst_grad_ratio": enc_ratio,
            "encoder_param_distance": _param_dist(student_initial_state, cur, "lstm."),
            "attention_param_distance": _param_dist(student_initial_state, cur, "attention."),
            "odst_param_distance": _param_dist(student_initial_state, cur, "node_head."),
        }
        epoch_rows.append(row)
        loss_rows.append(
            {
                "seed": seed,
                "epoch": epoch,
                "train_total_loss": row["train_total_loss"],
                "train_class_loss": row["train_class_loss"],
                "train_logit_consistency_loss": row["train_logit_consistency_loss"],
                "train_route_consistency_loss": row["train_route_consistency_loss"],
                "validation_loss": row["validation_loss"],
            }
        )
        grad_rows.append(
            {
                "seed": seed,
                "epoch": epoch,
                **{f"grad_lstm_{k}": v for k, v in g_l.items()},
                **{f"grad_attention_{k}": v for k, v in g_a.items()},
                **{f"grad_odst_{k}": v for k, v in g_o.items()},
                "encoder_to_odst_grad_ratio": enc_ratio,
                "n_grad_batches": len(batch_g["odst"]),
            }
        )
        param_rows.append(
            {
                "seed": seed,
                "epoch": epoch,
                "encoder_param_distance": row["encoder_param_distance"],
                "attention_param_distance": row["attention_param_distance"],
                "odst_param_distance": row["odst_param_distance"],
                "pooled_cosine_similarity": row["pooled_cosine_similarity"],
            }
        )
        routing_rows.append(
            {
                "seed": seed,
                "epoch": epoch,
                "student_routing_entropy": row["student_routing_entropy"],
                "teacher_routing_entropy": row["teacher_routing_entropy"],
                "routing_divergence": row["routing_divergence"],
                "student_unused_leaves_pct": row["student_unused_leaves_pct"],
                "teacher_unused_leaves_pct": row["teacher_unused_leaves_pct"],
            }
        )

        if s["pr_auc"] > best_pr:
            best_pr = float(s["pr_auc"])
            best_epoch = epoch
            best_metrics = val
            best_state = {k: v.detach().cpu().clone() for k, v in student.state_dict().items()}
            patience_left = PATIENCE
        else:
            patience_left -= 1
            if patience_left <= 0:
                break

    final_state = {k: v.detach().cpu().clone() for k, v in student.state_dict().items()}
    if best_state is not None:
        student.load_state_dict(best_state)

    final_val = evaluate_pair(teacher, student, val_loader, y_val, device, criterion)
    # diag cosine already in final_val
    bm = best_metrics or final_val
    s = bm["student"]
    param_explosion = any(
        _param_dist(student_initial_state, best_state or student.state_dict(), pfx) > 100.0
        for pfx in ("lstm.", "attention.", "node_head.")
    )
    fp_f = float(s.get("fp", 0))  # will overwrite from teacher meta in runner
    catastrophic_fp_fn = False

    return {
        "seed": seed,
        "completed": True,
        "best_epoch": best_epoch,
        "best_pr_auc": float(best_pr),
        "best_f1": float(s["f1"]),
        "best_precision": float(s["precision"]),
        "best_recall": float(s["recall"]),
        "best_fp": float(s["fp"]),
        "best_fn": float(s["fn"]),
        "best_threshold": float(s["threshold"]),
        "unused_leaves_pct": float(s["unused_leaves_pct"]),
        "routing_entropy_mean": float(s["routing_entropy_mean"]),
        "routing_divergence": float(bm["routing_divergence"]),
        "final_pooled_cosine": float(bm["pooled_cosine_similarity"]),
        "teacher_unchanged": teacher_unchanged,
        "encoder_updated": encoder_updated,
        "attention_updated": attention_updated,
        "odst_updated": odst_updated,
        "joint_training_verified": bool(encoder_updated and attention_updated and odst_updated),
        "nonzero_grads_all_components": all(nonzero.values()),
        "had_nan_or_inf": had_nan,
        "gradient_explosion": grad_explosion,
        "parameter_explosion": param_explosion,
        "protected_access": False,
        "threshold_from_validation_only": True,
        "student_independent_inference": True,
        "catastrophic_fp_fn": catastrophic_fp_fn,
        "catastrophic_collapse": bool(best_pr < 0.3),
        "best_state": best_state,
        "final_state": final_state,
        "best_metrics": best_metrics,
        "final_metrics": final_val,
        "epoch_rows": epoch_rows,
        "loss_rows": loss_rows,
        "grad_rows": grad_rows,
        "param_rows": param_rows,
        "routing_rows": routing_rows,
        "epochs_trained": len(epoch_rows),
        "used_lrs": used_lrs,
    }
