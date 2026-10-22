"""Local directional faithfulness and explanation stability after robustness training."""

from __future__ import annotations

from typing import Any

import numpy as np

from editor015_residual.explain import centred_contributions, directional_table, train_references
from editor017_robustness.constants import NOISE_LEVELS, SOURCE_CHANNELS
from editor017_robustness.stability import contribution_stability, route_leaf_pair

from .constants import DIRECTIONAL_KS, N_TREES_TOTAL


def faithfulness_packet(
    *,
    y: np.ndarray,
    tree_outputs: np.ndarray,
    references: np.ndarray,
    users: np.ndarray,
    linear_logit: np.ndarray | None = None,
) -> dict[str, Any]:
    import editor015_residual.explain as explain_mod

    # Point-estimate local directional table. Nested 2000-resample bootstrap inside
    # each k is not required for the EDITOR-020 ruling and can hang on empty draws.
    previous_n = explain_mod.BOOTSTRAP_RESAMPLES
    previous_boot = explain_mod.paired_user_cluster_mean_across_seeds

    def _skip_nested_bootstrap(*_args, **_kwargs):
        return {
            "skipped": True,
            "n_valid_resamples": 0,
            "note": "EDITOR-020 uses point-estimate directional faithfulness only",
        }

    explain_mod.BOOTSTRAP_RESAMPLES = 0
    explain_mod.paired_user_cluster_mean_across_seeds = _skip_nested_bootstrap
    try:
        lin = np.zeros(len(y), dtype=np.float64) if linear_logit is None else np.asarray(linear_logit)
        rec = directional_table(
            y=y,
            tree_outputs=tree_outputs,
            references=references,
            linear_logit=lin,
            reference_tree_outputs=None,
            users=users,
        )
    finally:
        explain_mod.BOOTSTRAP_RESAMPLES = previous_n
        explain_mod.paired_user_cluster_mean_across_seeds = previous_boot
    rec["k"] = list(DIRECTIONAL_KS)
    rec["n_trees"] = int(N_TREES_TOTAL)
    rec["references_from"] = "r5.2 TRAIN only"
    rec["same_sign_random_control"] = True
    rec["nested_user_cluster_bootstrap"] = False
    return rec


def explanation_stability_packet(
    *,
    clean_trees: np.ndarray,
    degraded: dict[str, np.ndarray],
    references: np.ndarray,
    clean_choices: np.ndarray,
    degraded_choices: dict[str, np.ndarray],
    clean_leaves: np.ndarray,
    degraded_leaves: dict[str, np.ndarray],
) -> dict[str, Any]:
    contrib_clean = centred_contributions(clean_trees, references)
    rows = []
    source_stab = []
    noise_stab = []
    for ch in SOURCE_CHANNELS:
        key = f"source_{ch}"
        contrib_d = centred_contributions(degraded[key], references)
        stab = contribution_stability(contrib_clean, contrib_d)
        route = route_leaf_pair(clean_choices, degraded_choices[key], clean_leaves, degraded_leaves[key])
        row = {"family": "source", "condition": ch, **stab, **route}
        rows.append(row)
        source_stab.append(stab)
    for level in NOISE_LEVELS:
        key = f"noise_{level:.2f}"
        contrib_d = centred_contributions(degraded[key], references)
        stab = contribution_stability(contrib_clean, contrib_d)
        route = route_leaf_pair(clean_choices, degraded_choices[key], clean_leaves, degraded_leaves[key])
        row = {"family": "noise", "condition": f"{level:.2f}", **stab, **route}
        rows.append(row)
        noise_stab.append(stab)

    def _mean_key(items: list[dict[str, Any]], key: str) -> float:
        return float(np.nanmean([float(x[key]) for x in items])) if items else float("nan")

    return {
        "rows": rows,
        "MEAN_SOURCE_CONTRIBUTION_SPEARMAN": _mean_key(source_stab, "tree_contribution_spearman"),
        "MEAN_NOISE_CONTRIBUTION_SPEARMAN": _mean_key(noise_stab, "tree_contribution_spearman"),
        "MEAN_SOURCE_TOP1_SIGN": _mean_key(source_stab, "top1_sign_preserving_agreement"),
        "MEAN_NOISE_TOP1_SIGN": _mean_key(noise_stab, "top1_sign_preserving_agreement"),
        "references_from": "r5.2 TRAIN only",
    }
