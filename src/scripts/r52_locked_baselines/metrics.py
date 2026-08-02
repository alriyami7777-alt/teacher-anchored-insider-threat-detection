"""Metrics and locked validation threshold procedure."""

from __future__ import annotations

import numpy as np
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    log_loss,
    precision_score,
    recall_score,
    roc_auc_score,
)


def choose_threshold(y_val: np.ndarray, p_val: np.ndarray) -> tuple[float, float]:
    """Locked r4.2 procedure: max validation F1 on linspace + probability quantiles."""
    candidates = set(np.linspace(0.01, 0.99, 99).tolist())
    qs = np.quantile(p_val, np.linspace(0.01, 0.99, 50))
    candidates.update(float(q) for q in qs)
    best_t, best_f1 = 0.5, -1.0
    for t in sorted(candidates):
        y_hat = (p_val >= t).astype(int)
        f1 = float(f1_score(y_val, y_hat, zero_division=0))
        if f1 > best_f1:
            best_f1 = f1
            best_t = float(t)
    return best_t, best_f1


def evaluate_validation(y_true: np.ndarray, y_proba: np.ndarray, threshold: float) -> dict:
    y_true = np.asarray(y_true).astype(int).ravel()
    y_proba = np.asarray(y_proba, dtype=np.float64).ravel()
    y_pred = (y_proba >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()
    n_neg = int((y_true == 0).sum())
    n_pos = int((y_true == 1).sum())
    fpr = float(fp / n_neg) if n_neg else float("nan")
    fnr = float(fn / n_pos) if n_pos else float("nan")
    return {
        "threshold": float(threshold),
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "f1": float(f1_score(y_true, y_pred, zero_division=0)),
        "pr_auc": float(average_precision_score(y_true, y_proba)),
        "roc_auc": float(roc_auc_score(y_true, y_proba)),
        "log_loss": float(log_loss(y_true, np.clip(y_proba, 1e-15, 1 - 1e-15))),
        "brier_score": float(brier_score_loss(y_true, y_proba)),
        "tn": int(tn),
        "fp": int(fp),
        "fn": int(fn),
        "tp": int(tp),
        "fpr": fpr,
        "fnr": fnr,
        "n_alerts": int(tp + fp),
    }
