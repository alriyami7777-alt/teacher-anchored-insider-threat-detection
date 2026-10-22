"""Stage-2 sequential refinement trainer and inherited CFP0_FULL trainer."""

from __future__ import annotations

import inspect
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
from editor020_robustness.sampler import apply_sampled_batch
from editor021_cfpr.grads import (
    assign_grad_,
    combine_encoder_grads,
    cosine_repr_loss,
    encoder_attention_params,
    flatten_grads,
    odst_head_params,
    unflatten_grads,
)

from .constants import (
    BATCH_SIZE,
    CANDIDATES,
    EPS_GRAD,
    GRAD_CLIP_NORM,
    LAMBDA_FP,
    LAMBDA_ROUTE,
    LAMBDA_TEACHER,
    MAX_EPOCHS,
    PATIENCE,
    SAMPLER_EPOCH_INDEX,
    STAGE2_EPOCHS,
)
from .models import (
    assert_initial_match,
    assert_reference_not_in_optimizer,
    build_optimizer,
    candidate_rho,
    load_cfp0_full_reference,
    load_cfp0_full_student,
    load_cfp0_reference,
    load_cfp0_student,
    load_ta2_reference,
    load_ta2_student,
    save_checkpoint,
)
from .safety import Editor022Blocked, assert_frozen_coefficients


def _set_seed(seed: int) -> None:
    set_seed = import_set_seed()
    set_seed(int(seed))
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False


def _ta2_clean_loss(
    *,
    student_out: dict[str, torch.Tensor],
    yb: torch.Tensor,
    ensb: torch.Tensor,
    teacher_out: dict[str, torch.Tensor],
    criterion: nn.Module,
    z_ref: torch.Tensor,
) -> torch.Tensor:
    loss = criterion(student_out["logit"], yb)
    loss = loss + float(LAMBDA_TEACHER) * et1_ensemble_logit_mse(student_out["logit"], ensb)
    loss = loss + float(LAMBDA_ROUTE) * route_consistency_loss(student_out["choices"], teacher_out["choices"])
    loss = loss + float(LAMBDA_FP) * torch.mean((student_out["logit"] - z_ref.detach()) ** 2)
    return loss


def _aggregate_grad_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "n_robust_steps": 0,
            "fraction_projected": 0.0,
            "mean_alpha": 0.0,
            "median_alpha": 0.0,
            "mean_gc_norm": 0.0,
            "median_gc_norm": 0.0,
            "mean_scaled_gr_norm": 0.0,
            "median_scaled_gr_norm": 0.0,
            "mean_scaled_over_clean": 0.0,
            "median_scaled_over_clean": 0.0,
        }
    projected = np.asarray([int(r["projected"]) for r in rows], dtype=np.float64)
    alpha = np.asarray([float(r["alpha"]) for r in rows], dtype=np.float64)
    gc = np.asarray([float(r["gc_norm"]) for r in rows], dtype=np.float64)
    scaled = np.asarray([float(r["scaled_norm"]) for r in rows], dtype=np.float64)
    ratio = scaled / np.clip(gc, EPS_GRAD, None)
    return {
        "n_robust_steps": int(len(rows)),
        "fraction_projected": float(projected.mean()),
        "mean_alpha": float(alpha.mean()),
        "median_alpha": float(np.median(alpha)),
        "mean_gc_norm": float(gc.mean()),
        "median_gc_norm": float(np.median(gc)),
        "mean_scaled_gr_norm": float(scaled.mean()),
        "median_scaled_gr_norm": float(np.median(scaled)),
        "mean_scaled_over_clean": float(ratio.mean()),
        "median_scaled_over_clean": float(np.median(ratio)),
    }


def train_stage2_candidate(
    *,
    candidate: str,
    seed: int,
    X: np.ndarray,
    y: np.ndarray,
    ens: np.ndarray,
    matched_teacher: nn.Module,
    device: torch.device,
    pos_weight: float,
    scaler: dict[str, Any],
    start_from: str = "cfp0_inner",
) -> dict[str, Any]:
    """Exactly one Stage-2 epoch. End-of-epoch checkpoint only. Fresh optimiser."""
    assert_frozen_coefficients()
    if int(STAGE2_EPOCHS) != 1:
        raise Editor022Blocked("STAGE2_EPOCHS must remain exactly 1")
    if int(SAMPLER_EPOCH_INDEX) != 1:
        raise Editor022Blocked("SAMPLER_EPOCH_INDEX must remain exactly 1")
    key = str(candidate).replace("_FULL", "")
    if key not in CANDIDATES:
        raise Editor022Blocked(f"unauthorised candidate {candidate}")
    rho = candidate_rho(candidate)
    robustness = bool(CANDIDATES[key]["robustness"])
    if robustness and rho <= 0:
        raise Editor022Blocked(f"{candidate} robustness flag/rho mismatch")
    if (not robustness) and rho != 0.0:
        raise Editor022Blocked("SEQ0 rho must be exactly 0")
    _set_seed(seed)
    if start_from == "cfp0_inner":
        student, start_sha = load_cfp0_student(seed, device)
        reference, ref_sha = load_cfp0_reference(seed, device)
    elif start_from == "cfp0_full":
        student, start_sha = load_cfp0_full_student(seed, device)
        reference, ref_sha = load_cfp0_full_reference(seed, device)
    else:
        raise Editor022Blocked(f"unauthorised Stage-2 start {start_from}")
    if start_sha != ref_sha:
        raise Editor022Blocked("student/reference checkpoint hash mismatch")
    freeze_teacher(reference)
    freeze_teacher(matched_teacher)
    fixture = torch.from_numpy(np.asarray(X[: min(8, len(X))], dtype=np.float32)).to(device)
    match = assert_initial_match(student, reference, fixture)
    opt = build_optimizer(student)
    assert_reference_not_in_optimizer(reference, opt)
    criterion = make_task_criterion(pos_weight, device)
    n = int(len(y))
    index = np.arange(n, dtype=np.float32)
    loader = make_xy_loader(X, y, seed=seed, batch_size=BATCH_SIZE, shuffle=True, extras=[ens, index])
    enc_params = encoder_attention_params(student)
    head_params = odst_head_params(student)
    t0 = time.time()
    step_stats: list[dict[str, Any]] = []

    student.train()
    reference.eval()
    matched_teacher.eval()
    train_tot = 0.0
    n_obs = 0
    n_steps = 0
    for xb, yb, ensb, idxb in loader:
        xb = xb.to(device)
        yb = yb.to(device)
        ensb = ensb.to(device)
        opt.zero_grad(set_to_none=True)
        clean = student_forward(student, xb)
        with torch.no_grad():
            ref_clean = student_forward(reference, xb)
            tr_clean = student_forward(matched_teacher, xb)
        z_ref = ref_clean["logit"].detach()
        h_ref = ref_clean["z"].detach()
        if h_ref.requires_grad or z_ref.requires_grad:
            raise Editor022Blocked("reference tensors must be detached")
        loss_clean = _ta2_clean_loss(
            student_out=clean,
            yb=yb,
            ensb=ensb,
            teacher_out=tr_clean,
            criterion=criterion,
            z_ref=z_ref,
        )
        if not torch.isfinite(loss_clean):
            raise Editor022Blocked(f"non-finite clean loss for {candidate} seed={seed}")
        g_c_all = torch.autograd.grad(
            loss_clean,
            enc_params + head_params,
            retain_graph=False,
            allow_unused=True,
        )
        g_c_enc = flatten_grads(g_c_all[: len(enc_params)], enc_params)
        g_c_head = list(g_c_all[len(enc_params) :])
        if robustness:
            x_np = xb.detach().cpu().numpy()
            idx_np = idxb.detach().cpu().numpy()
            x_deg = apply_sampled_batch(x_np, idx_np, SAMPLER_EPOCH_INDEX, scaler)
            xdb = torch.from_numpy(np.asarray(x_deg, dtype=np.float32)).to(device)
            deg = student_forward(student, xdb)
            loss_repr = cosine_repr_loss(deg["z"], h_ref)
            if not torch.isfinite(loss_repr):
                raise Editor022Blocked(f"non-finite repr loss for {candidate} seed={seed}")
            g_r_list = torch.autograd.grad(
                loss_repr,
                enc_params,
                retain_graph=False,
                allow_unused=True,
            )
            g_r_enc = flatten_grads(g_r_list, enc_params)
            packed = combine_encoder_grads(g_c_enc, g_r_enc, rho)
            g_enc_final = packed["combined"]
            if float(packed["scaled_norm"]) - float(rho) * float(packed["gc_norm"]) > 1e-6:
                raise Editor022Blocked("robustness gradient exceeded rho budget")
            step_stats.append(
                {
                    "alpha": float(packed["alpha"]),
                    "projected": bool(packed["projected"]),
                    "gc_norm": float(packed["gc_norm"]),
                    "scaled_norm": float(packed["scaled_norm"]),
                }
            )
        else:
            g_enc_final = g_c_enc
        enc_grads = unflatten_grads(g_enc_final, enc_params)
        assign_grad_(enc_params, enc_grads)
        assign_grad_(head_params, g_c_head)
        params = [p for p in student.parameters() if p.requires_grad]
        torch.nn.utils.clip_grad_norm_(params, GRAD_CLIP_NORM)
        opt.step()
        for p in reference.parameters():
            if p.requires_grad:
                raise Editor022Blocked("frozen reference acquired gradients")
        bs = int(yb.size(0))
        train_tot += float(loss_clean.detach().cpu()) * bs
        n_obs += bs
        n_steps += 1

    path, sha = save_checkpoint(
        candidate=candidate,
        seed=seed,
        student=student,
        filename="stage2.pt",
        extra={
            "stage2_epochs": STAGE2_EPOCHS,
            "checkpoint_rule": "end_of_epoch_only",
            "sampler_epoch_index": SAMPLER_EPOCH_INDEX,
            "start_sha256": start_sha,
            "rho": rho,
            "lambda_fp": LAMBDA_FP,
            "start_from": start_from,
            "n_optimiser_steps": n_steps,
        },
    )
    return {
        "candidate": candidate,
        "seed": seed,
        "rho": rho,
        "stage2_epochs": STAGE2_EPOCHS,
        "checkpoint_rule": "end_of_epoch_only",
        "n_optimiser_steps": n_steps,
        "train_loss": train_tot / max(n_obs, 1),
        "checkpoint": path,
        "checkpoint_sha256": sha,
        "start_sha256": start_sha,
        "initial_match": match,
        "training_time": time.time() - t0,
        "grad_diagnostics": _aggregate_grad_stats(step_stats),
        "FRESH_STAGE2_OPTIMISER": True,
        "OPTIMISER_STATE_CONTINUED_FROM_CFP0": False,
        "sampler_epoch_index": SAMPLER_EPOCH_INDEX,
        "start_from": start_from,
    }


def train_inherited_cfp0_full(
    *,
    seed: int,
    X: np.ndarray,
    y: np.ndarray,
    ens: np.ndarray,
    X_select: np.ndarray,
    y_select: np.ndarray,
    matched_teacher: nn.Module,
    device: torch.device,
    pos_weight: float,
) -> dict[str, Any]:
    """Inherited EDITOR-021 CFP0 training on full r5.2 TRAIN with validation checkpoint selection."""
    assert_frozen_coefficients()
    _set_seed(seed)
    student, start_sha = load_ta2_student(seed, device)
    reference, ref_sha = load_ta2_reference(seed, device)
    if start_sha != ref_sha:
        raise Editor022Blocked("TA2 student/reference checkpoint hash mismatch")
    freeze_teacher(reference)
    freeze_teacher(matched_teacher)
    fixture = torch.from_numpy(np.asarray(X[: min(8, len(X))], dtype=np.float32)).to(device)
    match = assert_initial_match(student, reference, fixture)
    opt = build_optimizer(student)
    assert_reference_not_in_optimizer(reference, opt)
    criterion = make_task_criterion(pos_weight, device)
    loader = make_xy_loader(X, y, seed=seed, batch_size=BATCH_SIZE, shuffle=True, extras=[ens])
    enc_params = encoder_attention_params(student)
    head_params = odst_head_params(student)
    best_pr = -1.0
    best_epoch = 0
    best_student = None
    best_metrics = None
    patience_left = PATIENCE
    t0 = time.time()
    history: list[dict[str, Any]] = []

    for epoch in range(1, MAX_EPOCHS + 1):
        student.train()
        reference.eval()
        matched_teacher.eval()
        train_tot = 0.0
        n_obs = 0
        for xb, yb, ensb in loader:
            xb = xb.to(device)
            yb = yb.to(device)
            ensb = ensb.to(device)
            opt.zero_grad(set_to_none=True)
            clean = student_forward(student, xb)
            with torch.no_grad():
                ref_clean = student_forward(reference, xb)
                tr_clean = student_forward(matched_teacher, xb)
            z_ref = ref_clean["logit"].detach()
            loss_clean = _ta2_clean_loss(
                student_out=clean,
                yb=yb,
                ensb=ensb,
                teacher_out=tr_clean,
                criterion=criterion,
                z_ref=z_ref,
            )
            if not torch.isfinite(loss_clean):
                raise Editor022Blocked(f"non-finite CFP0_FULL loss seed={seed}")
            g_c_all = torch.autograd.grad(
                loss_clean,
                enc_params + head_params,
                retain_graph=False,
                allow_unused=True,
            )
            g_c_enc = flatten_grads(g_c_all[: len(enc_params)], enc_params)
            g_c_head = list(g_c_all[len(enc_params) :])
            enc_grads = unflatten_grads(g_c_enc, enc_params)
            assign_grad_(enc_params, enc_grads)
            assign_grad_(head_params, g_c_head)
            params = [p for p in student.parameters() if p.requires_grad]
            torch.nn.utils.clip_grad_norm_(params, GRAD_CLIP_NORM)
            opt.step()
            bs = int(yb.size(0))
            train_tot += float(loss_clean.detach().cpu()) * bs
            n_obs += bs

        student.eval()
        with torch.no_grad():
            loader_sel = make_xy_loader(X_select, y_select, seed=0, batch_size=BATCH_SIZE, shuffle=False)
            logits = []
            ys = []
            for xb, yb in loader_sel:
                out = student_forward(student, xb.to(device))
                logits.append(out["logit"].detach().cpu().numpy())
                ys.append(np.asarray(yb).reshape(-1))
            lg = np.concatenate(logits)
            y_np = np.concatenate(ys).reshape(-1)
            met = metrics_from_logits(y_np, lg)
        pr = float(met["pr_auc"])
        history.append({"epoch": epoch, "select_PR_AUC": pr, "train_loss": train_tot / max(n_obs, 1)})
        if pr > best_pr:
            best_pr = pr
            best_epoch = epoch
            best_student = clone_state(student)
            best_metrics = {k: v for k, v in met.items() if k not in {"probs", "pred"}}
            patience_left = PATIENCE
        else:
            patience_left -= 1
            if patience_left <= 0:
                break

    if best_student is None:
        raise Editor022Blocked(f"no CFP0_FULL checkpoint for seed={seed}")
    student.load_state_dict(best_student)
    path, sha = save_checkpoint(
        candidate="CFP0_FULL",
        seed=seed,
        student=student,
        filename="best.pt",
        extra={
            "best_epoch": best_epoch,
            "select_PR_AUC": best_pr,
            "select_name": "validation",
            "start_sha256": start_sha,
            "rho": 0.0,
            "lambda_fp": LAMBDA_FP,
            "inherited_cfp0_procedure": True,
        },
    )
    return {
        "candidate": "CFP0_FULL",
        "seed": seed,
        "rho": 0.0,
        "best_epoch": best_epoch,
        "select_PR_AUC": best_pr,
        "best_metrics": best_metrics,
        "checkpoint": path,
        "checkpoint_sha256": sha,
        "start_sha256": start_sha,
        "initial_match": match,
        "history": history,
        "training_time": time.time() - t0,
    }


def stage2_has_no_early_stopping() -> bool:
    src = inspect.getsource(train_stage2_candidate)
    forbidden = ("patience", "early_stop", "best_pr", "best_epoch", "best_student")
    return all(token not in src for token in forbidden)
