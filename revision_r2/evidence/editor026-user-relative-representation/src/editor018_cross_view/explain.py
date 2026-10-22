"""Named 40-summary tree selection and cross-view directional faithfulness."""

from __future__ import annotations

from typing import Any

import numpy as np
import torch

from editor015_residual.explain import directional_table, train_references

from .constants import DIRECTIONAL_KS, GLOBAL_TOPK_PR_AUC_FAITHFULNESS, LOCKED_AGG_FEATURES, N_TREES_TOTAL
from .models import SummaryBranch


def feature_selection_rows(branch: SummaryBranch) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if branch.family not in {"ODST40", "IWODST40"}:
        return rows
    with torch.no_grad():
        for layer_i, layer in enumerate(branch.live.layers):
            probs = layer.feature_selection_probs().detach().cpu().numpy()
            thresholds = layer.thresholds.detach().cpu().numpy()
            n_trees, depth, in_dim = probs.shape
            names = list(LOCKED_AGG_FEATURES) if layer_i == 0 else (
                list(LOCKED_AGG_FEATURES) + [f"prev_tree_{j}" for j in range(in_dim - len(LOCKED_AGG_FEATURES))]
            )
            if len(names) != in_dim:
                names = [f"in_{j}" for j in range(in_dim)]
            for t in range(n_trees):
                for d in range(depth):
                    vec = probs[t, d]
                    order = np.argsort(-vec)
                    top = int(order[0])
                    rows.append(
                        {
                            "layer": layer_i,
                            "tree_in_layer": t,
                            "global_tree": layer_i * n_trees + t,
                            "depth": d,
                            "selected_feature_index": top,
                            "selected_feature_name": names[top],
                            "selection_mass": float(vec[top]),
                            "threshold": float(thresholds[t, d]),
                            "named_summary_mapping": layer_i == 0 and top < len(LOCKED_AGG_FEATURES),
                        }
                    )
    return rows


def classify_local_directional(table: dict[str, Any]) -> str:
    """Reuse EDITOR-015/017 same-sign intervention vs random control."""
    rows = table.get("rows") or table.get("directional") or []
    if not rows:
        return "NOT_SUPPORTED"
    supported = 0
    qualified = 0
    total = 0
    for row in rows:
        if int(row.get("k", 0)) not in DIRECTIONAL_KS:
            continue
        total += 1
        same = float(row.get("same_sign_mean_shift", row.get("mean_shift", 0.0)))
        rnd = float(row.get("random_same_sign_mean_shift", row.get("random_shift", 0.0)))
        if same > 0 and same > rnd:
            supported += 1
        elif same > 0:
            qualified += 1
    if total == 0:
        return "NOT_SUPPORTED"
    if supported >= max(1, total // 2):
        return "SUPPORTED"
    if supported + qualified >= max(1, total // 2):
        return "QUALIFIED"
    return "NOT_SUPPORTED"


def directional_from_trees(
    *,
    y: np.ndarray,
    tree_outputs: np.ndarray,
    train_tree_outputs: np.ndarray,
    l1_logit: np.ndarray,
    users: np.ndarray,
    reference_tree_outputs: np.ndarray | None = None,
) -> dict[str, Any]:
    refs = train_references(train_tree_outputs)
    table = directional_table(
        y=y,
        tree_outputs=tree_outputs,
        references=refs,
        linear_logit=l1_logit,
        reference_tree_outputs=reference_tree_outputs,
        users=users,
    )
    ruling = classify_local_directional(table)
    return {
        "table": table,
        "CROSS_VIEW_LOCAL_DIRECTIONAL_FAITHFULNESS": ruling,
        "GLOBAL_TOPK_PR_AUC_FAITHFULNESS": GLOBAL_TOPK_PR_AUC_FAITHFULNESS,
        "n_trees": int(tree_outputs.shape[1]) if tree_outputs.ndim == 2 else N_TREES_TOTAL,
        "named_summary_feature_mapping": "SUPPORTED",
    }
