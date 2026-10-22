"""Frozen EDITOR-015 identities. Residual complementarity only; no architecture search."""

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
)

TASK_ID = "EDITOR-015"
PRIMARY_METRIC = "PR_AUC"
EXTENDED_SEEDS = (72, 82, 92, 102, 112, 122, 132)
ALL_STABILITY_SEEDS = PRIMARY_SEEDS + EXTENDED_SEEDS

REVIEW_REL = Path("review/editor015_residual_complementarity")
OUTPUT_REL = Path("outputs/editor015_residual_complementarity")

EDITOR014_RESULTS_COMMIT = "c3343462dc3b35d20907da6ad017f5f853852f84"
EDITOR013_WORKTREE = Path(r"C:\PhD\07_Projects\teacher-anchored-insider-threat-detection-editor013")
EDITOR012_WORKTREE = Path(r"C:\PhD\07_Projects\teacher-anchored-insider-threat-detection-editor012")
EDITOR011_WORKTREE = Path(r"C:\PhD\07_Projects\teacher-anchored-insider-threat-detection-editor011")
EDITOR014_WORKTREE = Path(r"C:\PhD\07_Projects\teacher-anchored-insider-threat-detection-editor014")

LAMBDA_DISTILL = 0.5
LAMBDA_RESIDUAL_TEACHER = 0.5
PROMOTION_MARGIN = 0.001
MAX_PROMOTED_RESIDUAL = 2
BOOTSTRAP_SEED = 42
BOOTSTRAP_RESAMPLES = 2000
DIRECTIONAL_KS = (1, 2, 3)
POST_ATTENTION_ODST_INCREMENTAL_VALUE = "NOT_SUPPORTED"
TEMPORAL_ODST_INCREMENTAL_VALUE = "NOT_SUPPORTED"
BEST_CURRENT_PAPER_MODEL = "TA2"
TA2_REFERENCE_CENTRED_GLOBAL_TOPK_FAITHFULNESS = "NOT_SUPPORTED"

RESIDUAL_CONDITIONS: dict[str, dict[str, Any]] = {
    "R0": {
        "family": "residual",
        "task": True,
        "final_distill": True,
        "residual_teacher": False,
        "route": False,
        "identity": "task residual + ensemble guidance on final_logit",
    },
    "R1": {
        "family": "residual",
        "task": True,
        "final_distill": False,
        "residual_teacher": True,
        "route": False,
        "identity": "teacher-residual ODST",
    },
    "R2": {
        "family": "residual",
        "task": True,
        "final_distill": False,
        "residual_teacher": True,
        "route": True,
        "identity": "teacher-residual ODST + route fidelity",
    },
    "R3": {
        "family": "residual",
        "task": True,
        "final_distill": True,
        "residual_teacher": False,
        "route": False,
        "identity": "residual + final-logit teacher guidance",
        "redundant_if_frozen_base": True,
    },
}

FIXED_COMBINATIONS = ("C0", "C1", "C2")
INNER_REFERENCES = ("L1", "TA2", "C0", "C1", "C2")
SIMPLICITY_RANK = {"R0": 0, "R1": 1, "R2": 2, "R3": 1}

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
    "TOPT_CHECKPOINTS",
    "L1_CHECKPOINTS",
    "F11_CHECKPOINTS",
    "C2OPT_CHECKPOINTS",
    "ODST046",
    "ENCODER_ARCH",
    "LAMBDA_DISTILL",
    "LAMBDA_RESIDUAL_TEACHER",
    "LAMBDA_ROUTE",
    "BATCH_SIZE",
    "MAX_EPOCHS",
    "PATIENCE",
    "SEQUENCE_LENGTH",
    "FEATURE_DIM",
    "N_TREES_TOTAL",
    "ENCODER_DIM",
    "TEACHER_GUIDANCE_VS_INITIALISATION",
    "EDITOR012_RESULTS_COMMIT",
    "EDITOR013_RESULTS_COMMIT",
    "EDITOR014_RESULTS_COMMIT",
    "PROMOTION_MARGIN",
    "RESIDUAL_CONDITIONS",
]
