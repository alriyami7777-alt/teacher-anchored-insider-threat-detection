"""Routed directional faithfulness. Does not overwrite the frozen global top-k result."""

from __future__ import annotations

from typing import Any

import numpy as np

from editor015_residual.explain import directional_table, train_references

from .constants import DIRECTIONAL_KS, HISTORICAL_GLOBAL_TOPK_FAITHFULNESS


def routed_directional_table(
    *,
    y: np.ndarray,
    tree_outputs: np.ndarray,
    references: np.ndarray,
    linear_logit: np.ndarray,
    reference_tree_outputs: np.ndarray | None,
    users: np.ndarray,
    gate: np.ndarray,
) -> dict[str, Any]:
    g = np.asarray(gate).astype(bool).reshape(-1)
    if not g.any():
        return {
            "rows": [],
            "contributions": [],
            "bootstrap": {},
            "ROUTED_ODST_LOCAL_DIRECTIONAL_FAITHFULNESS": "NOT_SUPPORTED",
            "LOCAL_DIRECTIONAL_TREE_FAITHFULNESS": "NOT_SUPPORTED",
            "HISTORICAL_GLOBAL_TOPK_FAITHFULNESS": HISTORICAL_GLOBAL_TOPK_FAITHFULNESS,
            "n_routed": 0,
            "reason": "no gated validation cases",
        }
    faith = directional_table(
        y=np.asarray(y)[g],
        tree_outputs=np.asarray(tree_outputs)[g],
        references=references,
        linear_logit=np.asarray(linear_logit)[g],
        reference_tree_outputs=None if reference_tree_outputs is None else np.asarray(reference_tree_outputs)[g],
        users=np.asarray(users)[g],
    )
    routed = faith.get("LOCAL_DIRECTIONAL_TREE_FAITHFULNESS", "NOT_SUPPORTED")
    faith["ROUTED_ODST_LOCAL_DIRECTIONAL_FAITHFULNESS"] = routed
    faith["HISTORICAL_GLOBAL_TOPK_FAITHFULNESS"] = HISTORICAL_GLOBAL_TOPK_FAITHFULNESS
    faith["n_routed"] = int(g.sum())
    faith["gate_filter"] = "validation cases with gate=1"
    faith["directional_k"] = list(DIRECTIONAL_KS)
    faith["route_traceability"] = "SUPPORTED"
    faith["leaf_traceability"] = "SUPPORTED"
    faith["route_leaf_independent_faithfulness"] = "UNSUPPORTED"
    return faith


__all__ = ["routed_directional_table", "train_references"]
