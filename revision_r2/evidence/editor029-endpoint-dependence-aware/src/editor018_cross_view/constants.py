"""Frozen EDITOR-018 identities. No architecture, feature, or split search."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from editor012_rescue.constants import (
    BATCH_SIZE,
    ENCODER_ARCH,
    EXPECTED_INNER_DROPPED,
    EXPECTED_INNER_SELECT_N,
    EXPECTED_INNER_SELECT_POS,
    EXPECTED_INNER_TRAIN_N,
    EXPECTED_INNER_TRAIN_POS,
    EXPECTED_TRAIN_POS,
    EXPECTED_TRAIN_SHA256,
    EXPECTED_TRAIN_SHAPE,
    EXPECTED_USER_MAPPING_SHA256,
    EXPECTED_VAL_MALICIOUS_USERS,
    EXPECTED_VAL_POS,
    EXPECTED_VAL_SHA256,
    EXPECTED_VAL_SHAPE,
    EXPECTED_VAL_USERS,
    EXPECTED_VAL_WINDOWS_PER_USER,
    FEATURE_DIM,
    GRAD_CLIP_NORM,
    LAMBDA_HISTORICAL_SINGLE_TEACHER_LOGIT,
    LR_ATTENTION,
    LR_ENCODER,
    LR_ODST,
    MAX_EPOCHS,
    ODST046,
    PATIENCE,
    POS_WEIGHT_MULT,
    PRIMARY_SEEDS,
    SAFE_FEATURES,
    SCREENING_SEED,
    SEQUENCE_LENGTH,
    TOPT_CHECKPOINTS,
    WEIGHT_DECAY,
)
from editor013_odst_value.constants import (
    F11_CHECKPOINTS,
    LR_LINEAR,
    N_LAYERS,
    N_TREES_PER_LAYER,
    N_TREES_TOTAL,
    TEACHER_GUIDANCE_VS_INITIALISATION,
)
from editor014_temporal_odst.constants import (
    ENSEMBLE_CACHE,
    FROZEN_L1_MEAN_PR_AUC,
    FROZEN_TA2_L1_CI,
    FROZEN_TA2_MEAN_PR_AUC,
    FROZEN_TA2_MINUS_L1,
    L1_CHECKPOINTS,
)
from editor017_robustness.constants import (
    GLOBAL_TOPK_PR_AUC_FAITHFULNESS,
    NOISE_LEVELS,
    NOISE_PERTURBATION_SEED,
    SOURCE_CHANNELS,
)
from objective2_r52_same_information_baselines.constants import MLP_LOCKED

COMMON_13_FEATURES = list(SAFE_FEATURES)
NUMERIC_FEATURES = COMMON_13_FEATURES[:7]
BINARY_FEATURES = COMMON_13_FEATURES[7:]
LOCKED_AGG_FEATURES = [
    f"{c}_{a}" for c in NUMERIC_FEATURES for a in ("sum", "mean", "max", "std")
] + [
    f"{c}_{a}" for c in BINARY_FEATURES for a in ("active_days", "active_proportion")
]

TASK_ID = "EDITOR-018"
PRIMARY_METRIC = "PR_AUC"
EXTENDED_SEEDS = (72, 82, 92, 102, 112, 122, 132)
ALL_STABILITY_SEEDS = PRIMARY_SEEDS + EXTENDED_SEEDS

REVIEW_REL = Path("review/editor018_cross_view_tree_rescue")
OUTPUT_REL = Path("outputs/editor018_cross_view_tree_rescue")

EDITOR012_RESULTS_COMMIT = "4bcf522a502ed98e5dd393a80bd9da7fffd51964"
EDITOR013_RESULTS_COMMIT = "09c4bb97b143810147feef08f31a8d8d042a6726"
EDITOR014_RESULTS_COMMIT = "c3343462dc3b35d20907da6ad017f5f853852f84"
EDITOR015_RESULTS_COMMIT = "d8e1d04b8c199f56cab9956f62c16cd4301f0bac"
EDITOR016_RESULTS_COMMIT = "07b90867dc83ac42a4f3dce538ee7eca0cedb230"
EDITOR017_RESULTS_COMMIT = "c75321a627ecc7539d1a759764d7ce395895179a"
BASE_COMMIT = EDITOR017_RESULTS_COMMIT

EDITOR011_WORKTREE = Path(r"C:\PhD\07_Projects\teacher-anchored-insider-threat-detection-editor011")
EDITOR012_WORKTREE = Path(r"C:\PhD\07_Projects\teacher-anchored-insider-threat-detection-editor012")
EDITOR013_WORKTREE = Path(r"C:\PhD\07_Projects\teacher-anchored-insider-threat-detection-editor013")
EDITOR017_WORKTREE = Path(r"C:\PhD\07_Projects\teacher-anchored-insider-threat-detection-editor017")

SUMMARY_DIM = 40
LAMBDA_TEACHER = 0.5
PROMOTION_MARGIN = 0.001
MAX_PROMOTED = 2
BOOTSTRAP_SEED = 42
BOOTSTRAP_RESAMPLES = 2000
DIRECTIONAL_KS = (1, 2, 3)
LR_BRANCH = 1e-3

EXPECTED_AGGREGATE40_SHA256 = "0e9ad707221f6278f99b9fe143383386d0b01e3617151a0c3ef27d7ee776dfcf"
AGGREGATE40_SOURCE = Path("src/scripts/r52_locked_baselines/data.py")
AGGREGATE40_FUNCTION = "aggregate_common13_windows"
STD_DEFINITION = "numpy.ndarray.std(axis=1) default ddof=0 population standard deviation"
NUMERIC_AGGS = ("sum", "mean", "max", "std")
BINARY_AGGS = ("active_days", "active_proportion")

MLP40_HIDDEN = list(MLP_LOCKED["hidden_layers"])
MLP40_DROPOUT = float(MLP_LOCKED["dropout"])
MLP40_ACTIVATION = str(MLP_LOCKED["activation"])
MLP40_PROVENANCE = "RECOVERED_SAME_INFORMATION_SHALLOW_MLP_IN_DIM_CHANGED_TO_40"

ODST40_SPEC: dict[str, Any] = {
    "in_dim": SUMMARY_DIM,
    "num_layers": 2,
    "n_trees": 4,
    "depth": 4,
    "temperature": 0.5,
    "tree_dim": 1,
    "choice_function": "sparsemax_sigmoid",
    "readout": "canonical_tree_average",
    "leaf_init_std": 0.05,
    "dropout": 0.0,
}

BRANCH_FAMILIES = ("LIN40", "MLP40", "ODST40", "IWODST40")
GUIDANCE = ("T", "D")
INNER_CONDITIONS = tuple(f"{fam}-{g}" for fam in BRANCH_FAMILIES for g in GUIDANCE)

CONDITION_SPECS: dict[str, dict[str, Any]] = {
    "LIN40-T": {"family": "LIN40", "teacher": False, "identity": "linear40 task-only"},
    "LIN40-D": {"family": "LIN40", "teacher": True, "identity": "linear40 teacher-residual"},
    "MLP40-T": {"family": "MLP40", "teacher": False, "identity": "mlp40 task-only"},
    "MLP40-D": {"family": "MLP40", "teacher": True, "identity": "mlp40 teacher-residual"},
    "ODST40-T": {"family": "ODST40", "teacher": False, "identity": "odst40 task-only"},
    "ODST40-D": {"family": "ODST40", "teacher": True, "identity": "odst40 teacher-residual"},
    "IWODST40-T": {"family": "IWODST40", "teacher": False, "identity": "iw-odst40 task-only"},
    "IWODST40-D": {"family": "IWODST40", "teacher": True, "identity": "iw-odst40 teacher-residual"},
}

TREE_FAMILIES = ("ODST40", "IWODST40")
NON_TREE_TEACHER = ("LIN40-D", "MLP40-D")

LOCAL_DIRECTIONAL_FAITHFULNESS_FROM_017 = "SUPPORTED"
ROUTE_ANCHOR_STRUCTURAL_ROBUSTNESS = "SUPPORTED"
ODST_DEGRADED_INPUT_ADVANTAGE_OVER_LINEAR = "CONSISTENT"
TEACHER_GUIDANCE_DEGRADED_INPUT_VALUE = "CONSISTENT"
EDITOR_ISSUE_TEACHER_INITIALISATION_ONLY = "RESOLVED"
EDITOR_ISSUE_C5_NEGLIGIBLE_INCREMENT = "RESOLVED_BY_REPAIRED_FORMULATION"

__all__ = [
    "TASK_ID",
    "PRIMARY_SEEDS",
    "SCREENING_SEED",
    "L1_CHECKPOINTS",
    "F11_CHECKPOINTS",
    "TOPT_CHECKPOINTS",
    "ENSEMBLE_CACHE",
    "LAMBDA_TEACHER",
    "SUMMARY_DIM",
    "LOCKED_AGG_FEATURES",
    "NUMERIC_FEATURES",
    "BINARY_FEATURES",
    "COMMON_13_FEATURES",
    "SAFE_FEATURES",
    "EXPECTED_AGGREGATE40_SHA256",
    "TEACHER_GUIDANCE_VS_INITIALISATION",
    "GLOBAL_TOPK_PR_AUC_FAITHFULNESS",
    "FROZEN_TA2_MEAN_PR_AUC",
    "FROZEN_L1_MEAN_PR_AUC",
]
