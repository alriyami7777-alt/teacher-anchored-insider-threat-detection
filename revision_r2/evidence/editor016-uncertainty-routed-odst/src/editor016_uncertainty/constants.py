"""Frozen EDITOR-016 identities. Uncertainty-routed specialist only; no architecture search."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from editor012_rescue.constants import (
    BATCH_SIZE,
    C2OPT_CHECKPOINTS,
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
    LAMBDA_ROUTE,
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
    EDITOR012_IMPLEMENTATION_COMMIT,
    EDITOR012_PROMOTION_COMMIT,
    EDITOR012_PROTOCOL_COMMIT,
    EDITOR012_RESULTS_COMMIT,
    ENCODER_DIM,
    F11_CHECKPOINTS,
    HISTORICAL as EDITOR013_HISTORICAL,
    LR_LINEAR,
    N_LAYERS,
    N_TREES_PER_LAYER,
    N_TREES_TOTAL,
    TEACHER_GUIDANCE_VS_INITIALISATION,
    TREE_ORDER,
)
from editor014_temporal_odst.constants import (
    EDITOR013_RESULTS_COMMIT,
    ENSEMBLE_CACHE,
    FROZEN_L1_MEAN_PR_AUC,
    FROZEN_TA2_L1_CI,
    FROZEN_TA2_MEAN_PR_AUC,
    FROZEN_TA2_MINUS_L1,
    L1_CHECKPOINTS,
    LATENCY_BATCH_SIZE,
    LATENCY_ROUNDS,
    LATENCY_TIMED_BATCHES,
    LATENCY_WARMUP_BATCHES,
)

TASK_ID = "EDITOR-016"
PRIMARY_METRIC = "PR_AUC"
EXTENDED_SEEDS = (72, 82, 92, 102, 112, 122, 132)
ALL_STABILITY_SEEDS = PRIMARY_SEEDS + EXTENDED_SEEDS

REVIEW_REL = Path("review/editor016_uncertainty_routed_odst")
OUTPUT_REL = Path("outputs/editor016_uncertainty_routed_odst")

EDITOR015_WORKTREE = Path(r"C:\PhD\07_Projects\teacher-anchored-insider-threat-detection-editor015")
EDITOR014_WORKTREE = Path(r"C:\PhD\07_Projects\teacher-anchored-insider-threat-detection-editor014")
EDITOR013_WORKTREE = Path(r"C:\PhD\07_Projects\teacher-anchored-insider-threat-detection-editor013")
EDITOR012_WORKTREE = Path(r"C:\PhD\07_Projects\teacher-anchored-insider-threat-detection-editor012")
EDITOR011_WORKTREE = Path(r"C:\PhD\07_Projects\teacher-anchored-insider-threat-detection-editor011")

EDITOR015_PROTOCOL_COMMIT = "ba6fd93d8a2e1260ccb2e953e326885fe4e26afd"
EDITOR015_PROMOTION_COMMIT = "335dac8622c793c0468db14eca06d42cb405fed1"
EDITOR015_RESULTS_FULL_COMMIT = "d8e1d04b8c199f56cab9956f62c16cd4301f0bac"
EDITOR014_RESULTS_COMMIT = "c3343462dc3b35d20907da6ad017f5f853852f84"

LAMBDA_TEACHER = 0.5
LAMBDA_DISTILL = LAMBDA_TEACHER
LAMBDA_RESIDUAL_TEACHER = 0.5
PROMOTION_MARGIN = 0.001
MAX_PROMOTED = 2
BOOTSTRAP_SEED = 42
BOOTSTRAP_RESAMPLES = 2000
DIRECTIONAL_KS = (1, 2, 3)

Q_VALUES = (0.10, 0.20, 0.30, 0.40, 0.50)
ALLOWED_Q = frozenset(Q_VALUES)

POST_ATTENTION_ODST_INCREMENTAL_VALUE = "NOT_SUPPORTED"
TEMPORAL_ODST_INCREMENTAL_VALUE = "NOT_SUPPORTED"
RESIDUAL_ODST_VALUE = "NO_RESIDUAL_ODST_VALUE"
FIXED_LINEAR_ODST_COMPLEMENTARITY = "MIXED"
LOCAL_DIRECTIONAL_TREE_FAITHFULNESS = "SUPPORTED"
HISTORICAL_GLOBAL_TOPK_FAITHFULNESS = "NOT_SUPPORTED"
BEST_CURRENT_PAPER_MODEL = "TA2"
HISTORICAL_SINGLE_TEACHER_STATIC_LOGIT_ANCHOR = "RETIRED"

SPECIALIST_CONDITIONS: dict[str, dict[str, Any]] = {
    "S0": {
        "head": "linear",
        "teacher_residual": False,
        "route": False,
        "identity": "LINEAR-TASK residual specialist",
    },
    "S1": {
        "head": "linear",
        "teacher_residual": True,
        "route": False,
        "identity": "LINEAR-TEACHER residual specialist",
    },
    "S2": {
        "head": "odst",
        "teacher_residual": False,
        "route": False,
        "identity": "ODST-TASK residual specialist",
    },
    "S3": {
        "head": "odst",
        "teacher_residual": True,
        "route": False,
        "identity": "ODST-TEACHER residual specialist",
    },
    "S4": {
        "head": "odst",
        "teacher_residual": True,
        "route": True,
        "identity": "ODST-TEACHER-ROUTE residual specialist",
    },
}

SPECIALIST_ORDER = ("S0", "S1", "S2", "S3", "S4")

HISTORICAL = {
    **EDITOR013_HISTORICAL,
    "EDITOR013_L1": {
        "mean_PR_AUC": FROZEN_L1_MEAN_PR_AUC,
        "seeds": {s: L1_CHECKPOINTS[s]["validation_PR_AUC"] for s in PRIMARY_SEEDS},
        "identity": "matched teacher-guided linear",
    },
    "EDITOR013_TA2": {
        "mean_PR_AUC": FROZEN_TA2_MEAN_PR_AUC,
        "seeds": {s: F11_CHECKPOINTS[s]["validation_PR_AUC"] for s in PRIMARY_SEEDS},
        "identity": "ODST-046 uniform + ensemble guidance + route anchor (TA2)",
    },
}

__all__ = [
    "TASK_ID",
    "PRIMARY_SEEDS",
    "SCREENING_SEED",
    "Q_VALUES",
    "SPECIALIST_CONDITIONS",
    "LAMBDA_TEACHER",
    "LAMBDA_ROUTE",
    "PROMOTION_MARGIN",
    "EDITOR015_RESULTS_FULL_COMMIT",
    "TEACHER_GUIDANCE_VS_INITIALISATION",
]
