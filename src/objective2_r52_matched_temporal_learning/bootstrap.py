"""Paired user-cluster bootstrap for temporal effects."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score

from .constants import BOOTSTRAP_SEED, N_BOOTSTRAP_MAX_ATTEMPTS, N_BOOTSTRAP_TARGET


def _pr(y: np.ndarray, p: np.ndarray) -> float:
    return float(average_precision_score(y, p))


def paired_user_bootstrap_delta_pr(
    y: np.ndarray,
    probs_a: np.ndarray,
    probs_b: np.ndarray,
    users: np.ndarray,
    *,
    stream_seed: int,
    n_target: int = N_BOOTSTRAP_TARGET,
    n_max: int = N_BOOTSTRAP_MAX_ATTEMPTS,
) -> dict[str, Any]:
    """Delta = PR(probs_a) - PR(probs_b) under identical user draws."""
    y = np.asarray(y).astype(int).ravel()
    probs_a = np.asarray(probs_a, dtype=np.float64).ravel()
    probs_b = np.asarray(probs_b, dtype=np.float64).ravel()
    codes, uniq = pd.factorize(np.asarray(users), sort=False)
    n_users = int(len(uniq))
    order = np.argsort(codes, kind="mergesort")
    sorted_codes = codes[order]
    boundaries = np.flatnonzero(np.r_[True, sorted_codes[1:] != sorted_codes[:-1], True])
    slices = [(int(boundaries[i]), int(boundaries[i + 1])) for i in range(n_users)]
    rng = np.random.default_rng(stream_seed)
    deltas: list[float] = []
    attempted = discarded = 0
    observed = _pr(y, probs_a) - _pr(y, probs_b)
    while len(deltas) < n_target and attempted < n_max:
        attempted += 1
        chosen = rng.integers(0, n_users, size=n_users)
        idx = np.concatenate([order[slices[i][0] : slices[i][1]] for i in chosen])
        ya = y[idx]
        if ya.sum() == 0 or ya.sum() == len(ya):
            discarded += 1
            continue
        deltas.append(_pr(ya, probs_a[idx]) - _pr(ya, probs_b[idx]))
    arr = np.asarray(deltas, dtype=float)
    return {
        "observed_delta": float(observed),
        "boot_mean_delta": float(arr.mean()) if len(arr) else float("nan"),
        "ci95_low": float(np.quantile(arr, 0.025)) if len(arr) else float("nan"),
        "ci95_high": float(np.quantile(arr, 0.975)) if len(arr) else float("nan"),
        "n_users": n_users,
        "attempted": attempted,
        "valid": int(len(arr)),
        "discarded": discarded,
        "limited": len(arr) < n_target,
        "stream_seed": stream_seed,
        "ci_excludes_zero": bool(len(arr) and (arr.min() is not None) and (np.quantile(arr, 0.025) > 0 or np.quantile(arr, 0.975) < 0)),
    }


def interpret_delta(observed: float, ci_low: float, ci_high: float, margin: float) -> str:
    if np.isnan(ci_low):
        return "unverifiable"
    supports_pos = ci_low > 0
    supports_neg = ci_high < 0
    if observed >= margin and supports_pos:
        return "supported_chronological_dependence"
    if observed >= margin and not supports_pos:
        return "numerical_chronological_dependence_uncertain"
    if observed > 0:
        return "limited_chronological_dependence"
    if supports_neg:
        return "no_detectable_chronological_dependence"
    return "no_detectable_chronological_dependence"
