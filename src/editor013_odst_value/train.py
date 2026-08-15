"""Head-only and end-to-end trainers. Distill is ET1 MSE, never historical C5."""

from __future__ import annotations

import time
from typing import Any

import numpy as np
import torch
import torch.nn as nn

from editor012_rescue.evaluate import hash_gate_checkpoint
from editor012_rescue.losses import et1_ensemble_logit_mse, make_task_criterion, route_consistency_loss
from editor012_rescue.metrics import metrics_from_logits
from editor012_rescue.models import clone_state, freeze_teacher, student_forward as historical_student_forward
from editor012_rescue.producing import build_odst046_model, import_set_seed, load_state_dict

from .constants import (
    GRAD_CLIP_NORM,
    LAMBDA_DISTILL,
    LAMBDA_HISTORICAL_SINGLE_TEACHER_LOGIT,
    LAMBDA_ROUTE,
    MAX_EPOCHS,
    PATIENCE,
    TOPT_CHECKPOINTS,
)
from .models import (
    Editor013Modules,
    build_editor013_optimizer,
    configure_trainability,
    editor013_forward,
    editor013_forward_from_z,
    make_modules,
)
from .safety import OUTPUT_ROOT, Editor013Blocked, sha256_file


def _set_seed(seed: int) -> None:
    set_seed = import_set_seed()
    set_seed(int(seed))
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False


def load_topt(seed: int, device: torch.device) -> tuple[nn.Module, str]:
    spec = TOPT_CHECKPOINTS[seed]
    start_sha = hash_gate_checkpoint(spec["checkpoint"], spec["sha256"])
    model = build_odst046_model()
    load_state_dict(model, spec["checkpoint"], strict=True)
    model.to(device)
    return model, start_sha


def diversity_loss(tree_outputs: torch.Tensor) -> torch.Tensor:
    """Mean squared off-diagonal correlation of batch-standardised tree outputs."""
    x = tree_outputs
    x = x - x.mean(dim=0, keepdim=True)
    std = x.std(dim=0, unbiased=False).clamp_min(1e-6)
    z = x / std
    n = z.size(0)
    if n < 2:
        return z.new_zeros(())
    corr = (z.T @ z) / float(n)
    j = corr.size(0)
    off = corr - torch.diag(torch.diag(corr))
    return (off.pow(2).sum()) / float(max(j * (j - 1), 1))


def _distill_target(batch, *, teacher: str, device: torch.device) -> torch.Tensor | None:
    if teacher == "none":
        return None
    if teacher == "ensemble":
        return batch[2].to(device)
    if teacher == "single":
        return batch[3].to(device)
    raise Editor013Blocked(f"unknown teacher target {teacher!r}")


def train_head_only(
    *,
    condition: str,
    spec: dict[str, Any],
    student: nn.Module,
    modules: Editor013Modules,
    train_loader,
    select_loader,
    device: torch.device,
    pos_weight: float,
    seed: int,
    max_epochs: int = MAX_EPOCHS,
    patience: int = PATIENCE,
    lambda_div: float = 0.0,
) -> dict[str, Any]:
    if LAMBDA_HISTORICAL_SINGLE_TEACHER_LOGIT != 0.0:
        raise Editor013Blocked("historical single-teacher logit anchor must remain retired")
    criterion = make_task_criterion(pos_weight, device)
    opt = build_editor013_optimizer(student, modules, encoder_trainable=False)
    configure_trainability(student, modules, encoder_trainable=False)
    best_pr = -1.0
    best_epoch = 0
    best_student = None
    best_modules = None
    best_metrics = None
    patience_left = patience
    t0 = time.time()
    epoch_rows: list[dict[str, Any]] = []
    teacher = str(spec.get("teacher", "none"))
    distill = bool(spec.get("distill", False))

    for epoch in range(1, max_epochs + 1):
        student.train()
        student.lstm.eval()
        student.attention.eval()
        student.dropout.eval()
        modules.train()
        train_tot = 0.0
        n_obs = 0
        for batch in train_loader:
            zb = batch[0].to(device)
            yb = batch[1].to(device)
            opt.zero_grad(set_to_none=True)
            out = editor013_forward_from_z(student, zb, modules)
            loss = criterion(out["logit"], yb)
            if distill:
                tgt = _distill_target(batch, teacher=teacher, device=device)
                if tgt is None:
                    raise Editor013Blocked("distill requested without teacher target")
                loss = loss + float(LAMBDA_DISTILL) * et1_ensemble_logit_mse(out["logit"], tgt)
            if lambda_div > 0:
                loss = loss + float(lambda_div) * diversity_loss(out["tree_outputs"])
            loss.backward()
            torch.nn.utils.clip_grad_norm_(
                [p for p in list(student.parameters()) + list(modules.parameters()) if p.requires_grad],
                GRAD_CLIP_NORM,
            )
            opt.step()
            bs = int(yb.size(0))
            train_tot += float(loss.item()) * bs
            n_obs += bs
        val = evaluate_head(student, modules, select_loader, device)
        pr = float(val["pr_auc"])
        epoch_rows.append(
            {
                "condition": condition,
                "seed": seed,
                "epoch": epoch,
                "inner_select_pr_auc": pr,
                "train_loss": train_tot / max(n_obs, 1),
            }
        )
        print(
            f"[EDITOR-013] {condition} seed={seed} epoch={epoch} INNER_SELECT_PR-AUC={pr:.6f}",
            flush=True,
        )
        if pr > best_pr:
            best_pr = pr
            best_epoch = epoch
            best_metrics = val
            best_student = clone_state(student)
            best_modules = clone_state(modules)
            patience_left = patience
        else:
            patience_left -= 1
            if patience_left <= 0:
                break

    if best_student is not None:
        student.load_state_dict(best_student)
    if best_modules is not None:
        modules.load_state_dict(best_modules)
    out_dir = OUTPUT_ROOT / "inner_heads" / condition
    out_dir.mkdir(parents=True, exist_ok=True)
    ckpt = out_dir / "best.pt"
    torch.save(
        {
            "student_state_dict": best_student or clone_state(student),
            "modules_state_dict": best_modules or clone_state(modules),
            "condition": condition,
            "seed": seed,
            "best_epoch": best_epoch,
            "best_select_pr_auc": best_pr,
            "campaign": "EDITOR-013",
            "test_evaluated": False,
            "official_validation_used": False,
        },
        ckpt,
    )
    bm = best_metrics or val
    return {
        "condition": condition,
        "seed": seed,
        "best_epoch": best_epoch,
        "select_PR_AUC": float(best_pr),
        "select_F1": float(bm["f1"]),
        "Brier": float(bm["Brier"]),
        "log_loss": float(bm["log_loss"]),
        "threshold": float(bm["threshold"]),
        "training_time": float(time.time() - t0),
        "best_checkpoint": str(ckpt),
        "best_checkpoint_sha256": sha256_file(ckpt),
        "learned_tree_weights": modules.learned_tree_weights(),
        "learned_alpha": modules.learned_alpha(),
        "initial_linear_hash": modules.initial_linear_hash(),
        "epoch_rows": epoch_rows,
        "y_select": bm["y"],
        "logits": bm["logits"],
        "tree_outputs": bm.get("tree_outputs"),
        "family": spec["family"],
        "readout": spec.get("readout"),
        "hybrid": bool(spec.get("hybrid", False)),
        "distill": distill,
        "teacher": teacher,
        "lambda_div": float(lambda_div),
        "official_validation_used": False,
    }


def train_e2e(
    *,
    condition: str,
    spec: dict[str, Any],
    seed: int,
    start_seed: int,
    train_loader,
    select_loader,
    device: torch.device,
    pos_weight: float,
    matched_teacher: nn.Module | None = None,
    select_name: str = "validation",
    max_epochs: int = MAX_EPOCHS,
    patience: int = PATIENCE,
    lambda_div: float = 0.0,
) -> dict[str, Any]:
    if LAMBDA_HISTORICAL_SINGLE_TEACHER_LOGIT != 0.0:
        raise Editor013Blocked("historical single-teacher logit anchor must remain retired")
    _set_seed(seed)
    student, start_sha = load_topt(start_seed, device)
    if start_sha != TOPT_CHECKPOINTS[start_seed]["sha256"]:
        raise Editor013Blocked("paired-start T-OPT hash mismatch")
    modules = make_modules(spec)
    modules.to(device)
    init_lin = modules.initial_linear_hash()
    if modules.alpha_mod is not None and float(modules.alpha_mod.alpha.item()) != 0.0:
        raise Editor013Blocked("hybrid alpha initialisation mismatch")
    criterion = make_task_criterion(pos_weight, device)
    opt = build_editor013_optimizer(student, modules, encoder_trainable=True)
    if matched_teacher is not None:
        freeze_teacher(matched_teacher)
    best_pr = -1.0
    best_epoch = 0
    best_student = None
    best_modules = None
    best_metrics = None
    patience_left = patience
    t0 = time.time()
    teacher = str(spec.get("teacher", "none"))
    distill = bool(spec.get("distill", False))
    route_on = bool(spec.get("route", False))

    for epoch in range(1, max_epochs + 1):
        student.train()
        modules.train()
        if matched_teacher is not None:
            matched_teacher.eval()
        n_obs = 0
        train_tot = 0.0
        for batch in train_loader:
            xb = batch[0].to(device)
            yb = batch[1].to(device)
            opt.zero_grad(set_to_none=True)
            out = editor013_forward(student, xb, modules)
            loss = criterion(out["logit"], yb)
            if distill:
                tgt = _distill_target(batch, teacher=teacher, device=device)
                if tgt is None:
                    raise Editor013Blocked("distill requested without teacher target")
                loss = loss + float(LAMBDA_DISTILL) * et1_ensemble_logit_mse(out["logit"], tgt)
            if route_on:
                if matched_teacher is None:
                    raise Editor013Blocked("route anchor requires matched teacher")
                with torch.no_grad():
                    tr = historical_student_forward(matched_teacher, xb)
                loss = loss + float(LAMBDA_ROUTE) * route_consistency_loss(out["choices"], tr["choices"])
            if lambda_div > 0:
                loss = loss + float(lambda_div) * diversity_loss(out["tree_outputs"])
            loss.backward()
            torch.nn.utils.clip_grad_norm_(
                [p for p in list(student.parameters()) + list(modules.parameters()) if p.requires_grad],
                GRAD_CLIP_NORM,
            )
            opt.step()
            bs = int(yb.size(0))
            train_tot += float(loss.item()) * bs
            n_obs += bs
        val = evaluate_e2e(student, modules, select_loader, device)
        pr = float(val["pr_auc"])
        print(
            f"[EDITOR-013] {condition} seed={seed} epoch={epoch} {select_name}_PR-AUC={pr:.6f}",
            flush=True,
        )
        if pr > best_pr:
            best_pr = pr
            best_epoch = epoch
            best_metrics = val
            best_student = clone_state(student)
            best_modules = clone_state(modules)
            patience_left = patience
        else:
            patience_left -= 1
            if patience_left <= 0:
                break

    if best_student is not None:
        student.load_state_dict(best_student)
    if best_modules is not None:
        modules.load_state_dict(best_modules)
    out_dir = OUTPUT_ROOT / condition / f"seed{seed}"
    out_dir.mkdir(parents=True, exist_ok=True)
    ckpt = out_dir / "best.pt"
    torch.save(
        {
            "student_state_dict": best_student or clone_state(student),
            "modules_state_dict": best_modules or clone_state(modules),
            "condition": condition,
            "seed": seed,
            "start_seed": start_seed,
            "best_epoch": best_epoch,
            "best_select_pr_auc": best_pr,
            "initial_linear_hash": init_lin,
            "campaign": "EDITOR-013",
            "test_evaluated": False,
        },
        ckpt,
    )
    bm = best_metrics or val
    np.save(out_dir / "val_logits.npy", bm["logits"])
    np.save(out_dir / "val_y.npy", bm["y"])
    return {
        "condition": condition,
        "seed": seed,
        "start_seed": start_seed,
        "best_epoch": best_epoch,
        "select_PR_AUC": float(best_pr),
        "validation_PR_AUC": float(best_pr),
        "validation_F1": float(bm["f1"]),
        "precision": float(bm["precision"]),
        "recall": float(bm["recall"]),
        "FP": int(bm["fp"]),
        "FN": int(bm["fn"]),
        "Brier": float(bm["Brier"]),
        "log_loss": float(bm["log_loss"]),
        "predicted_positive_fraction": float(bm["predicted_positive_fraction"]),
        "threshold": float(bm["threshold"]),
        "training_time": float(time.time() - t0),
        "best_checkpoint": str(ckpt),
        "best_checkpoint_sha256": sha256_file(ckpt),
        "start_topt_sha256": start_sha,
        "initial_linear_hash": init_lin,
        "learned_tree_weights": modules.learned_tree_weights(),
        "learned_alpha": modules.learned_alpha(),
        "y_val": bm["y"],
        "student_logits": bm["logits"],
        "tree_outputs": bm.get("tree_outputs"),
        "linear_logits": bm.get("linear_logits"),
        "odst_logits": bm.get("odst_logits"),
        "family": spec["family"],
        "readout": spec.get("readout"),
        "hybrid": bool(spec.get("hybrid", False)),
        "distill": distill,
        "teacher": teacher,
        "route": route_on,
        "lambda_div": float(lambda_div),
    }


@torch.no_grad()
def evaluate_head(
    student: nn.Module,
    modules: Editor013Modules,
    loader,
    device: torch.device,
) -> dict[str, Any]:
    student.eval()
    modules.eval()
    logits, ys, trees = [], [], []
    for batch in loader:
        zb = batch[0].to(device)
        yb = batch[1]
        out = editor013_forward_from_z(student, zb, modules)
        logits.append(out["logit"].detach().cpu().numpy())
        trees.append(out["tree_outputs"].detach().cpu().numpy())
        ys.append(np.asarray(yb).reshape(-1))
    y = np.concatenate(ys).reshape(-1)
    lg = np.concatenate(logits)
    met = metrics_from_logits(y, lg)
    met["y"] = y
    met["logits"] = lg
    met["tree_outputs"] = np.concatenate(trees)
    return met


@torch.no_grad()
def evaluate_e2e(
    student: nn.Module,
    modules: Editor013Modules,
    loader,
    device: torch.device,
) -> dict[str, Any]:
    student.eval()
    modules.eval()
    logits, ys, trees, lins, odsts = [], [], [], [], []
    for batch in loader:
        xb = batch[0].to(device)
        yb = batch[1]
        out = editor013_forward(student, xb, modules)
        logits.append(out["logit"].detach().cpu().numpy())
        trees.append(out["tree_outputs"].detach().cpu().numpy())
        lins.append(out["linear_logit"].detach().cpu().numpy())
        odsts.append(out["odst_logit"].detach().cpu().numpy())
        ys.append(np.asarray(yb).reshape(-1))
    y = np.concatenate(ys).reshape(-1)
    lg = np.concatenate(logits)
    met = metrics_from_logits(y, lg)
    met["y"] = y
    met["logits"] = lg
    met["tree_outputs"] = np.concatenate(trees)
    met["linear_logits"] = np.concatenate(lins)
    met["odst_logits"] = np.concatenate(odsts)
    return met
