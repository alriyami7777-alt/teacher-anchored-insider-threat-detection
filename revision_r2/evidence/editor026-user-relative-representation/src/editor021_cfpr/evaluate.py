"""Clean and degraded scoring with EDITOR-021 composite resilience."""

from __future__ import annotations

from typing import Any

import numpy as np
import torch
import torch.nn as nn

from editor012_rescue.metrics import metrics_from_logits, sigmoid
from editor017_robustness.constants import NOISE_LEVELS, SOURCE_CHANNELS
from editor020_robustness.evaluate import build_degraded_views, score_condition

from .safety import Editor021Blocked, refuse_validation_threshold_search


def resilience_from_logits(
    y: np.ndarray,
    clean_logits: np.ndarray,
    source_logits: dict[str, np.ndarray],
    noise_logits: dict[float, np.ndarray],
    *,
    threshold: float,
) -> dict[str, Any]:
    if set(source_logits) != set(SOURCE_CHANNELS):
        raise Editor021Blocked("source logit map must contain the frozen five channels")
    if set(float(k) for k in noise_logits) != set(NOISE_LEVELS):
        raise Editor021Blocked("noise logit map must contain the frozen three levels")
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
                "delta": float(met["pr_auc"]) - float(clean["pr_auc"]),
                "retention": float(met["pr_auc"]) / max(float(clean["pr_auc"]), 1e-12),
                "Brier": float(met["Brier"]),
                "log_loss": float(met["log_loss"]),
            }
        )
    s_source = float(np.mean([r["delta"] for r in source_rows]))
    s_noise = float(np.mean([r["delta"] for r in noise_rows]))
    return {
        "clean_PR_AUC": float(clean["pr_auc"]),
        "clean_Brier": float(clean["Brier"]),
        "clean_log_loss": float(clean["log_loss"]),
        "clean_F1": float(clean.get("f1", clean.get("F1", float("nan")))),
        "source": source_rows,
        "noise": noise_rows,
        "S_source": s_source,
        "S_noise": s_noise,
        "S_composite": 0.5 * s_source + 0.5 * s_noise,
        "MEAN_SOURCE_DELTA": s_source,
        "WORST_SOURCE_DELTA": float(np.min([r["delta"] for r in source_rows])),
        "MEAN_NOISE_RETENTION": float(np.mean([r["retention"] for r in noise_rows])),
        "threshold": float(threshold),
    }


def score_all_views(
    student: nn.Module,
    views: dict[str, np.ndarray],
    y: np.ndarray,
    device: torch.device,
    *,
    split: str,
    threshold: float | None = None,
    allow_threshold_search: bool = False,
) -> dict[str, Any]:
    if not allow_threshold_search:
        refuse_validation_threshold_search(split=split, threshold=threshold)
    elif str(split).lower() in {"validation", "val", "official_validation"}:
        refuse_validation_threshold_search(split=split, threshold=threshold)
    clean = score_condition("TA2", student, None, views["clean"], y, device, threshold=threshold)
    thr = float(clean["threshold"])
    source_logits = {}
    source_pack = {}
    for ch in SOURCE_CHANNELS:
        pack = score_condition("TA2", student, None, views[f"source_{ch}"], y, device, threshold=thr)
        source_logits[ch] = pack["logits"]
        source_pack[ch] = pack
    noise_logits = {}
    noise_pack = {}
    for level in NOISE_LEVELS:
        pack = score_condition(
            "TA2", student, None, views[f"noise_{level:.2f}"], y, device, threshold=thr
        )
        noise_logits[float(level)] = pack["logits"]
        noise_pack[float(level)] = pack
    robust = resilience_from_logits(y, clean["logits"], source_logits, noise_logits, threshold=thr)
    return {
        "clean": clean,
        "source": source_pack,
        "noise": noise_pack,
        "robust": robust,
        "source_logits": source_logits,
        "noise_logits": noise_logits,
        "probs": sigmoid(clean["logits"]),
    }
