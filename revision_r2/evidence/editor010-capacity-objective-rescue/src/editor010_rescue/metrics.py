"""PR-AUC and locked F1-threshold metrics for EDITOR-010."""

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
)


def choose_threshold(y_true: np.ndarray, probs: np.ndarray) -> tuple[float, float]:
    y_true = np.asarray(y_true).astype(int).ravel()
    probs = np.asarray(probs, dtype=np.float64).ravel()
    candidates = set(np.linspace(0.01, 0.99, 99).tolist())
    candidates.update(float(q) for q in np.quantile(probs, np.linspace(0.01, 0.99, 50)))
    best_t, best_f1 = 0.5, -1.0
    for t in sorted(candidates):
        f1 = float(f1_score(y_true, (probs >= t).astype(int), zero_division=0))
        if f1 > best_f1:
            best_f1 = f1
            best_t = float(t)
    return best_t, best_f1


def evaluate_scores(y_true: np.ndarray, logits: np.ndarray | None = None, probs: np.ndarray | None = None) -> dict:
    y_true = np.asarray(y_true).astype(int).ravel()
    if probs is None:
        if logits is None:
            raise ValueError("logits or probs required")
        logits = np.asarray(logits, dtype=np.float64).ravel()
        probs = 1.0 / (1.0 + np.exp(-np.clip(logits, -40.0, 40.0)))
    else:
        probs = np.clip(np.asarray(probs, dtype=np.float64).ravel(), 1e-15, 1.0 - 1e-15)
        if logits is None:
            logits = np.log(probs / (1.0 - probs))
        else:
            logits = np.asarray(logits, dtype=np.float64).ravel()
    threshold, _ = choose_threshold(y_true, probs)
    pred = (probs >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y_true, pred, labels=[0, 1]).ravel()
    return {
        "pr_auc": float(average_precision_score(y_true, probs)),
        "f1": float(f1_score(y_true, pred, zero_division=0)),
        "precision": float(precision_score(y_true, pred, zero_division=0)),
        "recall": float(recall_score(y_true, pred, zero_division=0)),
        "fp": int(fp),
        "fn": int(fn),
        "tp": int(tp),
        "tn": int(tn),
        "brier": float(brier_score_loss(y_true, probs)),
        "log_loss": float(log_loss(y_true, np.clip(probs, 1e-15, 1.0 - 1e-15))),
        "threshold": float(threshold),
        "n": int(len(y_true)),
        "n_pos": int(y_true.sum()),
    }


def pairwise_disagreement(a: np.ndarray, b: np.ndarray, y: np.ndarray, threshold_a: float, threshold_b: float) -> dict:
    a = np.asarray(a, dtype=np.float64).ravel()
    b = np.asarray(b, dtype=np.float64).ravel()
    y = np.asarray(y).astype(int).ravel()
    pa = (a >= threshold_a).astype(int)
    pb = (b >= threshold_b).astype(int)
    return {
        "prediction_disagreement": float(np.mean(pa != pb)),
        "positive_case_disagreement": float(np.mean(pa[y == 1] != pb[y == 1])) if (y == 1).any() else float("nan"),
        "error_overlap": float(np.mean((pa != y) & (pb != y))),
    }
