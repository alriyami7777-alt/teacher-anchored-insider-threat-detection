"""Directional local tree interventions. Does not overwrite the frozen global top-k result."""

from __future__ import annotations

from typing import Any

import numpy as np

from editor012_rescue.bootstrap import paired_user_cluster_mean_across_seeds
from editor012_rescue.metrics import sigmoid

from .constants import BOOTSTRAP_RESAMPLES, BOOTSTRAP_SEED, DIRECTIONAL_KS, N_TREES_TOTAL


def train_references(tree_outputs_train: np.ndarray) -> np.ndarray:
    """Frozen TRAIN references only. Never validation."""
    t = np.asarray(tree_outputs_train, dtype=np.float64)
    return np.median(t, axis=0).astype(np.float64)


def centred_contributions(tree_outputs: np.ndarray, references: np.ndarray) -> np.ndarray:
    t = np.asarray(tree_outputs, dtype=np.float64)
    ref = np.asarray(references, dtype=np.float64).reshape(1, -1)
    return t - ref


def residual_logit_from_trees(
    tree_outputs: np.ndarray,
    reference_tree_outputs: np.ndarray | None,
) -> np.ndarray:
    live = np.asarray(tree_outputs, dtype=np.float64).mean(axis=-1)
    if reference_tree_outputs is None:
        return live
    ref = np.asarray(reference_tree_outputs, dtype=np.float64).mean(axis=-1)
    return live - ref


def intervene_trees(
    tree_outputs: np.ndarray,
    references: np.ndarray,
    replace: np.ndarray,
) -> np.ndarray:
    t = np.asarray(tree_outputs, dtype=np.float64).copy()
    ref = np.asarray(references, dtype=np.float64)
    mask = np.asarray(replace, dtype=bool)
    t[:, mask] = ref[mask]
    return t


def _same_sign_indices(contrib: np.ndarray, *, positive: bool) -> np.ndarray:
    if positive:
        return np.flatnonzero(contrib > 0)
    return np.flatnonzero(contrib < 0)


def directional_table(
    *,
    y: np.ndarray,
    tree_outputs: np.ndarray,
    references: np.ndarray,
    linear_logit: np.ndarray,
    reference_tree_outputs: np.ndarray | None,
    users: np.ndarray,
    rng_seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    y = np.asarray(y).astype(int).reshape(-1)
    trees = np.asarray(tree_outputs, dtype=np.float64)
    refs = np.asarray(references, dtype=np.float64)
    lin = np.asarray(linear_logit, dtype=np.float64).reshape(-1)
    ref_trees = None if reference_tree_outputs is None else np.asarray(reference_tree_outputs, dtype=np.float64)
    contrib = centred_contributions(trees, refs)
    base_res = residual_logit_from_trees(trees, ref_trees)
    base = lin + base_res
    rng = np.random.default_rng(rng_seed)
    rows = []
    contrib_rows = []
    for j in range(trees.shape[1]):
        contrib_rows.append(
            {
                "tree": j,
                "mean_centred_contribution": float(contrib[:, j].mean()),
                "mean_abs_centred_contribution": float(np.abs(contrib[:, j]).mean()),
                "reference": float(refs[j]),
                "references_from": "r5.2 TRAIN only",
            }
        )

    boot: dict[str, Any] = {}
    mal_ok = []
    ben_ok = []
    for k in DIRECTIONAL_KS:
        mal_base = []
        mal_top = []
        mal_rnd = []
        mal_users = []
        mal_y = []
        ben_base = []
        ben_top = []
        ben_rnd = []
        ben_users = []
        ben_y = []
        n_skip_mal = 0
        n_skip_ben = 0
        for i in range(len(y)):
            if y[i] == 1:
                eligible = _same_sign_indices(contrib[i], positive=True)
                if eligible.size < k:
                    n_skip_mal += 1
                    continue
                order = eligible[np.argsort(-contrib[i, eligible])]
                top = np.zeros(trees.shape[1], dtype=bool)
                top[order[:k]] = True
                rnd = np.zeros(trees.shape[1], dtype=bool)
                rnd[rng.choice(eligible, size=k, replace=False)] = True
                t_top = intervene_trees(trees[i : i + 1], refs, top)
                t_rnd = intervene_trees(trees[i : i + 1], refs, rnd)
                r0 = None if ref_trees is None else ref_trees[i : i + 1]
                top_logit = float(lin[i] + residual_logit_from_trees(t_top, r0)[0])
                rnd_logit = float(lin[i] + residual_logit_from_trees(t_rnd, r0)[0])
                mal_base.append(float(base[i]))
                mal_top.append(top_logit)
                mal_rnd.append(rnd_logit)
                mal_users.append(str(users[i]))
                mal_y.append(1)
            else:
                eligible = _same_sign_indices(contrib[i], positive=False)
                if eligible.size < k:
                    n_skip_ben += 1
                    continue
                order = eligible[np.argsort(-np.abs(contrib[i, eligible]))]
                top = np.zeros(trees.shape[1], dtype=bool)
                top[order[:k]] = True
                rnd = np.zeros(trees.shape[1], dtype=bool)
                rnd[rng.choice(eligible, size=k, replace=False)] = True
                t_top = intervene_trees(trees[i : i + 1], refs, top)
                t_rnd = intervene_trees(trees[i : i + 1], refs, rnd)
                r0 = None if ref_trees is None else ref_trees[i : i + 1]
                top_logit = float(lin[i] + residual_logit_from_trees(t_top, r0)[0])
                rnd_logit = float(lin[i] + residual_logit_from_trees(t_rnd, r0)[0])
                ben_base.append(float(base[i]))
                ben_top.append(top_logit)
                ben_rnd.append(rnd_logit)
                ben_users.append(str(users[i]))
                ben_y.append(0)

        mal_base_a = np.asarray(mal_base, dtype=np.float64)
        mal_top_a = np.asarray(mal_top, dtype=np.float64)
        mal_rnd_a = np.asarray(mal_rnd, dtype=np.float64)
        ben_base_a = np.asarray(ben_base, dtype=np.float64)
        ben_top_a = np.asarray(ben_top, dtype=np.float64)
        ben_rnd_a = np.asarray(ben_rnd, dtype=np.float64)
        mal_dec_top = float((mal_base_a - mal_top_a).mean()) if mal_base_a.size else float("nan")
        mal_dec_rnd = float((mal_base_a - mal_rnd_a).mean()) if mal_base_a.size else float("nan")
        ben_inc_top = float((ben_top_a - ben_base_a).mean()) if ben_base_a.size else float("nan")
        ben_inc_rnd = float((ben_rnd_a - ben_base_a).mean()) if ben_base_a.size else float("nan")
        mal_stat = mal_dec_top - mal_dec_rnd
        ben_stat = ben_inc_top - ben_inc_rnd
        mal_ok.append(bool(mal_stat > 0))
        ben_ok.append(bool(ben_stat > 0))
        rows.append(
            {
                "k": k,
                "n_malicious_used": int(mal_base_a.size),
                "n_benign_used": int(ben_base_a.size),
                "n_malicious_skipped_insufficient_same_sign": n_skip_mal,
                "n_benign_skipped_insufficient_same_sign": n_skip_ben,
                "malicious_top_k_logit_decrease": mal_dec_top,
                "malicious_random_same_sign_logit_decrease": mal_dec_rnd,
                "malicious_primary_stat": mal_stat,
                "malicious_top_k_prob_decrease": float((sigmoid(mal_base_a) - sigmoid(mal_top_a)).mean())
                if mal_base_a.size
                else float("nan"),
                "benign_top_k_logit_increase": ben_inc_top,
                "benign_random_same_sign_logit_increase": ben_inc_rnd,
                "benign_primary_stat": ben_stat,
                "benign_top_k_prob_increase": float((sigmoid(ben_top_a) - sigmoid(ben_base_a)).mean())
                if ben_base_a.size
                else float("nan"),
                "random_control": "same-sign eligible trees only",
                "n_trees": int(N_TREES_TOTAL),
                "references_from": "r5.2 TRAIN only",
            }
        )
        if mal_base_a.size and len(np.unique(mal_users)) > 1:
            boot[f"malicious_k{k}"] = paired_user_cluster_mean_across_seeds(
                np.asarray(mal_users),
                np.asarray(mal_y),
                [mal_rnd_a],
                [mal_top_a],
                frozen_thresholds_a=[0.5],
                frozen_thresholds_b=[0.5],
                n_valid=BOOTSTRAP_RESAMPLES,
                seed=BOOTSTRAP_SEED,
                contrast="top_minus_random_malicious_logit_proxy",
            )
        if ben_base_a.size and len(np.unique(ben_users)) > 1:
            boot[f"benign_k{k}"] = paired_user_cluster_mean_across_seeds(
                np.asarray(ben_users),
                np.asarray(ben_y),
                [ben_rnd_a],
                [ben_top_a],
                frozen_thresholds_a=[0.5],
                frozen_thresholds_b=[0.5],
                n_valid=BOOTSTRAP_RESAMPLES,
                seed=BOOTSTRAP_SEED,
                contrast="top_minus_random_benign_logit_proxy",
            )

    mal_supported = all(mal_ok) if mal_ok else False
    ben_supported = all(ben_ok) if ben_ok else False
    if mal_supported and ben_supported:
        local = "SUPPORTED"
    elif mal_supported or ben_supported or any(mal_ok) or any(ben_ok):
        local = "QUALIFIED"
    else:
        local = "NOT_SUPPORTED"
    return {
        "rows": rows,
        "contributions": contrib_rows,
        "bootstrap": boot,
        "MALICIOUS_DIRECTIONAL_FAITHFULNESS": "SUPPORTED" if mal_supported else ("QUALIFIED" if any(mal_ok) else "NOT_SUPPORTED"),
        "BENIGN_DIRECTIONAL_FAITHFULNESS": "SUPPORTED" if ben_supported else ("QUALIFIED" if any(ben_ok) else "NOT_SUPPORTED"),
        "LOCAL_DIRECTIONAL_TREE_FAITHFULNESS": local,
        "HISTORICAL_GLOBAL_TOPK_FAITHFULNESS": "NOT_SUPPORTED",
        "claim_scope": "local directional intervention faithfulness for class-supporting evidence",
        "not_global_pr_auc_faithfulness": True,
        "n_trees": int(N_TREES_TOTAL),
    }
