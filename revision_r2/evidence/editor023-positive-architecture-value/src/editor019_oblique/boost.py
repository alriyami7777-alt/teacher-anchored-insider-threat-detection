"""Stagewise residual fitting for BSO-DTE40. Tree count is frozen by capacity match."""

from __future__ import annotations

import time
from typing import Any

import numpy as np
import torch
import torch.nn as nn

from editor012_rescue.data import make_xy_loader
from editor012_rescue.losses import make_task_criterion
from editor012_rescue.metrics import metrics_from_logits

from .constants import BATCH_SIZE, GRAD_CLIP_NORM, LAMBDA_TEACHER, LR_BRANCH, MAX_EPOCHS, PATIENCE, WEIGHT_DECAY
from .models import SummaryBranch, branch_forward, clone_frozen_branch, teacher_residual
from .safety import OUTPUT_ROOT, Editor019Blocked, sha256_file
from .train import _pack_result, _set_seed, assert_teacher_lambda, score_branch


def _set_tree_requires_grad(forest: nn.Module, *, trainable_index: int | None) -> None:
    for i, tree in enumerate(forest.trees):
        active = trainable_index is None or i == trainable_index
        for p in tree.parameters():
            p.requires_grad = bool(active)


def _optimizer_for(params: list[nn.Parameter]) -> torch.optim.Optimizer:
    if not params:
        raise Editor019Blocked("boosted stage has no trainable parameters")
    return torch.optim.Adam(params, lr=LR_BRANCH, weight_decay=WEIGHT_DECAY)


def _run_epochs(
    *,
    branch: SummaryBranch,
    opt: torch.optim.Optimizer,
    loader,
    teacher: bool,
    residual_train: np.ndarray | None,
    criterion: nn.Module,
    s_select: np.ndarray,
    y_select: np.ndarray,
    l1_select: np.ndarray,
    device: torch.device,
    condition: str,
    seed: int,
    select_name: str,
    tag: str,
    max_epochs: int,
    patience: int,
) -> tuple[dict[str, Any], int, list[dict[str, Any]]]:
    best_pr = -1.0
    best_epoch = 0
    best_state = None
    best_metrics = None
    patience_left = patience
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
            opt.zero_grad(set_to_none=True)
            out = branch_forward(branch, sb, l1b)
            loss = criterion(out["logit"], yb)
            if teacher:
                loss = loss + float(LAMBDA_TEACHER) * torch.mean((out["correction"] - residual_target) ** 2)
            loss.backward()
            torch.nn.utils.clip_grad_norm_([p for p in branch.parameters() if p.requires_grad], GRAD_CLIP_NORM)
            opt.step()
            train_tot += float(loss.detach().cpu()) * int(yb.numel())
            n_obs += int(yb.numel())
        scored = score_branch(branch, s_select, y_select, l1_select, device)
        pr = float(scored["metrics"]["pr_auc"])
        history.append({"condition": condition, "epoch": epoch, "train_loss": train_tot / max(n_obs, 1), f"{select_name}_PR_AUC": pr})
        print(f"[{tag}] {condition} seed={seed} epoch={epoch} {select_name}_PR-AUC={pr:.6f}", flush=True)
        if pr > best_pr:
            best_pr = pr
            best_epoch = epoch
            best_state = {k: v.detach().cpu().clone() for k, v in branch.live.state_dict().items()}
            best_metrics = scored
            patience_left = patience
        else:
            patience_left -= 1
            if patience_left <= 0:
                break
    assert best_state is not None and best_metrics is not None
    branch.live.load_state_dict(best_state)
    return best_metrics, best_epoch, history


def train_boosted(
    *,
    condition: str,
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
    n_trees: int,
    select_name: str = "inner_select",
    residual_train: np.ndarray | None = None,
    tag: str = "EDITOR-019",
) -> dict[str, Any]:
    """Fit one new tree per stage, then one predeclared joint fine-tune."""
    assert_teacher_lambda()
    _set_seed(seed)
    branch = SummaryBranch("BSO-DTE40", n_trees=n_trees)
    branch.to(device)
    branch.attach_reference_from_live()
    branch.reference.to(device)
    for p in branch.reference.parameters():
        p.requires_grad = False
    criterion = make_task_criterion(pos_weight, device)
    extras = [l1_train, ens_train] if residual_train is None else [l1_train, residual_train]
    loader = make_xy_loader(s_train, y_train, seed=seed, batch_size=BATCH_SIZE, shuffle=True, extras=extras)
    t0 = time.time()
    stage_hist: list[dict[str, Any]] = []
    freeze_log: list[dict[str, Any]] = []

    for stage in range(n_trees):
        _set_tree_requires_grad(branch.live, trainable_index=stage)
        live_ids = {id(p) for p in branch.live.trees[stage].parameters()}
        for i, tree in enumerate(branch.live.trees):
            frozen = i != stage
            for p in tree.parameters():
                if frozen and p.requires_grad:
                    raise Editor019Blocked("earlier boosting stage was not frozen")
                if (not frozen) and (not p.requires_grad):
                    raise Editor019Blocked("new boosting stage has no gradient")
        params = [p for p in branch.live.trees[stage].parameters() if p.requires_grad]
        opt = _optimizer_for(params)
        scored, best_epoch, hist = _run_epochs(
            branch=branch,
            opt=opt,
            loader=loader,
            teacher=teacher,
            residual_train=residual_train,
            criterion=criterion,
            s_select=s_select,
            y_select=y_select,
            l1_select=l1_select,
            device=device,
            condition=f"{condition}/stage{stage}",
            seed=seed,
            select_name=select_name,
            tag=tag,
            max_epochs=MAX_EPOCHS,
            patience=PATIENCE,
        )
        _set_tree_requires_grad(branch.live, trainable_index=-1)
        for p in branch.live.trees[stage].parameters():
            p.requires_grad = False
        freeze_log.append(
            {
                "stage": stage,
                "best_epoch": best_epoch,
                "select_PR_AUC": float(scored["metrics"]["pr_auc"]),
                "frozen_after_fit": True,
                "trainable_ids_were_new_tree_only": True,
                "n_trainable": len(live_ids),
            }
        )
        stage_hist.extend(hist)

    joint_finetune_predeclared = True
    _set_tree_requires_grad(branch.live, trainable_index=None)
    params = [p for p in branch.live.parameters() if p.requires_grad]
    opt = _optimizer_for(params)
    scored, best_epoch, hist = _run_epochs(
        branch=branch,
        opt=opt,
        loader=loader,
        teacher=teacher,
        residual_train=residual_train,
        criterion=criterion,
        s_select=s_select,
        y_select=y_select,
        l1_select=l1_select,
        device=device,
        condition=f"{condition}/joint_finetune",
        seed=seed,
        select_name=select_name,
        tag=tag,
        max_epochs=MAX_EPOCHS,
        patience=PATIENCE,
    )
    stage_hist.extend(hist)
    out_dir = OUTPUT_ROOT / condition / f"seed{seed}"
    out_dir.mkdir(parents=True, exist_ok=True)
    ckpt = out_dir / "best.pt"
    torch.save(
        {
            "condition": condition,
            "family": "BSO-DTE40",
            "teacher": teacher,
            "seed": seed,
            "n_trees": n_trees,
            "live_state_dict": {k: v.detach().cpu().clone() for k, v in branch.live.state_dict().items()},
            "reference_state_dict": {k: v.detach().cpu().clone() for k, v in branch.reference.state_dict().items()},
            "best_epoch": best_epoch,
            "joint_finetune_predeclared": joint_finetune_predeclared,
            "stage_freeze_log": freeze_log,
        },
        ckpt,
    )
    np.save(out_dir / "select_logits.npy", scored["logits"])
    pack = _pack_result(
        condition=condition,
        family="BSO-DTE40",
        teacher=teacher,
        seed=seed,
        best_epoch=best_epoch,
        best_metrics=scored,
        seconds=time.time() - t0,
        ckpt=ckpt,
        history=stage_hist,
        branch=branch,
    )
    pack["stage_freeze_log"] = freeze_log
    pack["joint_finetune_predeclared"] = joint_finetune_predeclared
    pack["n_trees"] = n_trees
    return pack


def prove_stagewise_freeze(*, n_trees: int = 3, batch: int = 8) -> dict[str, Any]:
    torch.manual_seed(0)
    branch = SummaryBranch("BSO-DTE40", n_trees=n_trees)
    s = torch.randn(batch, 40)
    l1 = torch.randn(batch)
    out0 = branch_forward(branch, s, l1)
    if not torch.allclose(out0["correction"], torch.zeros_like(out0["correction"]), atol=1e-6):
        raise Editor019Blocked("boosted forest initial correction is not zero")
    _set_tree_requires_grad(branch.live, trainable_index=1)
    frozen0 = all(not p.requires_grad for p in branch.live.trees[0].parameters())
    live1 = all(p.requires_grad for p in branch.live.trees[1].parameters())
    frozen2 = all(not p.requires_grad for p in branch.live.trees[2].parameters())
    if not (frozen0 and live1 and frozen2):
        raise Editor019Blocked("stagewise freeze pattern failed")
    dummy = branch_forward(branch, s, l1)["branch_logit"].sum()
    dummy.backward()
    if any(p.grad is not None and float(p.grad.abs().sum()) > 0 for p in branch.live.trees[0].parameters()):
        raise Editor019Blocked("frozen earlier stage received gradient")
    if all(p.grad is None or float(p.grad.abs().sum()) == 0 for p in branch.live.trees[1].parameters()):
        raise Editor019Blocked("active boosting stage has zero gradient")
    return {
        "initial_correction_zero": True,
        "earlier_stage_frozen": True,
        "new_stage_trainable": True,
        "joint_finetune_predeclared": True,
    }
