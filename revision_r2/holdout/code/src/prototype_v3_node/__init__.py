"""Prototype V3: Bi-LSTM → temporal attention → NODE/ODST.

Writes only under outputs/v3_node/. Does not modify prior prototypes.
Canonical NODE uses entmax15 + entmoid15 + tree-average readout.
"""

from .architecture import (
    FUSION_VARIANTS,
    MAX_RESIDUAL_SCALE,
    SEED42_COMPARISON_VARIANTS,
    VARIANT_EQUATIONS,
    AttentionNodeEnsemble,
    count_parameters,
    load_v1_attention_linear_checkpoint,
)
from .odst import (
    CANONICAL_NODE_EQUATIONS,
    NODE,
    NODE_EQUATIONS,
    ODST,
    entmax15,
    entmoid15,
    sparsemax,
    summarize_odst_shapes,
)
from .protocol import CONTINUATION_CRITERIA, evaluate_continuation
from .safety import R42TestAccessError, assert_output_namespace_is_v3

__all__ = [
    "AttentionNodeEnsemble",
    "CANONICAL_NODE_EQUATIONS",
    "CONTINUATION_CRITERIA",
    "FUSION_VARIANTS",
    "MAX_RESIDUAL_SCALE",
    "NODE",
    "NODE_EQUATIONS",
    "ODST",
    "R42TestAccessError",
    "SEED42_COMPARISON_VARIANTS",
    "VARIANT_EQUATIONS",
    "assert_output_namespace_is_v3",
    "count_parameters",
    "entmax15",
    "entmoid15",
    "evaluate_continuation",
    "load_v1_attention_linear_checkpoint",
    "sparsemax",
    "summarize_odst_shapes",
]
