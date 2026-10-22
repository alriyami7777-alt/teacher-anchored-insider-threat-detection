"""Freeze SO-DTE40 tree count from MLP40-D parameter count before any outcome is viewed."""

from __future__ import annotations

from typing import Any

from objective2_r52_same_information_baselines.models import ShallowMLP

from .constants import (
    CAPACITY_RATIO,
    MAX_TREES,
    MIN_TREES,
    MLP40_DROPOUT,
    MLP40_HIDDEN,
    N_INTERNAL_NODES,
    N_LEAVES,
    SIGNED_DIM,
    SUMMARY_DIM,
    TREE_DEPTH,
)
from .safety import Editor019ProtocolError


def mlp40_branch_parameter_count() -> int:
    model = ShallowMLP(in_dim=SUMMARY_DIM, hidden=list(MLP40_HIDDEN), dropout=MLP40_DROPOUT)
    return int(sum(p.numel() for p in model.parameters() if p.requires_grad))


def so_dte_params_per_tree() -> int:
    """Each depth-4 tree: 15 nodes × (80 logits + threshold + log τ) + 16 leaves."""
    per_node = SIGNED_DIM + 1 + 1
    return int(N_INTERNAL_NODES * per_node + N_LEAVES)


def select_tree_count(*, mlp_params: int | None = None) -> dict[str, Any]:
    mlp_n = int(mlp_params if mlp_params is not None else mlp40_branch_parameter_count())
    per_tree = so_dte_params_per_tree()
    budget = CAPACITY_RATIO * float(mlp_n)
    chosen = MIN_TREES
    for n in range(MIN_TREES, MAX_TREES + 1):
        if n * per_tree <= budget:
            chosen = n
        else:
            break
    if chosen < MIN_TREES or chosen > MAX_TREES:
        raise Editor019ProtocolError("capacity-matched tree count outside [2, 32]")
    if chosen * per_tree > budget:
        raise Editor019ProtocolError("selected tree count exceeds 1.05 × MLP40 capacity")
    return {
        "MLP40_architecture": {
            "in_dim": SUMMARY_DIM,
            "hidden": list(MLP40_HIDDEN),
            "dropout": MLP40_DROPOUT,
        },
        "MLP40_branch_parameter_count": mlp_n,
        "capacity_ratio": CAPACITY_RATIO,
        "parameter_budget": budget,
        "SO_DTE40_depth": TREE_DEPTH,
        "internal_nodes_per_tree": N_INTERNAL_NODES,
        "leaves_per_tree": N_LEAVES,
        "signed_channels": SIGNED_DIM,
        "parameters_per_tree": per_tree,
        "min_trees": MIN_TREES,
        "max_trees": MAX_TREES,
        "CAPACITY_MATCHED_TREE_COUNT": chosen,
        "tree_branch_parameter_count": chosen * per_tree,
        "ratio_used": (chosen * per_tree) / float(mlp_n),
        "next_count_exceeds_budget": (chosen + 1) * per_tree > budget,
        "frozen_before_results": True,
        "no_later_tree_count_search": True,
    }
