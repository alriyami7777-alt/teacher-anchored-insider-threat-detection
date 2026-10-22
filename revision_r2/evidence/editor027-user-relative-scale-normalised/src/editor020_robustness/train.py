"""Matched robustness trainers. Teacher always sees clean x; student robustness terms use x_tilde."""

from __future__ import annotations

import time
from typing import Any

import numpy as np
import torch
import torch.nn as nn

from editor012_rescue.data import make_xy_loader
from editor012_rescue.losses import et1_ensemble_logit_mse, make_task_criterion, route_consistency_loss
from editor012_rescue.metrics import metrics_from_logits
from editor012_rescue.models import clone_state, freeze_teacher, student_forward
from editor012_rescue.producing import import_set_seed

from .constants import BATCH_SIZE, GRAD_CLIP_NORM, LAMBDA_ROUTE, LAMBDA_TEACHER, MAX_EPOCHS, PATIENCE
from .evaluate import score_condition
from .models import build_optimizer, condition_flags, forward_student, make_l1_modules, save_checkpoint, student_from_topt
from .safety import Editor020Blocked, assert_lambdas
from .sampler import apply_sampled_batch


def _set_seed(seed: int) -> None:
    set_seed = import_set_seed()
    set_seed(int(seed))
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False


def train_condition(
    *,
    arch: str,
    objective: str,
    seed: int,
    X: np.ndarray,
    y: np.ndarray,
    ens: np.ndarray,
    X_select: np.ndarray,
    y_select: np.ndarray,
    matched_teacher: nn.Module,
    device: torch.device,
    pos_weight: float,
    scaler: dict[str, Any],
    select_name: str = "inner_select",
    max_epochs: int = MAX_EPOCHS,
    patience: int = PATIENCE,
) -> dict[str, Any]:
    assert_lambdas()
    flags = condition_flags(arch, objective)
    _set_seed(seed)
    student, start_sha = student_from_topt(seed, device)
    modules = make_l1_modules().to(device) if arch == "L1" else None
    freeze_teacher(matched_teacher)
    opt = build_optimizer(arch, student, modules)
    criterion = make_task_criterion(pos_weight, device)
    n = int(len(y))
    index = np.arange(n, dtype=np.float32)
    loader = make_xy_loader(X, y, seed=seed, batch_size=BATCH_SIZE, shuffle=True, extras=[ens, index])
    best_pr = -1.0
    best_epoch = 0
    best_student = None
    best_modules = None
    best_metrics = None
    patience_left = patience
    t0 = time.time()
    history: list[dict[str, Any]] = []

    for epoch in range(1, max_epochs + 1):
        student.train()
        if modules is not None:
            modules.train()
        matched_teacher.eval()
        train_tot = 0.0
        n_obs = 0
        for xb, yb, ensb, idxb in loader:
            xb = xb.to(device)
            yb = yb.to(device)
            ensb = ensb.to(device)
            opt.zero_grad(set_to_none=True)
            clean = forward_student(arch, student, xb, modules)
            loss = yb.new_zeros(())
            if flags["task_clean"]:
                loss = loss + criterion(clean["logit"], yb)
            if flags["teacher_clean"]:
                loss = loss + float(LAMBDA_TEACHER) * et1_ensemble_logit_mse(clean["logit"], ensb)
            if flags["route_clean"]:
                with torch.no_grad():
                    tr_clean = student_forward(matched_teacher, xb)
                loss = loss + float(LAMBDA_ROUTE) * route_consistency_loss(clean["choices"], tr_clean["choices"])
            if flags["needs_degraded"]:
                x_np = xb.detach().cpu().numpy()
                idx_np = idxb.detach().cpu().numpy()
                x_deg = apply_sampled_batch(x_np, idx_np, epoch, scaler)
                xdb = torch.from_numpy(np.asarray(x_deg, dtype=np.float32)).to(device)
                deg = forward_student(arch, student, xdb, modules)
                if flags["task_degraded"]:
                    loss = loss + criterion(deg["logit"], yb)
                if flags["teacher_degraded"]:
                    loss = loss + float(LAMBDA_TEACHER) * et1_ensemble_logit_mse(deg["logit"], ensb)
                if flags["route_robust"]:
                    with torch.no_grad():
                        tr_route = student_forward(matched_teacher, xb)
                    loss = loss + float(LAMBDA_ROUTE) * route_consistency_loss(deg["choices"], tr_route["choices"])
            if not torch.isfinite(loss):
                raise Editor020Blocked(f"non-finite loss for {arch}-{objective} seed={seed}")
            loss.backward()
            params = [p for p in student.parameters() if p.requires_grad]
            if modules is not None:
                params.extend([p for p in modules.parameters() if p.requires_grad])
            torch.nn.utils.clip_grad_norm_(params, GRAD_CLIP_NORM)
            opt.step()
            bs = int(yb.size(0))
            train_tot += float(loss.detach().cpu()) * bs
            n_obs += bs

        scored = score_condition(arch, student, modules, X_select, y_select, device)
        pr = float(scored["metrics"]["pr_auc"])
        row = {
            "condition": f"{arch}-{objective}",
            "epoch": epoch,
            "train_loss": train_tot / max(n_obs, 1),
            f"{select_name}_PR_AUC": pr,
        }
        history.append(row)
        print(
            f"[EDITOR-020] {arch}-{objective} seed={seed} epoch={epoch} {select_name}_PR-AUC={pr:.6f}",
            flush=True,
        )
        if pr > best_pr:
            best_pr = pr
            best_epoch = epoch
            best_metrics = scored
            best_student = clone_state(student)
            best_modules = None if modules is None else clone_state(modules)
            patience_left = patience
        else:
            patience_left -= 1
            if patience_left <= 0:
                break

    if best_student is not None:
        student.load_state_dict(best_student)
    if modules is not None and best_modules is not None:
        modules.load_state_dict(best_modules)
    ckpt, ckpt_sha = save_checkpoint(
        arch=arch,
        objective=objective,
        seed=seed,
        student=student,
        modules=modules,
        extra={
            "best_epoch": best_epoch,
            "best_select_pr_auc": best_pr,
            "start_topt_sha256": start_sha,
            "flags": flags,
            "official_validation_used": select_name == "validation",
        },
    )
    bm = best_metrics or scored
    return {
        "condition": f"{arch}-{objective}",
        "arch": arch,
        "objective": objective,
        "seed": seed,
        "best_epoch": best_epoch,
        "select_PR_AUC": float(best_pr),
        "select_F1": float(bm["metrics"]["f1"]),
        "Brier": float(bm["metrics"]["Brier"]),
        "log_loss": float(bm["metrics"]["log_loss"]),
        "threshold": float(bm["metrics"]["threshold"]),
        "training_time": float(time.time() - t0),
        "best_checkpoint": ckpt,
        "best_checkpoint_sha256": ckpt_sha,
        "start_topt_sha256": start_sha,
        "flags": flags,
        "history": history,
        "logits": bm["logits"],
        "y": bm["y"],
        "choices": bm.get("choices"),
        "tree_outputs": bm.get("tree_outputs"),
        "leaf_probs_all": bm.get("leaf_probs_all"),
    }
