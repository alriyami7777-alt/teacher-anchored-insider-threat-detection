"""Rescue trainer with diagnostic hooks. Baseline C2/C5 semantics are preserved when weights match producing values."""

from __future__ import annotations

import time
from typing import Any, Callable

import numpy as np
import torch
import torch.nn as nn

from .evaluate import evaluate_pair
from .losses import (
    MAX_EPOCHS,
    annealed_weight,
    class_balanced_logit_loss,
    class_balanced_route_loss,
    logit_consistency_loss,
    make_task_criterion,
    route_consistency_loss,
    selective_logit_loss,
    selective_route_loss,
    teacher_correct_mask,
    total_loss,
)
from .models import (
    build_optimizer,
    student_forward,
    teacher_forward,
)
from .safety import OUTPUT_ROOT, sha256_file

LR_ENCODER = 3e-5
LR_ATTENTION = 3e-5
LR_ODST = 3e-4
GRAD_CLIP_NORM = 1.0
PATIENCE = 4


def _grad_vec(params) -> torch.Tensor | None:
    flats = []
    any_grad = False
    for p in params:
        if p.grad is None:
            flats.append(torch.zeros(p.numel(), device=p.device, dtype=p.dtype))
        else:
            any_grad = True
            flats.append(p.grad.detach().flatten())
    if not flats or not any_grad:
        return None
    return torch.cat(flats)


def _l2(v: torch.Tensor | None) -> float:
    if v is None or v.numel() == 0:
        return 0.0
    return float(torch.linalg.vector_norm(v).item())


def _cos(a: torch.Tensor | None, b: torch.Tensor | None) -> float:
    if a is None or b is None or a.numel() == 0 or b.numel() == 0:
        return float("nan")
    denom = torch.linalg.vector_norm(a) * torch.linalg.vector_norm(b)
    if float(denom.item()) <= 1e-12:
        return float("nan")
    return float(torch.dot(a, b).item() / float(denom.item()))


def capture_component_grads(student: nn.Module, loss: torch.Tensor) -> dict[str, torch.Tensor | None]:
    student.zero_grad(set_to_none=True)
    if float(loss.detach().item()) == 0.0 and not loss.requires_grad:
        return {"encoder": None, "attention": None, "odst": None, "all": None}
    loss.backward(retain_graph=True)
    enc = _grad_vec(student.lstm.parameters())
    att = _grad_vec(student.attention.parameters())
    od = _grad_vec(student.node_head.parameters())
    parts = [v for v in (enc, att, od) if v is not None]
    allv = torch.cat(parts) if parts else None
    return {"encoder": enc, "attention": att, "odst": od, "all": allv}


def train_condition(
    *,
    condition: str,
    seed: int,
    teacher: nn.Module,
    student: nn.Module,
    train_loader,
    val_loader,
    device: torch.device,
    pos_weight: float,
    teacher_threshold: float,
    w_logit0: float,
    w_route0: float,
    anneal_logit: bool = False,
    anneal_route: bool = False,
    class_balanced: bool = False,
    selective: bool = False,
    residual: bool = False,
    max_epochs: int = MAX_EPOCHS,
    patience: int = PATIENCE,
    diagnostic_epochs: tuple[int, ...] = (1, 8, 15),
    diagnostic_max_batches: int = 8,
    route_perm: torch.Tensor | None = None,
) -> dict[str, Any]:
    criterion = make_task_criterion(pos_weight, device)
    opt = build_optimizer(
        student, {"lr_encoder": LR_ENCODER, "lr_attention": LR_ATTENTION, "lr_odst": LR_ODST}
    )
    teacher_ids = {id(p) for p in teacher.parameters()}
    for group in opt.param_groups:
        for p in group["params"]:
            if id(p) in teacher_ids:
                raise RuntimeError("Teacher parameter found in optimiser")

    epoch_rows: list[dict[str, Any]] = []
    grad_rows: list[dict[str, Any]] = []
    best_pr = -1.0
    best_epoch = 0
    best_state = None
    best_metrics = None
    patience_left = patience
    t0 = time.time()

    for epoch in range(1, max_epochs + 1):
        student.train()
        teacher.eval()
        w_logit = annealed_weight(w_logit0, epoch) if anneal_logit else float(w_logit0)
        w_route = annealed_weight(w_route0, epoch) if anneal_route else float(w_route0)
        run_diag = epoch in diagnostic_epochs
        train_tot = train_cls = train_logit = train_route = 0.0
        n_obs = 0
        for b_i, (xb, yb) in enumerate(train_loader):
            xb = xb.to(device)
            yb = yb.to(device)
            opt.zero_grad(set_to_none=True)
            with torch.no_grad():
                tr = teacher_forward(teacher, xb)
            sr = student_forward(student, xb, residual=residual)
            t_choices = tr["choices"]
            if route_perm is not None:
                t_choices = t_choices.index_select(1, route_perm.to(device))
            l_class = criterion(sr["logit"], yb)
            if class_balanced:
                l_logit = class_balanced_logit_loss(sr["logit"], tr["logit"], yb)
                l_route = class_balanced_route_loss(sr["choices"], t_choices, yb)
            elif selective:
                mask = teacher_correct_mask(tr["logit"], yb, teacher_threshold)
                l_logit = selective_logit_loss(sr["logit"], tr["logit"], mask)
                l_route = selective_route_loss(sr["choices"], t_choices, mask)
            else:
                l_logit = logit_consistency_loss(sr["logit"], tr["logit"])
                l_route = route_consistency_loss(sr["choices"], t_choices)
            loss = total_loss(
                class_loss=l_class,
                logit_loss=l_logit,
                route_loss=l_route,
                w_logit=w_logit,
                w_route=w_route,
            )
            if run_diag and b_i < diagnostic_max_batches:
                pos_frac = float((yb > 0.5).float().mean().item())
                g_task = capture_component_grads(student, l_class)
                g_logit = capture_component_grads(student, w_logit * l_logit if w_logit else l_logit * 0)
                g_route = capture_component_grads(student, w_route * l_route if w_route else l_route * 0)
                opt.zero_grad(set_to_none=True)
                loss.backward()
                torch.nn.utils.clip_grad_norm_([p for p in student.parameters() if p.requires_grad], GRAD_CLIP_NORM)
                opt.step()
                n_pos_batch = int((yb > 0.5).sum().item())
                grad_rows.append(
                    {
                        "condition": condition,
                        "seed": seed,
                        "epoch": epoch,
                        "batch": b_i,
                        "phase": "early" if epoch == 1 else ("late" if epoch >= max_epochs - 1 else "middle"),
                        "pos_frac": pos_frac,
                        "n_pos": n_pos_batch,
                        "batch_class": "positive_containing" if n_pos_batch > 0 else "negative_dominant",
                        "w_logit": w_logit,
                        "w_route": w_route,
                        "task_loss": float(l_class.item()),
                        "logit_anchor_loss": float(l_logit.item()),
                        "route_anchor_loss": float(l_route.item()),
                        "grad_task_encoder": _l2(g_task["encoder"]),
                        "grad_task_attention": _l2(g_task["attention"]),
                        "grad_task_odst": _l2(g_task["odst"]),
                        "grad_logit_encoder": _l2(g_logit["encoder"]),
                        "grad_logit_attention": _l2(g_logit["attention"]),
                        "grad_logit_odst": _l2(g_logit["odst"]),
                        "grad_route_encoder": _l2(g_route["encoder"]),
                        "grad_route_attention": _l2(g_route["attention"]),
                        "grad_route_odst": _l2(g_route["odst"]),
                        "cos_task_logit_all": _cos(g_task["all"], g_logit["all"]),
                        "cos_task_route_all": _cos(g_task["all"], g_route["all"]),
                        "cos_logit_route_all": _cos(g_logit["all"], g_route["all"]),
                        "cos_task_logit_odst": _cos(g_task["odst"], g_logit["odst"]),
                        "cos_task_route_odst": _cos(g_task["odst"], g_route["odst"]),
                    }
                )
            else:
                loss.backward()
                torch.nn.utils.clip_grad_norm_([p for p in student.parameters() if p.requires_grad], GRAD_CLIP_NORM)
                opt.step()
            bs = int(yb.size(0))
            train_tot += float(loss.item()) * bs
            train_cls += float(l_class.item()) * bs
            train_logit += float(l_logit.item()) * bs
            train_route += float(l_route.item()) * bs
            n_obs += bs

        val = evaluate_pair(
            student=student, teacher=teacher, loader=val_loader, device=device, residual=residual
        )
        pr = float(val["student"]["pr_auc"])
        row = {
            "condition": condition,
            "seed": seed,
            "epoch": epoch,
            "w_logit": w_logit,
            "w_route": w_route,
            "train_total_loss": train_tot / max(n_obs, 1),
            "train_class_loss": train_cls / max(n_obs, 1),
            "train_logit_consistency_loss": train_logit / max(n_obs, 1),
            "train_route_consistency_loss": train_route / max(n_obs, 1),
            "validation_pr_auc": pr,
            "validation_f1": float(val["student"]["f1"]),
            "validation_fp": int(val["student"]["fp"]),
            "validation_fn": int(val["student"]["fn"]),
            "teacher_logit_deviation": float(val.get("teacher_logit_deviation", float("nan"))),
            "route_MAE": float(val.get("route_MAE", float("nan"))),
            "route_KL": float(val.get("route_KL", float("nan"))),
            "hard_route_agreement": float(val.get("hard_route_agreement", float("nan"))),
        }
        epoch_rows.append(row)
        print(
            f"[EDITOR-009] {condition} seed={seed} epoch={epoch} "
            f"wL={w_logit:.4f} wR={w_route:.4f} val_PR-AUC={pr:.6f} F1={row['validation_f1']:.4f}",
            flush=True,
        )
        if pr > best_pr:
            best_pr = pr
            best_epoch = epoch
            best_metrics = val
            best_state = {k: v.detach().cpu().clone() for k, v in student.state_dict().items()}
            patience_left = patience
        else:
            patience_left -= 1
            if patience_left <= 0:
                break

    if best_state is not None:
        student.load_state_dict(best_state)
    final_val = evaluate_pair(
        student=student, teacher=teacher, loader=val_loader, device=device, residual=residual
    )
    out_dir = OUTPUT_ROOT / condition / f"seed{seed}"
    out_dir.mkdir(parents=True, exist_ok=True)
    ckpt = out_dir / "best_student.pt"
    torch.save(
        {
            "model_state_dict": best_state or {k: v.detach().cpu().clone() for k, v in student.state_dict().items()},
            "condition": condition,
            "seed": seed,
            "best_epoch": best_epoch,
            "best_val_pr_auc": best_pr,
            "campaign": "EDITOR-009 DEVELOPMENT RESCUE",
            "test_evaluated": False,
        },
        ckpt,
    )
    bm = best_metrics or final_val
    s = bm["student"]
    return {
        "condition": condition,
        "seed": seed,
        "best_epoch": best_epoch,
        "train_PR_AUC": float("nan"),
        "validation_PR_AUC": float(best_pr),
        "validation_F1": float(s["f1"]),
        "precision": float(s["precision"]),
        "recall": float(s["recall"]),
        "FP": int(s["fp"]),
        "FN": int(s["fn"]),
        "Brier": float(s["Brier"]),
        "log_loss": float(s["log_loss"]),
        "teacher_logit_deviation": float(bm.get("teacher_logit_deviation", float("nan"))),
        "route_MAE": float(bm.get("route_MAE", float("nan"))),
        "route_KL": float(bm.get("route_KL", float("nan"))),
        "hard_route_agreement": float(bm.get("hard_route_agreement", float("nan"))),
        "training_time": float(time.time() - t0),
        "best_checkpoint": str(ckpt),
        "best_checkpoint_sha256": sha256_file(ckpt),
        "epoch_rows": epoch_rows,
        "grad_rows": grad_rows,
        "failure_status": "ok",
        "w_logit0": w_logit0,
        "w_route0": w_route0,
        "anneal_logit": anneal_logit,
        "anneal_route": anneal_route,
        "class_balanced": class_balanced,
        "selective": selective,
        "residual": residual,
        "y_val": bm["y"],
        "student_logits": bm["student_logits"],
        "teacher_logits": bm.get("teacher_logits"),
        "student_choices": bm.get("student_choices"),
        "teacher_choices": bm.get("teacher_choices"),
        "student_z": bm.get("student_z"),
        "student_tree_outputs": bm.get("student_tree_outputs"),
        "teacher_tree_outputs": bm.get("teacher_tree_outputs"),
    }
