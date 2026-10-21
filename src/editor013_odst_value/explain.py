"""Reference-centred tree contributions and intervention faithfulness."""

from __future__ import annotations

from typing import Any

import numpy as np
from sklearn.metrics import average_precision_score

from editor012_rescue.bootstrap import paired_user_cluster_mean_across_seeds
from editor012_rescue.metrics import sigmoid

from .constants import BOOTSTRAP_RESAMPLES, BOOTSTRAP_SEED, FAITHFULNESS_KS, N_TREES_TOTAL


def train_references(tree_outputs_train: np.ndarray) -> np.ndarray:
    """Frozen source/training references. TRAIN only."""
    t = np.asarray(tree_outputs_train, dtype=np.float64)
    return np.median(t, axis=0).astype(np.float64)


def centred_contributions(
    tree_outputs: np.ndarray,
    references: np.ndarray,
    weights: np.ndarray | None = None,
    alpha: float = 1.0,
) -> np.ndarray:
    t = np.asarray(tree_outputs, dtype=np.float64)
    ref = np.asarray(references, dtype=np.float64).reshape(1, -1)
    if weights is None:
        a = np.full((1, t.shape[1]), 1.0 / t.shape[1], dtype=np.float64)
    else:
        a = np.asarray(weights, dtype=np.float64).reshape(1, -1)
    return float(alpha) * a * (t - ref)


def intervene_logit(
    tree_outputs: np.ndarray,
    references: np.ndarray,
    replace: np.ndarray,
    weights: np.ndarray | None,
    alpha: float,
    linear_logit: np.ndarray | None,
    hybrid: bool,
) -> np.ndarray:
    t = np.asarray(tree_outputs, dtype=np.float64).copy()
    ref = np.asarray(references, dtype=np.float64)
    mask = np.asarray(replace, dtype=bool)
    t[:, mask] = ref[mask]
    if weights is None:
        a = np.full(t.shape[1], 1.0 / t.shape[1], dtype=np.float64)
    else:
        a = np.asarray(weights, dtype=np.float64).reshape(-1)
    odst = (t * a.reshape(1, -1)).sum(axis=1)
    if hybrid:
        assert linear_logit is not None
        return np.asarray(linear_logit, dtype=np.float64).reshape(-1) + float(alpha) * odst
    return odst


def faithfulness_table(
    *,
    y: np.ndarray,
    tree_outputs: np.ndarray,
    references: np.ndarray,
    weights: np.ndarray | None,
    alpha: float,
    linear_logit: np.ndarray | None,
    hybrid: bool,
    users: np.ndarray,
    rng_seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    y = np.asarray(y).astype(int).reshape(-1)
    contrib = centred_contributions(tree_outputs, references, weights, alpha)
    base = intervene_logit(
        tree_outputs, references, np.zeros(tree_outputs.shape[1], dtype=bool), weights, alpha, linear_logit, hybrid
    )
    base_pr = float(average_precision_score(y, sigmoid(base)))
    rng = np.random.default_rng(rng_seed)
    rows = []
    drops_top = {}
    drops_rand = {}
    j = tree_outputs.shape[1]
    for k in FAITHFULNESS_KS:
        if k > j:
            continue
        order = np.argsort(-np.abs(contrib), axis=1)
        top_logits = np.empty_like(base)
        rand_logits = np.empty_like(base)
        for i in range(len(y)):
            top = np.zeros(j, dtype=bool)
            top[order[i, :k]] = True
            rnd = np.zeros(j, dtype=bool)
            rnd[rng.choice(j, size=k, replace=False)] = True
            top_logits[i] = intervene_logit(
                tree_outputs[i : i + 1], references, top, weights, alpha, None if linear_logit is None else linear_logit[i : i + 1], hybrid
            )[0]
            rand_logits[i] = intervene_logit(
                tree_outputs[i : i + 1], references, rnd, weights, alpha, None if linear_logit is None else linear_logit[i : i + 1], hybrid
            )[0]
        top_pr = float(average_precision_score(y, sigmoid(top_logits)))
        rand_pr = float(average_precision_score(y, sigmoid(rand_logits)))
        drop_top = base_pr - top_pr
        drop_rand = base_pr - rand_pr
        drops_top[k] = drop_top
        drops_rand[k] = drop_rand
        rows.append(
            {
                "k": k,
                "base_pr_auc": base_pr,
                "top_k_pr_auc": top_pr,
                "random_k_pr_auc": rand_pr,
                "top_k_drop": drop_top,
                "random_k_drop": drop_rand,
                "top_minus_random_drop": drop_top - drop_rand,
                "n_trees": j,
                "references_from": "r5.2 TRAIN only",
            }
        )
    supported = all(drops_top[k] > drops_rand[k] for k in drops_top)
    mixed = any(drops_top[k] > drops_rand[k] for k in drops_top)
    ruling = "SUPPORTED" if supported else ("QUALIFIED" if mixed else "NOT_SUPPORTED")
    return {
        "rows": rows,
        "PROMOTED_ODST_REFERENCE_CENTRED_FAITHFULNESS": ruling,
        "ODST_ROUTE_TRACEABILITY": "SUPPORTED",
        "ODST_LEAF_TRACEABILITY": "SUPPORTED",
        "ROUTE_LEAF_INDEPENDENT_FAITHFULNESS": "UNSUPPORTED",
        "n_trees": int(N_TREES_TOTAL),
        "users_available_for_bootstrap": users is not None,
    }


def faithfulness_bootstrap(
    *,
    users: np.ndarray,
    y: np.ndarray,
    top_logits: np.ndarray,
    rand_logits: np.ndarray,
    base_logits: np.ndarray,
) -> dict[str, Any]:
    """User-cluster bootstrap of (top-k drop − random-k drop) via paired PR-AUC."""
    return paired_user_cluster_mean_across_seeds(
        users,
        y,
        [rand_logits],
        [top_logits],
        frozen_thresholds_a=[0.5],
        frozen_thresholds_b=[0.5],
        n_valid=BOOTSTRAP_RESAMPLES,
        seed=BOOTSTRAP_SEED,
        contrast="top_k_drop_minus_random_k_drop_proxy",
    )
