"""Paired user-cluster bootstrap. Windows are not resampled independently."""

from __future__ import annotations

from typing import Any

import numpy as np
from sklearn.metrics import average_precision_score, f1_score

from .constants import BOOTSTRAP_RESAMPLES, BOOTSTRAP_SEED
from .metrics import sigmoid


def _threshold_f1(y: np.ndarray, probs: np.ndarray) -> float:
    candidates = set(np.linspace(0.01, 0.99, 99).tolist())
    candidates.update(float(q) for q in np.quantile(probs, np.linspace(0.01, 0.99, 50)))
    best_t, best_f1 = 0.5, -1.0
    for t in sorted(candidates):
        f1 = f1_score(y, (probs >= t).astype(int), zero_division=0)
        if f1 > best_f1:
            best_f1 = float(f1)
            best_t = float(t)
    return best_t


def paired_user_cluster_deltas(
    users: np.ndarray,
    y: np.ndarray,
    logits_c2: np.ndarray,
    logits_r2: np.ndarray,
    *,
    n_valid: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    users = np.asarray(users).astype(str)
    y = np.asarray(y).astype(int).ravel()
    p_c2 = sigmoid(np.asarray(logits_c2, dtype=np.float64).ravel())
    p_r2 = sigmoid(np.asarray(logits_r2, dtype=np.float64).ravel())
    unique = np.unique(users)
    index = {u: np.flatnonzero(users == u) for u in unique}
    rng = np.random.default_rng(seed)
    d_pr: list[float] = []
    d_f1: list[float] = []
    attempted = 0
    while len(d_pr) < n_valid:
        attempted += 1
        if attempted > n_valid * 50:
            break
        draw = rng.choice(unique, size=len(unique), replace=True)
        parts_y = []
        parts_c2 = []
        parts_r2 = []
        for u in draw:
            sl = index[str(u)]
            parts_y.append(y[sl])
            parts_c2.append(p_c2[sl])
            parts_r2.append(p_r2[sl])
        yb = np.concatenate(parts_y)
        if len(np.unique(yb)) < 2:
            continue
        a = np.concatenate(parts_c2)
        b = np.concatenate(parts_r2)
        dpr = float(average_precision_score(yb, b) - average_precision_score(yb, a))
        t_c2 = _threshold_f1(yb, a)
        t_r2 = _threshold_f1(yb, b)
        df1 = float(
            f1_score(yb, (b >= t_r2).astype(int), zero_division=0)
            - f1_score(yb, (a >= t_c2).astype(int), zero_division=0)
        )
        if np.isfinite(dpr):
            d_pr.append(dpr)
            d_f1.append(df1)
    arr_pr = np.asarray(d_pr, dtype=np.float64) if d_pr else np.array([np.nan])
    arr_f1 = np.asarray(d_f1, dtype=np.float64) if d_f1 else np.array([np.nan])
    return {
        "cluster": "user",
        "n_users": int(len(unique)),
        "n_valid_resamples": int(len(d_pr)),
        "n_attempted_draws": attempted,
        "seed": seed,
        "primary_statistic": "delta_PR_AUC_R2OPT_minus_C2OPT",
        "mean_delta_pr_auc": float(np.nanmean(arr_pr)),
        "ci95_pr_auc": [float(np.nanpercentile(arr_pr, 2.5)), float(np.nanpercentile(arr_pr, 97.5))],
        "mean_delta_f1": float(np.nanmean(arr_f1)),
        "ci95_f1": [float(np.nanpercentile(arr_f1, 2.5)), float(np.nanpercentile(arr_f1, 97.5))],
        "note": "user-cluster bootstrap; windows not independent; incident clusters not invented",
    }


def paired_user_cluster_mean_across_seeds(
    users: np.ndarray,
    y: np.ndarray,
    logits_c2_by_seed: list[np.ndarray],
    logits_r2_by_seed: list[np.ndarray],
    *,
    n_valid: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    """Resample validation users once; statistic is the mean-across-seeds paired ΔPR-AUC."""
    users = np.asarray(users).astype(str)
    y = np.asarray(y).astype(int).ravel()
    c2s = [sigmoid(np.asarray(a, dtype=np.float64).ravel()) for a in logits_c2_by_seed]
    r2s = [sigmoid(np.asarray(a, dtype=np.float64).ravel()) for a in logits_r2_by_seed]
    unique = np.unique(users)
    index = {u: np.flatnonzero(users == u) for u in unique}
    frozen_thr = [(_threshold_f1(y, a), _threshold_f1(y, b)) for a, b in zip(c2s, r2s)]
    rng = np.random.default_rng(seed)
    d_pr: list[float] = []
    d_f1: list[float] = []
    attempted = 0
    while len(d_pr) < n_valid:
        attempted += 1
        if attempted > n_valid * 50:
            break
        draw = rng.choice(unique, size=len(unique), replace=True)
        sl = np.concatenate([index[str(u)] for u in draw])
        yb = y[sl]
        if len(np.unique(yb)) < 2:
            continue
        seed_dpr = []
        seed_df1 = []
        ok = True
        for (a, b), (t_c2, t_r2) in zip(zip(c2s, r2s), frozen_thr):
            ab = a[sl]
            bb = b[sl]
            dpr = float(average_precision_score(yb, bb) - average_precision_score(yb, ab))
            if not np.isfinite(dpr):
                ok = False
                break
            df1 = float(
                f1_score(yb, (bb >= t_r2).astype(int), zero_division=0)
                - f1_score(yb, (ab >= t_c2).astype(int), zero_division=0)
            )
            seed_dpr.append(dpr)
            seed_df1.append(df1)
        if ok:
            d_pr.append(float(np.mean(seed_dpr)))
            d_f1.append(float(np.mean(seed_df1)))
    arr_pr = np.asarray(d_pr, dtype=np.float64) if d_pr else np.array([np.nan])
    arr_f1 = np.asarray(d_f1, dtype=np.float64) if d_f1 else np.array([np.nan])
    return {
        "cluster": "user",
        "n_users": int(len(unique)),
        "n_valid_resamples": int(len(d_pr)),
        "n_attempted_draws": attempted,
        "seed": seed,
        "sampling_unit": "validation user",
        "statistic": "mean_across_seeds_delta_PR_AUC_R2OPT_minus_C2OPT",
        "mean_delta_pr_auc": float(np.nanmean(arr_pr)),
        "ci95_pr_auc": [float(np.nanpercentile(arr_pr, 2.5)), float(np.nanpercentile(arr_pr, 97.5))],
        "mean_delta_f1": float(np.nanmean(arr_f1)),
        "ci95_f1": [float(np.nanpercentile(arr_f1, 2.5)), float(np.nanpercentile(arr_f1, 97.5))],
        "note": "user-cluster bootstrap; windows not independent; three seeds are not independent experimental units",
    }
