"""User-cluster bootstrap. Windows are not resampled independently. No invented incidents."""

from __future__ import annotations

from typing import Any

import numpy as np
from sklearn.metrics import average_precision_score

from .constants import BOOTSTRAP_RESAMPLES, BOOTSTRAP_SEED


def paired_user_cluster_delta_pr(
    users: np.ndarray,
    y: np.ndarray,
    scores_a: np.ndarray,
    scores_b: np.ndarray,
    *,
    n_valid: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    users = np.asarray(users).astype(str)
    y = np.asarray(y).astype(int).ravel()
    a = np.asarray(scores_a, dtype=np.float64).ravel()
    b = np.asarray(scores_b, dtype=np.float64).ravel()
    unique = np.unique(users)
    index = {u: np.flatnonzero(users == u) for u in unique}
    rng = np.random.default_rng(seed)
    deltas: list[float] = []
    attempted = 0
    while len(deltas) < n_valid:
        attempted += 1
        if attempted > n_valid * 50:
            break
        draw = rng.choice(unique, size=len(unique), replace=True)
        parts_y = []
        parts_a = []
        parts_b = []
        for u in draw:
            sl = index[str(u)]
            parts_y.append(y[sl])
            parts_a.append(a[sl])
            parts_b.append(b[sl])
        yb = np.concatenate(parts_y)
        if len(np.unique(yb)) < 2:
            continue
        d = float(average_precision_score(yb, np.concatenate(parts_b)) - average_precision_score(yb, np.concatenate(parts_a)))
        if np.isfinite(d):
            deltas.append(d)
    arr = np.asarray(deltas, dtype=np.float64) if deltas else np.array([np.nan])
    return {
        "cluster": "user_id",
        "n_users": int(len(unique)),
        "n_valid_resamples": int(len(deltas)),
        "n_attempted_draws": attempted,
        "seed": seed,
        "mean_delta": float(np.nanmean(arr)),
        "ci95": [float(np.nanpercentile(arr, 2.5)), float(np.nanpercentile(arr, 97.5))],
        "note": "user-cluster bootstrap; windows not independent; incident clusters not invented",
    }
