"""Within-model and teacher-relative route/leaf/explanation stability.

Tree identities are compared only within the same model and seed.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from scipy.stats import spearmanr

from editor012_rescue.metrics import teacher_relative


def route_leaf_pair(
    a_choices: np.ndarray,
    b_choices: np.ndarray,
    a_leaves: np.ndarray,
    b_leaves: np.ndarray,
) -> dict[str, float]:
    rel = teacher_relative(
        np.zeros(len(a_choices)),
        np.zeros(len(b_choices)),
        a_choices,
        b_choices,
        a_leaves,
        b_leaves,
    )
    return {
        "route_MAE": float(rel["route_MAE"]),
        "route_KL": float(rel["route_KL"]),
        "hard_route_agreement": float(rel["hard_route_agreement"]),
        "dominant_leaf_agreement": float(rel["dominant_leaf_agreement"]),
    }


def contribution_stability(
    contrib_clean: np.ndarray,
    contrib_degraded: np.ndarray,
) -> dict[str, float]:
    clean = np.asarray(contrib_clean, dtype=np.float64)
    deg = np.asarray(contrib_degraded, dtype=np.float64)
    if clean.shape != deg.shape or clean.ndim != 2:
        raise ValueError("contribution matrices must share shape (N, n_trees)")
    n, j = clean.shape
    rhos = []
    cos = []
    top1_sign = []
    top1_id = []
    jacc = []
    for i in range(n):
        a = clean[i]
        b = deg[i]
        if np.std(a) > 0 and np.std(b) > 0:
            rho, _ = spearmanr(a, b)
            rhos.append(float(rho))
        else:
            rhos.append(float("nan"))
        na = np.linalg.norm(a)
        nb = np.linalg.norm(b)
        cos.append(float(np.dot(a, b) / (na * nb)) if na > 0 and nb > 0 else float("nan"))
        ia = int(np.argmax(np.abs(a)))
        ib = int(np.argmax(np.abs(b)))
        top1_id.append(float(ia == ib))
        top1_sign.append(float(np.sign(a[ia]) == np.sign(b[ia]) and a[ia] != 0 and b[ia] != 0))
        ka = set(np.argsort(-np.abs(a))[: min(3, j)].tolist())
        kb = set(np.argsort(-np.abs(b))[: min(3, j)].tolist())
        jacc.append(float(len(ka & kb) / len(ka | kb)) if (ka | kb) else float("nan"))
    return {
        "tree_contribution_spearman": float(np.nanmean(rhos)),
        "top1_sign_preserving_agreement": float(np.nanmean(top1_sign)),
        "top1_identity_agreement": float(np.nanmean(top1_id)),
        "top3_jaccard": float(np.nanmean(jacc)),
        "contribution_cosine": float(np.nanmean(cos)),
        "n_sequences": int(n),
        "n_trees": int(j),
        "tree_identities_compared_across_seeds": False,
    }


def mean_or_nan(xs: list[float]) -> float:
    arr = np.asarray(xs, dtype=np.float64)
    return float(np.nanmean(arr)) if arr.size else float("nan")
