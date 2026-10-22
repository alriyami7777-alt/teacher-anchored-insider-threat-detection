"""Clean and degraded scoring. Thresholds are never retuned on degraded inputs."""

from __future__ import annotations

from typing import Any

import numpy as np
import torch
import torch.nn as nn

from editor012_rescue.data import make_xy_loader
from editor012_rescue.metrics import metrics_from_logits
from editor017_robustness.constants import NOISE_LEVELS, SOURCE_CHANNELS
from editor017_robustness.perturbations import apply_gaussian_noise, apply_source_ablation

from .constants import BATCH_SIZE
from .models import forward_student
from .safety import Editor020Blocked


@torch.no_grad()
def score_condition(
    arch: str,
    student: nn.Module,
    modules: nn.Module | None,
    X: np.ndarray,
    y: np.ndarray,
    device: torch.device,
    *,
    threshold: float | None = None,
) -> dict[str, Any]:
    student.eval()
    if modules is not None:
        modules.eval()
    loader = make_xy_loader(X, y, seed=0, batch_size=BATCH_SIZE, shuffle=False)
    logits, choices, trees, leaves = [], [], [], []
    ys = []
    for xb, yb in loader:
        out = forward_student(arch, student, xb.to(device), modules)
        logits.append(out["logit"].detach().cpu().numpy())
        choices.append(out["choices"].detach().cpu().numpy())
        trees.append(out["tree_outputs"].detach().cpu().numpy())
        leaves.append(out["leaf_probs_all"].detach().cpu().numpy())
        ys.append(np.asarray(yb).reshape(-1))
    y_np = np.concatenate(ys).reshape(-1)
    lg = np.concatenate(logits)
    met = metrics_from_logits(y_np, lg, threshold=threshold)
    return {
        "metrics": {k: v for k, v in met.items() if k not in {"probs", "pred"}},
        "logits": lg.astype(np.float32),
        "y": y_np,
        "choices": np.concatenate(choices).astype(np.float32),
        "tree_outputs": np.concatenate(trees).astype(np.float32),
        "leaf_probs_all": np.concatenate(leaves).astype(np.float32),
        "threshold": float(met["threshold"]),
    }


def robustness_from_logits(
    y: np.ndarray,
    clean_logits: np.ndarray,
    source_logits: dict[str, np.ndarray],
    noise_logits: dict[float, np.ndarray],
    *,
    threshold: float,
) -> dict[str, Any]:
    if set(source_logits) != set(SOURCE_CHANNELS):
        raise Editor020Blocked("source logit map must contain the frozen five channels")
    if set(float(k) for k in noise_logits) != set(NOISE_LEVELS):
        raise Editor020Blocked("noise logit map must contain the frozen three levels")
    clean = metrics_from_logits(y, clean_logits, threshold=threshold)
    source_rows = []
    for ch in SOURCE_CHANNELS:
        met = metrics_from_logits(y, source_logits[ch], threshold=threshold)
        source_rows.append(
            {
                "channel": ch,
                "pr_auc": float(met["pr_auc"]),
                "delta": float(met["pr_auc"]) - float(clean["pr_auc"]),
                "Brier": float(met["Brier"]),
                "log_loss": float(met["log_loss"]),
            }
        )
    noise_rows = []
    for level in NOISE_LEVELS:
        met = metrics_from_logits(y, noise_logits[level], threshold=threshold)
        noise_rows.append(
            {
                "level": float(level),
                "pr_auc": float(met["pr_auc"]),
                "retention": float(met["pr_auc"]) / max(float(clean["pr_auc"]), 1e-12),
                "Brier": float(met["Brier"]),
                "log_loss": float(met["log_loss"]),
            }
        )
    src_d = [r["delta"] for r in source_rows]
    return {
        "clean_PR_AUC": float(clean["pr_auc"]),
        "clean_Brier": float(clean["Brier"]),
        "clean_log_loss": float(clean["log_loss"]),
        "source": source_rows,
        "noise": noise_rows,
        "MEAN_SOURCE_DELTA": float(np.mean(src_d)),
        "WORST_SOURCE_DELTA": float(np.min(src_d)),
        "MEAN_NOISE_RETENTION": float(np.mean([r["retention"] for r in noise_rows])),
        "threshold": float(threshold),
    }


def build_degraded_views(X: np.ndarray, scaler: dict[str, Any]) -> dict[str, np.ndarray]:
    views: dict[str, np.ndarray] = {"clean": np.asarray(X, dtype=np.float32)}
    for ch in SOURCE_CHANNELS:
        views[f"source_{ch}"] = apply_source_ablation(X, ch, scaler)
    for level in NOISE_LEVELS:
        views[f"noise_{level:.2f}"] = apply_gaussian_noise(X, float(level))
    return views


def score_all_views(
    arch: str,
    student: nn.Module,
    modules: nn.Module | None,
    views: dict[str, np.ndarray],
    y: np.ndarray,
    device: torch.device,
) -> dict[str, Any]:
    clean = score_condition(arch, student, modules, views["clean"], y, device)
    thr = float(clean["threshold"])
    source_logits = {}
    source_pack = {}
    for ch in SOURCE_CHANNELS:
        pack = score_condition(
            arch, student, modules, views[f"source_{ch}"], y, device, threshold=thr
        )
        source_logits[ch] = pack["logits"]
        source_pack[ch] = pack
    noise_logits = {}
    noise_pack = {}
    for level in NOISE_LEVELS:
        pack = score_condition(
            arch, student, modules, views[f"noise_{level:.2f}"], y, device, threshold=thr
        )
        noise_logits[float(level)] = pack["logits"]
        noise_pack[float(level)] = pack
    robust = robustness_from_logits(y, clean["logits"], source_logits, noise_logits, threshold=thr)
    return {
        "clean": clean,
        "source": source_pack,
        "noise": noise_pack,
        "robust": robust,
        "source_logits": source_logits,
        "noise_logits": noise_logits,
    }
