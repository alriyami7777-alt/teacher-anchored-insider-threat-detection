"""8-tree teacher-anchored student training + diagnostics."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import numpy as np
import torch
from torch.utils.data import DataLoader, Subset, TensorDataset

from objective2_teacher_anchored_odst.models import (
    assert_teacher_not_in_optimizer,
    build_model,
    build_student_optimizer,
    enable_all_student_components,
    freeze_teacher,
    live_odst_forward,
    load_checkpoint_into,
    student_forward_with_routing,
)
from objective2_teacher_anchored_odst.train import parity_check, train_teacher_anchored
from prototype_v3_node.diagnostics import leaf_utilization_stats
from prototype_v3_node.train import choose_threshold_f1, metrics_at_threshold, set_seed

from .constants import (
    ARCHITECTURE,
    BATCH_SIZE,
    LR_ATTENTION,
    LR_ENCODER,
    LR_ODST,
    M_TREES,
    NODE_N_TREES,
    POS_WEIGHT_MULT,
)
from .safety import sha256_file


def _loader(X: np.ndarray, y: np.ndarray, shuffle: bool) -> DataLoader:
    ds = TensorDataset(torch.from_numpy(X), torch.from_numpy(y.astype(np.float32)))
    return DataLoader(ds, batch_size=BATCH_SIZE, shuffle=shuffle, drop_last=False)


@torch.inference_mode()
def predict_proba(model, X: np.ndarray, device: torch.device) -> np.ndarray:
    model.eval()
    out = []
    bs = 1024
    for i in range(0, len(X), bs):
        xb = torch.from_numpy(X[i : i + bs]).to(device)
        logit, _ = model(xb)
        out.append(torch.sigmoid(logit.reshape(-1)).cpu().numpy())
    return np.concatenate(out)


@torch.inference_mode()
def extract_tree_outputs(model, X: np.ndarray, device: torch.device) -> dict[str, np.ndarray]:
    model.eval()
    trees, logits, leaves = [], [], []
    bs = 256
    for i in range(0, len(X), bs):
        xb = torch.from_numpy(X[i : i + bs]).to(device)
        z, _ = model.encode_attention_h(xb)
        off_logit, _, first_leaf = live_odst_forward(model.node_head, z)
        xh = z
        bags = []
        for layer in model.node_head.layers:
            feature_probs = layer.feature_selection_probs()
            selected = torch.einsum("bf,tdf->btd", xh, feature_probs)
            choice = layer.split_choice(selected)
            batch = xh.size(0)
            c = choice.unsqueeze(2).expand(batch, layer.n_trees, layer.n_leaves, layer.depth)
            codes = layer.leaf_codes.view(1, 1, layer.n_leaves, layer.depth)
            log_c = torch.log(c.clamp(1e-8, 1.0 - 1e-8))
            log_1mc = torch.log((1.0 - c).clamp(1e-8, 1.0))
            leaf_probs = torch.exp((codes * log_c + (1.0 - codes) * log_1mc).sum(dim=-1))
            response = torch.einsum("btl,tlu->btu", leaf_probs, layer.leaf_responses)
            bags.append(response.squeeze(-1))
            out = response.reshape(batch, layer.n_trees * layer.tree_dim)
            xh = torch.cat([xh, out], dim=-1)
        all_trees = torch.cat(bags, dim=1)
        trees.append(all_trees.cpu().numpy())
        logits.append(off_logit.cpu().numpy())
        leaves.append(first_leaf.cpu())
    t = np.concatenate(trees, axis=0)
    if t.shape[1] != M_TREES:
        raise RuntimeError(f"Expected M={M_TREES} trees, got {t.shape[1]}")
    return {
        "tree_outputs": t,
        "logit": np.concatenate(logits),
        "leaf_probs": torch.cat(leaves, dim=0),
    }


def effective_rank(mat: np.ndarray, eps: float = 1e-12) -> float:
    x = mat - mat.mean(axis=0, keepdims=True)
    s = np.linalg.svd(x, compute_uv=False)
    s = np.maximum(s, 0.0)
    if s.sum() <= eps:
        return 0.0
    p = s / s.sum()
    p = p[p > eps]
    return float(np.exp(-(p * np.log(p)).sum()))


def inference_benchmark(model, X: np.ndarray, device: torch.device) -> list[dict[str, Any]]:
    model.eval()
    rows = []
    for bs in (1, 32, 256):
        xb = torch.from_numpy(X[:bs]).to(device)
        for _ in range(20):
            _ = model(xb)
        if device.type == "cuda":
            torch.cuda.synchronize()
        times = []
        for _ in range(100):
            t0 = time.perf_counter()
            _ = model(xb)
            if device.type == "cuda":
                torch.cuda.synchronize()
            times.append(time.perf_counter() - t0)
        arr = np.asarray(times)
        peak = 0.0
        if device.type == "cuda":
            peak = float(torch.cuda.max_memory_allocated(device) / (1024**2))
        rows.append(
            {
                "batch_size": bs,
                "median_latency_sec": float(np.median(arr)),
                "iqr_latency_sec": float(np.percentile(arr, 75) - np.percentile(arr, 25)),
                "examples_per_sec": float(bs / max(np.median(arr), 1e-12)),
                "peak_gpu_memory_mb": peak,
            }
        )
    return rows


def calibration_metrics(y: np.ndarray, p: np.ndarray, n_bins: int = 15) -> dict[str, float]:
    from sklearn.metrics import brier_score_loss, log_loss

    y = np.asarray(y).astype(int)
    p = np.clip(np.asarray(p, dtype=float), 1e-7, 1 - 1e-7)
    bins = np.linspace(0, 1, n_bins + 1)
    ece = 0.0
    for i in range(n_bins):
        m = (p >= bins[i]) & (p < bins[i + 1] if i < n_bins - 1 else p <= bins[i + 1])
        if not m.any():
            continue
        ece += abs(y[m].mean() - p[m].mean()) * float(m.mean())
    return {
        "brier_score": float(brier_score_loss(y, p)),
        "log_loss": float(log_loss(y, p, labels=[0, 1])),
        "ece": float(ece),
    }


def train_8tree_student(
    *,
    seed: int,
    teacher_ckpt: Path,
    out_dir: Path,
    device: torch.device,
    data: dict[str, Any],
) -> dict[str, Any]:
    set_seed(int(seed))
    out_dir.mkdir(parents=True, exist_ok=True)

    teacher = build_model(**ARCHITECTURE).to(device)
    student = build_model(**ARCHITECTURE).to(device)
    load_checkpoint_into(teacher, teacher_ckpt)
    load_checkpoint_into(student, teacher_ckpt)
    freeze_teacher(teacher)
    enable_all_student_components(student)

    train_loader = _loader(data["X_train"], data["y_train"], shuffle=True)
    val_loader = _loader(data["X_val"], data["y_val"], shuffle=False)
    full_ds = TensorDataset(
        torch.from_numpy(data["X_val"]), torch.from_numpy(data["y_val"].astype(np.float32))
    )
    rng = np.random.default_rng(42)
    indices = rng.choice(len(full_ds), size=min(256, len(full_ds)), replace=False).tolist()
    diag_loader = DataLoader(Subset(full_ds, indices), batch_size=256, shuffle=False)

    opt, _ = build_student_optimizer(
        student, {"lr_encoder": LR_ENCODER, "lr_attention": LR_ATTENTION, "lr_odst": LR_ODST}
    )
    assert_teacher_not_in_optimizer(teacher, opt)
    del opt

    parity = parity_check(teacher, student, diag_loader, device, indices)
    if not parity["initial_parity_ok"]:
        raise RuntimeError(f"Initial teacher/student parity failed: {parity}")

    teacher_state0 = {k: v.detach().cpu().clone() for k, v in teacher.state_dict().items()}
    student_state0 = {k: v.detach().cpu().clone() for k, v in student.state_dict().items()}

    n_pos = float((data["y_train"] == 1).sum())
    n_neg = float((data["y_train"] == 0).sum())
    pos_weight = torch.tensor([(n_neg / max(n_pos, 1.0)) * POS_WEIGHT_MULT], dtype=torch.float32)

    t0 = time.perf_counter()
    if device.type == "cuda":
        torch.cuda.reset_peak_memory_stats(device)

    print(
        f"[8tree-student seed={seed}] device={device} M={M_TREES} "
        f"pos_weight={float(pos_weight):.6f}",
        flush=True,
    )
    result = train_teacher_anchored(
        teacher=teacher,
        student=student,
        train_loader=train_loader,
        val_loader=val_loader,
        diag_loader=diag_loader,
        y_val=data["y_val"].astype(np.float32),
        device=device,
        pos_weight=pos_weight,
        seed=seed,
        teacher_initial_state=teacher_state0,
        student_initial_state=student_state0,
    )
    duration = time.perf_counter() - t0
    peak_mem = float(torch.cuda.max_memory_allocated(device) / (1024**2)) if device.type == "cuda" else 0.0

    best_path = out_dir / "best_student.pt"
    torch.save(
        {
            "model_state_dict": result["best_state"],
            "seed": seed,
            "best_epoch": result["best_epoch"],
            "best_val_pr_auc": result["best_pr_auc"],
            "node_n_trees": NODE_N_TREES,
            "M_trees": M_TREES,
            "stage": "odst_r52_8tree_teacher_anchored_student",
            "teacher_checkpoint": str(teacher_ckpt),
            "test_evaluated": False,
        },
        best_path,
    )

    student_inf = build_model(**ARCHITECTURE).to(device)
    load_checkpoint_into(student_inf, best_path)
    student_inf.eval()
    for p in student_inf.parameters():
        p.requires_grad = False

    # teacher-independent inference
    proba = predict_proba(student_inf, data["X_val"], device)
    thr, _ = choose_threshold_f1(data["y_val"], proba)
    metrics = metrics_at_threshold(data["y_val"], proba, thr)
    calib = calibration_metrics(data["y_val"], proba)

    bundle = extract_tree_outputs(student_inf, data["X_val"][:8000], device)
    leaf_stats = leaf_utilization_stats(bundle["leaf_probs"])
    trees = bundle["tree_outputs"]
    corr = np.corrcoef(trees.T)
    m = corr.shape[0]
    off = corr[~np.eye(m, dtype=bool)]
    eff_rank = effective_rank(trees)
    abs_mean = np.abs(trees).mean(axis=0)
    top_share = float(np.sort(abs_mean)[::-1][: max(1, m // 2)].sum() / max(abs_mean.sum(), 1e-12))

    lat = inference_benchmark(student_inf, data["X_val"], device)
    t_ex = []
    for _ in range(20):
        _ = extract_tree_outputs(student_inf, data["X_val"][:32], device)
    for _ in range(50):
        t1 = time.perf_counter()
        _ = extract_tree_outputs(student_inf, data["X_val"][:32], device)
        if device.type == "cuda":
            torch.cuda.synchronize()
        t_ex.append(time.perf_counter() - t1)

    n_params = sum(p.numel() for p in student_inf.parameters())
    n_head = sum(p.numel() for p in student_inf.node_head.parameters())

    unused_pct = float(leaf_stats.get("unused_leaves_frac", 0.0)) * 100.0
    route_ent = float(leaf_stats.get("routing_entropy_mean", float("nan")))

    summary = {
        "seed": seed,
        "role": "8tree_student",
        "node_n_trees": NODE_N_TREES,
        "M_trees": M_TREES,
        "duration_sec": duration,
        "peak_gpu_memory_mb": peak_mem,
        "teacher_unchanged": bool(result["teacher_unchanged"]),
        "teacher_independent_inference": True,
        "encoder_updated": bool(result["encoder_updated"]),
        "attention_updated": bool(result["attention_updated"]),
        "odst_updated": bool(result["odst_updated"]),
        "joint_training_verified": bool(result["joint_training_verified"]),
        "had_nan_or_inf": bool(result["had_nan_or_inf"]),
        "catastrophic_collapse": bool(result["catastrophic_collapse"]),
        "initial_parity_ok": bool(parity["initial_parity_ok"]),
        "initial_parity": parity,
        "best_epoch": int(result["best_epoch"]),
        "validation_metrics": metrics,
        "threshold": float(thr),
        "calibration": calib,
        "unused_leaves_pct": unused_pct,
        "routing_entropy_mean": route_ent,
        "tree_output_mean_abs_corr": float(np.nanmean(np.abs(off))),
        "effective_rank": eff_rank,
        "effective_rank_over_M": float(eff_rank / M_TREES),
        "top_half_contribution_share": top_share,
        "latency": lat,
        "explanation_extraction_latency_bs32_median": float(np.median(t_ex)),
        "checkpoint_sha256": sha256_file(best_path),
        "checkpoint_size_bytes": best_path.stat().st_size,
        "n_parameters": int(n_params),
        "n_odst_head_parameters": int(n_head),
        "epoch_rows": result.get("epoch_rows", []),
    }
    np.savez_compressed(
        out_dir / "student_val_predictions.npz",
        y=data["y_val"],
        proba=proba.astype(np.float32),
        threshold=np.array([thr], dtype=np.float32),
    )
    return {
        "summary": summary,
        "student": student_inf,
        "best_path": best_path,
        "proba": proba,
        "threshold": float(thr),
        "metrics": metrics,
        "train_result": result,
    }
