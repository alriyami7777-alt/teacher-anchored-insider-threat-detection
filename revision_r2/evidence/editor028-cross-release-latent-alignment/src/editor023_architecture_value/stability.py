"""Per-sequence route and explanation statistics. Tree identities stay within model/seed."""

from __future__ import annotations

import numpy as np
from scipy.stats import spearmanr

from editor017_robustness.stability import contribution_stability, route_leaf_pair


def per_sequence_route(
    student_choices: np.ndarray,
    teacher_choices: np.ndarray,
    student_leaves: np.ndarray,
    teacher_leaves: np.ndarray,
) -> dict[str, np.ndarray]:
    sc = np.asarray(student_choices, dtype=np.float64)
    tc = np.asarray(teacher_choices, dtype=np.float64)
    axes = tuple(range(1, sc.ndim))
    mae = np.mean(np.abs(sc - tc), axis=axes)
    eps = 1e-6
    kl = tc * np.log((tc + eps) / (sc + eps)) + (1.0 - tc) * np.log((1.0 - tc + eps) / (1.0 - sc + eps))
    kl = np.mean(kl, axis=tuple(range(1, kl.ndim)))
    hard = np.mean((sc >= 0.5) == (tc >= 0.5), axis=axes)
    slv = np.asarray(student_leaves)
    tlv = np.asarray(teacher_leaves)
    leaf = (slv.argmax(axis=-1) == tlv.argmax(axis=-1)).astype(np.float64)
    if leaf.ndim > 1:
        leaf = np.mean(leaf, axis=tuple(range(1, leaf.ndim)))
    return {
        "route_MAE": mae.astype(np.float64),
        "route_KL": kl.astype(np.float64),
        "hard_route_agreement": hard.astype(np.float64),
        "dominant_leaf_agreement": leaf.astype(np.float64),
    }


def per_sequence_spearman(contrib_clean: np.ndarray, contrib_degraded: np.ndarray) -> np.ndarray:
    clean = np.asarray(contrib_clean, dtype=np.float64)
    deg = np.asarray(contrib_degraded, dtype=np.float64)
    n = int(clean.shape[0])
    out = np.full(n, np.nan, dtype=np.float64)
    for i in range(n):
        a = clean[i]
        b = deg[i]
        if np.std(a) > 0 and np.std(b) > 0:
            rho, _ = spearmanr(a, b)
            out[i] = float(rho)
    return out


__all__ = [
    "contribution_stability",
    "route_leaf_pair",
    "per_sequence_route",
    "per_sequence_spearman",
]
