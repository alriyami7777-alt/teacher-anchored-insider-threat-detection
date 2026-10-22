"""Head-only trainers for EDITOR-019 correction branches."""

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
from .constants import BATCH_SIZE, GRAD_CLIP_NORM, LAMBDA_HISTORICAL_SINGLE_TEACHER_LOGIT, LAMBDA_TEACHER, MAX_EPOCHS, PATIENCE
from .models import SummaryBranch, branch_forward, build_branch_optimizer, teacher_residual
from .safety import OUTPUT_ROOT, Editor019Blocked, sha256_file


def _set_seed(seed: int) -> None:
    set_seed = import_set_seed()
    set_seed(int(seed))
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False


def assert_teacher_lambda() -> None:
    if LAMBDA_HISTORICAL_SINGLE_TEACHER_LOGIT != 0.0:
        raise Editor019Blocked("historical single-teacher logit anchor must remain retired")
    if abs(float(LAMBDA_TEACHER) - 0.5) > 1e-15:
        raise Editor019Blocked("lambda teacher must stay exactly 0.5")


def _loss(
    out: dict[str, torch.Tensor],
    yb: torch.Tensor,
    residual_target: torch.Tensor,
    *,
    teacher: bool,
    criterion: nn.Module,
) -> torch.Tensor:
    assert_teacher_lambda()
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
        out = branch_forward(branch, sb.to(device), l1b.to(device))
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


def _pack_result(
    *,
    condition: str,
    family: str,
    teacher: bool,
    seed: int,
    best_epoch: int,
    best_metrics: dict[str, Any],
    seconds: float,
    ckpt,
    history: list[dict[str, Any]],
    branch: SummaryBranch,
) -> dict[str, Any]:
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
        "seconds": seconds,
        "checkpoint": str(ckpt),
        "checkpoint_sha256": sha256_file(ckpt),
        "history": history,
        "select_logits": best_metrics["logits"],
        "select_tree_outputs": best_metrics["tree_outputs"],
        "select_tree_weights": best_metrics["tree_weights"],
        "select_choices": best_metrics["choices"],
        "branch": branch,
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
    n_trees: int | None = None,
    residual_train: np.ndarray | None = None,
    tag: str = "EDITOR-019",
) -> dict[str, Any]:
    assert_teacher_lambda()
    _set_seed(seed)
    branch = SummaryBranch(family, n_trees=n_trees)
    branch.to(device)
    branch.attach_reference_from_live()
    branch.reference.to(device)
    opt = build_branch_optimizer(branch)
    criterion = make_task_criterion(pos_weight, device)
    extras = [l1_train, ens_train] if residual_train is None else [l1_train, residual_train]
    loader = make_xy_loader(s_train, y_train, seed=seed, batch_size=BATCH_SIZE, shuffle=True, extras=extras)
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
        train_tot = 0.0
        n_obs = 0
        for batch in loader:
            sb, yb, l1b, third = batch
            sb = sb.to(device)
            yb = yb.to(device)
            l1b = l1b.to(device)
            third = third.to(device)
            residual_target = third if residual_train is not None else teacher_residual(third, l1b)
            if residual_train is None and not torch.allclose(residual_target, third.detach() - l1b.detach(), atol=1e-6):
                raise Editor019Blocked("teacher residual is not ensemble logit minus L1 logit")
            opt.zero_grad(set_to_none=True)
            out = branch_forward(branch, sb, l1b)
            loss = _loss(out, yb, residual_target, teacher=teacher, criterion=criterion)
            loss.backward()
            torch.nn.utils.clip_grad_norm_([p for p in branch.parameters() if p.requires_grad], GRAD_CLIP_NORM)
            opt.step()
            train_tot += float(loss.detach().cpu()) * int(yb.numel())
            n_obs += int(yb.numel())
        scored = score_branch(branch, s_select, y_select, l1_select, device)
        pr = float(scored["metrics"]["pr_auc"])
        history.append(
            {
                "condition": condition,
                "epoch": epoch,
                "train_loss": train_tot / max(n_obs, 1),
                f"{select_name}_PR_AUC": pr,
                f"{select_name}_F1": float(scored["metrics"]["f1"]),
                f"{select_name}_Brier": float(scored["metrics"]["Brier"]),
                f"{select_name}_log_loss": float(scored["metrics"]["log_loss"]),
            }
        )
        print(f"[{tag}] {condition} seed={seed} epoch={epoch} {select_name}_PR-AUC={pr:.6f}", flush=True)
        if pr > best_pr:
            best_pr = pr
            best_epoch = epoch
            best_state = {
                "live": {k: v.detach().cpu().clone() for k, v in branch.live.state_dict().items()},
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
    out_dir = OUTPUT_ROOT / condition / f"seed{seed}"
    out_dir.mkdir(parents=True, exist_ok=True)
    ckpt = out_dir / "best.pt"
    torch.save(
        {
            "condition": condition,
            "family": family,
            "teacher": teacher,
            "seed": seed,
            "n_trees": branch.n_trees,
            "live_state_dict": best_state["live"],
            "reference_state_dict": best_state["reference"],
            "best_epoch": best_epoch,
        },
        ckpt,
    )
    np.save(out_dir / "select_logits.npy", best_metrics["logits"])
    return _pack_result(
        condition=condition,
        family=family,
        teacher=teacher,
        seed=seed,
        best_epoch=best_epoch,
        best_metrics=best_metrics,
        seconds=time.time() - t0,
        ckpt=ckpt,
        history=history,
        branch=branch,
    )


def load_branch(family: str, payload: dict[str, Any], device: torch.device, n_trees: int | None = None) -> SummaryBranch:
    n = payload.get("n_trees", n_trees)
    branch = SummaryBranch(family, n_trees=n)
    branch.live.load_state_dict(payload["live_state_dict"])
    if payload.get("reference_state_dict") is not None:
        branch.reference.load_state_dict(payload["reference_state_dict"])
    else:
        branch.attach_reference_from_live()
    branch.to(device)
    branch.reference.to(device)
    return branch
