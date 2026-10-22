"""Conditional degraded-input confirmation using frozen EDITOR-017 perturbations."""

from __future__ import annotations

from typing import Any

import numpy as np
import torch

from editor012_rescue.data import make_xy_loader
from editor012_rescue.losses import make_task_criterion
from editor012_rescue.metrics import metrics_from_logits
from editor017_robustness.constants import NOISE_LEVELS, SOURCE_CHANNELS
from editor017_robustness.perturbations import apply_gaussian_noise, apply_source_ablation, load_r52_train_scaler
from editor018_cross_view.aggregate40 import aggregate40, transform_standard

from .constants import BATCH_SIZE, GRAD_CLIP_NORM, LAMBDA_TEACHER, MAX_EPOCHS, PATIENCE
from .models import SummaryBranch, branch_forward
from .safety import Editor019Blocked
from .train import _set_seed, assert_teacher_lambda, score_branch


def perturb_then_summarise(
    X: np.ndarray,
    *,
    kind: str,
    channel: str | None = None,
    level: float | None = None,
    scaler,
) -> tuple[np.ndarray, np.ndarray]:
    if kind == "source":
        seq_scaler = load_r52_train_scaler()
        Xp = apply_source_ablation(X, str(channel), seq_scaler)
    elif kind == "noise":
        Xp = apply_gaussian_noise(X, float(level))
    else:
        raise Editor019Blocked(f"unknown perturbation {kind}")
    raw, _ = aggregate40(Xp)
    s = transform_standard(scaler, raw)
    if s.shape[0] != X.shape[0]:
        raise Editor019Blocked("degraded sequence and degraded summary view are not aligned")
    return Xp, s


def degraded_metrics(
    branch: SummaryBranch,
    X: np.ndarray,
    y: np.ndarray,
    l1_fn,
    scaler,
    device: torch.device,
) -> dict[str, Any]:
    raw, _ = aggregate40(X)
    s = transform_standard(scaler, raw)
    l1 = l1_fn(X)
    clean = score_branch(branch, s, y, l1, device)
    source_rows = []
    for ch in SOURCE_CHANNELS:
        Xp, sp = perturb_then_summarise(X, kind="source", channel=ch, scaler=scaler)
        lp = l1_fn(Xp)
        met = score_branch(branch, sp, y, lp, device)["metrics"]
        source_rows.append(
            {"channel": ch, "pr_auc": float(met["pr_auc"]), "delta": float(met["pr_auc"]) - float(clean["metrics"]["pr_auc"])}
        )
    noise_rows = []
    for level in NOISE_LEVELS:
        Xp, sp = perturb_then_summarise(X, kind="noise", level=level, scaler=scaler)
        lp = l1_fn(Xp)
        met = score_branch(branch, sp, y, lp, device)["metrics"]
        noise_rows.append(
            {
                "level": level,
                "pr_auc": float(met["pr_auc"]),
                "retention": float(met["pr_auc"]) / max(float(clean["metrics"]["pr_auc"]), 1e-12),
            }
        )
    src_d = [r["delta"] for r in source_rows]
    return {
        "clean_PR_AUC": float(clean["metrics"]["pr_auc"]),
        "source": source_rows,
        "noise": noise_rows,
        "MEAN_SOURCE_DELTA": float(np.mean(src_d)),
        "WORST_SOURCE_DELTA": float(np.min(src_d)),
        "MEAN_NOISE_RETENTION": float(np.mean([r["retention"] for r in noise_rows])),
    }


def train_hardening(
    *,
    family: str,
    seed: int,
    n_trees: int,
    s_clean: np.ndarray,
    y: np.ndarray,
    l1_clean: np.ndarray,
    ens_clean: np.ndarray,
    s_deg: np.ndarray,
    device: torch.device,
    pos_weight: float,
    s_select: np.ndarray,
    y_select: np.ndarray,
    l1_select: np.ndarray,
) -> dict[str, Any]:
    """One predefined hardening: clean task + 0.5 MSE(degraded student, clean neural teacher)."""
    assert_teacher_lambda()
    _set_seed(seed)
    from .models import build_branch_optimizer

    branch = SummaryBranch(family, n_trees=n_trees)
    branch.to(device)
    branch.attach_reference_from_live()
    branch.reference.to(device)
    opt = build_branch_optimizer(branch)
    criterion = make_task_criterion(pos_weight, device)
    loader = make_xy_loader(
        s_clean, y, seed=seed, batch_size=BATCH_SIZE, shuffle=True, extras=[l1_clean, ens_clean, s_deg]
    )
    best_pr = -1.0
    best_state = None
    patience_left = PATIENCE
    for _epoch in range(1, MAX_EPOCHS + 1):
        branch.train()
        for sb, yb, l1b, ensb, sdb in loader:
            sb, yb, l1b, ensb, sdb = sb.to(device), yb.to(device), l1b.to(device), ensb.to(device), sdb.to(device)
            opt.zero_grad(set_to_none=True)
            clean = branch_forward(branch, sb, l1b)
            deg = branch_forward(branch, sdb, l1b)
            loss = criterion(clean["logit"], yb) + float(LAMBDA_TEACHER) * torch.mean((deg["logit"] - ensb.detach()) ** 2)
            loss.backward()
            torch.nn.utils.clip_grad_norm_([p for p in branch.parameters() if p.requires_grad], GRAD_CLIP_NORM)
            opt.step()
        scored = score_branch(branch, s_select, y_select, l1_select, device)
        pr = float(scored["metrics"]["pr_auc"])
        if pr > best_pr:
            best_pr = pr
            best_state = {k: v.detach().cpu().clone() for k, v in branch.live.state_dict().items()}
            patience_left = PATIENCE
        else:
            patience_left -= 1
            if patience_left <= 0:
                break
    assert best_state is not None
    branch.live.load_state_dict(best_state)
    return {"family": family, "seed": seed, "select_PR_AUC": best_pr, "branch": branch}
