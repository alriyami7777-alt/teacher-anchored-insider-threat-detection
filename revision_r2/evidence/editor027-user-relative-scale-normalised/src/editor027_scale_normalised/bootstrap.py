"""Paired user-cluster bootstrap. Windows are never independent sampling units."""

from __future__ import annotations

from typing import Any, Callable

import numpy as np
from sklearn.metrics import average_precision_score

from editor012_rescue.metrics import sigmoid

from .constants import BOOTSTRAP_RESAMPLES, BOOTSTRAP_SEED


def pr_auc(y: np.ndarray, scores: np.ndarray) -> float:
    y = np.asarray(y).astype(int).ravel()
    p = np.asarray(scores, dtype=np.float64).ravel()
    if len(np.unique(y)) < 2:
        return float("nan")
    return float(average_precision_score(y, p))


def pr_auc_from_logits(y: np.ndarray, logits: np.ndarray) -> float:
    return pr_auc(y, sigmoid(np.asarray(logits, dtype=np.float64)))


def ap_lift(pr: float, prevalence: float) -> float:
    if prevalence == 0.0 or not np.isfinite(prevalence):
        return float("nan")
    return float(pr / prevalence)


def user_cluster_bootstrap(
    users: np.ndarray,
    y: np.ndarray,
    stat_fn: Callable[[np.ndarray, np.ndarray], dict[str, float]],
    *,
    n_valid: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    y = np.asarray(y).astype(int).ravel()
    users = np.asarray(users).astype(str)
    unique = np.unique(users)
    index = {u: np.flatnonzero(users == u) for u in unique}
    rng = np.random.default_rng(seed)
    buckets: dict[str, list[float]] = {}
    attempted = 0
    n_ok = 0
    while n_ok < n_valid:
        attempted += 1
        if attempted > n_valid * 50:
            break
        chosen = rng.choice(unique, size=len(unique), replace=True)
        sl = np.concatenate([index[str(u)] for u in chosen])
        yb = y[sl]
        if len(np.unique(yb)) < 2:
            continue
        rec = stat_fn(sl, yb)
        if not rec or any(not np.isfinite(v) for v in rec.values()):
            continue
        for k, v in rec.items():
            buckets.setdefault(k, []).append(float(v))
        n_ok += 1
    out: dict[str, Any] = {
        "cluster": "user",
        "sampling_unit": "user",
        "windows_not_independent": True,
        "matched_contrasts_share_resampled_users": True,
        "n_users": int(len(unique)),
        "n_attempted_draws": attempted,
        "n_valid_resamples": n_ok,
        "seed": seed,
        "statistics": {},
    }
    for name, draws in buckets.items():
        arr = np.asarray(draws, dtype=np.float64)
        out["statistics"][name] = {
            "mean": float(np.mean(arr)),
            "ci95": [float(np.percentile(arr, 2.5)), float(np.percentile(arr, 97.5))],
        }
    return out
