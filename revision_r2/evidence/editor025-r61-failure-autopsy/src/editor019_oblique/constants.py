"""Frozen EDITOR-019 identities. No architecture, sparsity, or tree-count search."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from editor012_rescue.constants import (
    BATCH_SIZE,
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
    MAX_EPOCHS,
    PATIENCE,
    PRIMARY_SEEDS,
    SAFE_FEATURES,
    SCREENING_SEED,
    SEQUENCE_LENGTH,
    TOPT_CHECKPOINTS,
    WEIGHT_DECAY,
)
from editor013_odst_value.constants import (
    F11_CHECKPOINTS,
    N_TREES_TOTAL,
    TEACHER_GUIDANCE_VS_INITIALISATION,
)
from editor014_temporal_odst.constants import ENSEMBLE_CACHE, FROZEN_L1_MEAN_PR_AUC, FROZEN_TA2_MEAN_PR_AUC, L1_CHECKPOINTS
from editor017_robustness.constants import GLOBAL_TOPK_PR_AUC_FAITHFULNESS, NOISE_LEVELS, SOURCE_CHANNELS
from editor018_cross_view.constants import (
    EXPECTED_AGGREGATE40_SHA256,
    LOCKED_AGG_FEATURES,
    MLP40_ACTIVATION,
    MLP40_DROPOUT,
    MLP40_HIDDEN,
    MLP40_PROVENANCE,
    ODST40_SPEC,
    SUMMARY_DIM,
)

TASK_ID = "EDITOR-019"
PRIMARY_METRIC = "PR_AUC"
EXTENDED_SEEDS = (72, 82, 92, 102, 112, 122, 132)
ALL_STABILITY_SEEDS = PRIMARY_SEEDS + EXTENDED_SEEDS

REVIEW_REL = Path("review/editor019_oblique_boosted_tree_rescue")
OUTPUT_REL = Path("outputs/editor019_oblique_boosted_tree_rescue")

EDITOR017_RESULTS_COMMIT = "c75321a627ecc7539d1a759764d7ce395895179a"
EDITOR018_RESULTS_COMMIT = "9dafa51b7dd81d97cead84b4b7e10b2c230b08b4"
BASE_COMMIT = EDITOR018_RESULTS_COMMIT

EDITOR017_WORKTREE = Path(r"C:\PhD\07_Projects\teacher-anchored-insider-threat-detection-editor017")
EDITOR018_WORKTREE = Path(r"C:\PhD\07_Projects\teacher-anchored-insider-threat-detection-editor018")

SIGNED_DIM = SUMMARY_DIM * 2
TREE_DEPTH = 4
N_INTERNAL_NODES = 2**TREE_DEPTH - 1
N_LEAVES = 2**TREE_DEPTH
MIN_TREES = 2
MAX_TREES = 32
CAPACITY_RATIO = 1.05
LAMBDA_TEACHER = 0.5
PROMOTION_MARGIN = 0.001
XGB_TRIGGER_ODST_MARGIN = 0.001
XGB_TRIGGER_MLP_BAND = 0.002
MAX_PROMOTED = 2
BOOTSTRAP_SEED = 42
BOOTSTRAP_RESAMPLES = 2000
DIRECTIONAL_KS = (1, 2, 3)
LR_BRANCH = 1e-3
XGB_PROB_EPS = 1e-7

SO_ODST40_SPEC: dict[str, Any] = {
    **dict(ODST40_SPEC),
    "in_dim": SIGNED_DIM,
    "identity": "oblivious ODST40 with signed 80-channel sparse splits only",
}

XGB40_SEED = SCREENING_SEED
XGB40_PATH = Path(
    r"C:\PhD\07_Projects\cert-r52-locked-baselines\outputs\objective2\r52_locked_baselines\xgboost_seed42\model.json"
)
XGB40_EXPECTED_SHA256 = "2109554164abdd002ce0a4377f957c5aa3bc26886a197749ea79fc04d9b94fae"
XGB40_ROOT = Path(r"C:\PhD\07_Projects\cert-r52-locked-baselines\outputs\objective2\r52_locked_baselines")

REFERENCE_FAMILIES = ("MLP40", "ODST40")
NEW_TREE_FAMILIES = ("SO-ODST40", "SO-DTE40", "BSO-DTE40")
TREE_FAMILIES = NEW_TREE_FAMILIES
DTE_FAMILIES = ("SO-DTE40", "BSO-DTE40")

INNER_REFERENCE = ("L1", "MLP40-D", "ODST40-D")
INNER_NEW = tuple(f"{fam}-{g}" for fam in NEW_TREE_FAMILIES for g in ("T", "D"))
INNER_CONDITIONS = INNER_NEW

CONDITION_SPECS: dict[str, dict[str, Any]] = {
    "MLP40-D": {"family": "MLP40", "teacher": True, "identity": "recovered EDITOR-018 mlp40 teacher-residual"},
    "ODST40-D": {"family": "ODST40", "teacher": True, "identity": "recovered EDITOR-018 odst40 teacher-residual"},
    "SO-ODST40-T": {"family": "SO-ODST40", "teacher": False, "identity": "signed-oblique ODST40 task-only"},
    "SO-ODST40-D": {"family": "SO-ODST40", "teacher": True, "identity": "signed-oblique ODST40 teacher-residual"},
    "SO-DTE40-T": {"family": "SO-DTE40", "teacher": False, "identity": "node-specific signed oblique DTE task-only"},
    "SO-DTE40-D": {"family": "SO-DTE40", "teacher": True, "identity": "node-specific signed oblique DTE teacher-residual"},
    "BSO-DTE40-T": {"family": "BSO-DTE40", "teacher": False, "identity": "stagewise boosted SO-DTE40 task-only"},
    "BSO-DTE40-D": {"family": "BSO-DTE40", "teacher": True, "identity": "stagewise boosted SO-DTE40 teacher-residual"},
}

FACTORIAL = {
    "ODST40": "oblivious soft tree ensemble, jointly trained",
    "SO-ODST40": "same oblivious topology, signed sparse split directions",
    "SO-DTE40": "signed sparse split directions + node-specific non-oblivious splits",
    "BSO-DTE40": "SO-DTE40 + stagewise residual fitting",
}

EDITOR018_INNER = {
    "L1": 0.9381787168197482,
    "MLP40-D": 0.9401117154719215,
    "ODST40-D": 0.9382243122714573,
    "IWODST40-D": 0.9374952794840229,
}

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
    "SIGNED_DIM",
    "LOCKED_AGG_FEATURES",
    "EXPECTED_AGGREGATE40_SHA256",
    "TEACHER_GUIDANCE_VS_INITIALISATION",
    "GLOBAL_TOPK_PR_AUC_FAITHFULNESS",
    "FROZEN_TA2_MEAN_PR_AUC",
    "FROZEN_L1_MEAN_PR_AUC",
]
