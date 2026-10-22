"""Frozen EDITOR-027 identities. Representation rescue only. Architecture unchanged."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from editor006b_harness.safety import (
    COMMON_13_FEATURES,
    DENSE_PARQUET,
    EXPECTED_SCALER_SHA256,
    EXPECTED_TRAIN_NPZ_SHA256,
    EXPECTED_TRAIN_X_RAW_SHA256,
    EXPECTED_VAL_X_RAW_SHA256,
    N_FEATURES,
    TRAIN_NPZ,
    T_WINDOW,
    VAL_NPZ,
)
from editor012_rescue.constants import (
    BATCH_SIZE,
    ENCODER_ARCH,
    ET1_LOGIT_DISTILL_WEIGHT,
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
    SEQUENCE_LENGTH,
    WEIGHT_DECAY,
)
from editor013_odst_value.constants import ENCODER_DIM, LR_LINEAR
from editor017_robustness.constants import FROZEN_CLEAN_PR_AUC

TASK_ID = "EDITOR-027"
TASK_NAME = "CAUSAL USER-RELATIVE SCALE-NORMALISED REPRESENTATION"
EXPERIMENT_TYPE = "ROOT-CAUSE-TARGETED REPRESENTATION REFINEMENT"
RESULT_STATUS_AT_START = "UNSEEN"
MODEL_FAMILY = "UNCHANGED"
PRIMARY_INTERVENTION = "USER-RELATIVE SCALE NORMALISATION ONLY"
ARCHITECTURE_CHANGE = "NO"

EDITOR026_RESULTS_COMMIT = "83f3f8f6cbe2b75faa176e2840bec84bf84b09d0"
EDITOR025_RESULTS_COMMIT = "1f176bb7bf589da20be8ae9b02a23a4c8f0e0af7"
PROTOCOL_FREEZE_SUBJECT = "Freeze EDITOR-027 scale-normalised representation protocol"
R52_MODEL_FREEZE_SUBJECT = "Freeze EDITOR-027 r5.2 scale-normalised model checkpoints"
RESULTS_COMMIT_SUBJECT = "Freeze EDITOR-027 scale-normalised representation results"
RESULTS_COMMIT_PLACEHOLDER = "PENDING_BY_DESIGN"

SCALE_C2_READER = "scale-normalised user-relative teacher-initialised task-only control"
SCALE_F10_READER = "scale-normalised user-relative ensemble-guided ODST student without route anchoring"
SCALE_FINAL_READER = "scale-normalised user-relative final ensemble-guided, route-anchored ODST student"
SCALE_LINEAR_READER = "scale-normalised user-relative matched attention-linear reference"

STUDENT_MODELS = ("SCALE_C2", "SCALE_F10", "SCALE_FINAL", "SCALE_LINEAR")
SEEDS = PRIMARY_SEEDS  # (42, 52, 62)
FEATURE_ORDER = tuple(COMMON_13_FEATURES)
FEATURE_DIM = 13
SEQUENCE_LENGTH_LOCKED = 20
STRIDE = 1

VOLUME_FEATURES = (
    "total_events",
    "logon_count",
    "device_count",
    "file_count",
    "email_count",
    "http_count",
    "active_duration_minutes",
)
BINARY_FEATURES = (
    "has_logon_activity",
    "has_device_activity",
    "has_file_activity",
    "has_email_activity",
    "has_http_activity",
    "is_active_day",
)
BINARY_ALIASES = {
    "has_logon": "has_logon_activity",
    "has_device": "has_device_activity",
    "has_file": "has_file_activity",
    "has_email": "has_email_activity",
    "has_http": "has_http_activity",
}

USER_RELATIVE_LOOKBACK_DAYS = 20
MAD_SCALE_CONSTANT = 1.4826
SCALE_FLOOR_PERCENTILE = 0.25
FLOOR_FALLBACK = 1.0
SCALE_NETWORK_SCALER_FIT_DATA = "CERT r5.2 TRAIN ONLY"
R61_TARGET_SCALER_FIT = "NO"
R61_SCALER_FIT = "NO"
R61_TARGET_NORMALISATION_FIT = "NO"
R61_MODEL_TRAINING = "NO"
R61_CHECKPOINT_SELECTION = "NO"
R61_EARLY_STOPPING = "NO"
R61_HYPERPARAMETER_SELECTION = "NO"

R61_ROLE = "DIAGNOSTIC_DEVELOPMENT_RELEASE"
R61_CAN_BE_USED_TO_EVALUATE_EDITOR027_REMEDY = "YES"
R61_CAN_SERVE_AS_FUTURE_UNTOUCHED_TARGET = "NO"
R61_CAN_BE_USED_AS_FUTURE_UNTOUCHED_CONFIRMATION = "NO"
EDITOR024_RESULT_REMAINS_IMMUTABLE = "YES"
R61_LABEL_VIEW_A = "R61_EDITOR024_LABEL_VIEW"
R61_LABEL_VIEW_B = "R61_INSIDER_CONSISTENT_VIEW"
R61_SCENARIO4_ANSWER_AVAILABLE = "NO"
SCENARIO4_STATUS = "NOT_EVALUABLE"

# Frozen before Stage 0. Matches existing diagnostic zero-guard scale.
SEPARATION_EPSILON = 1e-12
PSI_FLOOR = 1e-6
SUPPORT_LOW_QUANTILE = 0.005
SUPPORT_HIGH_QUANTILE = 0.995

G0A_MEAN_ABS_SHIFT_REDUCTION_MIN = 0.50
G0B_MEAN_PSI_REDUCTION_VS_ORIGINAL_MIN = 0.50
G0B_MEAN_PSI_REDUCTION_MIN = 0.50
G0C_N_FEATURES_LOWER_PSI_MIN = 9
G0D_MEAN_PSI_REDUCTION_VS_CENTERED_MIN = 0.50
G0F_EDITOR024_INPUT_TRANSFER_MIN = 0.50
G0G_INSIDER_INPUT_TRANSFER_MIN = 0.50
G0E_EDITOR024_INPUT_TRANSFER_MIN = 0.50
G0F_INSIDER_INPUT_TRANSFER_MIN = 0.50

HISTORICAL_TA2_R52_MEAN_PR_AUC = 0.9428421883320307
HISTORICAL_C2OPT_R52_MEAN_PR_AUC = 0.9353238885175368
G1_SCALE_FINAL_R52_MIN = HISTORICAL_C2OPT_R52_MEAN_PR_AUC
G2_SCALE_FINAL_SEED_MIN = 0.93
G2_N_SEEDS_MIN = 2
MINIMUM_AP_PREVALENCE_LIFT = 10.0
G8_REPRESENTATION_TRANSFER_MIN = 0.50

BOOTSTRAP_SEED = 42
BOOTSTRAP_RESAMPLES = 2000
BOOTSTRAP_SAMPLING_UNIT = "user"

REVIEW_REL = Path("review/editor027_scale_normalised_representation")
OUTPUT_REL = Path("outputs/editor027_scale_normalised_representation")
EDITOR025_REVIEW_REL = Path("review/editor025_r61_failure_autopsy")
EDITOR024_REVIEW_REL = Path("review/editor024_r61_final_confirmation")
EDITOR024_OUTPUT_REL = Path("outputs/editor024_r61_final_confirmation")
EDITOR026_REVIEW_REL = Path("review/editor026_user_relative_representation")
SCALER_JSON_REL = Path("review/editor006a_preinference_freeze/EDITOR006A_SCALER.json")
SHA256_MANIFEST_NAME = "EDITOR027_SHA256_MANIFEST.json"

R52_TRAIN_NPZ = TRAIN_NPZ
R52_VAL_NPZ = VAL_NPZ
R52_DENSE_PARQUET = DENSE_PARQUET

# Frozen EDITOR-025 original-representation shift (all user-days).
EDITOR025_ORIGINAL_MEAN_SHIFT_Z = {
    "total_events": -0.1587618550296383,
    "logon_count": -0.04096792641043758,
    "device_count": 0.005226937994736664,
    "file_count": 0.03784128581107536,
    "email_count": -0.6442391695392732,
    "http_count": -0.018428916497261597,
    "active_duration_minutes": -0.06105442131594883,
    "has_logon_activity": -0.009228204223875857,
    "has_device_activity": -0.004882516154525145,
    "has_file_activity": 0.22486704669288815,
    "has_email_activity": -0.021479549668506782,
    "has_http_activity": -0.00844613848798373,
    "is_active_day": -0.011362341413065238,
}
EDITOR025_ORIGINAL_PSI = {
    "total_events": 0.5260258524393907,
    "logon_count": 0.0028811208630801386,
    "device_count": 5.345155994590028e-05,
    "file_count": 0.0,
    "email_count": 3.317436383694681,
    "http_count": 0.07770887179973726,
    "active_duration_minutes": 0.04053469653450822,
    "has_logon_activity": 0.0,
    "has_device_activity": 0.0,
    "has_file_activity": 0.0,
    "has_email_activity": 0.0,
    "has_http_activity": 0.0,
    "is_active_day": 0.0,
}

# Frozen EDITOR-026 centred user-relative Stage-0 PSI (CENTERED_SHIFT_REFERENCE).
EDITOR026_CENTERED_PSI = {
    "total_events": 0.8933480001243184,
    "logon_count": 0.5526324617373247,
    "device_count": 4.790806961941347e-06,
    "file_count": 0.038474914997389476,
    "email_count": 3.1802111176935677,
    "http_count": 0.15977211369594455,
    "active_duration_minutes": 0.009152261196993495,
    "has_logon_activity": 0.0012665396586280216,
    "has_device_activity": 0.0006832194654473719,
    "has_file_activity": 0.35301855481878874,
    "has_email_activity": 0.6650106876662083,
    "has_http_activity": 0.0013559239451585957,
    "is_active_day": 4.650173525189193,
}
EDITOR026_CENTERED_MEAN_PSI = 0.808084931615071
EDITOR026_STAGE0_MEAN_ABS_SHIFT_REDUCTION = 0.786484039149139
EDITOR026_STAGE0_MEAN_PSI_REDUCTION = -1.649699118292522
EDITOR026_STAGE0_FEATURES_WITH_LOWER_PSI = 3
EDITOR026_DISTRIBUTION_GATE = "FAIL"
EDITOR026_INPUT_SIGNAL_GATE = "PASS"

R61_EDITOR024_PREVALENCE = 9.557344064386318e-05
R61_EDITOR024_TA2_MEAN_PR_AUC = 9.445740146879832e-05
R61_INSIDER_CONSISTENT_PREVALENCE = 6.99195171026157e-05
R61_INSIDER_CONSISTENT_TA2_MEAN_PR_AUC = 7.471499955922729e-05

EDITOR025_REPRESENTATION_TRANSFER = {
    "C2-OPT": 0.15626504499761829,
    "F10": 0.15855185810847014,
    "TA2": 0.15950650800769253,
    "L1": 0.18111742091721014,
}

FROZEN_CLEAN_PR_AUC_BY_ALIAS = dict(FROZEN_CLEAN_PR_AUC)

# Producing attention-linear encoder (r52_odst_confirmation config.json).
ATTENTION_LINEAR_PRODUCING = {
    "source": (
        r"C:\PhD\07_Projects\cert-r42-feasibility\outputs\objective2"
        r"\r52_odst_confirmation\attention_linear_seed42\config.json"
    ),
    "architecture": "SequenceEnsembleModel",
    "classification_head": "linear",
    "temporal_aggregation": "attention",
    "hidden_size": 64,
    "dropout": 0.2,
    "attention_dim": 64,
    "learning_rate": 1e-3,
    "weight_decay": 0.0,
    "batch_size": 1024,
    "max_epochs": 15,
    "patience": 4,
    "grad_clip_norm": 1.0,
    "pos_weight_multiplier": 1.0,
    "optimizer": "Adam",
    "scheduler": {
        "name": "ReduceLROnPlateau",
        "mode": "max",
        "factor": 0.5,
        "patience": 2,
        "min_lr": 1e-5,
    },
    "early_stopping_metric": "validation_pr_auc",
    "checkpoint_selection_metric": "validation_pr_auc",
}

STUDENT_SPECS: dict[str, dict[str, Any]] = {
    "SCALE_C2": {
        "reader": SCALE_C2_READER,
        "family": "odst",
        "teacher_guidance": False,
        "route_anchor": False,
        "lambda_et1": 0.0,
        "lambda_route": 0.0,
        "historical_counterpart": "C2-OPT",
    },
    "SCALE_F10": {
        "reader": SCALE_F10_READER,
        "family": "odst",
        "teacher_guidance": True,
        "route_anchor": False,
        "lambda_et1": ET1_LOGIT_DISTILL_WEIGHT,
        "lambda_route": 0.0,
        "historical_counterpart": "F10",
    },
    "SCALE_FINAL": {
        "reader": SCALE_FINAL_READER,
        "family": "odst",
        "teacher_guidance": True,
        "route_anchor": True,
        "lambda_et1": ET1_LOGIT_DISTILL_WEIGHT,
        "lambda_route": LAMBDA_ROUTE,
        "historical_counterpart": "TA2",
    },
    "SCALE_LINEAR": {
        "reader": SCALE_LINEAR_READER,
        "family": "linear",
        "teacher_guidance": True,
        "route_anchor": False,
        "lambda_et1": ET1_LOGIT_DISTILL_WEIGHT,
        "lambda_route": 0.0,
        "historical_counterpart": "L1",
    },
}

TOPK_MULTIPLIERS = (1, 5, 10)
FALSE_POSITIVE_COHORT_N = 10000
REPRESENTATION_NEGATIVE_N = 20000

assert SEQUENCE_LENGTH_LOCKED == T_WINDOW == SEQUENCE_LENGTH == 20
assert FEATURE_DIM == N_FEATURES == 13
assert SEEDS == (42, 52, 62)
assert STUDENT_MODELS == ("SCALE_C2", "SCALE_F10", "SCALE_FINAL", "SCALE_LINEAR")
assert USER_RELATIVE_LOOKBACK_DAYS == 20
assert MINIMUM_AP_PREVALENCE_LIFT == 10.0
assert LAMBDA_HISTORICAL_SINGLE_TEACHER_LOGIT == 0.0
assert list(FEATURE_ORDER) == list(SAFE_FEATURES)
assert FEATURE_ORDER[:7] == VOLUME_FEATURES
assert FEATURE_ORDER[7:] == BINARY_FEATURES
assert MAD_SCALE_CONSTANT == 1.4826
assert SCALE_FLOOR_PERCENTILE == 0.25
assert FLOOR_FALLBACK == 1.0
assert abs(sum(EDITOR026_CENTERED_PSI.values()) / 13.0 - EDITOR026_CENTERED_MEAN_PSI) < 1e-12


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_editor025_json(name: str) -> Any:
    path = repo_root() / EDITOR025_REVIEW_REL / name
    return json.loads(path.read_text(encoding="utf-8"))


__all__ = [
    "TASK_ID",
    "EDITOR026_RESULTS_COMMIT",
    "EDITOR025_RESULTS_COMMIT",
    "STUDENT_MODELS",
    "SEEDS",
    "FEATURE_ORDER",
    "USER_RELATIVE_LOOKBACK_DAYS",
    "MAD_SCALE_CONSTANT",
    "SCALE_FLOOR_PERCENTILE",
    "SEPARATION_EPSILON",
    "MINIMUM_AP_PREVALENCE_LIFT",
]
