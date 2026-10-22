"""Frozen-base and end-to-end residual trainers. Distill is ET1 MSE, never historical C5."""

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
from editor013_odst_value.models import Editor013Modules, editor013_forward

from .constants import (
    F11_CHECKPOINTS,
    GRAD_CLIP_NORM,
    L1_CHECKPOINTS,
    LAMBDA_DISTILL,
    LAMBDA_HISTORICAL_SINGLE_TEACHER_LOGIT,
    LAMBDA_RESIDUAL_TEACHER,
    LAMBDA_ROUTE,
    MAX_EPOCHS,
    PATIENCE,
    TOPT_CHECKPOINTS,
)
from .models import (
    Editor015Modules,
    build_editor015_optimizer,
    configure_trainability,
    editor015_forward,
    editor015_forward_from_z,
    make_modules,
)
from .safety import OUTPUT_ROOT, Editor015Blocked, sha256_file


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


def load_ta2(seed: int, device: torch.device) -> tuple[nn.Module, str]:
    spec = F11_CHECKPOINTS[seed]
    sha = hash_gate_checkpoint(spec["checkpoint"], spec["sha256"])
    model = build_odst046_model()
    load_state_dict(model, spec["checkpoint"], strict=True)
    model.to(device)
    model.eval()
    return model, sha


def load_l1_pair(seed: int, device: torch.device) -> tuple[nn.Module, Editor013Modules, str]:
    spec = L1_CHECKPOINTS[seed]
    sha = hash_gate_checkpoint(spec["checkpoint"], spec["sha256"])
    payload = torch.load(spec["checkpoint"], map_location="cpu", weights_only=False)
    student = build_odst046_model()
    student.load_state_dict(payload["student_state_dict"])
    modules = Editor013Modules(family="linear", readout="none", hybrid=False)
    modules.load_state_dict(payload["modules_state_dict"])
    student.to(device)
    modules.to(device)
    student.eval()
    modules.eval()
    return student, modules, sha


def build_residual_from_l1(seed: int, device: torch.device) -> tuple[nn.Module, Editor015Modules, str]:
    """Matched L1 encoder/linear plus function-preserving ODST residual at r=0."""
    l1_student, l1_mods, sha = load_l1_pair(seed, device)
    modules = make_modules()
    modules.linear_head.load_state_dict(l1_mods.linear_head.state_dict())
    modules.attach_reference(l1_student.node_head)
    modules.to(device)
    if modules.reference_odst is not None:
        modules.reference_odst.to(device)
    return l1_student, modules, sha


def _residual_loss(
    out: dict[str, torch.Tensor],
    yb: torch.Tensor,
    batch: tuple,
    *,
    spec: dict[str, Any],
    criterion: nn.Module,
    device: torch.device,
    matched_teacher: nn.Module | None,
    xb: torch.Tensor | None,
) -> torch.Tensor:
    if LAMBDA_HISTORICAL_SINGLE_TEACHER_LOGIT != 0.0:
        raise Editor015Blocked("historical single-teacher logit anchor must remain retired")
    loss = criterion(out["logit"], yb)
    if spec.get("final_distill"):
        ens = batch[2].to(device)
        loss = loss + float(LAMBDA_DISTILL) * et1_ensemble_logit_mse(out["logit"], ens)
    if spec.get("residual_teacher"):
        ens = batch[2].to(device)
        frozen_l1 = batch[3].to(device)
        target = ens.detach() - frozen_l1.detach()
        loss = loss + float(LAMBDA_RESIDUAL_TEACHER) * torch.mean((out["residual_logit"] - target) ** 2)
    if spec.get("route"):
        if matched_teacher is None or xb is None:
            raise Editor015Blocked("route anchor requires matched T-OPT and raw sequences")
        with torch.no_grad():
            tr = historical_student_forward(matched_teacher, xb)
        loss = loss + float(LAMBDA_ROUTE) * route_consistency_loss(out["choices"], tr["choices"])
    return loss


def train_residual(
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
    select_name: str = "inner_select",
    encoder_trainable: bool = False,
    max_epochs: int = MAX_EPOCHS,
    patience: int = PATIENCE,
) -> dict[str, Any]:
    if LAMBDA_HISTORICAL_SINGLE_TEACHER_LOGIT != 0.0:
        raise Editor015Blocked("historical single-teacher logit anchor must remain retired")
    if abs(float(LAMBDA_DISTILL) - 0.5) > 1e-15 or abs(float(LAMBDA_RESIDUAL_TEACHER) - 0.5) > 1e-15:
        raise Editor015Blocked("teacher residual / distill lambda must stay 0.5")
    if spec.get("route") and abs(float(LAMBDA_ROUTE) - 0.5) > 1e-15:
        raise Editor015Blocked("route lambda must stay 0.5 where declared")
    _set_seed(seed)
    student, modules, l1_sha = build_residual_from_l1(start_seed, device)
    linear_trainable = bool(encoder_trainable)
    configure_trainability(
        student, modules, encoder_trainable=encoder_trainable, linear_trainable=linear_trainable
    )
    opt = build_editor015_optimizer(
        student, modules, encoder_trainable=encoder_trainable, linear_trainable=linear_trainable
    )
    if matched_teacher is not None:
        freeze_teacher(matched_teacher)
    criterion = make_task_criterion(pos_weight, device)
    best_pr = -1.0
    best_epoch = 0
    best_student = None
    best_modules = None
    best_ref = None
    best_metrics = None
    patience_left = patience
    t0 = time.time()
    epoch_rows: list[dict[str, Any]] = []

    for epoch in range(1, max_epochs + 1):
        student.train()
        modules.train()
        if not encoder_trainable:
            student.lstm.eval()
            student.attention.eval()
            student.dropout.eval()
        if modules.reference_odst is not None:
            modules.reference_odst.eval()
        if matched_teacher is not None:
            matched_teacher.eval()
        train_tot = 0.0
        n_obs = 0
        for batch in train_loader:
            xb = batch[0].to(device)
            yb = batch[1].to(device)
            opt.zero_grad(set_to_none=True)
            if encoder_trainable or spec.get("route"):
                out = editor015_forward(student, xb, modules)
                loss = _residual_loss(
                    out, yb, batch, spec=spec, criterion=criterion, device=device,
                    matched_teacher=matched_teacher, xb=xb,
                )
            else:
                out = editor015_forward_from_z(student, xb, modules)
                loss = _residual_loss(
                    out, yb, batch, spec=spec, criterion=criterion, device=device,
                    matched_teacher=None, xb=None,
                )
            loss.backward()
            torch.nn.utils.clip_grad_norm_(
                [p for p in list(student.parameters()) + list(modules.parameters()) if p.requires_grad],
                GRAD_CLIP_NORM,
            )
            opt.step()
            if modules.reference_odst is not None:
                for p in modules.reference_odst.parameters():
                    if p.grad is not None:
                        raise Editor015Blocked("frozen reference ODST received a gradient")
            bs = int(yb.size(0))
            train_tot += float(loss.item()) * bs
            n_obs += bs
        val = evaluate_residual(student, modules, select_loader, device, from_z=not encoder_trainable and not spec.get("route"))
        pr = float(val["pr_auc"])
        epoch_rows.append(
            {
                "condition": condition,
                "seed": seed,
                "epoch": epoch,
                "select_pr_auc": pr,
                "train_loss": train_tot / max(n_obs, 1),
            }
        )
        print(
            f"[EDITOR-015] {condition} seed={seed} epoch={epoch} {select_name}_PR-AUC={pr:.6f}",
            flush=True,
        )
        if pr > best_pr:
            best_pr = pr
            best_epoch = epoch
            best_metrics = val
            best_student = clone_state(student)
            best_modules = clone_state(modules)
            best_ref = clone_state(modules.reference_odst) if modules.reference_odst is not None else None
            patience_left = patience
        else:
            patience_left -= 1
            if patience_left <= 0:
                break

    if best_student is not None:
        student.load_state_dict(best_student)
    if best_modules is not None:
        modules.load_state_dict(best_modules)
    if best_ref is not None and modules.reference_odst is not None:
        modules.reference_odst.load_state_dict(best_ref)
    out_dir = OUTPUT_ROOT / condition / f"seed{seed}"
    out_dir.mkdir(parents=True, exist_ok=True)
    ckpt = out_dir / "best.pt"
    torch.save(
        {
            "student_state_dict": best_student or clone_state(student),
            "modules_state_dict": best_modules or clone_state(modules),
            "reference_state_dict": best_ref,
            "condition": condition,
            "seed": seed,
            "start_seed": start_seed,
            "best_epoch": best_epoch,
            "best_select_pr_auc": best_pr,
            "campaign": "EDITOR-015",
            "test_evaluated": False,
            "encoder_trainable": encoder_trainable,
        },
        ckpt,
    )
    bm = best_metrics or val
    np.save(out_dir / "select_logits.npy", bm["logits"])
    np.save(out_dir / "select_y.npy", bm["y"])
    return {
        "condition": condition,
        "seed": seed,
        "start_seed": start_seed,
        "best_epoch": best_epoch,
        "select_PR_AUC": float(best_pr),
        "validation_PR_AUC": float(best_pr),
        "select_F1": float(bm["f1"]),
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
        "l1_start_sha256": l1_sha,
        "y_val": bm["y"],
        "student_logits": bm["logits"],
        "linear_logits": bm.get("linear_logits"),
        "residual_logits": bm.get("residual_logits"),
        "odst_logits": bm.get("odst_logits"),
        "tree_outputs": bm.get("tree_outputs"),
        "epoch_rows": epoch_rows,
        "encoder_trainable": encoder_trainable,
        "official_validation_used": select_name == "validation",
        **{k: spec.get(k) for k in ("final_distill", "residual_teacher", "route", "identity")},
    }


@torch.no_grad()
def evaluate_residual(
    student: nn.Module,
    modules: Editor015Modules,
    loader,
    device: torch.device,
    *,
    from_z: bool = False,
) -> dict[str, Any]:
    student.eval()
    modules.eval()
    if modules.reference_odst is not None:
        modules.reference_odst.eval()
    logits, ys, trees, lins, res, odsts = [], [], [], [], [], []
    for batch in loader:
        xb = batch[0].to(device)
        yb = batch[1]
        out = editor015_forward_from_z(student, xb, modules) if from_z else editor015_forward(student, xb, modules)
        logits.append(out["logit"].detach().cpu().numpy())
        trees.append(out["tree_outputs"].detach().cpu().numpy())
        lins.append(out["linear_logit"].detach().cpu().numpy())
        res.append(out["residual_logit"].detach().cpu().numpy())
        odsts.append(out["odst_logit"].detach().cpu().numpy())
        ys.append(np.asarray(yb).reshape(-1))
    y = np.concatenate(ys).reshape(-1)
    lg = np.concatenate(logits)
    met = metrics_from_logits(y, lg)
    met["y"] = y
    met["logits"] = lg
    met["tree_outputs"] = np.concatenate(trees)
    met["linear_logits"] = np.concatenate(lins)
    met["residual_logits"] = np.concatenate(res)
    met["odst_logits"] = np.concatenate(odsts)
    return met


@torch.no_grad()
def score_l1(student: nn.Module, modules: Editor013Modules, loader, device: torch.device) -> dict[str, np.ndarray]:
    student.eval()
    modules.eval()
    logits, ys = [], []
    for batch in loader:
        xb = batch[0].to(device)
        out = editor013_forward(student, xb, modules)
        logits.append(out["logit"].detach().cpu().numpy())
        ys.append(np.asarray(batch[1]).reshape(-1))
    return {"logits": np.concatenate(logits), "y": np.concatenate(ys).reshape(-1)}


@torch.no_grad()
def score_ta2(student: nn.Module, loader, device: torch.device) -> dict[str, np.ndarray]:
    student.eval()
    logits, ys, trees, choices, leaves = [], [], [], [], []
    for batch in loader:
        xb = batch[0].to(device)
        out = historical_student_forward(student, xb)
        logits.append(out["logit"].detach().cpu().numpy())
        trees.append(out["tree_outputs"].detach().cpu().numpy())
        choices.append(out["choices"].detach().cpu().numpy())
        leaves.append(out["leaf_probs_all"].detach().cpu().numpy())
        ys.append(np.asarray(batch[1]).reshape(-1))
    return {
        "logits": np.concatenate(logits),
        "y": np.concatenate(ys).reshape(-1),
        "tree_outputs": np.concatenate(trees),
        "choices": np.concatenate(choices),
        "leaf_probs_all": np.concatenate(leaves),
    }


def load_trained_residual(path, device: torch.device) -> tuple[nn.Module, Editor015Modules]:
    payload = torch.load(path, map_location="cpu", weights_only=False)
    student = build_odst046_model()
    student.load_state_dict(payload["student_state_dict"])
    modules = make_modules()
    modules.attach_reference(student.node_head)
    modules.load_state_dict(payload["modules_state_dict"])
    if payload.get("reference_state_dict") is not None and modules.reference_odst is not None:
        modules.reference_odst.load_state_dict(payload["reference_state_dict"])
    student.to(device)
    modules.to(device)
    if modules.reference_odst is not None:
        modules.reference_odst.to(device)
    return student, modules
