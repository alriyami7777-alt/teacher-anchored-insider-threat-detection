"""User-cluster bootstrap for family-level degraded-input statistics.

Sampling unit is the validation user. Windows are never resampled independently.
Three seeds are repeated realisations, not independent experimental units.
"""

from __future__ import annotations

from typing import Any, Callable

import numpy as np
from sklearn.metrics import average_precision_score

from .constants import BOOTSTRAP_RESAMPLES, BOOTSTRAP_SEED


def _user_index(users: np.ndarray) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    users = np.asarray(users).astype(str)
    unique = np.unique(users)
    index = {u: np.flatnonzero(users == u) for u in unique}
    return unique, index


def user_cluster_stat(
    users: np.ndarray,
    y: np.ndarray,
    stat_fn: Callable[[np.ndarray, np.ndarray], float],
    *,
    n_valid: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
    contrast: str = "family_stat",
) -> dict[str, Any]:
    """Bootstrap a scalar statistic that already averages across seeds internally.

    ``stat_fn(sl, yb)`` receives resampled row indices and labels.
    """
    y = np.asarray(y).astype(int).ravel()
    unique, index = _user_index(users)
    rng = np.random.default_rng(seed)
    draws: list[float] = []
    attempted = 0
    while len(draws) < n_valid:
        attempted += 1
        if attempted > n_valid * 50:
            break
        chosen = rng.choice(unique, size=len(unique), replace=True)
        sl = np.concatenate([index[str(u)] for u in chosen])
        yb = y[sl]
        if len(np.unique(yb)) < 2:
            continue
        val = float(stat_fn(sl, yb))
        if np.isfinite(val):
            draws.append(val)
    arr = np.asarray(draws, dtype=np.float64) if draws else np.array([np.nan])
    return {
        "cluster": "user",
        "n_users": int(len(unique)),
        "n_valid_resamples": int(len(draws)),
        "n_attempted_draws": attempted,
        "seed": seed,
        "sampling_unit": "validation user",
        "statistic": contrast,
        "mean": float(np.nanmean(arr)),
        "ci95": [float(np.nanpercentile(arr, 2.5)), float(np.nanpercentile(arr, 97.5))],
        "ci_excludes_zero": bool(
            np.isfinite(arr).any()
            and float(np.nanpercentile(arr, 2.5)) > 0
            or (np.isfinite(arr).any() and float(np.nanpercentile(arr, 97.5)) < 0)
        ),
        "windows_not_independent": True,
        "three_seeds_are_not_independent_experimental_units": True,
    }


def _pr_auc(y: np.ndarray, logits: np.ndarray) -> float:
    from editor012_rescue.metrics import sigmoid

    y = np.asarray(y).astype(int).ravel()
    p = sigmoid(np.asarray(logits, dtype=np.float64).ravel())
    if len(np.unique(y)) < 2:
        return float("nan")
    return float(average_precision_score(y, p))


def mean_source_delta_contrast(
    y: np.ndarray,
    users: np.ndarray,
    clean_a: list[np.ndarray],
    clean_b: list[np.ndarray],
    degraded_a: list[list[np.ndarray]],
    degraded_b: list[list[np.ndarray]],
    *,
    contrast: str,
) -> dict[str, Any]:
    """Contrast MEAN_SOURCE_DELTA(B) - MEAN_SOURCE_DELTA(A), mean across seeds.

    ``degraded_*[seed_i][source_j]`` are logit arrays.
    """

    def stat(sl: np.ndarray, yb: np.ndarray) -> float:
        seed_stats = []
        for ca, cb, das, dbs in zip(clean_a, clean_b, degraded_a, degraded_b):
            pr_ca = _pr_auc(yb, ca[sl])
            pr_cb = _pr_auc(yb, cb[sl])
            d_a = [(_pr_auc(yb, d[sl]) - pr_ca) for d in das]
            d_b = [(_pr_auc(yb, d[sl]) - pr_cb) for d in dbs]
            seed_stats.append(float(np.mean(d_b) - np.mean(d_a)))
        return float(np.mean(seed_stats))

    rec = user_cluster_stat(users, y, stat, contrast=contrast)
    lo, hi = rec["ci95"]
    rec["ci_excludes_zero"] = bool(hi < 0 or lo > 0)
    rec["direction_favours_B"] = bool(rec["mean"] > 0)
    return rec


def mean_noise_retention_contrast(
    y: np.ndarray,
    users: np.ndarray,
    clean_a: list[np.ndarray],
    clean_b: list[np.ndarray],
    degraded_a: list[list[np.ndarray]],
    degraded_b: list[list[np.ndarray]],
    *,
    contrast: str,
) -> dict[str, Any]:
    """Contrast MEAN_NOISE_RETENTION(B) - MEAN_NOISE_RETENTION(A)."""

    def stat(sl: np.ndarray, yb: np.ndarray) -> float:
        seed_stats = []
        for ca, cb, das, dbs in zip(clean_a, clean_b, degraded_a, degraded_b):
            pr_ca = _pr_auc(yb, ca[sl])
            pr_cb = _pr_auc(yb, cb[sl])
            r_a = [( _pr_auc(yb, d[sl]) / pr_ca) if pr_ca > 0 else float("nan") for d in das]
            r_b = [( _pr_auc(yb, d[sl]) / pr_cb) if pr_cb > 0 else float("nan") for d in dbs]
            seed_stats.append(float(np.nanmean(r_b) - np.nanmean(r_a)))
        return float(np.mean(seed_stats))

    rec = user_cluster_stat(users, y, stat, contrast=contrast)
    lo, hi = rec["ci95"]
    rec["ci_excludes_zero"] = bool(hi < 0 or lo > 0)
    rec["direction_favours_B"] = bool(rec["mean"] > 0)
    return rec


def mean_scalar_contrast(
    users: np.ndarray,
    y: np.ndarray,
    values_a: list[np.ndarray],
    values_b: list[np.ndarray],
    *,
    contrast: str,
    higher_is_better: bool = True,
) -> dict[str, Any]:
    """Mean-across-seeds contrast of a per-sequence scalar (B - A)."""

    def stat(sl: np.ndarray, yb: np.ndarray) -> float:
        seed_stats = []
        for a, b in zip(values_a, values_b):
            seed_stats.append(float(np.mean(b[sl]) - np.mean(a[sl])))
        return float(np.mean(seed_stats))

    rec = user_cluster_stat(users, y, stat, contrast=contrast)
    lo, hi = rec["ci95"]
    rec["ci_excludes_zero"] = bool(hi < 0 or lo > 0)
    rec["direction_favours_B"] = bool(rec["mean"] > 0) if higher_is_better else bool(rec["mean"] < 0)
    return rec
