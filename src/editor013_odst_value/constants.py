"""Frozen EDITOR-013 identities. No architecture, feature, or split search."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from editor012_rescue.constants import (
    BATCH_SIZE,
    C2OPT_CHECKPOINTS,
    ENCODER_ARCH,
    ET1_LOGIT_DISTILL_WEIGHT,
    ET1_TEMPERATURE,
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
    HISTORICAL as EDITOR012_HISTORICAL,
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
    R2OPT_CHECKPOINTS,
    SAFE_FEATURES,
    SCREENING_SEED,
    SEQUENCE_LENGTH,
    TOPT_CHECKPOINTS,
    WEIGHT_DECAY,
)

TASK_ID = "EDITOR-013"
PRIMARY_METRIC = "PR_AUC"
EXTENDED_SEEDS = (72, 82, 92, 102, 112, 122, 132)
ALL_STABILITY_SEEDS = PRIMARY_SEEDS + EXTENDED_SEEDS

REVIEW_REL = Path("review/editor013_odst_value_proof")
OUTPUT_REL = Path("outputs/editor013_odst_value_proof")

EDITOR012_WORKTREE = Path(r"C:\PhD\07_Projects\teacher-anchored-insider-threat-detection-editor012")
EDITOR011_WORKTREE = Path(r"C:\PhD\07_Projects\teacher-anchored-insider-threat-detection-editor011")
EDITOR010_WORKTREE = Path(r"C:\PhD\07_Projects\teacher-anchored-insider-threat-detection-editor010")
EDITOR009_WORKTREE = Path(r"C:\PhD\07_Projects\teacher-anchored-insider-threat-detection")

EDITOR012_PROTOCOL_COMMIT = "065d8080ec06148e12a46f0a5710b0225c9b66c7"
EDITOR012_IMPLEMENTATION_COMMIT = "7007fa7927a46951129aa428970dd9cc567eb4d1"
EDITOR012_PROMOTION_COMMIT = "6c9fa3fca92e3820d236d1d001c5c709245c00f9"
EDITOR012_RESULTS_COMMIT = "4bcf522a502ed98e5dd393a80bd9da7fffd51964"
EDITOR012_RESULTS_FULL_COMMIT = EDITOR012_RESULTS_COMMIT

N_TREES_TOTAL = 8
N_LAYERS = 2
N_TREES_PER_LAYER = 4
TREE_DIM = 1
ENCODER_DIM = 128
LINEAR_HEAD_IN_DIM = ENCODER_DIM
LINEAR_HEAD_OUT_DIM = 1

LR_LINEAR = 1e-3
LR_READOUT = 1e-3
LR_ALPHA = 1e-3

LAMBDA_DISTILL = 0.5
LAMBDA_DIVERSITY_CANDIDATES = (0.01, 0.05, 0.10)
TREE_DIVERSITY_TRIGGER = 0.90
PROMOTION_MARGIN = 0.001
BOOTSTRAP_SEED = 42
BOOTSTRAP_RESAMPLES = 2000
FAITHFULNESS_KS = (3, 5, 10)
LATENCY_BATCH_SIZE = 1024
LATENCY_WARMUP = 5
LATENCY_REPEATS = 20

HISTORICAL_SINGLE_TEACHER_LOGIT_ANCHOR = "RETIRED"
TEACHER_GUIDANCE_VS_INITIALISATION = "SUPPORTED_STRONG"

HISTORICAL = {
    **EDITOR012_HISTORICAL,
    "EDITOR012_F00_C2OPT": {
        "mean_PR_AUC": 0.9353238885175368,
        "seeds": {42: 0.9443205892331505, 52: 0.9214711755922543, 62: 0.9401799007272055},
        "identity": "ODST-046 uniform + task only (C2-OPT / F00)",
    },
    "EDITOR012_F10_DOPT": {
        "mean_PR_AUC": 0.9425948632340028,
        "seeds": {42: 0.9441007472746944, 52: 0.9361330144482553, 62: 0.9475508279790588},
        "identity": "ODST-046 uniform + ensemble teacher guidance (O1 / ENSEMBLE-MSE)",
    },
    "EDITOR012_F01_R2OPT": {
        "mean_PR_AUC": 0.9374955810783120,
        "seeds": {42: 0.9471384496065599, 52: 0.9257403375052433, 62: 0.9396079561231327},
    },
    "EDITOR012_F11_TA2": {
        "mean_PR_AUC": 0.9428421883320307,
        "seeds": {42: 0.9454098053584642, 52: 0.9337067425514769, 62: 0.9494100170861509},
        "identity": "ODST-046 uniform + ensemble guidance + route anchor (TA2)",
        "do_not_relabel_as_historical_C5": True,
    },
}

F10_CHECKPOINTS = {
    42: {
        "checkpoint": EDITOR012_WORKTREE
        / "outputs/editor012_teacher_anchor_rescue/F10_DOPT/seed42/best_student.pt",
        "sha256": "ea8cd41a1ae3f845719956fd7a49230fa82807ffac87841be5f5ab95c64ac0c2",
        "validation_PR_AUC": 0.9441007472746944,
        "val_logits": EDITOR012_WORKTREE
        / "outputs/editor012_teacher_anchor_rescue/F10_DOPT/seed42/val_logits.npy",
    },
    52: {
        "checkpoint": EDITOR012_WORKTREE
        / "outputs/editor012_teacher_anchor_rescue/F10_DOPT/seed52/best_student.pt",
        "sha256": "829135230c5629f0b11161e11d76eba7a15e65bf9d03b5a55ffa297a93ddf959",
        "validation_PR_AUC": 0.9361330144482553,
        "val_logits": EDITOR012_WORKTREE
        / "outputs/editor012_teacher_anchor_rescue/F10_DOPT/seed52/val_logits.npy",
    },
    62: {
        "checkpoint": EDITOR012_WORKTREE
        / "outputs/editor012_teacher_anchor_rescue/F10_DOPT/seed62/best_student.pt",
        "sha256": "06313d6f2602de51f8dd6e15e1d1292864fd8cbd158f33977fa42c8a47036aee",
        "validation_PR_AUC": 0.9475508279790588,
        "val_logits": EDITOR012_WORKTREE
        / "outputs/editor012_teacher_anchor_rescue/F10_DOPT/seed62/val_logits.npy",
    },
}

F11_CHECKPOINTS = {
    42: {
        "checkpoint": EDITOR012_WORKTREE
        / "outputs/editor012_teacher_anchor_rescue/F11_DROPT/seed42/best_student.pt",
        "sha256": "54f6c097af9568a4ee5701ef375559a2f649cec6c1817e578d3e8e01e6d73df8",
        "validation_PR_AUC": 0.9454098053584642,
        "val_logits": EDITOR012_WORKTREE
        / "outputs/editor012_teacher_anchor_rescue/F11_DROPT/seed42/val_logits.npy",
    },
    52: {
        "checkpoint": EDITOR012_WORKTREE
        / "outputs/editor012_teacher_anchor_rescue/F11_DROPT/seed52/best_student.pt",
        "sha256": "7613ba559bcf55827d04129066eb595b677994494609646f8b2463308ed5edb4",
        "validation_PR_AUC": 0.9337067425514769,
        "val_logits": EDITOR012_WORKTREE
        / "outputs/editor012_teacher_anchor_rescue/F11_DROPT/seed52/val_logits.npy",
    },
    62: {
        "checkpoint": EDITOR012_WORKTREE
        / "outputs/editor012_teacher_anchor_rescue/F11_DROPT/seed62/best_student.pt",
        "sha256": "904003dca219435464476cf36abedb11ee4e2f7a11ff09caa3791d685b8f644d",
        "validation_PR_AUC": 0.9494100170861509,
        "val_logits": EDITOR012_WORKTREE
        / "outputs/editor012_teacher_anchor_rescue/F11_DROPT/seed62/val_logits.npy",
    },
}

C2_VAL_LOGITS = {
    seed: EDITOR012_WORKTREE
    / f"outputs/editor012_teacher_anchor_rescue/F00_C2OPT/seed{seed}/val_logits.npy"
    for seed in PRIMARY_SEEDS
}

HEAD_CONDITIONS: dict[str, dict[str, Any]] = {
    "H0-LIN": {
        "family": "linear",
        "readout": "none",
        "hybrid": False,
        "distill": False,
        "teacher": "none",
        "route": False,
    },
    "H1-LIN-D": {
        "family": "linear",
        "readout": "none",
        "hybrid": False,
        "distill": True,
        "teacher": "ensemble",
        "route": False,
    },
    "H2-ODST-U": {
        "family": "odst",
        "readout": "uniform",
        "hybrid": False,
        "distill": False,
        "teacher": "none",
        "route": False,
    },
    "H3-ODST-U-D": {
        "family": "odst",
        "readout": "uniform",
        "hybrid": False,
        "distill": True,
        "teacher": "ensemble",
        "route": False,
    },
    "H4-ODST-W": {
        "family": "odst",
        "readout": "weighted",
        "hybrid": False,
        "distill": False,
        "teacher": "none",
        "route": False,
    },
    "H5-ODST-W-D": {
        "family": "odst",
        "readout": "weighted",
        "hybrid": False,
        "distill": True,
        "teacher": "ensemble",
        "route": False,
    },
    "H6-HYB-U": {
        "family": "hybrid",
        "readout": "uniform",
        "hybrid": True,
        "distill": False,
        "teacher": "none",
        "route": False,
    },
    "H7-HYB-U-D": {
        "family": "hybrid",
        "readout": "uniform",
        "hybrid": True,
        "distill": True,
        "teacher": "ensemble",
        "route": False,
    },
    "H8-HYB-W": {
        "family": "hybrid",
        "readout": "weighted",
        "hybrid": True,
        "distill": False,
        "teacher": "none",
        "route": False,
    },
    "H9-HYB-W-D": {
        "family": "hybrid",
        "readout": "weighted",
        "hybrid": True,
        "distill": True,
        "teacher": "ensemble",
        "route": False,
    },
    "H1-LIN-S": {
        "family": "linear",
        "readout": "none",
        "hybrid": False,
        "distill": True,
        "teacher": "single",
        "route": False,
    },
    "H3-ODST-U-S": {
        "family": "odst",
        "readout": "uniform",
        "hybrid": False,
        "distill": True,
        "teacher": "single",
        "route": False,
    },
}

VALIDATION_MANDATORY = {
    "L0": {"family": "linear", "distill": False, "teacher": "none", "route": False, "readout": "none", "hybrid": False},
    "L1": {"family": "linear", "distill": True, "teacher": "ensemble", "route": False, "readout": "none", "hybrid": False},
    "O0": {"family": "odst", "distill": False, "teacher": "none", "route": False, "readout": "uniform", "hybrid": False, "reuse": "C2-OPT"},
    "O1": {"family": "odst", "distill": True, "teacher": "ensemble", "route": False, "readout": "uniform", "hybrid": False, "reuse": "F10"},
    "TA2": {"family": "odst", "distill": True, "teacher": "ensemble", "route": True, "readout": "uniform", "hybrid": False, "reuse": "F11"},
    "SINGLE-MSE": {"family": "odst", "distill": True, "teacher": "single", "route": False, "readout": "uniform", "hybrid": False},
    "ENSEMBLE-MSE": {"family": "odst", "distill": True, "teacher": "ensemble", "route": False, "readout": "uniform", "hybrid": False, "reuse": "F10"},
}

TREE_ORDER = [
    "layer0_tree0",
    "layer0_tree1",
    "layer0_tree2",
    "layer0_tree3",
    "layer1_tree0",
    "layer1_tree1",
    "layer1_tree2",
    "layer1_tree3",
]

__all__ = [
    "TASK_ID",
    "PRIMARY_SEEDS",
    "SCREENING_SEED",
    "TOPT_CHECKPOINTS",
    "C2OPT_CHECKPOINTS",
    "ODST046",
    "ENCODER_ARCH",
    "ET1_LOGIT_DISTILL_WEIGHT",
    "ET1_TEMPERATURE",
    "LAMBDA_DISTILL",
    "LAMBDA_ROUTE",
    "LAMBDA_HISTORICAL_SINGLE_TEACHER_LOGIT",
    "HISTORICAL_SINGLE_TEACHER_LOGIT_ANCHOR",
    "BATCH_SIZE",
    "MAX_EPOCHS",
    "PATIENCE",
    "LR_ENCODER",
    "LR_ATTENTION",
    "LR_ODST",
    "LR_LINEAR",
    "WEIGHT_DECAY",
    "GRAD_CLIP_NORM",
    "POS_WEIGHT_MULT",
    "SEQUENCE_LENGTH",
    "FEATURE_DIM",
    "SAFE_FEATURES",
    "EXPECTED_TRAIN_SHA256",
    "EXPECTED_VAL_SHA256",
    "EXPECTED_TRAIN_SHAPE",
    "EXPECTED_VAL_SHAPE",
    "EXPECTED_TRAIN_POS",
    "EXPECTED_VAL_POS",
    "EXPECTED_INNER_TRAIN_N",
    "EXPECTED_INNER_SELECT_N",
    "EXPECTED_INNER_TRAIN_POS",
    "EXPECTED_INNER_SELECT_POS",
    "EXPECTED_INNER_DROPPED",
    "EXPECTED_VAL_USERS",
    "EXPECTED_VAL_WINDOWS_PER_USER",
    "EXPECTED_VAL_MALICIOUS_USERS",
    "EXPECTED_USER_MAPPING_SHA256",
    "R2OPT_CHECKPOINTS",
    "TEACHER_GUIDANCE_VS_INITIALISATION",
]
