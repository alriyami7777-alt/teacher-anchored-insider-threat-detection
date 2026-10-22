"""User-cluster bootstrap. Windows are never resampled independently."""

from __future__ import annotations

from typing import Any, Callable

import numpy as np
from sklearn.metrics import average_precision_score

from editor012_rescue.metrics import sigmoid

from .constants import BOOTSTRAP_RESAMPLES, BOOTSTRAP_SEED, SEEDS, STUDENT_MODELS


def pr_auc(y: np.ndarray, scores: np.ndarray) -> float:
    y = np.asarray(y).astype(int).ravel()
    p = np.asarray(scores, dtype=np.float64).ravel()
    if len(np.unique(y)) < 2:
        return float("nan")
    return float(average_precision_score(y, p))


def pr_auc_from_logits(y: np.ndarray, logits: np.ndarray) -> float:
    return pr_auc(y, sigmoid(np.asarray(logits, dtype=np.float64)))


def _user_index(users: np.ndarray) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    users = np.asarray(users).astype(str)
    unique = np.unique(users)
    index = {u: np.flatnonzero(users == u) for u in unique}
    return unique, index


def user_cluster_bootstrap(
    users: np.ndarray,
    y: np.ndarray,
    stat_fn: Callable[[np.ndarray, np.ndarray], dict[str, float]],
    *,
    n_valid: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
    n_positive_label_users: int | None = None,
) -> dict[str, Any]:
    """One user-resampling loop; matched-model stats share identical resampled users."""
    y = np.asarray(y).astype(int).ravel()
    unique, index = _user_index(users)
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
        "sampling_unit": "r6.1 user",
        "n_users": int(len(unique)),
        "n_positive_label_users": int(n_positive_label_users)
        if n_positive_label_users is not None
        else int(len({str(u) for u, lab in zip(np.asarray(users).astype(str), y) if lab > 0})),
        "n_attempted_draws": attempted,
        "n_valid_resamples": n_ok,
        "seed": seed,
        "windows_not_independent": True,
        "matched_models_share_resampled_users": True,
        "statistics": {},
    }
    for name, draws in buckets.items():
        arr = np.asarray(draws, dtype=np.float64)
        lo = float(np.percentile(arr, 2.5))
        hi = float(np.percentile(arr, 97.5))
        out["statistics"][name] = {
            "mean": float(np.mean(arr)),
            "ci95": [lo, hi],
            "ci_lower_bound_gt_0": bool(lo > 0),
            "n_valid_resamples": int(arr.size),
        }
    return out


def mean_seed_pr_auc(y: np.ndarray, logits_by_seed: dict[int, np.ndarray], sl: np.ndarray) -> float:
    vals = [pr_auc_from_logits(y[sl], logits_by_seed[seed][sl]) for seed in SEEDS]
    return float(np.mean(vals))


def contrast_stat_fn(
    logits: dict[str, dict[int, np.ndarray]],
    prevalence: float,
) -> Callable[[np.ndarray, np.ndarray], dict[str, float]]:
    def stat(sl: np.ndarray, yb: np.ndarray) -> dict[str, float]:
        means = {
            m: float(np.mean([pr_auc_from_logits(yb, logits[m][seed][sl]) for seed in SEEDS]))
            for m in STUDENT_MODELS
        }
        return {
            "TA2_PR_AUC": means["TA2"],
            "C2-OPT_PR_AUC": means["C2-OPT"],
            "F10_PR_AUC": means["F10"],
            "L1_PR_AUC": means["L1"],
            "TA2_RANKING_EXCESS": means["TA2"] - float(prevalence),
            "TA2_MINUS_C2": means["TA2"] - means["C2-OPT"],
            "F10_MINUS_C2": means["F10"] - means["C2-OPT"],
            "TA2_MINUS_F10": means["TA2"] - means["F10"],
            "TA2_MINUS_L1": means["TA2"] - means["L1"],
        }

    return stat
