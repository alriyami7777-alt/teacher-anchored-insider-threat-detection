"""Matched student trainer with optional ET1 ensemble anchor and route fidelity."""

from __future__ import annotations

import time
from typing import Any

import numpy as np
import torch
import torch.nn as nn

from .constants import (
    ET1_LOGIT_DISTILL_WEIGHT,
    GRAD_CLIP_NORM,
    LAMBDA_HISTORICAL_SINGLE_TEACHER_LOGIT,
    MAX_EPOCHS,
    PATIENCE,
)
from .evaluate import evaluate_pair
from .losses import ensemble_anchor_loss, make_task_criterion, route_consistency_loss
from .models import (
    assert_teacher_not_in_optimizer,
    build_student_optimizer,
    clone_state,
    student_forward,
    teacher_forward,
)
from .safety import OUTPUT_ROOT, Editor012Blocked, sha256_file


def train_student(
    *,
    condition: str,
    seed: int,
    matched_teacher: nn.Module,
    student: nn.Module,
    train_loader,
    select_loader,
    device: torch.device,
    pos_weight: float,
    ensemble_on: bool,
    route_on: bool,
    lambda_et1: float = ET1_LOGIT_DISTILL_WEIGHT,
    lambda_route: float = 0.5,
    confidence_weight: bool = False,
    agreement_weight: bool = False,
    class_balanced: bool = False,
    max_epochs: int = MAX_EPOCHS,
    patience: int = PATIENCE,
    select_name: str = "validation",
    ensemble_logits_select: np.ndarray | None = None,
) -> dict[str, Any]:
    if LAMBDA_HISTORICAL_SINGLE_TEACHER_LOGIT != 0.0:
        raise Editor012Blocked("historical single-teacher logit anchor must remain retired")
    if (not ensemble_on) and (confidence_weight or agreement_weight or class_balanced):
        raise Editor012Blocked("anchor variants require ensemble teacher predictive anchor ON")

    criterion = make_task_criterion(pos_weight, device)
    opt = build_student_optimizer(student)
    assert_teacher_not_in_optimizer(matched_teacher, opt)
    epoch_rows: list[dict[str, Any]] = []
    best_pr = -1.0
    best_epoch = 0
    best_state = None
    best_metrics = None
    patience_left = patience
    t0 = time.time()

    for epoch in range(1, max_epochs + 1):
        student.train()
        matched_teacher.eval()
        train_tot = train_cls = train_ens = train_route = 0.0
        n_obs = 0
        for batch in train_loader:
            xb = batch[0].to(device)
            yb = batch[1].to(device)
            opt.zero_grad(set_to_none=True)
            with torch.no_grad():
                tr = teacher_forward(matched_teacher, xb)
            sr = student_forward(student, xb)
            l_class = criterion(sr["logit"], yb)
            if ensemble_on:
                ens_logit = batch[2].to(device)
                p_bar = batch[3].to(device) if len(batch) > 3 else None
                p42 = batch[4].to(device) if len(batch) > 4 else None
                p52 = batch[5].to(device) if len(batch) > 5 else None
                p62 = batch[6].to(device) if len(batch) > 6 else None
                l_ens = ensemble_anchor_loss(
                    sr["logit"],
                    ens_logit,
                    yb,
                    confidence_weight=confidence_weight,
                    agreement_weight=agreement_weight,
                    class_balanced_reduction_flag=class_balanced,
                    p_bar=p_bar,
                    p42=p42,
                    p52=p52,
                    p62=p62,
                )
            else:
                l_ens = sr["logit"].new_zeros(())
            if route_on:
                l_route = route_consistency_loss(sr["choices"], tr["choices"])
            else:
                l_route = sr["choices"].new_zeros(())
            loss = l_class
            if ensemble_on:
                loss = loss + float(lambda_et1) * l_ens
            if route_on:
                loss = loss + float(lambda_route) * l_route
            loss.backward()
            torch.nn.utils.clip_grad_norm_(
                [p for p in student.parameters() if p.requires_grad], GRAD_CLIP_NORM
            )
            opt.step()
            bs = int(yb.size(0))
            train_tot += float(loss.item()) * bs
            train_cls += float(l_class.item()) * bs
            train_ens += float(l_ens.item()) * bs if l_ens.numel() else 0.0
            train_route += float(l_route.item()) * bs if l_route.numel() else 0.0
            n_obs += bs

        val = evaluate_pair(
            student=student,
            teacher=matched_teacher,
            loader=select_loader,
            device=device,
            ensemble_logits=ensemble_logits_select,
        )
        pr = float(val["student"]["pr_auc"])
        row = {
            "condition": condition,
            "seed": seed,
            "epoch": epoch,
            "ensemble_on": ensemble_on,
            "route_on": route_on,
            "lambda_et1": float(lambda_et1) if ensemble_on else 0.0,
            "lambda_route": float(lambda_route) if route_on else 0.0,
            "historical_single_teacher_logit_anchor": False,
            "train_total_loss": train_tot / max(n_obs, 1),
            "train_class_loss": train_cls / max(n_obs, 1),
            "train_ensemble_anchor_loss": train_ens / max(n_obs, 1),
            "train_route_consistency_loss": train_route / max(n_obs, 1),
            f"{select_name}_pr_auc": pr,
            f"{select_name}_f1": float(val["student"]["f1"]),
            "teacher_logit_deviation": float(val.get("teacher_logit_deviation", float("nan"))),
            "ensemble_logit_deviation": float(val.get("ensemble_logit_deviation", float("nan"))),
            "route_MAE": float(val.get("route_MAE", float("nan"))),
            "route_KL": float(val.get("route_KL", float("nan"))),
            "hard_route_agreement": float(val.get("hard_route_agreement", float("nan"))),
            "dominant_leaf_agreement": float(val.get("dominant_leaf_agreement", float("nan"))),
        }
        epoch_rows.append(row)
        print(
            f"[EDITOR-012] {condition} seed={seed} epoch={epoch} "
            f"ens={int(ensemble_on)} route={int(route_on)} {select_name}_PR-AUC={pr:.6f}",
            flush=True,
        )
        if pr > best_pr:
            best_pr = pr
            best_epoch = epoch
            best_metrics = val
            best_state = clone_state(student)
            patience_left = patience
        else:
            patience_left -= 1
            if patience_left <= 0:
                break

    if best_state is not None:
        student.load_state_dict(best_state)
    out_dir = OUTPUT_ROOT / condition / f"seed{seed}"
    out_dir.mkdir(parents=True, exist_ok=True)
    ckpt = out_dir / "best_student.pt"
    torch.save(
        {
            "model_state_dict": best_state or clone_state(student),
            "condition": condition,
            "seed": seed,
            "best_epoch": best_epoch,
            "best_select_pr_auc": best_pr,
            "ensemble_on": ensemble_on,
            "route_on": route_on,
            "lambda_et1": float(lambda_et1) if ensemble_on else 0.0,
            "lambda_route": float(lambda_route) if route_on else 0.0,
            "historical_single_teacher_logit_anchor": False,
            "campaign": "EDITOR-012",
            "odst": "ODST-046",
            "test_evaluated": False,
        },
        ckpt,
    )
    bm = best_metrics or val
    s = bm["student"]
    return {
        "condition": condition,
        "seed": seed,
        "best_epoch": best_epoch,
        "select_PR_AUC": float(best_pr),
        "validation_PR_AUC": float(best_pr) if select_name == "validation" else float("nan"),
        "validation_F1": float(s["f1"]),
        "precision": float(s["precision"]),
        "recall": float(s["recall"]),
        "FP": int(s["fp"]),
        "FN": int(s["fn"]),
        "Brier": float(s["Brier"]),
        "log_loss": float(s["log_loss"]),
        "predicted_positive_fraction": float(s["predicted_positive_fraction"]),
        "threshold": float(bm.get("threshold", s.get("threshold", float("nan")))),
        "teacher_logit_deviation": float(bm.get("teacher_logit_deviation", float("nan"))),
        "ensemble_logit_deviation": float(bm.get("ensemble_logit_deviation", float("nan"))),
        "ensemble_prob_deviation": float(bm.get("ensemble_prob_deviation", float("nan"))),
        "route_MAE": float(bm.get("route_MAE", float("nan"))),
        "route_KL": float(bm.get("route_KL", float("nan"))),
        "hard_route_agreement": float(bm.get("hard_route_agreement", float("nan"))),
        "dominant_leaf_agreement": float(bm.get("dominant_leaf_agreement", float("nan"))),
        "training_time": float(time.time() - t0),
        "best_checkpoint": str(ckpt),
        "best_checkpoint_sha256": sha256_file(ckpt),
        "epoch_rows": epoch_rows,
        "ensemble_on": ensemble_on,
        "route_on": route_on,
        "lambda_et1": float(lambda_et1) if ensemble_on else 0.0,
        "lambda_route": float(lambda_route) if route_on else 0.0,
        "historical_single_teacher_logit_anchor": False,
        "y_val": bm["y"],
        "student_logits": bm["student_logits"],
        "teacher_logits": bm.get("teacher_logits"),
        "failure_status": "ok",
    }
