"""Frozen EDITOR-014 identities. Placement test only; no architecture search."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from editor012_rescue.constants import (
    BATCH_SIZE,
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
    EDITOR012_RESULTS_FULL_COMMIT,
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

TASK_ID = "EDITOR-014"
PRIMARY_METRIC = "PR_AUC"
EXTENDED_SEEDS = (72, 82, 92, 102, 112, 122, 132)
ALL_STABILITY_SEEDS = PRIMARY_SEEDS + EXTENDED_SEEDS

REVIEW_REL = Path("review/editor014_temporal_odst_value")
OUTPUT_REL = Path("outputs/editor014_temporal_odst_value")

EDITOR013_WORKTREE = Path(r"C:\PhD\07_Projects\teacher-anchored-insider-threat-detection-editor013")
EDITOR012_WORKTREE = Path(r"C:\PhD\07_Projects\teacher-anchored-insider-threat-detection-editor012")
EDITOR011_WORKTREE = Path(r"C:\PhD\07_Projects\teacher-anchored-insider-threat-detection-editor011")

EDITOR013_RESULTS_COMMIT = "09c4bb97b143810147feef08f31a8d8d042a6726"
EDITOR013_PROTOCOL_COMMIT = EDITOR013_RESULTS_COMMIT

LR_BETA = 1e-3
LAMBDA_DISTILL = 0.5
PROMOTION_MARGIN = 0.001
BOOTSTRAP_SEED = 42
BOOTSTRAP_RESAMPLES = 2000
FAITHFULNESS_KS = (3, 5, 10)
LATENCY_BATCH_SIZE = 1024
LATENCY_WARMUP_BATCHES = 50
LATENCY_TIMED_BATCHES = 200
LATENCY_ROUNDS = 5
POST_ATTENTION_ODST_VALUE = "NOT_SUPPORTED_FROM_EDITOR013"
CONSENSUS_TEACHER_ADVANTAGE = "MIXED"

FROZEN_TA2_MEAN_PR_AUC = 0.9428421883320307
FROZEN_L1_MEAN_PR_AUC = 0.9388809579807144
FROZEN_TA2_MINUS_L1 = 0.003961230351316347
FROZEN_TA2_L1_CI = [-0.0013708139376007687, 0.011356265117941461]

L1_CHECKPOINTS = {
    42: {
        "checkpoint": EDITOR013_WORKTREE
        / "outputs/editor013_odst_value_proof/L1/seed42/best.pt",
        "sha256": "513e272063250aa209efa2c42b490cc44316c7979fa6b2be5dd8cce4592d1ab2",
        "validation_PR_AUC": 0.9368690603400606,
        "val_logits": EDITOR013_WORKTREE
        / "outputs/editor013_odst_value_proof/L1/seed42/val_logits.npy",
    },
    52: {
        "checkpoint": EDITOR013_WORKTREE
        / "outputs/editor013_odst_value_proof/L1/seed52/best.pt",
        "sha256": "a503f6705955da221bdbd1921034e9102b90db6acb5187114276ccaeb474e1c4",
        "validation_PR_AUC": 0.9360656904165168,
        "val_logits": EDITOR013_WORKTREE
        / "outputs/editor013_odst_value_proof/L1/seed52/val_logits.npy",
    },
    62: {
        "checkpoint": EDITOR013_WORKTREE
        / "outputs/editor013_odst_value_proof/L1/seed62/best.pt",
        "sha256": "60d5c43692a17ba6971c8d23f74048ac3c4fe0bd1b18889eeb21bbab7bf3d3e9",
        "validation_PR_AUC": 0.9437081231855656,
        "val_logits": EDITOR013_WORKTREE
        / "outputs/editor013_odst_value_proof/L1/seed62/val_logits.npy",
    },
}

ENSEMBLE_CACHE = {
    "train_ens": EDITOR013_WORKTREE / "outputs/editor013_odst_value_proof/ensemble_cache/train_ens_logit.npy",
    "train_42": EDITOR013_WORKTREE / "outputs/editor013_odst_value_proof/ensemble_cache/train_logit42.npy",
    "train_52": EDITOR013_WORKTREE / "outputs/editor013_odst_value_proof/ensemble_cache/train_logit52.npy",
    "train_62": EDITOR013_WORKTREE / "outputs/editor013_odst_value_proof/ensemble_cache/train_logit62.npy",
    "val_ens": EDITOR013_WORKTREE / "outputs/editor013_odst_value_proof/ensemble_cache/val_ens_logit.npy",
    "val_42": EDITOR013_WORKTREE / "outputs/editor013_odst_value_proof/ensemble_cache/val_logit42.npy",
    "val_52": EDITOR013_WORKTREE / "outputs/editor013_odst_value_proof/ensemble_cache/val_logit52.npy",
    "val_62": EDITOR013_WORKTREE / "outputs/editor013_odst_value_proof/ensemble_cache/val_logit62.npy",
}

EDITOR013_H1_LIN_D_INNER = {
    "condition": "H1-LIN-D",
    "select_PR_AUC": 0.9317652700255719,
    "select_F1": 0.8885245901639345,
    "source": "review/editor013_odst_value_proof/01_inner_search/EDITOR013_HEAD_SCREEN.csv",
    "hash_gate_allowed": True,
}

CONDITIONS: dict[str, dict[str, Any]] = {
    "B0": {
        "family": "linear",
        "placement": "none",
        "hybrid": False,
        "center": False,
        "distill": True,
        "teacher": "ensemble",
        "route": False,
        "identity": "matched teacher-guided linear (L1)",
    },
    "B1": {
        "family": "odst",
        "placement": "post_attention",
        "hybrid": False,
        "center": False,
        "distill": True,
        "teacher": "ensemble",
        "route": True,
        "identity": "current TA2 / post-attention ODST-046",
    },
    "T0": {
        "family": "temporal_odst",
        "placement": "pre_pooling",
        "hybrid": False,
        "center": False,
        "distill": True,
        "teacher": "ensemble",
        "route": False,
        "identity": "shared temporal ODST before attention aggregation",
    },
    "T1": {
        "family": "temporal_hybrid",
        "placement": "pre_pooling",
        "hybrid": True,
        "center": False,
        "distill": True,
        "teacher": "ensemble",
        "route": False,
        "identity": "teacher-guided linear + temporal ODST residual",
    },
    "T2": {
        "family": "temporal_hybrid",
        "placement": "pre_pooling",
        "hybrid": True,
        "center": True,
        "distill": True,
        "teacher": "ensemble",
        "route": False,
        "identity": "teacher-guided linear + centred temporal ODST residual",
    },
}

TEMPORAL_CANDIDATES = ("T0", "T1", "T2")
MAX_PROMOTED_TEMPORAL = 2

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
    "ODST046",
    "ENCODER_ARCH",
    "LAMBDA_DISTILL",
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
    "PROMOTION_MARGIN",
]
