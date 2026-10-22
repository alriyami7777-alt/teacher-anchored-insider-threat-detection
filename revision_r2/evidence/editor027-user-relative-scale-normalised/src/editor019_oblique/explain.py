"""Signed-oblique split tables and local intervention faithfulness."""

from __future__ import annotations

from typing import Any

import numpy as np
import torch

from editor015_residual.explain import directional_table, train_references
from editor018_cross_view.explain import classify_local_directional

from .constants import DIRECTIONAL_KS, GLOBAL_TOPK_PR_AUC_FAITHFULNESS, LOCKED_AGG_FEATURES, SUMMARY_DIM
from .models import SummaryBranch, signed_coefficients_from_probs


def _nonzero_terms(coeff: np.ndarray, *, eps: float = 1e-8) -> list[dict[str, Any]]:
    rows = []
    for i, v in enumerate(coeff.tolist()):
        if abs(float(v)) > eps:
            rows.append({"feature": LOCKED_AGG_FEATURES[i], "coefficient": float(v)})
    rows.sort(key=lambda r: -abs(r["coefficient"]))
    return rows


def signed_split_rows(branch: SummaryBranch) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    live = branch.live
    if branch.family == "SO-ODST40":
        with torch.no_grad():
            for layer_i, layer in enumerate(live.layers):
                probs = layer.feature_selection_probs().detach().cpu()
                if int(probs.shape[-1]) != 80:
                    continue
                coeff = signed_coefficients_from_probs(probs).cpu().numpy()
                thr = layer.thresholds.detach().cpu().numpy()
                for t in range(coeff.shape[0]):
                    for d in range(coeff.shape[1]):
                        terms = _nonzero_terms(coeff[t, d])
                        rows.append(
                            {
                                "family": branch.family,
                                "layer": layer_i,
                                "tree": t,
                                "node": f"depth_{d}_shared",
                                "oblivious": True,
                                "node_specific": False,
                                "threshold": float(thr[t, d]),
                                "n_nonzero": len(terms),
                                "projection": " + ".join(
                                    f"{term['coefficient']:+.4f} {term['feature']}" for term in terms[:8]
                                ),
                                "nonzero_features": ",".join(term["feature"] for term in terms),
                                "one_feature_threshold": False,
                            }
                        )
        return rows
    if branch.family not in {"SO-DTE40", "BSO-DTE40"}:
        return rows
    with torch.no_grad():
        for t, tree in enumerate(live.trees):
            coeff = tree.signed_feature_coefficients().detach().cpu().numpy()
            thr = tree.thresholds.detach().cpu().numpy()
            for node in range(coeff.shape[0]):
                terms = _nonzero_terms(coeff[node])
                rows.append(
                    {
                        "family": branch.family,
                        "layer": 0,
                        "tree": t,
                        "node": int(node),
                        "oblivious": False,
                        "node_specific": True,
                        "threshold": float(thr[node]),
                        "n_nonzero": len(terms),
                        "projection": " + ".join(
                            f"{term['coefficient']:+.4f} {term['feature']}" for term in terms[:8]
                        ),
                        "nonzero_features": ",".join(term["feature"] for term in terms),
                        "one_feature_threshold": False,
                    }
                )
    return rows


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
        "SIGNED_OBLIQUE_TREE_LOCAL_FAITHFULNESS": ruling,
        "TA2_GLOBAL_TOPK_PR_AUC_FAITHFULNESS": GLOBAL_TOPK_PR_AUC_FAITHFULNESS,
        "n_trees": int(tree_outputs.shape[1]) if tree_outputs.ndim == 2 else 0,
        "explanation_references": "TRAIN_ONLY",
        "directional_ks": list(DIRECTIONAL_KS),
        "summary_dim": SUMMARY_DIM,
    }
