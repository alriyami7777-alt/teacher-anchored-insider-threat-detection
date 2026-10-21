"""Development metrics. PR-AUC is primary."""

from __future__ import annotations

from typing import Any

import numpy as np
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    f1_score,
    log_loss,
)

from .producing import import_threshold_fns


def sigmoid(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    return 1.0 / (1.0 + np.exp(-np.clip(x, -60, 60)))


def metrics_from_logits(
    y: np.ndarray,
    logits: np.ndarray,
    *,
    threshold: float | None = None,
) -> dict[str, Any]:
    y = np.asarray(y).astype(int).reshape(-1)
    logits = np.asarray(logits, dtype=np.float64).reshape(-1)
    probs = sigmoid(logits)
    choose_threshold_f1, metrics_at_threshold = import_threshold_fns()
    if threshold is None:
        thr, _ = choose_threshold_f1(y, probs)
    else:
        thr = float(threshold)
    met = metrics_at_threshold(y, probs, thr)
    pred = (probs >= thr).astype(int)
    brier = float(brier_score_loss(y, np.clip(probs, 1e-7, 1 - 1e-7)))
    ll = float(log_loss(y, np.clip(probs, 1e-7, 1 - 1e-7), labels=[0, 1]))
    return {
        **met,
        "pr_auc": float(average_precision_score(y, probs)),
        "Brier": brier,
        "log_loss": ll,
        "predicted_positive_fraction": float(pred.mean()),
        "probs": probs,
        "pred": pred,
        "threshold": float(thr),
        "n": int(len(y)),
        "n_pos": int(y.sum()),
    }


def teacher_relative(
    student_logits: np.ndarray,
    teacher_logits: np.ndarray,
    student_choices: np.ndarray | None = None,
    teacher_choices: np.ndarray | None = None,
    student_leaves: np.ndarray | None = None,
    teacher_leaves: np.ndarray | None = None,
) -> dict[str, float]:
    sl = np.asarray(student_logits, dtype=np.float64).reshape(-1)
    tl = np.asarray(teacher_logits, dtype=np.float64).reshape(-1)
    out = {
        "teacher_logit_deviation": float(np.mean(np.abs(sl - tl))),
        "logit_pearson": float(np.corrcoef(sl, tl)[0, 1]) if sl.size > 2 else float("nan"),
    }
    if student_choices is not None and teacher_choices is not None:
        sc = np.asarray(student_choices, dtype=np.float64)
        tc = np.asarray(teacher_choices, dtype=np.float64)
        out["route_MAE"] = float(np.mean(np.abs(sc - tc)))
        eps = 1e-6
        kl = tc * np.log((tc + eps) / (sc + eps)) + (1.0 - tc) * np.log((1.0 - tc + eps) / (1.0 - sc + eps))
        out["route_KL"] = float(np.mean(kl))
        out["hard_route_agreement"] = float(np.mean((sc >= 0.5) == (tc >= 0.5)))
    if student_leaves is not None and teacher_leaves is not None:
        slv = np.asarray(student_leaves)
        tlv = np.asarray(teacher_leaves)
        out["dominant_leaf_agreement"] = float(np.mean(slv.argmax(axis=-1) == tlv.argmax(axis=-1)))
    return out
