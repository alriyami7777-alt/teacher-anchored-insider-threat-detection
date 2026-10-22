"""Frozen EDITOR-020 identities. No architecture search. No new corruptions."""

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
    F10_CHECKPOINTS,
    F11_CHECKPOINTS,
    LR_LINEAR,
    N_TREES_TOTAL,
    TEACHER_GUIDANCE_VS_INITIALISATION,
)
from editor014_temporal_odst.constants import ENSEMBLE_CACHE, FROZEN_L1_MEAN_PR_AUC, FROZEN_TA2_MEAN_PR_AUC, L1_CHECKPOINTS
from editor017_robustness.constants import (
    AUTHORITATIVE_GAUSSIAN,
    AUTHORITATIVE_SOURCE_ABLATION,
    CONTROLLED_GAUSSIAN_INPUT_NOISE,
    CONTROLLED_SOURCE_CHANNEL_ABLATION,
    EXPECTED_SCALER_JSON_SHA256,
    GLOBAL_TOPK_PR_AUC_FAITHFULNESS,
    NOISE_LEVELS,
    NOISE_PERTURBATION_SEED,
    NOISE_SCENARIO,
    SCALER_ID,
    SCALER_JSON,
    SOURCE_CHANNELS,
    SOURCE_CONDITIONS,
)
from editor018_cross_view.constants import (
    ODST_DEGRADED_INPUT_ADVANTAGE_OVER_LINEAR,
    ROUTE_ANCHOR_STRUCTURAL_ROBUSTNESS,
    TEACHER_GUIDANCE_DEGRADED_INPUT_VALUE,
)

TASK_ID = "EDITOR-020"
PRIMARY_METRIC = "PR_AUC"
REVIEW_REL = Path("review/editor020_teacher_degraded_consistency")
OUTPUT_REL = Path("outputs/editor020_teacher_degraded_consistency")

EDITOR017_RESULTS_COMMIT = "c75321a627ecc7539d1a759764d7ce395895179a"
EDITOR018_RESULTS_COMMIT = "9dafa51b7dd81d97cead84b4b7e10b2c230b08b4"
EDITOR019_RESULTS_COMMIT = "26614089fe4ee8695f1a15d902ebf2f5fdf1f45a"
BASE_COMMIT = EDITOR019_RESULTS_COMMIT

EDITOR017_WORKTREE = Path(r"C:\PhD\07_Projects\teacher-anchored-insider-threat-detection-editor017")
EDITOR018_WORKTREE = Path(r"C:\PhD\07_Projects\teacher-anchored-insider-threat-detection-editor018")
EDITOR019_WORKTREE = Path(r"C:\PhD\07_Projects\teacher-anchored-insider-threat-detection-editor019")

LAMBDA_TEACHER = 0.5
LAMBDA_ROUTE = 0.5
CLEAN_PRESERVATION_MARGIN = 0.001
SAMPLER_SEED = 42
FAMILY_P_SOURCE = 0.5
FAMILY_P_NOISE = 0.5
BOOTSTRAP_SEED = 42
BOOTSTRAP_RESAMPLES = 2000
DIRECTIONAL_KS = (1, 2, 3)

EXPECTED_SOURCE_ABLATION_SHA256 = "dc83b14cbf27822f86b1626032c5947ac79aa55c264b0a2c524ca44c9e1b07c2"
EXPECTED_GAUSSIAN_SHA256 = "bcab265042f6b6363d6bc7245d5a0bf6d177d2fcb75528a124978f04d8d9bb1f"

FORBIDDEN_THREAT_TERMS = (
    "ADVERSARIAL_ROBUSTNESS",
    "EVASION_ROBUSTNESS",
    "POISONING_ROBUSTNESS",
    "ADVERSARIAL ROBUSTNESS",
    "EVASION RESISTANCE",
    "POISONING RESISTANCE",
)
ALLOWED_TERMS = (
    "ROBUSTNESS-ORIENTED TRAINING",
    "CONTROLLED DEGRADED-INPUT ROBUSTNESS",
    "NOISE-ROBUST TRAINING",
    "SOURCE-CHANNEL DEGRADATION",
    "CLEAN-TO-DEGRADED TEACHER CONSISTENCY",
    "DATA-QUALITY RESILIENCE",
)

CLEAN_ODST_PREDICTIVE_SUPERIORITY = "NOT_SUPPORTED"

ARCH_SPECS: dict[str, dict[str, Any]] = {
    "L1": {
        "family": "linear",
        "identity": "teacher-guided attention-linear architecture",
        "teacher_guidance": True,
        "route_anchor": False,
        "route_clean": False,
        "objectives": ("R0", "R1", "R2", "R3"),
        "checkpoints": L1_CHECKPOINTS,
    },
    "F10": {
        "family": "odst",
        "identity": "ODST-046 ensemble teacher guidance route anchor OFF",
        "teacher_guidance": True,
        "route_anchor": False,
        "route_clean": False,
        "objectives": ("R0", "R1", "R2", "R3"),
        "checkpoints": F10_CHECKPOINTS,
    },
    "TA2": {
        "family": "odst",
        "identity": "ODST-046 ensemble teacher guidance route anchor ON",
        "teacher_guidance": True,
        "route_anchor": True,
        "route_clean": True,
        "objectives": ("R0", "R1", "R2", "R3", "R4"),
        "checkpoints": F11_CHECKPOINTS,
    },
}

# Robustness objectives are complete loss specifications.
# R0 retains the existing clean teacher-logit term.
# R1/R2/R3/R4 teacher consistency, when present, is clean-teacher -> degraded-student.
# TA2 keeps clean-view route consistency as architecture identity.
# R4 adds robust route consistency only.
OBJECTIVES: dict[str, dict[str, Any]] = {
    "R0": {
        "name": "CLEAN",
        "task_clean": True,
        "task_degraded": False,
        "teacher_clean": True,
        "teacher_degraded": False,
        "route_robust": False,
        "purpose": "existing clean training; no degraded training",
        "simplicity_rank": 0,
    },
    "R1": {
        "name": "DEGRADED_SUPERVISED",
        "task_clean": True,
        "task_degraded": True,
        "teacher_clean": False,
        "teacher_degraded": False,
        "route_robust": False,
        "purpose": "ordinary robustness-oriented data augmentation",
        "simplicity_rank": 1,
    },
    "R2": {
        "name": "CLEAN_TEACHER_CONSISTENCY",
        "task_clean": True,
        "task_degraded": False,
        "teacher_clean": False,
        "teacher_degraded": True,
        "route_robust": False,
        "purpose": "isolate clean-to-degraded teacher transfer",
        "simplicity_rank": 2,
    },
    "R3": {
        "name": "COMBINED",
        "task_clean": True,
        "task_degraded": True,
        "teacher_clean": False,
        "teacher_degraded": True,
        "route_robust": False,
        "purpose": "principal robustness candidate",
        "simplicity_rank": 3,
    },
    "R4": {
        "name": "COMBINED_ROBUST_ROUTE_ANCHOR",
        "task_clean": True,
        "task_degraded": True,
        "teacher_clean": False,
        "teacher_degraded": True,
        "route_robust": True,
        "purpose": "R3 plus robust route consistency; TA2 only",
        "simplicity_rank": 4,
    },
}

INNER_CONDITIONS = tuple(
    f"{arch}-{obj}"
    for arch, spec in ARCH_SPECS.items()
    for obj in spec["objectives"]
)

FROZEN_CLEAN_VAL_PR_AUC = {
    "L1": {42: 0.9368690603400606, 52: 0.9360656904165168, 62: 0.9437081231855656},
    "F10": {42: 0.9441007472746944, 52: 0.9361330144482553, 62: 0.9475508279790588},
    "TA2": {42: 0.9454098053584642, 52: 0.9337067425514769, 62: 0.9494100170861509},
}

__all__ = [
    "TASK_ID",
    "PRIMARY_SEEDS",
    "SCREENING_SEED",
    "SOURCE_CHANNELS",
    "NOISE_LEVELS",
    "LAMBDA_TEACHER",
    "LAMBDA_ROUTE",
    "ARCH_SPECS",
    "OBJECTIVES",
    "INNER_CONDITIONS",
    "TEACHER_GUIDANCE_VS_INITIALISATION",
    "CLEAN_ODST_PREDICTIVE_SUPERIORITY",
    "ODST_DEGRADED_INPUT_ADVANTAGE_OVER_LINEAR",
    "ROUTE_ANCHOR_STRUCTURAL_ROBUSTNESS",
    "TEACHER_GUIDANCE_DEGRADED_INPUT_VALUE",
]
