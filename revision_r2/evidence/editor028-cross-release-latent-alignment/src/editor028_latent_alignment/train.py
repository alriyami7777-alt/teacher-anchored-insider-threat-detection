"""Representation-matched teachers and CORAL-aligned students. r6.1 labels never enter."""

from __future__ import annotations

import inspect
import time
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
from editor026_user_relative.train import (
    ATTENTION_LINEAR_PRODUCING,
    GRAD_CLIP_NORM,
    LAMBDA_HISTORICAL_SINGLE_TEACHER_LOGIT,
    MAX_EPOCHS,
    PATIENCE,
    POS_WEIGHT_MULT,
    pos_weight_from_y,
)

from .alignment import UnlabeledAlignmentStore, assert_no_alignment_labels, candidate_lambda, iter_matched_batches
from .constants import (
    BATCH_SIZE,
    STUDENT_SPEC,
    TEACHER_IDS,
)
from .coral import coral_loss
from .safety import Editor028Blocked, OUTPUT_ROOT, sha256_file


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
        raise Editor028Blocked("no trainable teacher ODST parameters")
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
    logits, ys, zs, att = [], [], [], []
    for batch in loader:
        xb = batch[0].to(device)
        z, enc = model.encode_attention_h(xb)
        logits.append(enc["linear_logit"].detach().cpu().numpy())
        zs.append(z.detach().cpu().numpy())
        att.append(enc["attention_weights"].detach().cpu().numpy())
        ys.append(np.asarray(batch[1]).reshape(-1))
    return {
        "logits": np.concatenate(logits),
        "y": np.concatenate(ys).reshape(-1),
        "z": np.concatenate(zs),
        "attention_weights": np.concatenate(att),
    }


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
    recipe_ok = (
        "ATTENTION_LINEAR_PRODUCING" in src_al
        and "apply_frozen_node_trainability" in src_t
        and "data_aware_initialize_from_batch" in src_t
    )
    if not all(required.values()) or not recipe_ok:
        raise Editor028Blocked("EDITOR028_TEACHER_REPRODUCTION_GATE = FAIL")
    return {
        "EDITOR028_TEACHER_REPRODUCTION_GATE": "PASS",
        "producing_attention_linear": "editor026_user_relative.train.train_attention_linear",
        "producing_teacher": "editor026_user_relative.train.train_ur_teacher",
        "producing_student": "editor012_rescue.train.train_student",
        "recipe_markers_present": recipe_ok,
        "r61_used": False,
    }


def train_centered_attention_linear(
    *,
    seed: int,
    x_train: np.ndarray,
    y_train: np.ndarray,
    x_val: np.ndarray,
    y_val: np.ndarray,
    device: torch.device | None = None,
) -> dict[str, Any]:
    """Producing r52_odst_confirmation attention-linear recipe. r5.2 only."""
    if LAMBDA_HISTORICAL_SINGLE_TEACHER_LOGIT != 0.0:
        raise Editor028Blocked("historical single-teacher logit anchor must remain retired")
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
        rows.append(
            {
                "epoch": epoch,
                "train_loss": running / max(n_obs, 1),
                "validation_pr_auc": pr,
                "lr": float(opt.param_groups[0]["lr"]),
            }
        )
        print(f"[EDITOR-028] CENTERED_ATTENTION_LINEAR seed={seed} epoch={epoch} val_PR-AUC={pr:.6f}", flush=True)
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
    out_dir = OUTPUT_ROOT / "teachers" / "CENTERED_ATTENTION_LINEAR" / f"seed{seed}"
    out_dir.mkdir(parents=True, exist_ok=True)
    ckpt = out_dir / "best.pt"
    torch.save(
        {
            "model_state_dict": best_state or clone_state(model),
            "condition": "CENTERED_ATTENTION_LINEAR",
            "seed": seed,
            "best_epoch": best_epoch,
            "best_val_pr_auc": best_pr,
            "campaign": "EDITOR-028",
            "r61_used": False,
        },
        ckpt,
    )
    return {
        "condition": "CENTERED_ATTENTION_LINEAR",
        "seed": seed,
        "best_epoch": best_epoch,
        "validation_PR_AUC": float(best_pr),
        "best_checkpoint": str(ckpt),
        "best_checkpoint_sha256": sha256_file(ckpt),
        "pos_weight": pw,
        "pos_weight_multiplier": float(cfg["pos_weight_multiplier"]),
        "training_time": float(time.time() - t0),
        "epoch_rows": rows,
        "r61_used": False,
    }


def train_centered_teacher(
    *,
    seed: int,
    encoder_ckpt: str,
    x_train: np.ndarray,
    y_train: np.ndarray,
    x_val: np.ndarray,
    y_val: np.ndarray,
    device: torch.device | None = None,
) -> dict[str, Any]:
    """EDITOR-011 train_teacher recipe on centred user-relative tensors. No r6.1."""
    device = device or _device()
    _set_seed(seed)
    teacher_id = TEACHER_IDS[int(seed)]
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
        print(f"[EDITOR-028] {teacher_id} seed={seed} epoch={epoch} val_PR-AUC={pr:.6f}", flush=True)
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
    out_dir = OUTPUT_ROOT / "teachers" / teacher_id / f"seed{seed}"
    out_dir.mkdir(parents=True, exist_ok=True)
    ckpt = out_dir / "best_teacher.pt"
    torch.save(
        {
            "model_state_dict": best_state or clone_state(model),
            "condition": teacher_id,
            "seed": seed,
            "best_epoch": best_epoch,
            "best_val_pr_auc": best_pr,
            "campaign": "EDITOR-028",
            "odst": "ODST-046",
            "r61_used": False,
        },
        ckpt,
    )
    np.save(out_dir / "val_logits.npy", (best_metrics or val)["student_logits"])
    return {
        "condition": teacher_id,
        "seed": seed,
        "best_epoch": best_epoch,
        "validation_PR_AUC": float(best_pr),
        "best_checkpoint": str(ckpt),
        "best_checkpoint_sha256": sha256_file(ckpt),
        "architecture": architecture_identity(model),
        "threshold": float((best_metrics or val)["threshold"]),
        "student_logits": (best_metrics or val)["student_logits"],
        "y_val": (best_metrics or val)["y"],
        "training_time": float(time.time() - t0),
        "epoch_rows": rows,
        "r61_used": False,
        "model": model,
    }


def train_aligned_student(
    *,
    alias: str,
    seed: int,
    teacher_ckpt: str,
    x_train: np.ndarray,
    y_train: np.ndarray,
    x_val: np.ndarray,
    y_val: np.ndarray,
    ensemble_train: np.ndarray,
    ensemble_val: np.ndarray,
    target: UnlabeledAlignmentStore,
    device: torch.device | None = None,
) -> dict[str, Any]:
    """Final repaired student objective plus frozen-weight CORAL on attention-pooled h(x)."""
    assert_no_alignment_labels(target)
    spec = STUDENT_SPEC
    lam = candidate_lambda(alias)
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
    train_loader = make_xy_loader(x_train, y_train, seed=seed, shuffle=True, extras=[ensemble_train])
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
        for batch, x_tgt, _idx in iter_matched_batches(train_loader, target, seed=seed, epoch=epoch):
            xb = batch[0].to(device)
            yb = batch[1].to(device)
            ens = batch[2].to(device)
            xt = torch.from_numpy(np.asarray(x_tgt, dtype=np.float32)).to(device)
            opt.zero_grad(set_to_none=True)
            with torch.no_grad():
                tr = teacher_forward(teacher, xb)
            sr = student_forward(student, xb)
            h_s = sr["z"]
            loss = criterion(sr["logit"], yb)
            loss = loss + float(spec["lambda_et1"]) * ensemble_anchor_loss(
                sr["logit"], ens, yb, confidence_weight=False, agreement_weight=False, class_balanced_reduction_flag=False
            )
            loss = loss + float(spec["lambda_route"]) * route_consistency_loss(sr["choices"], tr["choices"])
            if lam != 0.0:
                h_t, _ = student.encode_attention_h(xt)
                loss = loss + float(lam) * coral_loss(h_s, h_t)
            loss.backward()
            torch.nn.utils.clip_grad_norm_([p for p in student.parameters() if p.requires_grad], GRAD_CLIP_NORM)
            opt.step()
        val = evaluate_pair(
            student=student,
            teacher=teacher,
            loader=val_loader,
            device=device,
            ensemble_logits=ensemble_val,
        )
        pr = float(val["student"]["pr_auc"])
        print(f"[EDITOR-028] {alias} seed={seed} epoch={epoch} val_PR-AUC={pr:.6f} lambda_CORAL={lam}", flush=True)
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
            "campaign": "EDITOR-028",
            "lambda_CORAL": lam,
            "r61_used": False,
            "r61_labels_used": False,
            "teacher_guidance": True,
            "route_anchor": True,
            "coral_input": "attention-pooled representation directly before ODST",
        },
        ckpt,
    )
    bm = best_metrics or val
    np.save(out_dir / "val_logits.npy", bm["student_logits"])
    np.save(out_dir / "val_z.npy", bm["student_z"])
    return {
        "condition": alias,
        "seed": seed,
        "lambda_CORAL": lam,
        "best_epoch": best_epoch,
        "validation_PR_AUC": float(best_pr),
        "validation_F1": float(bm["student"]["f1"]),
        "threshold": float(bm["threshold"]),
        "best_checkpoint": str(ckpt),
        "best_checkpoint_sha256": sha256_file(ckpt),
        "student_logits": bm["student_logits"],
        "student_z": bm["student_z"],
        "student_choices": bm.get("student_choices"),
        "student_leaves": bm.get("student_leaves"),
        "y_val": bm["y"],
        "route_MAE": float(bm.get("route_MAE", float("nan"))),
        "route_KL": float(bm.get("route_KL", float("nan"))),
        "hard_route_agreement": float(bm.get("hard_route_agreement", float("nan"))),
        "dominant_leaf_agreement": float(bm.get("dominant_leaf_agreement", float("nan"))),
        "training_time": float(time.time() - t0),
        "r61_used": False,
        "r61_labels_used": False,
        "batch_size": BATCH_SIZE,
    }


def score_odst_arrays(model: nn.Module, x: np.ndarray, y: np.ndarray, device: torch.device, seed: int = 0) -> dict[str, np.ndarray]:
    loader = make_xy_loader(x, y, seed=seed, shuffle=False)
    model.eval()
    logits, zs, choices, leaves, att = [], [], [], [], []
    with torch.no_grad():
        for xb, _ in loader:
            out = student_forward(model, xb.to(device))
            logits.append(out["logit"].detach().cpu().numpy())
            zs.append(out["z"].detach().cpu().numpy())
            choices.append(out["choices"].detach().cpu().numpy())
            leaves.append(out["leaf_probs_all"].detach().cpu().numpy())
            att.append(out["attention_weights"].detach().cpu().numpy())
    return {
        "logits": np.concatenate(logits),
        "z": np.concatenate(zs),
        "choices": np.concatenate(choices),
        "leaf_probs_all": np.concatenate(leaves),
        "attention_weights": np.concatenate(att),
    }


def score_odst_unlabeled(model: nn.Module, x: np.ndarray, device: torch.device, seed: int = 0) -> dict[str, np.ndarray]:
    """Score unlabeled alignment windows. Dummy y is local and discarded."""
    dummy = np.zeros((len(x),), dtype=np.float32)
    scored = score_odst_arrays(model, x, dummy, device, seed=seed)
    return {k: v for k, v in scored.items() if k != "y"}


def load_odst(ckpt: str, device: torch.device) -> nn.Module:
    model = build_odst046_model()
    load_state_dict(model, ckpt, strict=True)
    model.to(device)
    model.eval()
    return model
