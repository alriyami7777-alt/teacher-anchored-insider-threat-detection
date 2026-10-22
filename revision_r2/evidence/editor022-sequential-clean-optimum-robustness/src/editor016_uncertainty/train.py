"""Gated specialist trainers. Distill is residual MSE to ensemble-L1; C5 remains retired."""

from __future__ import annotations

import time
from typing import Any

import numpy as np
import torch
import torch.nn as nn

from editor012_rescue.evaluate import hash_gate_checkpoint
from editor012_rescue.losses import make_task_criterion, route_consistency_loss
from editor012_rescue.metrics import metrics_from_logits
from editor012_rescue.models import clone_state, freeze_teacher, student_forward as historical_student_forward
from editor012_rescue.producing import build_odst046_model, import_set_seed, load_state_dict
from editor013_odst_value.models import Editor013Modules, editor013_forward

from .constants import (
    F11_CHECKPOINTS,
    GRAD_CLIP_NORM,
    L1_CHECKPOINTS,
    LAMBDA_HISTORICAL_SINGLE_TEACHER_LOGIT,
    LAMBDA_RESIDUAL_TEACHER,
    LAMBDA_ROUTE,
    LAMBDA_TEACHER,
    MAX_EPOCHS,
    PATIENCE,
    TOPT_CHECKPOINTS,
)
from .gate import apply_cascade
from .models import (
    Editor016Modules,
    build_editor016_optimizer,
    configure_trainability,
    editor016_forward,
    editor016_forward_from_z,
    make_modules,
    reference_grad_l1,
)
from .safety import OUTPUT_ROOT, Editor016Blocked, sha256_file


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


def build_specialist_from_l1(
    seed: int,
    device: torch.device,
    *,
    head: str,
) -> tuple[nn.Module, Editor016Modules, str]:
    l1_student, l1_mods, sha = load_l1_pair(seed, device)
    modules = make_modules(head)
    modules.linear_base.load_state_dict(l1_mods.linear_head.state_dict())
    if head == "odst":
        modules.attach_reference(l1_student.node_head)
    modules.to(device)
    if modules.reference_odst is not None:
        modules.reference_odst.to(device)
    return l1_student, modules, sha


def _specialist_loss(
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
        raise Editor016Blocked("historical single-teacher logit anchor must remain retired")
    loss = criterion(out["logit"], yb)
    if spec.get("teacher_residual"):
        ens = batch[2].to(device)
        frozen_l1 = batch[3].to(device)
        target = ens.detach() - frozen_l1.detach()
        loss = loss + float(LAMBDA_TEACHER) * torch.mean((out["delta"] - target) ** 2)
    if spec.get("route"):
        if out.get("teacher_choices") is not None:
            teacher_choices = out["teacher_choices"]
        else:
            if matched_teacher is None or xb is None:
                raise Editor016Blocked("route anchor requires matched T-OPT choices or raw sequences")
            with torch.no_grad():
                tr = historical_student_forward(matched_teacher, xb)
            teacher_choices = tr["choices"]
        loss = loss + float(LAMBDA_ROUTE) * route_consistency_loss(out["choices"], teacher_choices)
    return loss


def train_specialist(
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
    use_source_l1: bool = True,
) -> dict[str, Any]:
    if LAMBDA_HISTORICAL_SINGLE_TEACHER_LOGIT != 0.0:
        raise Editor016Blocked("historical single-teacher logit anchor must remain retired")
    if abs(float(LAMBDA_TEACHER) - 0.5) > 1e-15 or abs(float(LAMBDA_RESIDUAL_TEACHER) - 0.5) > 1e-15:
        raise Editor016Blocked("teacher residual lambda must stay 0.5")
    if spec.get("route") and abs(float(LAMBDA_ROUTE) - 0.5) > 1e-15:
        raise Editor016Blocked("route lambda must stay 0.5 where declared")
    if spec.get("route") and spec["head"] != "odst":
        raise Editor016Blocked("route anchor is defined only for ODST specialists")
    _set_seed(seed)
    student, modules, l1_sha = build_specialist_from_l1(start_seed, device, head=spec["head"])
    linear_base_trainable = bool(encoder_trainable)
    configure_trainability(
        student,
        modules,
        encoder_trainable=encoder_trainable,
        linear_base_trainable=linear_base_trainable,
    )
    opt = build_editor016_optimizer(
        student,
        modules,
        encoder_trainable=encoder_trainable,
        linear_base_trainable=linear_base_trainable,
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
    from_z = not encoder_trainable

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
            source_l1 = batch[3].to(device)
            gate = batch[4].to(device)
            teacher_choices = batch[5].to(device) if len(batch) > 5 else None
            opt.zero_grad(set_to_none=True)
            if from_z:
                out = editor016_forward_from_z(
                    student,
                    xb,
                    modules,
                    gate=gate,
                    source_l1=source_l1,
                    use_source_l1=use_source_l1,
                    teacher_choices=teacher_choices,
                )
                loss = _specialist_loss(
                    out,
                    yb,
                    batch,
                    spec=spec,
                    criterion=criterion,
                    device=device,
                    matched_teacher=None,
                    xb=None,
                )
            else:
                out = editor016_forward(
                    student,
                    xb,
                    modules,
                    gate=gate,
                    source_l1=source_l1,
                    use_source_l1=False,
                )
                loss = _specialist_loss(
                    out,
                    yb,
                    batch,
                    spec=spec,
                    criterion=criterion,
                    device=device,
                    matched_teacher=matched_teacher,
                    xb=xb,
                )
            loss.backward()
            if reference_grad_l1(modules) != 0.0:
                raise Editor016Blocked("frozen reference ODST received a gradient")
            torch.nn.utils.clip_grad_norm_(
                [p for p in list(student.parameters()) + list(modules.parameters()) if p.requires_grad],
                GRAD_CLIP_NORM,
            )
            opt.step()
            bs = int(yb.size(0))
            train_tot += float(loss.item()) * bs
            n_obs += bs
        val = evaluate_specialist(
            student,
            modules,
            select_loader,
            device,
            from_z=from_z,
            use_source_l1=use_source_l1 if from_z else False,
        )
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
            f"[EDITOR-016] {condition} seed={seed} epoch={epoch} {select_name}_PR-AUC={pr:.6f}",
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
            "head": spec["head"],
            "seed": seed,
            "start_seed": start_seed,
            "best_epoch": best_epoch,
            "best_select_pr_auc": best_pr,
            "campaign": "EDITOR-016",
            "test_evaluated": False,
            "encoder_trainable": encoder_trainable,
        },
        ckpt,
    )
    bm = best_metrics or val
    np.save(out_dir / "select_logits.npy", bm["logits"])
    np.save(out_dir / "select_y.npy", bm["y"])
    np.save(out_dir / "select_delta.npy", bm["deltas"])
    np.save(out_dir / "select_gate.npy", bm["gates"])
    np.save(out_dir / "select_l1.npy", bm["linear_logits"])
    return {
        "condition": condition,
        "head": spec["head"],
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
        "residual_logits": bm.get("deltas"),
        "deltas": bm.get("deltas"),
        "gates": bm.get("gates"),
        "odst_logits": bm.get("odst_logits"),
        "tree_outputs": bm.get("tree_outputs"),
        "choices": bm.get("choices"),
        "leaf_probs_all": bm.get("leaf_probs_all"),
        "epoch_rows": epoch_rows,
        "encoder_trainable": encoder_trainable,
        "official_validation_used": select_name == "validation",
        **{k: spec.get(k) for k in ("teacher_residual", "route", "identity", "q")},
    }


@torch.no_grad()
def evaluate_specialist(
    student: nn.Module,
    modules: Editor016Modules,
    loader,
    device: torch.device,
    *,
    from_z: bool = False,
    use_source_l1: bool = True,
) -> dict[str, Any]:
    student.eval()
    modules.eval()
    if modules.reference_odst is not None:
        modules.reference_odst.eval()
    logits, ys, trees, lins, deltas, gates, odsts, choices, leaves = (
        [],
        [],
        [],
        [],
        [],
        [],
        [],
        [],
        [],
    )
    for batch in loader:
        xb = batch[0].to(device)
        yb = batch[1]
        source_l1 = batch[3].to(device)
        gate = batch[4].to(device)
        if from_z:
            out = editor016_forward_from_z(
                student,
                xb,
                modules,
                gate=gate,
                source_l1=source_l1,
                use_source_l1=use_source_l1,
            )
        else:
            out = editor016_forward(
                student,
                xb,
                modules,
                gate=gate,
                source_l1=source_l1,
                use_source_l1=use_source_l1,
            )
        logits.append(out["logit"].detach().cpu().numpy())
        trees.append(out["tree_outputs"].detach().cpu().numpy())
        lins.append(out["linear_logit"].detach().cpu().numpy())
        deltas.append(out["delta"].detach().cpu().numpy())
        gates.append(out["gate"].detach().cpu().numpy())
        odsts.append(out["odst_logit"].detach().cpu().numpy())
        choices.append(out["choices"].detach().cpu().numpy())
        leaves.append(out["leaf_probs_all"].detach().cpu().numpy())
        ys.append(np.asarray(yb).reshape(-1))
    y = np.concatenate(ys).reshape(-1)
    lg = np.concatenate(logits)
    g = np.concatenate(gates)
    d = np.concatenate(deltas)
    l1 = np.concatenate(lins)
    reconstructed = apply_cascade(l1, d, g)
    if not np.allclose(lg, reconstructed, atol=1e-5, rtol=1e-5):
        raise Editor016Blocked("whole-system prediction does not match L1 + gate * delta")
    confident = g < 0.5
    if confident.any() and not np.allclose(lg[confident], l1[confident], atol=1e-5, rtol=1e-5):
        raise Editor016Blocked("whole-system prediction must equal L1 where gate=0")
    routed = g >= 0.5
    if routed.any() and not np.allclose(lg[routed], l1[routed] + d[routed], atol=1e-5, rtol=1e-5):
        raise Editor016Blocked("whole-system prediction must equal L1+correction where gate=1")
    met = metrics_from_logits(y, lg)
    met["y"] = y
    met["logits"] = lg
    met["tree_outputs"] = np.concatenate(trees)
    met["linear_logits"] = l1
    met["deltas"] = d
    met["gates"] = g
    met["odst_logits"] = np.concatenate(odsts)
    met["choices"] = np.concatenate(choices)
    met["leaf_probs_all"] = np.concatenate(leaves)
    return met


@torch.no_grad()
def score_l1(student: nn.Module, modules: Editor013Modules, loader, device: torch.device) -> dict[str, np.ndarray]:
    student.eval()
    modules.eval()
    logits, ys, zs = [], [], []
    for batch in loader:
        xb = batch[0].to(device)
        out = editor013_forward(student, xb, modules)
        logits.append(out["logit"].detach().cpu().numpy())
        zs.append(out["z"].detach().cpu().numpy())
        ys.append(np.asarray(batch[1]).reshape(-1))
    return {
        "logits": np.concatenate(logits),
        "z": np.concatenate(zs),
        "y": np.concatenate(ys).reshape(-1),
    }


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


def load_trained_specialist(path, device: torch.device, *, head: str) -> tuple[nn.Module, Editor016Modules]:
    payload = torch.load(path, map_location="cpu", weights_only=False)
    student = build_odst046_model()
    student.load_state_dict(payload["student_state_dict"])
    modules = make_modules(payload.get("head", head))
    if modules.head == "odst":
        modules.attach_reference(student.node_head)
    modules.load_state_dict(payload["modules_state_dict"])
    if payload.get("reference_state_dict") is not None and modules.reference_odst is not None:
        modules.reference_odst.load_state_dict(payload["reference_state_dict"])
    student.to(device)
    modules.to(device)
    if modules.reference_odst is not None:
        modules.reference_odst.to(device)
    return student, modules
