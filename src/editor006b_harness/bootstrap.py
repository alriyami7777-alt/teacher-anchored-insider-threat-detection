"""Predeclared user-clustered bootstrap on the de-overlap offset-0 subset.

Five official incidents are 1:1 with five official insiders; user- and
incident-cluster intervals are not independent levels of resolution.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from sklearn.metrics import average_precision_score, f1_score

from .safety import BOOTSTRAP_SEED, BOOTSTRAP_VALID_RESAMPLES, HarnessProtocolError


def _pr_auc(y: np.ndarray, p: np.ndarray) -> float:
    if len(np.unique(y)) < 2:
        return float("nan")
    return float(average_precision_score(y, p))


def _f1(y: np.ndarray, p: np.ndarray, threshold: float) -> float:
    pred = (p >= threshold).astype(int)
    return float(f1_score(y, pred, zero_division=0))


def paired_user_cluster_bootstrap(
    *,
    user_ids: np.ndarray,
    y: np.ndarray,
    scores_c2: np.ndarray,
    scores_c5: np.ndarray,
    threshold_c2: float,
    threshold_c5: float,
    n_valid: int = BOOTSTRAP_VALID_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    users = np.asarray(user_ids)
    unique = np.unique(users)
    rng = np.random.default_rng(seed)
    deltas_pr: list[float] = []
    deltas_f1: list[float] = []
    attempted = 0
    while len(deltas_pr) < n_valid:
        attempted += 1
        if attempted > n_valid * 50:
            raise HarnessProtocolError("Bootstrap failed to obtain 2000 valid resamples")
        draw = rng.choice(unique, size=len(unique), replace=True)
        # Preserve multiplicity: concatenate windows for each drawn user occurrence.
        parts_y = []
        parts_c2 = []
        parts_c5 = []
        for u in draw:
            sel = users == u
            parts_y.append(y[sel])
            parts_c2.append(scores_c2[sel])
            parts_c5.append(scores_c5[sel])
        yb = np.concatenate(parts_y)
        p2 = np.concatenate(parts_c2)
        p5 = np.concatenate(parts_c5)
        if len(np.unique(yb)) < 2:
            continue
        d_pr = _pr_auc(yb, p5) - _pr_auc(yb, p2)
        d_f1 = _f1(yb, p5, threshold_c5) - _f1(yb, p2, threshold_c2)
        if not np.isfinite(d_pr) or not np.isfinite(d_f1):
            continue
        deltas_pr.append(float(d_pr))
        deltas_f1.append(float(d_f1))
    pr = np.asarray(deltas_pr)
    f1 = np.asarray(deltas_f1)
    return {
        "cluster": "user_id",
        "n_valid_resamples": n_valid,
        "n_attempted_draws": attempted,
        "seed": seed,
        "percentile_95": {
            "delta_PR_AUC_C5_minus_C2": [float(np.percentile(pr, 2.5)), float(np.percentile(pr, 97.5))],
            "delta_F1_C5_minus_C2": [float(np.percentile(f1, 2.5)), float(np.percentile(f1, 97.5))],
        },
        "point_delta_PR_AUC_C5_minus_C2": float(_pr_auc(y, scores_c5) - _pr_auc(y, scores_c2)),
        "point_delta_F1_C5_minus_C2": float(
            _f1(y, scores_c5, threshold_c5) - _f1(y, scores_c2, threshold_c2)
        ),
        "interpretation": "interval is evidence, not a selection rule; no hard-coded superiority",
        "user_and_incident_not_independent": True,
        "frozen_wording": "Five official insider–incident clusters are represented.",
        "effective_malicious_cluster_count": 5,
    }
