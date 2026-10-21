"""Scoring helpers for matched temporal evaluation."""

from __future__ import annotations

from typing import Any

import numpy as np
from sklearn.metrics import (
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
)


def score_at_threshold(y: np.ndarray, probs: np.ndarray, threshold: float) -> dict[str, Any]:
    y = np.asarray(y).astype(int).ravel()
    probs = np.asarray(probs, dtype=np.float64).ravel()
    pred = (probs >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y, pred, labels=[0, 1]).ravel()
    return {
        "pr_auc": float(average_precision_score(y, probs)),
        "precision": float(precision_score(y, pred, zero_division=0)),
        "recall": float(recall_score(y, pred, zero_division=0)),
        "f1": float(f1_score(y, pred, zero_division=0)),
        "fp": int(fp),
        "fn": int(fn),
        "tp": int(tp),
        "tn": int(tn),
        "threshold": float(threshold),
        "malicious_detection_rate": float(tp / max(int((y == 1).sum()), 1)),
        "n_pred_pos": int(pred.sum()),
    }


def compare_to_clean(
    y: np.ndarray,
    probs: np.ndarray,
    clean_probs: np.ndarray,
    threshold: float,
) -> dict[str, Any]:
    y = np.asarray(y).astype(int).ravel()
    probs = np.asarray(probs, dtype=np.float64).ravel()
    clean_probs = np.asarray(clean_probs, dtype=np.float64).ravel()
    pred = (probs >= threshold).astype(int)
    clean_pred = (clean_probs >= threshold).astype(int)
    mal = y == 1
    nor = y == 0
    return {
        "prediction_agreement_with_t0": float((pred == clean_pred).mean()),
        "mean_abs_score_displacement": float(np.mean(np.abs(probs - clean_probs))),
        "mean_malicious_score_change": float(np.mean(probs[mal] - clean_probs[mal])) if mal.any() else float("nan"),
        "mean_normal_score_change": float(np.mean(probs[nor] - clean_probs[nor])) if nor.any() else float("nan"),
        "n_malicious_to_normal": int(((clean_pred == 1) & (pred == 0) & mal).sum()),
        "n_normal_to_malicious": int(((clean_pred == 0) & (pred == 1) & nor).sum()),
    }
