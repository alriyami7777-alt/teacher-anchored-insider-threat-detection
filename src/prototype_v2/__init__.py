"""Prototype V2: Adaptive Residual-Gated Differentiable Sequence–Ensemble.

Isolated from V1 / Objective 2 / Objective 3 artefacts. Development commands
default to CERT r4.2 train + validation only and refuse r4.2 test access.
"""

from .architecture import (
    FUSION_VARIANT_ALIASES,
    FUSION_VARIANTS,
    FOREST_CORRECTION_SEMANTICS,
    ResidualGatedSequenceEnsemble,
    VARIANT_EQUATIONS,
    assert_v2_component_gradients,
    assert_v2_outputs,
    count_parameters,
    normalize_fusion_variant,
)
from .diagnostics import compute_v2_diagnostics, evaluate_gate_safeguards
from .protocol import (
    SEEDS,
    SELECTION_CRITERIA,
    build_protocol_manifest,
    select_variant,
)
from .safety import (
    R42TestAccessError,
    assert_no_r42_test_access,
    refuse_if_test_requested,
    snapshot_v1_artefact_hashes,
    verify_v1_artefacts_unchanged,
)

__all__ = [
    "FUSION_VARIANT_ALIASES",
    "FUSION_VARIANTS",
    "FOREST_CORRECTION_SEMANTICS",
    "ResidualGatedSequenceEnsemble",
    "R42TestAccessError",
    "SEEDS",
    "SELECTION_CRITERIA",
    "VARIANT_EQUATIONS",
    "assert_no_r42_test_access",
    "assert_v2_component_gradients",
    "assert_v2_outputs",
    "build_protocol_manifest",
    "compute_v2_diagnostics",
    "count_parameters",
    "evaluate_gate_safeguards",
    "normalize_fusion_variant",
    "refuse_if_test_requested",
    "select_variant",
    "snapshot_v1_artefact_hashes",
    "verify_v1_artefacts_unchanged",
]
