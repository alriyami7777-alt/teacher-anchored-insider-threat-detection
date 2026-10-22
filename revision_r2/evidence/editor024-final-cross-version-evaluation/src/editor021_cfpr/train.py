"""Clean-function-preserving representation-robustness trainer."""

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
from editor020_robustness.sampler import apply_sampled_batch

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
)
from .grads import (
    assign_grad_,
    combine_encoder_grads,
    cosine_repr_loss,
    encoder_attention_params,
    flatten_grads,
    odst_head_params,
    unflatten_grads,
)
from .models import (
    assert_initial_match,
    assert_reference_not_in_optimizer,
    build_optimizer,
    candidate_rho,
    load_ta2_reference,
    load_ta2_student,
    save_checkpoint,
)
from .safety import Editor021Blocked, assert_frozen_coefficients


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


def train_candidate(
    *,
    candidate: str,
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
    assert_frozen_coefficients()
    if candidate not in CANDIDATES:
        raise Editor021Blocked(f"unauthorised candidate {candidate}")
    rho = candidate_rho(candidate)
    robustness = bool(CANDIDATES[candidate]["robustness"])
    if robustness and rho <= 0:
        raise Editor021Blocked(f"{candidate} robustness flag/rho mismatch")
    if (not robustness) and rho != 0.0:
        raise Editor021Blocked("CFP0 rho must be exactly 0")
    _set_seed(seed)
    student, start_sha = load_ta2_student(seed, device)
    reference, ref_sha = load_ta2_reference(seed, device)
    if start_sha != ref_sha:
        raise Editor021Blocked("student/reference checkpoint hash mismatch")
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
    best_pr = -1.0
    best_epoch = 0
    best_student = None
    best_metrics = None
    patience_left = patience
    t0 = time.time()
    history: list[dict[str, Any]] = []
    last_grad_stats: dict[str, Any] = {}

    for epoch in range(1, max_epochs + 1):
        student.train()
        reference.eval()
        matched_teacher.eval()
        train_tot = 0.0
        n_obs = 0
        robust_steps = 0
        projected_steps = 0
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
                raise Editor021Blocked("reference tensors must be detached")
            loss_clean = _ta2_clean_loss(
                student_out=clean,
                yb=yb,
                ensb=ensb,
                teacher_out=tr_clean,
                criterion=criterion,
                z_ref=z_ref,
            )
            if not torch.isfinite(loss_clean):
                raise Editor021Blocked(f"non-finite clean loss for {candidate} seed={seed}")
            g_c_all = torch.autograd.grad(
                loss_clean,
                enc_params + head_params,
                retain_graph=False,
                allow_unused=True,
            )
            g_c_enc = flatten_grads(g_c_all[: len(enc_params)], enc_params)
            g_c_head = list(g_c_all[len(enc_params) :])
            alpha = 0.0
            projected = False
            if robustness:
                x_np = xb.detach().cpu().numpy()
                idx_np = idxb.detach().cpu().numpy()
                x_deg = apply_sampled_batch(x_np, idx_np, epoch, scaler)
                xdb = torch.from_numpy(np.asarray(x_deg, dtype=np.float32)).to(device)
                deg = student_forward(student, xdb)
                loss_repr = cosine_repr_loss(deg["z"], h_ref)
                if not torch.isfinite(loss_repr):
                    raise Editor021Blocked(f"non-finite repr loss for {candidate} seed={seed}")
                g_r_list = torch.autograd.grad(
                    loss_repr,
                    enc_params,
                    retain_graph=False,
                    allow_unused=True,
                )
                g_r_enc = flatten_grads(g_r_list, enc_params)
                packed = combine_encoder_grads(g_c_enc, g_r_enc, rho)
                g_enc_final = packed["combined"]
                alpha = float(packed["alpha"])
                projected = bool(packed["projected"])
                last_grad_stats = {k: packed[k] for k in ("alpha", "projected", "dot_before", "dot_after", "gc_norm", "scaled_norm")}
                if float(packed["scaled_norm"]) - float(rho) * float(packed["gc_norm"]) > 1e-6:
                    raise Editor021Blocked("robustness gradient exceeded rho budget")
                robust_steps += 1
                projected_steps += int(projected)
            else:
                g_enc_final = g_c_enc
                last_grad_stats = {"alpha": 0.0, "projected": False, "rho": 0.0}

            enc_grads = unflatten_grads(g_enc_final, enc_params)
            assign_grad_(enc_params, enc_grads)
            assign_grad_(head_params, g_c_head)
            params = [p for p in student.parameters() if p.requires_grad]
            torch.nn.utils.clip_grad_norm_(params, GRAD_CLIP_NORM)
            opt.step()
            for p in reference.parameters():
                if p.requires_grad:
                    raise Editor021Blocked("frozen reference acquired gradients")
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
        row = {
            "epoch": epoch,
            "select_PR_AUC": pr,
            "train_loss": train_tot / max(n_obs, 1),
            "rho": rho,
            "robust_steps": robust_steps,
            "projected_steps": projected_steps,
            **{k: last_grad_stats.get(k) for k in ("alpha", "projected")},
        }
        history.append(row)
        if pr > best_pr:
            best_pr = pr
            best_epoch = epoch
            best_student = clone_state(student)
            best_metrics = {k: v for k, v in met.items() if k not in {"probs", "pred"}}
            patience_left = patience
        else:
            patience_left -= 1
            if patience_left <= 0:
                break

    if best_student is None:
        raise Editor021Blocked(f"no checkpoint for {candidate} seed={seed}")
    student.load_state_dict(best_student)
    path, sha = save_checkpoint(
        candidate=candidate,
        seed=seed,
        student=student,
        extra={
            "best_epoch": best_epoch,
            "select_PR_AUC": best_pr,
            "select_name": select_name,
            "start_sha256": start_sha,
            "rho": rho,
            "lambda_fp": LAMBDA_FP,
        },
    )
    return {
        "candidate": candidate,
        "seed": seed,
        "rho": rho,
        "best_epoch": best_epoch,
        "select_PR_AUC": best_pr,
        "best_metrics": best_metrics,
        "best_checkpoint": path,
        "best_checkpoint_sha256": sha,
        "start_sha256": start_sha,
        "initial_match": match,
        "history": history,
        "training_time": time.time() - t0,
        "select_name": select_name,
    }
