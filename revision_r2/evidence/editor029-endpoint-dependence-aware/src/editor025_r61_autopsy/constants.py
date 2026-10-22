"""Frozen EDITOR-025 identities. Read-only r6.1 failure autopsy. No training."""

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
from editor012_rescue.constants import PRIMARY_SEEDS
from editor017_robustness.constants import MODEL_SPECS

TASK_ID = "EDITOR-025"
TASK_NAME = "CERT r6.1 CROSS-VERSION FAILURE AUTOPSY"
EXPERIMENT_TYPE = "READ-ONLY DIAGNOSTIC / ROOT-CAUSE ANALYSIS"
MODEL_TRAINING = "PROHIBITED"
MODEL_PARAMETER_UPDATE = "PROHIBITED"
RESULT_STATUS_AT_START = "NEW_DIAGNOSTICS_UNSEEN"

EDITOR024_RESULTS_COMMIT = "23794a721a2215957da02d513f7e0af473fde4e6"
PROTOCOL_FREEZE_SUBJECT = "Freeze EDITOR-025 r6.1 failure autopsy protocol"
RESULTS_COMMIT_SUBJECT = "Freeze EDITOR-025 r6.1 failure autopsy"
RESULTS_COMMIT_PLACEHOLDER = "PENDING_BY_DESIGN"

# Internal model labels (document before use).
C2_OPT_READER = "teacher-initialised task-only control"
F10_READER = "ensemble-guided ODST student without route anchoring"
TA2_READER = "final ensemble-guided, route-anchored ODST student"
L1_READER = "matched attention-linear reference"
ODST_READER = "Oblivious Differentiable Sparsemax Tree"
F10_IS_INTERNAL_FACTORIAL_IDENTIFIER = True
TA2_NUMERAL_HAS_NO_FORMAL_EXPANSION = True

STUDENT_MODELS = ("C2-OPT", "F10", "TA2", "L1")
SEEDS = PRIMARY_SEEDS  # (42, 52, 62)
FEATURE_ORDER = tuple(COMMON_13_FEATURES)
SEQUENCE_LENGTH = 20
FEATURE_DIM = 13
BATCH_SIZE = 1024

COUNT_FEATURES = (
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

REVIEW_REL = Path("review/editor025_r61_failure_autopsy")
OUTPUT_REL = Path("outputs/editor025_r61_failure_autopsy")
EDITOR024_REVIEW_REL = Path("review/editor024_r61_final_confirmation")
EDITOR024_OUTPUT_REL = Path("outputs/editor024_r61_final_confirmation")
EDITOR007D_REVIEW_REL = Path("review/editor007d_cross_version_synthesis")
SCALER_JSON_REL = Path("review/editor006a_preinference_freeze/EDITOR006A_SCALER.json")

R52_TRAIN_NPZ = TRAIN_NPZ
R52_VAL_NPZ = VAL_NPZ
R52_DENSE_PARQUET = DENSE_PARQUET

ANSWER_SEARCH_ROOTS = (
    Path(r"C:\PhD\06_Datasets\answers"),
    Path(r"C:\PhD\07_Projects\cert-r42-feasibility\answers\answers"),
    Path(r"C:\PhD\07_Projects\cert-r42-feasibility\answers"),
    Path(r"C:\PhD\06_Datasets\r6.1"),
)
EXPECTED_ANSWER_FILES = (
    "r6.1-1.csv",
    "r6.1-2.csv",
    "r6.1-3.csv",
    "r6.1-4.csv",
    "r6.1-5.csv",
    "insiders.csv",
)

# Frozen EDITOR-024 facts (inputs; do not alter).
R61_COMPLETED_N = 1988000
R61_COMPLETED_POSITIVES = 190
R61_PREVALENCE = 9.557344064386318e-05
R61_MEAN_PR_AUC = {
    "C2-OPT": 9.58548433287757e-05,
    "F10": 9.391288112518778e-05,
    "TA2": 9.445740146879832e-05,
    "L1": 9.99715314772706e-05,
}
F10_TEACHER_RELATIVE_ROUTE_MAE = 0.013852491027299319
TA2_TEACHER_RELATIVE_ROUTE_MAE = 0.009477296424532945
R61_FINAL_TA2_RANKING_TRANSFER = "NOT_SUPPORTED"

R61_ROLE_BEFORE = "PROSPECTIVELY_RESERVED_FINAL_CONFIRMATION_TARGET"
R61_ROLE_FROM_EDITOR025 = "DIAGNOSTIC_DEVELOPMENT_RELEASE"
EDITOR024_RESULT_REMAINS_IMMUTABLE = "YES"
R61_UNTOUCHED_STATUS_HISTORICAL_FOR_EDITOR024 = "PRESERVED"
R61_ELIGIBLE_AS_FUTURE_UNTOUCHED_TARGET = "NO"
R61_CAN_BE_USED_FOR_EDITOR026_DEVELOPMENT = "YES"
R61_CAN_BE_USED_AS_FINAL_UNTOUCHED_CONFIRMATION_AFTER_EDITOR025 = "NO"

# Phase E prospectively frozen capture thresholds.
TOPK_MULTIPLIERS = (1, 5, 10)
TOPK_FRACTIONS = (0.001, 0.01)
FALSE_POSITIVE_COHORT_N = 10000
REFERENCE_NEGATIVE_COHORT_N = 10000
REPRESENTATION_NEGATIVE_N = 20000

# Phase I: exactly one non-trained input counterfactual.
SUPPORT_CLIP_VIEW_NAME = "R52_SUPPORT_CLIP"
SUPPORT_CLIP_LOW_QUANTILE = 0.005
SUPPORT_CLIP_HIGH_QUANTILE = 0.995
SUPPORT_CLIP_LEVELS = (SUPPORT_CLIP_VIEW_NAME,)

# Conventional PSI / shift descriptors frozen before seeing r6.1 diagnostics.
PSI_LIMITED_MAX = 0.10
PSI_SEVERE_MIN = 0.25
MEAN_SHIFT_Z_MODERATE = 0.25
MEAN_SHIFT_Z_SEVERE = 0.50
OOS_RATE_MODERATE = 0.01
OOS_RATE_SEVERE = 0.05
BINARY_RATE_DIFF_MODERATE = 0.05
BINARY_RATE_DIFF_SEVERE = 0.10

QUANTILES = (0.01, 0.05, 0.25, 0.50, 0.75, 0.95, 0.99)
SCORE_QUANTILES = (0.001, 0.01, 0.05, 0.25, 0.50, 0.75, 0.95, 0.99, 0.999)

PSI_FLOOR = 1e-6
REPRESENTATION_NONPORTABILITY_LOW = 0.25
REPRESENTATION_NONPORTABILITY_HIGH = 0.50
HEAD_SURVIVAL_RATIO = 0.50

SHA256_MANIFEST_NAME = "EDITOR025_SHA256_MANIFEST.json"

assert SEQUENCE_LENGTH == T_WINDOW == 20
assert FEATURE_DIM == N_FEATURES == 13
assert SEEDS == (42, 52, 62)
assert STUDENT_MODELS == ("C2-OPT", "F10", "TA2", "L1")
assert len(SUPPORT_CLIP_LEVELS) == 1
assert SUPPORT_CLIP_LOW_QUANTILE == 0.005
assert SUPPORT_CLIP_HIGH_QUANTILE == 0.995


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_editor024_json(name: str) -> Any:
    path = repo_root() / EDITOR024_REVIEW_REL / name
    return json.loads(path.read_text(encoding="utf-8"))


def frozen_thresholds() -> dict[str, dict[str, float]]:
    raw = load_editor024_json("EDITOR024_PROTOCOL.json")["frozen_thresholds"]
    return {model: {str(seed): float(raw[model][str(seed)]) for seed in SEEDS} for model in STUDENT_MODELS}


def model_checkpoint_spec(model: str, seed: int) -> dict[str, Any]:
    return MODEL_SPECS[model]["checkpoints"][seed]


__all__ = [
    "TASK_ID",
    "EDITOR024_RESULTS_COMMIT",
    "STUDENT_MODELS",
    "SEEDS",
    "FEATURE_ORDER",
    "SUPPORT_CLIP_VIEW_NAME",
    "SUPPORT_CLIP_LOW_QUANTILE",
    "SUPPORT_CLIP_HIGH_QUANTILE",
]
