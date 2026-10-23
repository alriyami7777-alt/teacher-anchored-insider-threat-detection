"""T-OPT teacher trainer and matched C2-OPT / R2-OPT student trainer."""

from __future__ import annotations

import time
from typing import Any

import torch
import torch.nn as nn

from .constants import GRAD_CLIP_NORM, MAX_EPOCHS, PATIENCE
from .evaluate import evaluate_pair
from .losses import logit_consistency_loss, make_task_criterion, route_consistency_loss, total_loss
from .models import (
    assert_teacher_not_in_optimizer,
    build_student_optimizer,
    build_teacher_optimizer,
    clone_state,
    student_forward,
    teacher_forward,
)
from .safety import OUTPUT_ROOT, sha256_file


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


def train_teacher(
    *,
    seed: int,
    model: nn.Module,
    train_loader,
    val_loader,
    device: torch.device,
    pos_weight: float,
    max_epochs: int = MAX_EPOCHS,
    patience: int = PATIENCE,
) -> dict[str, Any]:
    criterion = make_task_criterion(pos_weight, device)
    opt = build_teacher_optimizer(model)
    epoch_rows: list[dict[str, Any]] = []
    best_pr = -1.0
    best_epoch = 0
    best_state = None
    best_metrics = None
    patience_left = patience
    t0 = time.time()
    for epoch in range(1, max_epochs + 1):
        model.train()
        model.lstm.eval()
        model.attention.eval()
        model.linear_head.eval()
        model.dropout.eval()
        running = 0.0
        n_obs = 0
        for xb, yb in train_loader:
            xb = xb.to(device)
            yb = yb.to(device)
            opt.zero_grad(set_to_none=True)
            out = student_forward(model, xb)
            loss = criterion(out["logit"], yb)
            loss.backward()
            torch.nn.utils.clip_grad_norm_([p for p in model.parameters() if p.requires_grad], GRAD_CLIP_NORM)
            opt.step()
            bs = int(yb.size(0))
            running += float(loss.item()) * bs
            n_obs += bs
        val = evaluate_pair(student=model, teacher=None, loader=val_loader, device=device)
        pr = float(val["student"]["pr_auc"])
        row = {
            "condition": "T-OPT",
            "seed": seed,
            "epoch": epoch,
            "train_task_loss": running / max(n_obs, 1),
            "validation_pr_auc": pr,
            "validation_f1": float(val["student"]["f1"]),
        }
        epoch_rows.append(row)
        print(f"[EDITOR-011] T-OPT seed={seed} epoch={epoch} val_PR-AUC={pr:.6f}", flush=True)
        if pr > best_pr:
            best_pr = pr
            best_epoch = epoch
            best_metrics = val
            best_state = clone_state(model)
            patience_left = patience
        else:
            patience_left -= 1
            if patience_left <= 0:
                break
    if best_state is not None:
        model.load_state_dict(best_state)
    out_dir = OUTPUT_ROOT / "T-OPT" / f"seed{seed}"
    out_dir.mkdir(parents=True, exist_ok=True)
    ckpt = out_dir / "best_teacher.pt"
    torch.save(
        {
            "model_state_dict": best_state or clone_state(model),
            "condition": "T-OPT",
            "seed": seed,
            "best_epoch": best_epoch,
            "best_val_pr_auc": best_pr,
            "campaign": "EDITOR-011",
            "odst": "ODST-046",
            "test_evaluated": False,
        },
        ckpt,
    )
    bm = best_metrics or val
    s = bm["student"]
    return {
        "condition": "T-OPT",
        "seed": seed,
        "best_epoch": best_epoch,
        "validation_PR_AUC": float(best_pr),
        "validation_F1": float(s["f1"]),
        "precision": float(s["precision"]),
        "recall": float(s["recall"]),
        "FP": int(s["fp"]),
        "FN": int(s["fn"]),
        "Brier": float(s["Brier"]),
        "log_loss": float(s["log_loss"]),
        "predicted_positive_fraction": float(s["predicted_positive_fraction"]),
        "training_time": float(time.time() - t0),
        "best_checkpoint": str(ckpt),
        "best_checkpoint_sha256": sha256_file(ckpt),
        "epoch_rows": epoch_rows,
        "y_val": bm["y"],
        "student_logits": bm["student_logits"],
        "failure_status": "ok",
    }


def train_student(
    *,
    condition: str,
    seed: int,
    teacher: nn.Module,
    student: nn.Module,
    train_loader,
    val_loader,
    device: torch.device,
    pos_weight: float,
    w_logit: float,
    w_route: float,
    max_epochs: int = MAX_EPOCHS,
    patience: int = PATIENCE,
    diagnostic_epochs: tuple[int, ...] = (1, 8, 15),
    diagnostic_max_batches: int = 4,
) -> dict[str, Any]:
    criterion = make_task_criterion(pos_weight, device)
    opt = build_student_optimizer(student)
    assert_teacher_not_in_optimizer(teacher, opt)
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
        run_diag = epoch in diagnostic_epochs
        train_tot = train_cls = train_logit = train_route = 0.0
        n_obs = 0
        for b_i, (xb, yb) in enumerate(train_loader):
            xb = xb.to(device)
            yb = yb.to(device)
            opt.zero_grad(set_to_none=True)
            with torch.no_grad():
                tr = teacher_forward(teacher, xb)
            sr = student_forward(student, xb)
            l_class = criterion(sr["logit"], yb)
            if w_logit == 0.0:
                l_logit = sr["logit"].new_zeros(())
            else:
                l_logit = logit_consistency_loss(sr["logit"], tr["logit"])
            if w_route == 0.0:
                l_route = sr["choices"].new_zeros(())
            else:
                l_route = route_consistency_loss(sr["choices"], tr["choices"])
            loss = total_loss(
                class_loss=l_class,
                logit_loss=l_logit,
                route_loss=l_route,
                w_logit=w_logit,
                w_route=w_route,
            )
            if run_diag and b_i < diagnostic_max_batches:
                g_task = capture_component_grads(student, l_class)
                g_logit = capture_component_grads(
                    student, l_logit if w_logit else sr["logit"].new_zeros(()).requires_grad_(False)
                )
                g_route = capture_component_grads(
                    student,
                    (w_route * l_route) if w_route else sr["choices"].new_zeros(()).requires_grad_(False),
                )
                opt.zero_grad(set_to_none=True)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(
                    [p for p in student.parameters() if p.requires_grad], GRAD_CLIP_NORM
                )
                opt.step()
                grad_rows.append(
                    {
                        "condition": condition,
                        "seed": seed,
                        "epoch": epoch,
                        "batch": b_i,
                        "phase": "early" if epoch == 1 else ("late" if epoch >= max_epochs - 1 else "middle"),
                        "w_logit": w_logit,
                        "w_route": w_route,
                        "task_loss": float(l_class.item()),
                        "logit_anchor_loss": float(l_logit.item()) if l_logit.numel() else 0.0,
                        "route_anchor_loss": float(l_route.item()) if l_route.numel() else 0.0,
                        "grad_task_all": _l2(g_task["all"]),
                        "grad_logit_all": _l2(g_logit["all"]),
                        "grad_route_all": _l2(g_route["all"]),
                        "cos_task_route_all": _cos(g_task["all"], g_route["all"]),
                        "logit_anchor_gradient_absent": bool(_l2(g_logit["all"]) == 0.0),
                        "route_gradient_exists": bool(_l2(g_route["all"]) > 0.0) if w_route else False,
                        "task_gradient_exists": bool(_l2(g_task["all"]) > 0.0),
                    }
                )
            else:
                loss.backward()
                torch.nn.utils.clip_grad_norm_(
                    [p for p in student.parameters() if p.requires_grad], GRAD_CLIP_NORM
                )
                opt.step()
            bs = int(yb.size(0))
            train_tot += float(loss.item()) * bs
            train_cls += float(l_class.item()) * bs
            train_logit += float(l_logit.item()) * bs if l_logit.numel() else 0.0
            train_route += float(l_route.item()) * bs if l_route.numel() else 0.0
            n_obs += bs
        val = evaluate_pair(student=student, teacher=teacher, loader=val_loader, device=device)
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
            "teacher_logit_deviation": float(val.get("teacher_logit_deviation", float("nan"))),
            "route_MAE": float(val.get("route_MAE", float("nan"))),
            "route_KL": float(val.get("route_KL", float("nan"))),
            "hard_route_agreement": float(val.get("hard_route_agreement", float("nan"))),
            "dominant_leaf_agreement": float(val.get("dominant_leaf_agreement", float("nan"))),
        }
        epoch_rows.append(row)
        print(
            f"[EDITOR-011] {condition} seed={seed} epoch={epoch} "
            f"wR={w_route:.1f} val_PR-AUC={pr:.6f}",
            flush=True,
        )
        if pr > best_pr:
            best_pr = pr
            best_epoch = epoch
            best_metrics = val
            best_state = clone_state(student)
            patience_left = patience
        else:
            patience_left -= 1
            if patience_left <= 0:
                break
    if best_state is not None:
        student.load_state_dict(best_state)
    out_dir = OUTPUT_ROOT / condition / f"seed{seed}"
    out_dir.mkdir(parents=True, exist_ok=True)
    ckpt = out_dir / "best_student.pt"
    torch.save(
        {
            "model_state_dict": best_state or clone_state(student),
            "condition": condition,
            "seed": seed,
            "best_epoch": best_epoch,
            "best_val_pr_auc": best_pr,
            "w_logit": w_logit,
            "w_route": w_route,
            "campaign": "EDITOR-011",
            "odst": "ODST-046",
            "test_evaluated": False,
        },
        ckpt,
    )
    bm = best_metrics or val
    s = bm["student"]
    return {
        "condition": condition,
        "seed": seed,
        "best_epoch": best_epoch,
        "validation_PR_AUC": float(best_pr),
        "validation_F1": float(s["f1"]),
        "precision": float(s["precision"]),
        "recall": float(s["recall"]),
        "FP": int(s["fp"]),
        "FN": int(s["fn"]),
        "Brier": float(s["Brier"]),
        "log_loss": float(s["log_loss"]),
        "predicted_positive_fraction": float(s["predicted_positive_fraction"]),
        "teacher_logit_deviation": float(bm.get("teacher_logit_deviation", float("nan"))),
        "route_MAE": float(bm.get("route_MAE", float("nan"))),
        "route_KL": float(bm.get("route_KL", float("nan"))),
        "hard_route_agreement": float(bm.get("hard_route_agreement", float("nan"))),
        "dominant_leaf_agreement": float(bm.get("dominant_leaf_agreement", float("nan"))),
        "training_time": float(time.time() - t0),
        "best_checkpoint": str(ckpt),
        "best_checkpoint_sha256": sha256_file(ckpt),
        "epoch_rows": epoch_rows,
        "grad_rows": grad_rows,
        "w_logit": w_logit,
        "w_route": w_route,
        "y_val": bm["y"],
        "student_logits": bm["student_logits"],
        "teacher_logits": bm.get("teacher_logits"),
        "failure_status": "ok",
    }
