"""Endpoint-matched teachers and students. Original 13-feature representation only."""

from __future__ import annotations

import inspect
import time
from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn as nn

from editor012_rescue.data import make_xy_loader
from editor012_rescue.evaluate import evaluate_pair
from editor012_rescue.losses import ensemble_anchor_loss, make_task_criterion, route_consistency_loss
from editor012_rescue.metrics import metrics_from_logits
from editor012_rescue.models import (
    architecture_identity,
    assert_odst046,
    assert_teacher_not_in_optimizer,
    build_student_optimizer,
    clone_state,
    enable_student,
    freeze_teacher,
    student_forward,
    teacher_forward,
)
from editor012_rescue.producing import build_odst046_model, import_set_seed, load_state_dict
from editor012_rescue.constants import LR_ODST, WEIGHT_DECAY
from editor013_odst_value.models import (
    build_editor013_optimizer,
    configure_trainability,
    editor013_forward,
    make_modules,
)
from editor013_odst_value.constants import LR_LINEAR
from editor026_user_relative.train import (
    ATTENTION_LINEAR_PRODUCING,
    GRAD_CLIP_NORM,
    LAMBDA_HISTORICAL_SINGLE_TEACHER_LOGIT,
    MAX_EPOCHS,
    PATIENCE,
    POS_WEIGHT_MULT,
    pos_weight_from_y,
)

from .constants import BATCH_SIZE, OUTPUT_REL, STUDENT_SPECS
from .safety import OUTPUT_ROOT, Editor029Blocked, sha256_file


def _set_seed(seed: int) -> None:
    set_seed = import_set_seed()
    set_seed(int(seed))
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False


def _device() -> torch.device:
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def build_teacher_optimizer(teacher: nn.Module) -> torch.optim.Optimizer:
    plist = [p for p in teacher.node_head.parameters() if p.requires_grad]
    if not plist:
        raise Editor029Blocked("no trainable teacher ODST parameters")
    return torch.optim.Adam(plist, lr=LR_ODST, weight_decay=WEIGHT_DECAY)


def _enable_attention_linear(model: nn.Module) -> None:
    for p in model.lstm.parameters():
        p.requires_grad = True
    for p in model.attention.parameters():
        p.requires_grad = True
    for p in model.linear_head.parameters():
        p.requires_grad = True
    for p in model.node_head.parameters():
        p.requires_grad = False
    model.residual_scale_logit.requires_grad = False
    for p in model.sample_gate.parameters():
        p.requires_grad = False


def _linear_logit(model: nn.Module, x: torch.Tensor) -> torch.Tensor:
    z, enc = model.encode_attention_h(x)
    return enc["linear_logit"]


@torch.no_grad()
def _score_linear(model: nn.Module, loader, device: torch.device) -> dict[str, np.ndarray]:
    model.eval()
    logits, ys = [], []
    for batch in loader:
        xb = batch[0].to(device)
        logits.append(_linear_logit(model, xb).detach().cpu().numpy())
        ys.append(np.asarray(batch[1]).reshape(-1))
    return {"logits": np.concatenate(logits), "y": np.concatenate(ys).reshape(-1)}


def teacher_reproduction_gate() -> dict[str, Any]:
    """Producing code wins over manuscript prose. Fail closed if ambiguous."""
    from editor012_rescue import train as e012_train
    from editor026_user_relative import train as e026_train

    required = {
        "editor026_attention_linear": hasattr(e026_train, "train_attention_linear"),
        "editor026_ur_teacher": hasattr(e026_train, "train_ur_teacher"),
        "editor012_train_student": hasattr(e012_train, "train_student"),
    }
    src_al = inspect.getsource(e026_train.train_attention_linear)
    src_t = inspect.getsource(e026_train.train_ur_teacher)
    src_s = inspect.getsource(e012_train.train_student)
    recipe_ok = (
        "ATTENTION_LINEAR_PRODUCING" in src_al
        and "apply_frozen_node_trainability" in src_t
        and "data_aware_initialize_from_batch" in src_t
        and "ensemble_anchor_loss" in src_s
        and "route_consistency_loss" in src_s
    )
    if not all(required.values()) or not recipe_ok:
        raise Editor029Blocked("EDITOR029_ENDPOINT_TEACHER_GATE = FAIL")
    if LAMBDA_HISTORICAL_SINGLE_TEACHER_LOGIT != 0.0:
        raise Editor029Blocked("historical single-teacher logit anchor must remain retired")
    return {
        "EDITOR029_ENDPOINT_TEACHER_GATE": "PASS",
        "producing_attention_linear": "editor026_user_relative.train.train_attention_linear",
        "producing_teacher": "editor011 train_teacher recipe via editor026.train_ur_teacher",
        "producing_student": "editor012_rescue.train.train_student",
        "producing_linear": "editor013 L1 / editor026.train_ur_linear_student",
        "recipe_markers_present": recipe_ok,
        "ensemble": "equal-weight predictive consensus of endpoint-matched teachers",
        "route": "matched-teacher route consistency, seed-specific teacher",
        "r52_test_used": False,
        "new_scaler_fit": False,
    }


def train_endpoint_attention_linear(
    *,
    seed: int,
    x_train: np.ndarray,
    y_train: np.ndarray,
    x_val: np.ndarray,
    y_val: np.ndarray,
    device: torch.device | None = None,
) -> dict[str, Any]:
    if LAMBDA_HISTORICAL_SINGLE_TEACHER_LOGIT != 0.0:
        raise Editor029Blocked("historical single-teacher logit anchor must remain retired")
    device = device or _device()
    _set_seed(seed)
    cfg = ATTENTION_LINEAR_PRODUCING
    model = build_odst046_model()
    _enable_attention_linear(model)
    model.to(device)
    pw = pos_weight_from_y(y_train, float(cfg["pos_weight_multiplier"]))
    criterion = make_task_criterion(pw, device)
    params = [p for p in model.parameters() if p.requires_grad]
    opt = torch.optim.Adam(params, lr=float(cfg["learning_rate"]), weight_decay=float(cfg["weight_decay"]))
    sched = torch.optim.lr_scheduler.ReduceLROnPlateau(
        opt,
        mode=str(cfg["scheduler"]["mode"]),
        factor=float(cfg["scheduler"]["factor"]),
        patience=int(cfg["scheduler"]["patience"]),
        min_lr=float(cfg["scheduler"]["min_lr"]),
    )
    train_loader = make_xy_loader(x_train, y_train, seed=seed, shuffle=True)
    val_loader = make_xy_loader(x_val, y_val, seed=seed, shuffle=False)
    best_pr = -1.0
    best_epoch = 0
    best_state = None
    patience_left = int(cfg["patience"])
    rows = []
    t0 = time.time()
    for epoch in range(1, int(cfg["max_epochs"]) + 1):
        model.train()
        running = 0.0
        n_obs = 0
        for xb, yb in train_loader:
            xb = xb.to(device)
            yb = yb.to(device)
            opt.zero_grad(set_to_none=True)
            logit = _linear_logit(model, xb)
            loss = criterion(logit, yb)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(params, float(cfg["grad_clip_norm"]))
            opt.step()
            bs = int(yb.size(0))
            running += float(loss.item()) * bs
            n_obs += bs
        scored = _score_linear(model, val_loader, device)
        met = metrics_from_logits(scored["y"], scored["logits"])
        pr = float(met["pr_auc"])
        sched.step(pr)
        rows.append({"epoch": epoch, "train_loss": running / max(n_obs, 1), "validation_pr_auc": pr})
        print(f"[EDITOR-029] EP_ATTENTION_LINEAR seed={seed} epoch={epoch} val_PR-AUC={pr:.6f}", flush=True)
        if pr > best_pr:
            best_pr = pr
            best_epoch = epoch
            best_state = clone_state(model)
            patience_left = int(cfg["patience"])
        else:
            patience_left -= 1
            if patience_left <= 0:
                break
    if best_state is not None:
        model.load_state_dict(best_state)
    out_dir = OUTPUT_ROOT / "teachers" / "EP_ATTENTION_LINEAR" / f"seed{seed}"
    out_dir.mkdir(parents=True, exist_ok=True)
    ckpt = out_dir / "best.pt"
    torch.save(
        {
            "model_state_dict": best_state or clone_state(model),
            "condition": "EP_ATTENTION_LINEAR",
            "seed": seed,
            "best_epoch": best_epoch,
            "best_val_pr_auc": best_pr,
            "campaign": "EDITOR-029",
            "checkpoint_selection": "r5.2 ENDPOINT VALIDATION PR-AUC",
            "r52_test_used": False,
        },
        ckpt,
    )
    return {
        "condition": "EP_ATTENTION_LINEAR",
        "seed": seed,
        "best_epoch": best_epoch,
        "validation_PR_AUC": float(best_pr),
        "best_checkpoint": str(ckpt),
        "best_checkpoint_sha256": sha256_file(ckpt),
        "pos_weight": pw,
        "pos_weight_multiplier": float(cfg["pos_weight_multiplier"]),
        "training_time": float(time.time() - t0),
        "epoch_rows": rows,
        "r52_test_used": False,
    }


def train_endpoint_teacher(
    *,
    seed: int,
    encoder_ckpt: str,
    x_train: np.ndarray,
    y_train: np.ndarray,
    x_val: np.ndarray,
    y_val: np.ndarray,
    device: torch.device | None = None,
) -> dict[str, Any]:
    """EDITOR-011 train_teacher recipe on original 13-feature endpoint tensors."""
    device = device or _device()
    _set_seed(seed)
    model = build_odst046_model()
    load_state_dict(model, encoder_ckpt, strict=True)
    model.apply_frozen_node_trainability()
    model.to(device)
    train_loader = make_xy_loader(x_train, y_train, seed=seed, shuffle=True)
    val_loader = make_xy_loader(x_val, y_val, seed=seed, shuffle=False)
    x_init, _ = next(iter(train_loader))
    model.data_aware_initialize_from_batch(x_init.to(device))
    assert_odst046(model)
    pw = pos_weight_from_y(y_train, POS_WEIGHT_MULT)
    criterion = make_task_criterion(pw, device)
    opt = build_teacher_optimizer(model)
    best_pr = -1.0
    best_epoch = 0
    best_state = None
    best_metrics = None
    patience_left = PATIENCE
    rows = []
    t0 = time.time()
    val = None
    for epoch in range(1, MAX_EPOCHS + 1):
        model.train()
        model.lstm.eval()
        model.attention.eval()
        model.linear_head.eval()
        model.dropout.eval()
        running = 0.0
        n_obs = 0
        for xb, yb in train_loader:
            xb = xb.to(device)
            yb = yb.to(device)
            opt.zero_grad(set_to_none=True)
            out = student_forward(model, xb)
            loss = criterion(out["logit"], yb)
            loss.backward()
            torch.nn.utils.clip_grad_norm_([p for p in model.parameters() if p.requires_grad], GRAD_CLIP_NORM)
            opt.step()
            bs = int(yb.size(0))
            running += float(loss.item()) * bs
            n_obs += bs
        val = evaluate_pair(student=model, teacher=None, loader=val_loader, device=device)
        pr = float(val["student"]["pr_auc"])
        rows.append({"epoch": epoch, "train_task_loss": running / max(n_obs, 1), "validation_pr_auc": pr})
        print(f"[EDITOR-029] EP_TEACHER seed={seed} epoch={epoch} val_PR-AUC={pr:.6f}", flush=True)
        if pr > best_pr:
            best_pr = pr
            best_epoch = epoch
            best_metrics = val
            best_state = clone_state(model)
            patience_left = PATIENCE
        else:
            patience_left -= 1
            if patience_left <= 0:
                break
    if best_state is not None:
        model.load_state_dict(best_state)
    out_dir = OUTPUT_ROOT / "teachers" / f"EP_TEACHER_{seed}" / f"seed{seed}"
    out_dir.mkdir(parents=True, exist_ok=True)
    ckpt = out_dir / "best_teacher.pt"
    torch.save(
        {
            "model_state_dict": best_state or clone_state(model),
            "condition": f"EP_TEACHER_{seed}",
            "seed": seed,
            "best_epoch": best_epoch,
            "best_val_pr_auc": best_pr,
            "campaign": "EDITOR-029",
            "odst": "ODST-046",
            "checkpoint_selection": "r5.2 ENDPOINT VALIDATION PR-AUC",
            "r52_test_used": False,
        },
        ckpt,
    )
    bm = best_metrics or val
    np.save(out_dir / "val_logits.npy", bm["student_logits"])
    return {
        "condition": f"EP_TEACHER_{seed}",
        "seed": seed,
        "best_epoch": best_epoch,
        "validation_PR_AUC": float(best_pr),
        "best_checkpoint": str(ckpt),
        "best_checkpoint_sha256": sha256_file(ckpt),
        "architecture": architecture_identity(model),
        "threshold": float(bm["threshold"]),
        "student_logits": bm["student_logits"],
        "y_val": bm["y"],
        "pos_weight": pw,
        "training_time": float(time.time() - t0),
        "epoch_rows": rows,
        "r52_test_used": False,
        "model": model,
    }


def train_endpoint_odst_student(
    *,
    alias: str,
    seed: int,
    teacher_ckpt: str,
    x_train: np.ndarray,
    y_train: np.ndarray,
    x_val: np.ndarray,
    y_val: np.ndarray,
    ensemble_train: np.ndarray | None,
    ensemble_val: np.ndarray | None,
    device: torch.device | None = None,
) -> dict[str, Any]:
    spec = STUDENT_SPECS[alias]
    device = device or _device()
    _set_seed(seed)
    teacher = build_odst046_model()
    load_state_dict(teacher, teacher_ckpt, strict=True)
    teacher.to(device)
    freeze_teacher(teacher)
    student = build_odst046_model()
    load_state_dict(student, teacher_ckpt, strict=True)
    student.to(device)
    enable_student(student)
    assert_odst046(student)
    extras_train = [ensemble_train] if spec["teacher_guidance"] else None
    train_loader = make_xy_loader(x_train, y_train, seed=seed, shuffle=True, extras=extras_train)
    val_loader = make_xy_loader(x_val, y_val, seed=seed, shuffle=False)
    pw = pos_weight_from_y(y_train, POS_WEIGHT_MULT)
    criterion = make_task_criterion(pw, device)
    opt = build_student_optimizer(student)
    assert_teacher_not_in_optimizer(teacher, opt)
    best_pr = -1.0
    best_epoch = 0
    best_state = None
    best_metrics = None
    patience_left = PATIENCE
    t0 = time.time()
    val = None
    for epoch in range(1, MAX_EPOCHS + 1):
        student.train()
        teacher.eval()
        for batch in train_loader:
            xb = batch[0].to(device)
            yb = batch[1].to(device)
            opt.zero_grad(set_to_none=True)
            with torch.no_grad():
                tr = teacher_forward(teacher, xb)
            sr = student_forward(student, xb)
            loss = criterion(sr["logit"], yb)
            if spec["teacher_guidance"]:
                ens = batch[2].to(device)
                loss = loss + float(spec["lambda_et1"]) * ensemble_anchor_loss(
                    sr["logit"],
                    ens,
                    yb,
                    confidence_weight=False,
                    agreement_weight=False,
                    class_balanced_reduction_flag=False,
                )
            if spec["route_anchor"]:
                loss = loss + float(spec["lambda_route"]) * route_consistency_loss(sr["choices"], tr["choices"])
            loss.backward()
            torch.nn.utils.clip_grad_norm_([p for p in student.parameters() if p.requires_grad], GRAD_CLIP_NORM)
            opt.step()
        val = evaluate_pair(
            student=student,
            teacher=teacher,
            loader=val_loader,
            device=device,
            ensemble_logits=ensemble_val if spec["teacher_guidance"] else None,
        )
        pr = float(val["student"]["pr_auc"])
        print(f"[EDITOR-029] {alias} seed={seed} epoch={epoch} val_PR-AUC={pr:.6f}", flush=True)
        if pr > best_pr:
            best_pr = pr
            best_epoch = epoch
            best_metrics = val
            best_state = clone_state(student)
            patience_left = PATIENCE
        else:
            patience_left -= 1
            if patience_left <= 0:
                break
    if best_state is not None:
        student.load_state_dict(best_state)
    out_dir = OUTPUT_ROOT / alias / f"seed{seed}"
    out_dir.mkdir(parents=True, exist_ok=True)
    ckpt = out_dir / "best_student.pt"
    torch.save(
        {
            "model_state_dict": best_state or clone_state(student),
            "condition": alias,
            "seed": seed,
            "best_epoch": best_epoch,
            "best_val_pr_auc": best_pr,
            "campaign": "EDITOR-029",
            "checkpoint_selection": "r5.2 ENDPOINT VALIDATION PR-AUC",
            "teacher_guidance": spec["teacher_guidance"],
            "route_anchor": spec["route_anchor"],
            "r52_test_used": False,
        },
        ckpt,
    )
    bm = best_metrics or val
    np.save(out_dir / "val_logits.npy", bm["student_logits"])
    return {
        "condition": alias,
        "seed": seed,
        "best_epoch": best_epoch,
        "validation_PR_AUC": float(best_pr),
        "validation_F1": float(bm["student"]["f1"]),
        "Brier": float(bm["student"]["Brier"]),
        "log_loss": float(bm["student"]["log_loss"]),
        "threshold": float(bm["threshold"]),
        "best_checkpoint": str(ckpt),
        "best_checkpoint_sha256": sha256_file(ckpt),
        "student_logits": bm["student_logits"],
        "student_choices": bm.get("student_choices"),
        "student_leaves": bm.get("student_leaves"),
        "y_val": bm["y"],
        "route_MAE": float(bm.get("route_MAE", float("nan"))),
        "route_KL": float(bm.get("route_KL", float("nan"))),
        "hard_route_agreement": float(bm.get("hard_route_agreement", float("nan"))),
        "dominant_leaf_agreement": float(bm.get("dominant_leaf_agreement", float("nan"))),
        "training_time": float(time.time() - t0),
        "r52_test_used": False,
    }


def train_endpoint_linear_student(
    *,
    seed: int,
    teacher_ckpt: str,
    x_train: np.ndarray,
    y_train: np.ndarray,
    x_val: np.ndarray,
    y_val: np.ndarray,
    ensemble_train: np.ndarray,
    ensemble_val: np.ndarray,
    device: torch.device | None = None,
) -> dict[str, Any]:
    device = device or _device()
    _set_seed(seed)
    spec = {"family": "linear", "distill": True, "teacher": "ensemble", "route": False, "readout": "none", "hybrid": False}
    student = build_odst046_model()
    load_state_dict(student, teacher_ckpt, strict=True)
    student.to(device)
    modules = make_modules(spec)
    modules.to(device)
    configure_trainability(student, modules, encoder_trainable=True)
    opt = build_editor013_optimizer(student, modules, encoder_trainable=True)
    pw = pos_weight_from_y(y_train, POS_WEIGHT_MULT)
    criterion = make_task_criterion(pw, device)
    train_loader = make_xy_loader(x_train, y_train, seed=seed, shuffle=True, extras=[ensemble_train])
    val_loader = make_xy_loader(x_val, y_val, seed=seed, shuffle=False)
    best_pr = -1.0
    best_epoch = 0
    best_student = None
    best_modules = None
    best_logits = None
    best_y = None
    best_thr = None
    best_brier = None
    best_ll = None
    patience_left = PATIENCE
    t0 = time.time()
    for epoch in range(1, MAX_EPOCHS + 1):
        student.train()
        modules.train()
        for batch in train_loader:
            xb = batch[0].to(device)
            yb = batch[1].to(device)
            ens = batch[2].to(device)
            opt.zero_grad(set_to_none=True)
            out = editor013_forward(student, xb, modules)
            loss = criterion(out["logit"], yb)
            loss = loss + float(STUDENT_SPECS["EP_LINEAR"]["lambda_et1"]) * torch.mean(
                (out["logit"] - ens.detach()) ** 2
            )
            loss.backward()
            torch.nn.utils.clip_grad_norm_(
                [p for p in list(student.parameters()) + list(modules.parameters()) if p.requires_grad],
                GRAD_CLIP_NORM,
            )
            opt.step()
        student.eval()
        modules.eval()
        logits = []
        ys = []
        with torch.no_grad():
            for xb, yb in val_loader:
                out = editor013_forward(student, xb.to(device), modules)
                logits.append(out["logit"].detach().cpu().numpy())
                ys.append(np.asarray(yb).reshape(-1))
        logits_np = np.concatenate(logits)
        y_np = np.concatenate(ys).reshape(-1)
        met = metrics_from_logits(y_np, logits_np)
        pr = float(met["pr_auc"])
        print(f"[EDITOR-029] EP_LINEAR seed={seed} epoch={epoch} val_PR-AUC={pr:.6f}", flush=True)
        if pr > best_pr:
            best_pr = pr
            best_epoch = epoch
            best_student = clone_state(student)
            best_modules = clone_state(modules)
            best_logits = logits_np
            best_y = y_np
            best_thr = float(met["threshold"])
            best_brier = float(met["Brier"])
            best_ll = float(met["log_loss"])
            patience_left = PATIENCE
        else:
            patience_left -= 1
            if patience_left <= 0:
                break
    if best_student is not None:
        student.load_state_dict(best_student)
    if best_modules is not None:
        modules.load_state_dict(best_modules)
    out_dir = OUTPUT_ROOT / "EP_LINEAR" / f"seed{seed}"
    out_dir.mkdir(parents=True, exist_ok=True)
    ckpt = out_dir / "best.pt"
    torch.save(
        {
            "student_state_dict": best_student or clone_state(student),
            "modules_state_dict": best_modules or clone_state(modules),
            "condition": "EP_LINEAR",
            "seed": seed,
            "best_epoch": best_epoch,
            "best_val_pr_auc": best_pr,
            "campaign": "EDITOR-029",
            "checkpoint_selection": "r5.2 ENDPOINT VALIDATION PR-AUC",
            "lr_linear": LR_LINEAR,
            "r52_test_used": False,
        },
        ckpt,
    )
    np.save(out_dir / "val_logits.npy", best_logits)
    return {
        "condition": "EP_LINEAR",
        "seed": seed,
        "best_epoch": best_epoch,
        "validation_PR_AUC": float(best_pr),
        "Brier": float(best_brier),
        "log_loss": float(best_ll),
        "threshold": float(best_thr),
        "best_checkpoint": str(ckpt),
        "best_checkpoint_sha256": sha256_file(ckpt),
        "student_logits": best_logits,
        "y_val": best_y,
        "training_time": float(time.time() - t0),
        "r52_test_used": False,
    }


def score_odst_arrays(model: nn.Module, x: np.ndarray, y: np.ndarray, device: torch.device, seed: int = 0) -> dict[str, np.ndarray]:
    loader = make_xy_loader(x, y, seed=seed, shuffle=False)
    model.eval()
    logits, choices, leaves = [], [], []
    with torch.no_grad():
        for xb, _ in loader:
            out = student_forward(model, xb.to(device))
            logits.append(out["logit"].detach().cpu().numpy())
            choices.append(out["choices"].detach().cpu().numpy())
            leaves.append(out["leaf_probs_all"].detach().cpu().numpy())
    return {
        "logits": np.concatenate(logits),
        "choices": np.concatenate(choices),
        "leaf_probs_all": np.concatenate(leaves),
    }


def score_linear_arrays(student: nn.Module, modules, x: np.ndarray, y: np.ndarray, device: torch.device, seed: int = 0) -> dict[str, np.ndarray]:
    loader = make_xy_loader(x, y, seed=seed, shuffle=False)
    student.eval()
    modules.eval()
    logits = []
    with torch.no_grad():
        for xb, _ in loader:
            out = editor013_forward(student, xb.to(device), modules)
            logits.append(out["logit"].detach().cpu().numpy())
    return {"logits": np.concatenate(logits)}


def load_odst(ckpt: str, device: torch.device) -> nn.Module:
    model = build_odst046_model()
    load_state_dict(model, ckpt, strict=True)
    model.to(device)
    model.eval()
    return model


def load_linear(ckpt: str, device: torch.device):
    spec = {"family": "linear", "readout": "none", "hybrid": False}
    student = build_odst046_model()
    modules = make_modules(spec)
    payload = torch.load(ckpt, map_location="cpu", weights_only=False)
    student.load_state_dict(payload["student_state_dict"], strict=True)
    modules.load_state_dict(payload["modules_state_dict"], strict=True)
    student.to(device)
    modules.to(device)
    student.eval()
    modules.eval()
    return student, modules
