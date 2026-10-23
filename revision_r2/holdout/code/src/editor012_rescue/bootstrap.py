"""Paired user-cluster bootstrap. Windows are not resampled independently."""

from __future__ import annotations

from typing import Any

import numpy as np
from sklearn.metrics import average_precision_score, f1_score

from .constants import BOOTSTRAP_RESAMPLES, BOOTSTRAP_SEED
from .metrics import sigmoid


def paired_user_cluster_mean_across_seeds(
    users: np.ndarray,
    y: np.ndarray,
    logits_a_by_seed: list[np.ndarray],
    logits_b_by_seed: list[np.ndarray],
    *,
    frozen_thresholds_a: list[float],
    frozen_thresholds_b: list[float],
    n_valid: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
    contrast: str = "B_minus_A",
) -> dict[str, Any]:
    """Resample validation users once; statistic is the mean-across-seeds paired Δ.

    F1 uses frozen condition thresholds. Thresholds are not retuned inside replicates.
    """
    users = np.asarray(users).astype(str)
    y = np.asarray(y).astype(int).ravel()
    as_ = [sigmoid(np.asarray(a, dtype=np.float64).ravel()) for a in logits_a_by_seed]
    bs = [sigmoid(np.asarray(b, dtype=np.float64).ravel()) for b in logits_b_by_seed]
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
        sl = np.concatenate([index[str(u)] for u in draw])
        yb = y[sl]
        if len(np.unique(yb)) < 2:
            continue
        seed_dpr = []
        seed_df1 = []
        ok = True
        for a, b, t_a, t_b in zip(as_, bs, frozen_thresholds_a, frozen_thresholds_b):
            ab = a[sl]
            bb = b[sl]
            dpr = float(average_precision_score(yb, bb) - average_precision_score(yb, ab))
            if not np.isfinite(dpr):
                ok = False
                break
            df1 = float(
                f1_score(yb, (bb >= t_b).astype(int), zero_division=0)
                - f1_score(yb, (ab >= t_a).astype(int), zero_division=0)
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
        "statistic": f"mean_across_seeds_delta_PR_AUC_{contrast}",
        "mean_delta_pr_auc": float(np.nanmean(arr_pr)),
        "ci95_pr_auc": [float(np.nanpercentile(arr_pr, 2.5)), float(np.nanpercentile(arr_pr, 97.5))],
        "mean_delta_f1": float(np.nanmean(arr_f1)),
        "ci95_f1": [float(np.nanpercentile(arr_f1, 2.5)), float(np.nanpercentile(arr_f1, 97.5))],
        "f1_thresholds_frozen": True,
        "f1_retuned_inside_bootstrap": False,
        "windows_not_independent": True,
        "three_seeds_are_not_independent_experimental_units": True,
        "note": "user-cluster bootstrap; windows not independent; seeds are repeated realisations",
    }
