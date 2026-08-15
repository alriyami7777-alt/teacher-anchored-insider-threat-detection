"""Time × tree contributions and reference-centred faithfulness."""

from __future__ import annotations

from typing import Any

import numpy as np
from sklearn.metrics import average_precision_score

from editor012_rescue.metrics import sigmoid

from .constants import BOOTSTRAP_SEED, FAITHFULNESS_KS, N_TREES_TOTAL, SEQUENCE_LENGTH


def train_time_tree_references(q_tj_train: np.ndarray) -> np.ndarray:
    """Median q_tj under TRAIN/INNER_TRAIN only. Shape (T, J)."""
    t = np.asarray(q_tj_train, dtype=np.float64)
    if t.ndim != 3:
        raise ValueError(f"expected (N,T,J); got {t.shape}")
    return np.median(t, axis=0).astype(np.float64)


def time_tree_contributions(
    q_tj: np.ndarray,
    alpha: np.ndarray,
    references: np.ndarray | None = None,
) -> np.ndarray:
    """c'_tj = α_t * (q_tj - r_tj) / J so Σ_{t,j} c' + α·mean(r) recovers the logit."""
    q = np.asarray(q_tj, dtype=np.float64)
    a = np.asarray(alpha, dtype=np.float64)
    if q.ndim != 3:
        raise ValueError(f"expected (N,T,J); got {q.shape}")
    n_trees = q.shape[-1]
    centred = q if references is None else q - np.asarray(references, dtype=np.float64).reshape(1, q.shape[1], n_trees)
    return a[:, :, None] * centred / float(n_trees)


def temporal_logit_from_units(q_tj: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    q = np.asarray(q_tj, dtype=np.float64)
    a = np.asarray(alpha, dtype=np.float64)
    q_t = q.mean(axis=-1)
    return (a * q_t).sum(axis=-1)


def intervene_time_tree(
    q_tj: np.ndarray,
    alpha: np.ndarray,
    references: np.ndarray,
    replace: np.ndarray,
) -> np.ndarray:
    q = np.asarray(q_tj, dtype=np.float64).copy()
    ref = np.asarray(references, dtype=np.float64)
    mask = np.asarray(replace, dtype=bool)
    if mask.ndim == 1:
        mask = mask.reshape(q.shape[1], q.shape[2])
    q[:, mask] = ref[mask]
    return temporal_logit_from_units(q, alpha)


def _rank_units(contrib: np.ndarray) -> np.ndarray:
    n, t, j = contrib.shape
    flat = np.abs(contrib).reshape(n, t * j)
    return np.argsort(-flat, axis=1)


def faithfulness_table(
    *,
    y: np.ndarray,
    q_tj: np.ndarray,
    alpha: np.ndarray,
    references: np.ndarray,
    users: np.ndarray,
    rng_seed: int = BOOTSTRAP_SEED,
    level: str = "time_tree",
) -> dict[str, Any]:
    y = np.asarray(y).astype(int).reshape(-1)
    contrib = time_tree_contributions(q_tj, alpha, references)
    if level == "tree":
        units = contrib.sum(axis=1)
        q_use = q_tj.mean(axis=1, keepdims=True)
        a_use = np.ones((len(y), 1), dtype=np.float64)
        refs = references.mean(axis=0, keepdims=True)
    elif level == "time":
        units = contrib.sum(axis=2)
        q_use = q_tj.mean(axis=2, keepdims=True)
        a_use = np.asarray(alpha, dtype=np.float64)
        refs = references.mean(axis=1, keepdims=True)
    else:
        units = contrib
        q_use = q_tj
        a_use = alpha
        refs = references
    base = temporal_logit_from_units(q_tj, alpha)
    base_pr = float(average_precision_score(y, sigmoid(base)))
    rng = np.random.default_rng(rng_seed)
    rows = []
    drops_top = {}
    drops_rand = {}
    n_units = int(np.prod(units.shape[1:]))
    order = np.argsort(-np.abs(units).reshape(len(y), n_units), axis=1)
    for k in FAITHFULNESS_KS:
        if k > n_units:
            continue
        top_logits = np.empty_like(base)
        rand_logits = np.empty_like(base)
        for i in range(len(y)):
            top = np.zeros(n_units, dtype=bool)
            top[order[i, :k]] = True
            rnd = np.zeros(n_units, dtype=bool)
            rnd[rng.choice(n_units, size=k, replace=False)] = True
            if level == "time_tree":
                top_logits[i] = intervene_time_tree(q_tj[i : i + 1], alpha[i : i + 1], refs, top)[0]
                rand_logits[i] = intervene_time_tree(q_tj[i : i + 1], alpha[i : i + 1], refs, rnd)[0]
            else:
                top_m = top.reshape(units.shape[1:])
                rnd_m = rnd.reshape(units.shape[1:])
                q_top = np.asarray(q_use[i : i + 1], dtype=np.float64).copy()
                q_rnd = q_top.copy()
                q_top[:, top_m] = np.asarray(refs)[top_m]
                q_rnd[:, rnd_m] = np.asarray(refs)[rnd_m]
                top_logits[i] = temporal_logit_from_units(q_top, a_use[i : i + 1])[0]
                rand_logits[i] = temporal_logit_from_units(q_rnd, a_use[i : i + 1])[0]
        top_pr = float(average_precision_score(y, sigmoid(top_logits)))
        rand_pr = float(average_precision_score(y, sigmoid(rand_logits)))
        drop_top = base_pr - top_pr
        drop_rand = base_pr - rand_pr
        drops_top[k] = drop_top
        drops_rand[k] = drop_rand
        rows.append(
            {
                "level": level,
                "k": k,
                "base_pr_auc": base_pr,
                "top_k_pr_auc": top_pr,
                "random_k_pr_auc": rand_pr,
                "top_k_drop": drop_top,
                "random_k_drop": drop_rand,
                "top_minus_random_drop": drop_top - drop_rand,
                "n_units": n_units,
                "references_from": "r5.2 TRAIN only",
            }
        )
    supported = bool(drops_top) and all(drops_top[k] > drops_rand[k] for k in drops_top)
    mixed = any(drops_top[k] > drops_rand[k] for k in drops_top)
    ruling = "SUPPORTED" if supported else ("QUALIFIED" if mixed else "NOT_SUPPORTED")
    return {
        "rows": rows,
        "TEMPORAL_ODST_REFERENCE_CENTRED_FAITHFULNESS": ruling,
        "ROUTE_LEAF_INDEPENDENT_FAITHFULNESS": "UNSUPPORTED",
        "n_times": int(SEQUENCE_LENGTH),
        "n_trees": int(N_TREES_TOTAL),
        "users_available_for_bootstrap": users is not None,
        "level": level,
    }


def classify_faithfulness(primary: dict[str, Any], secondary: list[dict[str, Any]]) -> str:
    main = str(primary.get("TEMPORAL_ODST_REFERENCE_CENTRED_FAITHFULNESS"))
    if main == "SUPPORTED":
        return "SUPPORTED"
    if main == "QUALIFIED" or any(
        s.get("TEMPORAL_ODST_REFERENCE_CENTRED_FAITHFULNESS") == "SUPPORTED" for s in secondary
    ):
        return "QUALIFIED"
    return "NOT_SUPPORTED"
