"""Conditional degraded-input training and confirmation. Perturb sequence first, then rebuild 40."""

from __future__ import annotations

from typing import Any

import numpy as np
import torch

from editor012_rescue.data import make_xy_loader
from editor012_rescue.losses import make_task_criterion, route_consistency_loss
from editor012_rescue.metrics import metrics_from_logits
from editor017_robustness.constants import NOISE_LEVELS, NOISE_PERTURBATION_SEED, SOURCE_CHANNELS
from editor017_robustness.perturbations import apply_gaussian_noise, apply_source_ablation, load_r52_train_scaler

from .aggregate40 import aggregate40, transform_standard
from .constants import BATCH_SIZE, GRAD_CLIP_NORM, LAMBDA_TEACHER, MAX_EPOCHS, PATIENCE
from .models import SummaryBranch, build_branch_optimizer, cross_view_forward, teacher_residual
from .safety import Editor018Blocked
from .train import _set_seed, assert_teacher_lambda, score_branch


def perturb_then_summarise(
    X: np.ndarray,
    *,
    kind: str,
    channel: str | None = None,
    level: float | None = None,
    scaler,
) -> tuple[np.ndarray, np.ndarray]:
    """Apply EDITOR-017 perturbation to 20x13, then recompute aligned 40 summaries."""
    if kind == "source":
        seq_scaler = load_r52_train_scaler()
        Xp = apply_source_ablation(X, str(channel), seq_scaler)
    elif kind == "noise":
        Xp = apply_gaussian_noise(X, float(level))
    else:
        raise Editor018Blocked(f"unknown perturbation {kind}")
    raw, _ = aggregate40(Xp)
    s = transform_standard(scaler, raw)
    if s.shape[0] != X.shape[0]:
        raise Editor018Blocked("degraded sequence and degraded summary view are not aligned")
    return Xp, s


def train_robust_head(
    *,
    variant: str,
    family: str,
    seed: int,
    s_clean: np.ndarray,
    y: np.ndarray,
    l1_clean: np.ndarray,
    ens: np.ndarray,
    s_deg: np.ndarray,
    l1_deg: np.ndarray,
    route_teacher: SummaryBranch | None,
    device: torch.device,
    pos_weight: float,
    s_select: np.ndarray,
    y_select: np.ndarray,
    l1_select: np.ndarray,
) -> dict[str, Any]:
    assert_teacher_lambda()
    if variant == "R3" and route_teacher is None:
        return {"variant": "R3", "status": "BLOCKED_ROUTE_IDENTITY"}
    _set_seed(seed)
    branch = SummaryBranch(family)
    branch.to(device)
    branch.attach_reference_from_live()
    branch.reference.to(device)
    opt = build_branch_optimizer(branch)
    criterion = make_task_criterion(pos_weight, device)
    loader = make_xy_loader(
        s_clean, y, seed=seed, batch_size=BATCH_SIZE, shuffle=True, extras=[l1_clean, ens, s_deg, l1_deg]
    )
    best_pr = -1.0
    best_state = None
    patience_left = PATIENCE
    for epoch in range(1, MAX_EPOCHS + 1):
        branch.train()
        for sb, yb, l1b, ensb, sdb, l1db in loader:
            sb, yb, l1b, ensb, sdb, l1db = (
                sb.to(device),
                yb.to(device),
                l1b.to(device),
                ensb.to(device),
                sdb.to(device),
                l1db.to(device),
            )
            opt.zero_grad(set_to_none=True)
            clean = cross_view_forward(branch, sb, l1b)
            loss = criterion(clean["logit"], yb)
            if variant == "R1":
                deg = cross_view_forward(branch, sdb, l1db)
                loss = loss + criterion(deg["logit"], yb)
            elif variant in {"R2", "R3"}:
                deg = cross_view_forward(branch, sdb, l1db)
                loss = loss + float(LAMBDA_TEACHER) * torch.mean((deg["logit"] - ensb.detach()) ** 2)
                if variant == "R3":
                    assert route_teacher is not None
                    with torch.no_grad():
                        ref = cross_view_forward(route_teacher, sb, l1b)
                    loss = loss + float(LAMBDA_TEACHER) * route_consistency_loss(deg["choices"], ref["choices"])
            else:
                target = teacher_residual(ensb, l1b)
                loss = loss + float(LAMBDA_TEACHER) * torch.mean((clean["correction"] - target) ** 2)
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
    return {"variant": variant, "family": family, "seed": seed, "select_PR_AUC": best_pr, "branch": branch}


def degraded_metrics(
    branch: SummaryBranch,
    X: np.ndarray,
    y: np.ndarray,
    l1_fn,
    scaler,
    device: torch.device,
) -> dict[str, Any]:
    """l1_fn(X_perturbed) -> l1 logits aligned to X."""
    raw, _ = aggregate40(X)
    s = transform_standard(scaler, raw)
    l1 = l1_fn(X)
    clean = score_branch(branch, s, y, l1, device)
    source_rows = []
    for ch in SOURCE_CHANNELS:
        Xp, sp = perturb_then_summarise(X, kind="source", channel=ch, scaler=scaler)
        lp = l1_fn(Xp)
        met = score_branch(branch, sp, y, lp, device)["metrics"]
        source_rows.append({"channel": ch, "pr_auc": float(met["pr_auc"]), "delta": float(met["pr_auc"]) - float(clean["metrics"]["pr_auc"])})
    noise_rows = []
    for level in NOISE_LEVELS:
        Xp, sp = perturb_then_summarise(X, kind="noise", level=level, scaler=scaler)
        lp = l1_fn(Xp)
        met = score_branch(branch, sp, y, lp, device)["metrics"]
        noise_rows.append({"level": level, "pr_auc": float(met["pr_auc"]), "retention": float(met["pr_auc"]) / max(float(clean["metrics"]["pr_auc"]), 1e-12)})
    src_d = [r["delta"] for r in source_rows]
    return {
        "clean_PR_AUC": float(clean["metrics"]["pr_auc"]),
        "source": source_rows,
        "noise": noise_rows,
        "MEAN_SOURCE_DELTA": float(np.mean(src_d)),
        "WORST_SOURCE_DELTA": float(np.min(src_d)),
        "MEAN_NOISE_RETENTION": float(np.mean([r["retention"] for r in noise_rows])),
    }
