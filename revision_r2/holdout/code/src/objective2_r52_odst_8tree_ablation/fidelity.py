"""Reference-centred faithfulness for M=8 trees."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .constants import (
    BOOTSTRAP_SEED,
    FIDELITY_K,
    M_TREES,
    N_BOOTSTRAP,
    N_BOOTSTRAP_MAX,
    N_RANDOM_CONTROLS,
    RANDOM_CTRL_SEED,
)
from .student_train import extract_tree_outputs


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def training_median_refs(model, X_train: np.ndarray, device, max_n: int = 5000) -> np.ndarray:
    idx = np.linspace(0, len(X_train) - 1, min(max_n, len(X_train)), dtype=int)
    b = extract_tree_outputs(model, X_train[idx], device)
    return np.median(b["tree_outputs"], axis=0).astype(np.float64)


def _user_bootstrap_mean(deltas: np.ndarray, users: np.ndarray, seed: int) -> dict:
    codes, _ = pd.factorize(users.astype(str), sort=False)
    n_users = int(codes.max()) + 1 if len(codes) else 0
    order = np.argsort(codes)
    sc = codes[order]
    boundaries = np.flatnonzero(np.r_[True, sc[1:] != sc[:-1], True])
    user_idx = [order[boundaries[i] : boundaries[i + 1]] for i in range(n_users)]
    obs = float(np.mean(deltas))
    rng = np.random.default_rng(seed)
    store = []
    n_valid = attempts = 0
    while n_valid < N_BOOTSTRAP and attempts < N_BOOTSTRAP_MAX:
        attempts += 1
        chosen = rng.integers(0, n_users, size=n_users)
        ix = np.concatenate([user_idx[int(j)] for j in chosen])
        store.append(float(np.mean(deltas[ix])))
        n_valid += 1
    arr = np.asarray(store, dtype=float)
    lo, hi = float(np.percentile(arr, 2.5)), float(np.percentile(arr, 97.5))
    return {
        "observed_mean_delta": obs,
        "ci_low": lo,
        "ci_high": hi,
        "n_valid": n_valid,
        "ci_excludes_zero_positive": bool(lo > 0),
    }


def centred_faithfulness(
    trees: np.ndarray,
    refs: np.ndarray,
    users: np.ndarray,
    thr: float,
    seed: int,
) -> pd.DataFrame:
    """c_m = (o_m - b_m) / 8; top-k vs random; k in {1,3,5}."""
    M = trees.shape[1]
    assert M == M_TREES
    n = len(trees)
    contrib = (trees - refs.reshape(1, -1)) / M
    base_p = _sigmoid(trees.mean(axis=1))
    base_cls = (base_p >= thr).astype(int)
    rng = np.random.default_rng(RANDOM_CTRL_SEED)
    rand_sets = {k: [rng.choice(M, size=k, replace=False) for _ in range(N_RANDOM_CONTROLS)] for k in FIDELITY_K}
    order = np.argsort(-np.abs(contrib), axis=1)
    rows = []
    for k in FIDELITY_K:
        t_rem = trees.copy()
        top = order[:, :k]
        rows_idx = np.arange(n)[:, None]
        t_rem[rows_idx, top] = refs[top]
        p_rem = _sigmoid(t_rem.mean(axis=1))
        deltas_top = np.abs(base_p - p_rem)
        rand_mat = np.zeros((n, N_RANDOM_CONTROLS), dtype=np.float64)
        for r, ridx in enumerate(rand_sets[k]):
            tr = trees.copy()
            tr[:, ridx] = refs[ridx]
            rand_mat[:, r] = np.abs(base_p - _sigmoid(tr.mean(axis=1)))
        deltas_rand = rand_mat.mean(axis=1)
        paired = deltas_top - deltas_rand
        boot = _user_bootstrap_mean(paired, users, BOOTSTRAP_SEED + seed + k)
        rows.append(
            {
                "seed": seed,
                "mode": "centred",
                "k": int(k),
                "n_samples": n,
                "M": M,
                "reference": "training_median_per_tree",
                "denominator_preserved": True,
                "comprehensiveness_top_mean": float(deltas_top.mean()),
                "comprehensiveness_random_mean": float(deltas_rand.mean()),
                "delta_top_minus_random": float(paired.mean()),
                "class_retention_rate": float(((p_rem >= thr).astype(int) == base_cls).mean()),
                **boot,
            }
        )
    return pd.DataFrame(rows)
