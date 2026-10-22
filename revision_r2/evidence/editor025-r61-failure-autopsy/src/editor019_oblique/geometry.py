"""Inspect the producing ODST split geometry. Do not infer from names."""

from __future__ import annotations

import inspect
from typing import Any

import torch

from editor012_rescue.producing import pin_producing_sources
from editor018_cross_view.models import build_odst40

from .constants import ODST40_SPEC, SUMMARY_DIM
from .safety import Editor019Blocked


def _import_odst_module():
    pin_producing_sources()
    from prototype_v3_node import odst as odst_mod  # noqa: WPS433

    return odst_mod


def audit_current_odst_geometry() -> dict[str, Any]:
    odst_mod = _import_odst_module()
    src = inspect.getsource(odst_mod.ODST)
    probs_src = inspect.getsource(odst_mod.ODST.feature_selection_probs)
    forward_src = inspect.getsource(odst_mod.ODST.forward)
    sparsemax_src = inspect.getsource(odst_mod.sparsemax)

    model = build_odst40()
    layer0 = model.layers[0]
    if tuple(layer0.feature_logits.shape) != (int(ODST40_SPEC["n_trees"]), int(ODST40_SPEC["depth"]), SUMMARY_DIM):
        raise Editor019Blocked(
            f"unexpected feature_logits shape {tuple(layer0.feature_logits.shape)}"
        )

    with torch.no_grad():
        probs = layer0.feature_selection_probs()
        row_sums = probs.sum(dim=-1)
        n_nonzero = int((probs > 0).sum().item())
        support_sizes = (probs > 0).sum(dim=-1)

    signed_possible = (
        "clamp(z - tau, min=0.0)" in sparsemax_src
        and "return sparsemax(self.feature_logits, dim=-1)" in probs_src
        and "einsum(\"bf,tdf->btd\", h, feature_probs)" in forward_src.replace(" ", "")
    )
    # Signed coefficients would require negative feature_selection_probs or an explicit
    # difference of positive/negative channels. Neither exists in the producing ODST.
    current_split_signed = False
    if "concat" in forward_src and "-h" in forward_src:
        current_split_signed = True
    if float(probs.min()) < 0:
        current_split_signed = True

    current_split_oblivious = (
        "feature_logits = nn.Parameter" in src
        and "n_trees, self.depth, self.in_dim" in src
        and "einsum(\"bf,tdf->btd\"" in forward_src.replace(" ", "")
    )
    # One (tree, depth) selector is shared by every node at that depth.
    current_split_node_specific = False
    if "n_internal" in src or "2 ** self.depth - 1" in src.replace(" ", ""):
        current_split_node_specific = True

    if current_split_signed and (not current_split_oblivious) and current_split_node_specific:
        raise Editor019Blocked(
            "CURRENT ODST already supports unrestricted signed oblique node-specific splits; "
            "signed-oblique branch is redundant"
        )

    return {
        "producing_module": "prototype_v3_node.odst.ODST",
        "producing_choice_function": str(layer0.choice_function),
        "feature_selection_activation": "sparsemax",
        "feature_selection_equation": "pi = sparsemax(F); sparsemax(z)_i = max(0, z_i - tau(z))",
        "weights_constrained_non_negative": True,
        "weights_sum_to_one": True,
        "observed_min_prob": float(probs.min()),
        "observed_max_prob": float(probs.max()),
        "observed_row_sum_min": float(row_sums.min()),
        "observed_row_sum_max": float(row_sums.max()),
        "n_nonzero_after_sparsemax_this_init": n_nonzero,
        "support_size_per_tree_depth": "variable; sparsemax support k_z is logit-dependent, not a fixed cardinality",
        "observed_support_size_min": int(support_sizes.min()),
        "observed_support_size_max": int(support_sizes.max()),
        "one_split_vector_shared_across_nodes_at_a_depth": True,
        "each_tree_has_own_depth_wise_vector": True,
        "feature_logits_shape": list(layer0.feature_logits.shape),
        "negative_feature_coefficients_impossible": True,
        "CURRENT_SPLIT_SIGNED": "YES" if current_split_signed else "NO",
        "CURRENT_SPLIT_OBLIVIOUS": "YES" if current_split_oblivious else "NO",
        "CURRENT_SPLIT_NODE_SPECIFIC": "YES" if current_split_node_specific else "NO",
        "signed_oblique_branch_redundant": False,
        "signed_possible_projection_is_convex_combination": signed_possible,
        "odst40_spec": dict(ODST40_SPEC),
        "inspection_method": "source_inspection_plus_live_parameter_shapes_not_name_inference",
    }
