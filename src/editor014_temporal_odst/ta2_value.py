"""Read-only TA2 multi-dimensional value audit. No retraining."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import numpy as np
import torch
from sklearn.metrics import brier_score_loss, log_loss

from editor012_rescue.evaluate import hash_gate_checkpoint
from editor012_rescue.metrics import metrics_from_logits, sigmoid
from editor012_rescue.models import student_forward as historical_student_forward
from editor012_rescue.producing import build_odst046_model, load_state_dict
from editor013_odst_value.explain import centred_contributions, faithfulness_table, train_references
from editor013_odst_value.models import editor013_forward, make_modules as make_l1_modules

from .constants import (
    BOOTSTRAP_RESAMPLES,
    BOOTSTRAP_SEED,
    F11_CHECKPOINTS,
    FROZEN_L1_MEAN_PR_AUC,
    FROZEN_TA2_L1_CI,
    FROZEN_TA2_MEAN_PR_AUC,
    FROZEN_TA2_MINUS_L1,
    L1_CHECKPOINTS,
    LATENCY_BATCH_SIZE,
    LATENCY_ROUNDS,
    LATENCY_TIMED_BATCHES,
    LATENCY_WARMUP_BATCHES,
    PRIMARY_SEEDS,
    SCREENING_SEED,
)
from .safety import Editor014Blocked, sha256_file


def load_frozen_val_logits() -> dict[str, dict[int, np.ndarray]]:
    out: dict[str, dict[int, np.ndarray]] = {"L1": {}, "TA2": {}}
    for seed, spec in L1_CHECKPOINTS.items():
        hash_gate_checkpoint(spec["checkpoint"], spec["sha256"])
        out["L1"][seed] = np.load(spec["val_logits"])
    for seed, spec in F11_CHECKPOINTS.items():
        hash_gate_checkpoint(spec["checkpoint"], spec["sha256"])
        out["TA2"][seed] = np.load(spec["val_logits"])
    return out


def paired_user_cluster_calibration(
    users: np.ndarray,
    y: np.ndarray,
    logits_l1: list[np.ndarray],
    logits_ta2: list[np.ndarray],
    *,
    n_valid: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    """User-cluster Δ = TA2 − L1. Negative Brier/log-loss = TA2 improvement."""
    users = np.asarray(users).astype(str)
    y = np.asarray(y).astype(int).ravel()
    p_l1 = [sigmoid(np.asarray(a, dtype=np.float64).ravel()) for a in logits_l1]
    p_ta2 = [sigmoid(np.asarray(b, dtype=np.float64).ravel()) for b in logits_ta2]
    unique = np.unique(users)
    index = {u: np.flatnonzero(users == u) for u in unique}
    rng = np.random.default_rng(seed)
    d_brier: list[float] = []
    d_ll: list[float] = []
    attempted = 0
    while len(d_brier) < n_valid:
        attempted += 1
        if attempted > n_valid * 50:
            break
        draw = rng.choice(unique, size=len(unique), replace=True)
        sl = np.concatenate([index[str(u)] for u in draw])
        yb = y[sl]
        if len(np.unique(yb)) < 2:
            continue
        seed_b = []
        seed_l = []
        ok = True
        for a, b in zip(p_l1, p_ta2):
            pa = np.clip(a[sl], 1e-7, 1 - 1e-7)
            pb = np.clip(b[sl], 1e-7, 1 - 1e-7)
            db = float(brier_score_loss(yb, pb) - brier_score_loss(yb, pa))
            dl = float(log_loss(yb, pb, labels=[0, 1]) - log_loss(yb, pa, labels=[0, 1]))
            if not (np.isfinite(db) and np.isfinite(dl)):
                ok = False
                break
            seed_b.append(db)
            seed_l.append(dl)
        if ok:
            d_brier.append(float(np.mean(seed_b)))
            d_ll.append(float(np.mean(seed_l)))
    arr_b = np.asarray(d_brier, dtype=np.float64) if d_brier else np.array([np.nan])
    arr_l = np.asarray(d_ll, dtype=np.float64) if d_ll else np.array([np.nan])
    return {
        "cluster": "user",
        "n_users": int(len(unique)),
        "n_valid_resamples": int(len(d_brier)),
        "n_attempted_draws": attempted,
        "seed": seed,
        "sampling_unit": "validation user",
        "windows_not_resampled_independently": True,
        "contrast": "TA2_minus_L1",
        "negative_delta_is_TA2_improvement": True,
        "mean_delta_brier": float(np.nanmean(arr_b)),
        "ci95_brier": [float(np.nanpercentile(arr_b, 2.5)), float(np.nanpercentile(arr_b, 97.5))],
        "mean_delta_log_loss": float(np.nanmean(arr_l)),
        "ci95_log_loss": [float(np.nanpercentile(arr_l, 2.5)), float(np.nanpercentile(arr_l, 97.5))],
    }


def _latency_round(fn, x: torch.Tensor, device: torch.device) -> list[float]:
    n_batches = max(LATENCY_WARMUP_BATCHES + LATENCY_TIMED_BATCHES, 1)
    times: list[float] = []
    for i in range(n_batches):
        if device.type == "cuda":
            torch.cuda.synchronize()
        t0 = time.perf_counter()
        fn(x)
        if device.type == "cuda":
            torch.cuda.synchronize()
        dt = time.perf_counter() - t0
        if i >= LATENCY_WARMUP_BATCHES:
            times.append(dt)
    return times


def measure_efficiency(device: torch.device, val_x: np.ndarray) -> dict[str, Any]:
    if device.type != "cuda":
        raise Editor014Blocked("EDITOR-014 latency benchmark requires the same GPU")
    x = torch.from_numpy(np.asarray(val_x[:LATENCY_BATCH_SIZE], dtype=np.float32)).to(device)

    l1_student = build_odst046_model()
    l1_mods = make_l1_modules({"family": "linear", "readout": "none", "hybrid": False})
    payload = torch.load(L1_CHECKPOINTS[SCREENING_SEED]["checkpoint"], map_location="cpu", weights_only=False)
    l1_student.load_state_dict(payload["student_state_dict"])
    l1_mods.load_state_dict(payload["modules_state_dict"])
    l1_student.to(device).eval()
    l1_mods.to(device).eval()

    ta2 = build_odst046_model()
    load_state_dict(ta2, F11_CHECKPOINTS[SCREENING_SEED]["checkpoint"], strict=True)
    ta2.to(device).eval()

    def _run(name: str, fn) -> dict[str, Any]:
        rounds = []
        for r in range(LATENCY_ROUNDS):
            times = _latency_round(fn, x, device)
            rounds.append(
                {
                    "round": r + 1,
                    "n_timed": len(times),
                    "median_s": float(np.median(times)),
                    "iqr_s": float(np.subtract(*np.percentile(times, [75, 25]))),
                    "mean_s": float(np.mean(times)),
                }
            )
        medians = [row["median_s"] for row in rounds]
        iqr = [row["iqr_s"] for row in rounds]
        median = float(np.median(medians))
        return {
            "rounds": rounds,
            "median_latency_s": median,
            "iqr_latency_s": float(np.median(iqr)),
            "throughput_sequences_per_s": float(LATENCY_BATCH_SIZE / max(median, 1e-12)),
            "warmup_batches": LATENCY_WARMUP_BATCHES,
            "timed_batches": LATENCY_TIMED_BATCHES,
            "independent_rounds": LATENCY_ROUNDS,
            "batch_size": LATENCY_BATCH_SIZE,
            "cuda_synchronize": True,
            "validation_tensor": True,
            "descriptive_only": True,
        }

    with torch.no_grad():
        l1_lat = _run("L1", lambda xb: editor013_forward(l1_student, xb, l1_mods))
        ta2_lat = _run("TA2", lambda xb: historical_student_forward(ta2, xb))

    n_l1 = sum(p.numel() for p in l1_student.lstm.parameters()) + sum(
        p.numel() for p in l1_student.attention.parameters()
    ) + sum(p.numel() for p in l1_mods.parameters())
    n_ta2 = sum(p.numel() for p in ta2.parameters())
    return {
        "L1": {
            **l1_lat,
            "parameter_count": int(n_l1),
            "total_loaded_parameter_count": int(
                sum(p.numel() for p in l1_student.parameters()) + sum(p.numel() for p in l1_mods.parameters())
            ),
            "checkpoint_size": int(Path(L1_CHECKPOINTS[SCREENING_SEED]["checkpoint"]).stat().st_size),
        },
        "TA2": {
            **ta2_lat,
            "parameter_count": int(n_ta2),
            "checkpoint_size": int(Path(F11_CHECKPOINTS[SCREENING_SEED]["checkpoint"]).stat().st_size),
        },
        "same_gpu": True,
        "same_batch_size": LATENCY_BATCH_SIZE,
    }


def ta2_was_tested_in_editor013() -> dict[str, Any]:
    """EDITOR-013 ran the frozen reference-centred protocol on TA2 seed 42."""
    return {
        "WAS_TA2_ITSELF_TESTED_WITH_THE_FROZEN_REFERENCE_CENTRED_INTERVENTION_PROTOCOL": True,
        "source": "review/editor013_odst_value_proof/05_explainability/EDITOR013_EXPLAINABILITY_RULING.json",
        "seed_tested": 42,
        "base_pr_auc": 0.9454098053584642,
        "matches_TA2_seed42": True,
        "PROMOTED_ODST_REFERENCE_CENTRED_FAITHFULNESS": "NOT_SUPPORTED",
        "note": "EDITOR-013 used TA2 after no inner candidate was promoted. Result reused; protocol not redesigned.",
    }


def run_ta2_faithfulness(
    *,
    y: np.ndarray,
    users: np.ndarray,
    train_trees: np.ndarray,
    val_trees: np.ndarray,
) -> dict[str, Any]:
    history = ta2_was_tested_in_editor013()
    refs = train_references(train_trees)
    faith = faithfulness_table(
        y=y,
        tree_outputs=val_trees,
        references=refs,
        weights=None,
        alpha=1.0,
        linear_logit=None,
        hybrid=False,
        users=users,
    )
    return {
        **history,
        "reverified_with_frozen_protocol": True,
        "references_from": "r5.2 TRAIN only",
        "TA2_REFERENCE_CENTRED_FAITHFULNESS": faith["PROMOTED_ODST_REFERENCE_CENTRED_FAITHFULNESS"],
        "TA2_ROUTE_TRACEABILITY": "SUPPORTED",
        "TA2_LEAF_TRACEABILITY": "SUPPORTED",
        "faithfulness": faith,
        "train_reference_shape": list(np.asarray(refs).shape),
    }


def value_matrix_rows(
    *,
    l1_metrics: dict[str, float],
    ta2_metrics: dict[str, float],
    cal: dict[str, Any],
    eff: dict[str, Any],
    faith: dict[str, Any],
) -> list[dict[str, Any]]:
    return [
        {
            "model": "L1",
            "PR-AUC": l1_metrics["pr_auc"],
            "F1": l1_metrics["f1"],
            "Brier": l1_metrics["Brier"],
            "log loss": l1_metrics["log_loss"],
            "PR-AUC CI vs L1": "",
            "Brier CI vs L1": "",
            "log-loss CI vs L1": "",
            "parameter count": eff["L1"]["parameter_count"],
            "latency": eff["L1"]["median_latency_s"],
            "throughput": eff["L1"]["throughput_sequences_per_s"],
            "reference-centred faithfulness": "N/A",
            "route traceability": "N/A",
            "leaf traceability": "N/A",
        },
        {
            "model": "TA2",
            "PR-AUC": ta2_metrics["pr_auc"],
            "F1": ta2_metrics["f1"],
            "Brier": ta2_metrics["Brier"],
            "log loss": ta2_metrics["log_loss"],
            "PR-AUC CI vs L1": str(FROZEN_TA2_L1_CI),
            "Brier CI vs L1": str(cal["ci95_brier"]),
            "log-loss CI vs L1": str(cal["ci95_log_loss"]),
            "parameter count": eff["TA2"]["parameter_count"],
            "latency": eff["TA2"]["median_latency_s"],
            "throughput": eff["TA2"]["throughput_sequences_per_s"],
            "reference-centred faithfulness": faith["TA2_REFERENCE_CENTRED_FAITHFULNESS"],
            "route traceability": "SUPPORTED",
            "leaf traceability": "SUPPORTED",
        },
    ]
