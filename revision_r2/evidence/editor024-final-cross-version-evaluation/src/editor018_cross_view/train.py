"""Head-only and end-to-end trainers for cross-view correction branches."""

from __future__ import annotations

import time
from typing import Any

import numpy as np
import torch
import torch.nn as nn

from editor012_rescue.data import make_xy_loader
from editor012_rescue.losses import make_task_criterion
from editor012_rescue.metrics import metrics_from_logits
from editor012_rescue.producing import import_set_seed
from editor013_odst_value.models import editor013_forward
from editor015_residual.train import load_l1_pair

from .constants import (
    BATCH_SIZE,
    GRAD_CLIP_NORM,
    LAMBDA_HISTORICAL_SINGLE_TEACHER_LOGIT,
    LAMBDA_TEACHER,
    MAX_EPOCHS,
    PATIENCE,
)
from .models import (
    SummaryBranch,
    build_branch_optimizer,
    build_e2e_optimizer,
    cross_view_forward,
    teacher_residual,
)
from .safety import OUTPUT_ROOT, Editor018Blocked, sha256_file


def _set_seed(seed: int) -> None:
    set_seed = import_set_seed()
    set_seed(int(seed))
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False


def assert_teacher_lambda() -> None:
    if LAMBDA_HISTORICAL_SINGLE_TEACHER_LOGIT != 0.0:
        raise Editor018Blocked("historical single-teacher logit anchor must remain retired")
    if abs(float(LAMBDA_TEACHER) - 0.5) > 1e-15:
        raise Editor018Blocked("lambda teacher must stay exactly 0.5")


def _loss(
    out: dict[str, torch.Tensor],
    yb: torch.Tensor,
    ens: torch.Tensor,
    frozen_l1: torch.Tensor,
    *,
    teacher: bool,
    criterion: nn.Module,
) -> torch.Tensor:
    assert_teacher_lambda()
    residual_target = teacher_residual(ens, frozen_l1)
    if not torch.allclose(residual_target, ens.detach() - frozen_l1.detach(), atol=1e-6):
        raise Editor018Blocked("teacher residual is not ensemble logit minus L1 logit")
    loss = criterion(out["logit"], yb)
    if teacher:
        loss = loss + float(LAMBDA_TEACHER) * torch.mean((out["correction"] - residual_target) ** 2)
    return loss


@torch.no_grad()
def score_branch(
    branch: SummaryBranch,
    s: np.ndarray,
    y: np.ndarray,
    l1: np.ndarray,
    device: torch.device,
) -> dict[str, Any]:
    branch.eval()
    loader = make_xy_loader(s, y, seed=0, batch_size=BATCH_SIZE, shuffle=False, extras=[l1])
    logits = []
    corrections = []
    trees = []
    weights = []
    choices = []
    for sb, yb, l1b in loader:
        out = cross_view_forward(branch, sb.to(device), l1b.to(device))
        logits.append(out["logit"].detach().cpu().numpy())
        corrections.append(out["correction"].detach().cpu().numpy())
        trees.append(out["tree_outputs"].detach().cpu().numpy())
        weights.append(out["tree_weights"].detach().cpu().numpy())
        choices.append(out["choices"].detach().cpu().numpy())
    logits_np = np.concatenate(logits)
    met = metrics_from_logits(y, logits_np)
    return {
        "metrics": {k: v for k, v in met.items() if k not in {"probs", "pred"}},
        "logits": logits_np.astype(np.float32),
        "correction": np.concatenate(corrections).astype(np.float32),
        "tree_outputs": np.concatenate(trees).astype(np.float32),
        "tree_weights": np.concatenate(weights).astype(np.float32),
        "choices": np.concatenate(choices).astype(np.float32),
        "y": np.asarray(y).reshape(-1),
    }


def train_head_only(
    *,
    condition: str,
    family: str,
    teacher: bool,
    seed: int,
    s_train: np.ndarray,
    y_train: np.ndarray,
    l1_train: np.ndarray,
    ens_train: np.ndarray,
    s_select: np.ndarray,
    y_select: np.ndarray,
    l1_select: np.ndarray,
    device: torch.device,
    pos_weight: float,
    select_name: str = "inner_select",
    max_epochs: int = MAX_EPOCHS,
    patience: int = PATIENCE,
) -> dict[str, Any]:
    assert_teacher_lambda()
    _set_seed(seed)
    branch = SummaryBranch(family)
    branch.to(device)
    branch.attach_reference_from_live()
    branch.reference.to(device)
    if branch.reference_gate is not None:
        branch.reference_gate.to(device)
    opt = build_branch_optimizer(branch)
    criterion = make_task_criterion(pos_weight, device)
    loader = make_xy_loader(
        s_train,
        y_train,
        seed=seed,
        batch_size=BATCH_SIZE,
        shuffle=True,
        extras=[l1_train, ens_train],
    )
    best_pr = -1.0
    best_epoch = 0
    best_state = None
    best_metrics = None
    patience_left = patience
    t0 = time.time()
    history: list[dict[str, Any]] = []

    for epoch in range(1, max_epochs + 1):
        branch.train()
        branch.reference.eval()
        if branch.reference_gate is not None:
            branch.reference_gate.eval()
        train_tot = 0.0
        n_obs = 0
        for sb, yb, l1b, ensb in loader:
            sb = sb.to(device)
            yb = yb.to(device)
            l1b = l1b.to(device)
            ensb = ensb.to(device)
            opt.zero_grad(set_to_none=True)
            out = cross_view_forward(branch, sb, l1b)
            loss = _loss(out, yb, ensb, l1b, teacher=teacher, criterion=criterion)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(
                [p for p in branch.parameters() if p.requires_grad], GRAD_CLIP_NORM
            )
            opt.step()
            train_tot += float(loss.detach().cpu()) * int(yb.numel())
            n_obs += int(yb.numel())
        scored = score_branch(branch, s_select, y_select, l1_select, device)
        pr = float(scored["metrics"]["pr_auc"])
        row = {
            "condition": condition,
            "epoch": epoch,
            "train_loss": train_tot / max(n_obs, 1),
            f"{select_name}_PR_AUC": pr,
            f"{select_name}_F1": float(scored["metrics"]["f1"]),
            f"{select_name}_Brier": float(scored["metrics"]["Brier"]),
            f"{select_name}_log_loss": float(scored["metrics"]["log_loss"]),
        }
        history.append(row)
        print(f"[EDITOR-018] {condition} seed={seed} epoch={epoch} {select_name}_PR-AUC={pr:.6f}", flush=True)
        if pr > best_pr:
            best_pr = pr
            best_epoch = epoch
            best_state = {
                "live": {k: v.detach().cpu().clone() for k, v in branch.live.state_dict().items()},
                "gate": None
                if branch.gate is None
                else {k: v.detach().cpu().clone() for k, v in branch.gate.state_dict().items()},
                "reference": {k: v.detach().cpu().clone() for k, v in branch.reference.state_dict().items()},
            }
            best_metrics = scored
            patience_left = patience
        else:
            patience_left -= 1
            if patience_left <= 0:
                break

    assert best_state is not None and best_metrics is not None
    branch.live.load_state_dict(best_state["live"])
    if branch.gate is not None and best_state["gate"] is not None:
        branch.gate.load_state_dict(best_state["gate"])
    out_dir = OUTPUT_ROOT / condition / f"seed{seed}"
    out_dir.mkdir(parents=True, exist_ok=True)
    ckpt = out_dir / "best.pt"
    torch.save(
        {
            "condition": condition,
            "family": family,
            "teacher": teacher,
            "seed": seed,
            "live_state_dict": best_state["live"],
            "gate_state_dict": best_state["gate"],
            "reference_state_dict": best_state["reference"],
            "best_epoch": best_epoch,
        },
        ckpt,
    )
    np.save(out_dir / "select_logits.npy", best_metrics["logits"])
    return {
        "condition": condition,
        "family": family,
        "teacher": teacher,
        "seed": seed,
        "best_epoch": best_epoch,
        "select_PR_AUC": float(best_metrics["metrics"]["pr_auc"]),
        "select_F1": float(best_metrics["metrics"]["f1"]),
        "select_Brier": float(best_metrics["metrics"]["Brier"]),
        "select_log_loss": float(best_metrics["metrics"]["log_loss"]),
        "precision": float(best_metrics["metrics"]["precision"]),
        "recall": float(best_metrics["metrics"]["recall"]),
        "threshold": float(best_metrics["metrics"]["threshold"]),
        "predicted_positive_fraction": float(best_metrics["metrics"]["predicted_positive_fraction"]),
        "seconds": time.time() - t0,
        "checkpoint": str(ckpt),
        "checkpoint_sha256": sha256_file(ckpt),
        "history": history,
        "select_logits": best_metrics["logits"],
        "select_tree_outputs": best_metrics["tree_outputs"],
        "select_tree_weights": best_metrics["tree_weights"],
        "select_choices": best_metrics["choices"],
        "branch": branch,
    }


def load_branch(family: str, payload: dict[str, Any], device: torch.device) -> SummaryBranch:
    branch = SummaryBranch(family)
    branch.live.load_state_dict(payload["live_state_dict"])
    if branch.gate is not None and payload.get("gate_state_dict") is not None:
        branch.gate.load_state_dict(payload["gate_state_dict"])
    if payload.get("reference_state_dict") is not None:
        branch.reference.load_state_dict(payload["reference_state_dict"])
    else:
        branch.attach_reference_from_live()
    branch.to(device)
    branch.reference.to(device)
    if branch.reference_gate is not None:
        branch.reference_gate.to(device)
    return branch


def train_e2e(
    *,
    condition: str,
    family: str,
    teacher: bool,
    seed: int,
    l1_seed: int,
    X_train: np.ndarray,
    s_train: np.ndarray,
    y_train: np.ndarray,
    frozen_l1_train: np.ndarray,
    ens_train: np.ndarray,
    X_select: np.ndarray,
    s_select: np.ndarray,
    y_select: np.ndarray,
    frozen_l1_select: np.ndarray,
    device: torch.device,
    pos_weight: float,
    max_epochs: int = MAX_EPOCHS,
    patience: int = PATIENCE,
) -> dict[str, Any]:
    assert_teacher_lambda()
    _set_seed(seed)
    student, l1_modules, _ = load_l1_pair(l1_seed, device)
    branch = SummaryBranch(family)
    branch.to(device)
    branch.attach_reference_from_live()
    branch.reference.to(device)
    if branch.reference_gate is not None:
        branch.reference_gate.to(device)
    opt = build_e2e_optimizer(student, l1_modules, branch)
    criterion = make_task_criterion(pos_weight, device)
    loader = make_xy_loader(
        X_train,
        y_train,
        seed=seed,
        batch_size=BATCH_SIZE,
        shuffle=True,
        extras=[s_train, frozen_l1_train, ens_train],
    )
    best_pr = -1.0
    best_epoch = 0
    best = None
    t0 = time.time()
    patience_left = patience
    history: list[dict[str, Any]] = []

    for epoch in range(1, max_epochs + 1):
        student.train()
        l1_modules.train()
        branch.train()
        branch.reference.eval()
        train_tot = 0.0
        n_obs = 0
        for xb, yb, sb, l1b, ensb in loader:
            xb = xb.to(device)
            yb = yb.to(device)
            sb = sb.to(device)
            l1b = l1b.to(device)
            ensb = ensb.to(device)
            opt.zero_grad(set_to_none=True)
            live_l1 = editor013_forward(student, xb, l1_modules)["logit"]
            out = cross_view_forward(branch, sb, live_l1)
            loss = _loss(out, yb, ensb, l1b, teacher=teacher, criterion=criterion)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(
                [p for p in list(student.parameters()) + list(l1_modules.parameters()) + list(branch.parameters()) if p.requires_grad],
                GRAD_CLIP_NORM,
            )
            opt.step()
            train_tot += float(loss.detach().cpu()) * int(yb.numel())
            n_obs += int(yb.numel())
        scored = score_e2e(student, l1_modules, branch, X_select, s_select, y_select, device)
        pr = float(scored["metrics"]["pr_auc"])
        history.append({"epoch": epoch, "select_PR_AUC": pr, "train_loss": train_tot / max(n_obs, 1)})
        print(f"[EDITOR-018] E2E {condition} seed={seed} epoch={epoch} INNER_SELECT_PR-AUC={pr:.6f}", flush=True)
        if pr > best_pr:
            best_pr = pr
            best_epoch = epoch
            best = {
                "student": {k: v.detach().cpu().clone() for k, v in student.state_dict().items()},
                "l1_modules": {k: v.detach().cpu().clone() for k, v in l1_modules.state_dict().items()},
                "live": {k: v.detach().cpu().clone() for k, v in branch.live.state_dict().items()},
                "gate": None
                if branch.gate is None
                else {k: v.detach().cpu().clone() for k, v in branch.gate.state_dict().items()},
                "metrics": scored,
            }
            patience_left = patience
        else:
            patience_left -= 1
            if patience_left <= 0:
                break
    assert best is not None
    out_dir = OUTPUT_ROOT / f"{condition}_E2E" / f"seed{seed}"
    out_dir.mkdir(parents=True, exist_ok=True)
    ckpt = out_dir / "best.pt"
    torch.save({"condition": condition, "family": family, "teacher": teacher, "seed": seed, **best}, ckpt)
    return {
        "condition": condition,
        "mode": "e2e",
        "seed": seed,
        "best_epoch": best_epoch,
        "select_PR_AUC": float(best["metrics"]["metrics"]["pr_auc"]),
        "select_F1": float(best["metrics"]["metrics"]["f1"]),
        "select_Brier": float(best["metrics"]["metrics"]["Brier"]),
        "select_log_loss": float(best["metrics"]["metrics"]["log_loss"]),
        "seconds": time.time() - t0,
        "checkpoint": str(ckpt),
        "checkpoint_sha256": sha256_file(ckpt),
        "history": history,
        "select_logits": best["metrics"]["logits"],
    }


@torch.no_grad()
def score_e2e(
    student: nn.Module,
    l1_modules: nn.Module,
    branch: SummaryBranch,
    X: np.ndarray,
    s: np.ndarray,
    y: np.ndarray,
    device: torch.device,
) -> dict[str, Any]:
    student.eval()
    l1_modules.eval()
    branch.eval()
    loader = make_xy_loader(X, y, seed=0, batch_size=BATCH_SIZE, shuffle=False, extras=[s])
    logits = []
    for xb, yb, sb in loader:
        live_l1 = editor013_forward(student, xb.to(device), l1_modules)["logit"]
        out = cross_view_forward(branch, sb.to(device), live_l1)
        logits.append(out["logit"].detach().cpu().numpy())
    logits_np = np.concatenate(logits)
    met = metrics_from_logits(y, logits_np)
    return {"metrics": {k: v for k, v in met.items() if k not in {"probs", "pred"}}, "logits": logits_np.astype(np.float32)}
