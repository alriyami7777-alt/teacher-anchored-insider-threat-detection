"""Frozen EDITOR-029 identities. No architecture search. Model-rescue remains closed."""

from __future__ import annotations

from types import MappingProxyType
from pathlib import Path
from typing import Any

from editor006b_harness.safety import (
    COMMON_13_FEATURES,
    DENSE_PARQUET,
    EXPECTED_SCALER_SHA256,
    TRAIN_NPZ,
    VAL_NPZ,
    N_FEATURES,
    T_WINDOW,
)
from editor012_rescue.constants import (
    BATCH_SIZE,
    C2OPT_CHECKPOINTS,
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
    TOPT_CHECKPOINTS,
    WEIGHT_DECAY,
)
from editor013_odst_value.constants import ENCODER_DIM, F10_CHECKPOINTS, F11_CHECKPOINTS, LR_LINEAR
from editor014_temporal_odst.constants import L1_CHECKPOINTS
from editor017_robustness.constants import FROZEN_CLEAN_PR_AUC, MODEL_SPECS
from editor026_user_relative.constants import ATTENTION_LINEAR_PRODUCING

TASK_ID = "EDITOR-029"
TASK_NAME = "ENDPOINT-DEFINED AND DEPENDENCE-AWARE EVALUATION"
EXPERIMENT_TYPE = "EDITOR-CLOSURE SENSITIVITY AND ENDPOINT-TASK EVALUATION"
RESULT_STATUS_AT_START = "UNSEEN_FOR_NEW_EDITOR029_ANALYSES"
MODEL_RESCUE = "NO"
ARCHITECTURE_SEARCH = "NO"
MODEL_RESCUE_PROGRAMME = "CLOSED"
CURRENT_PAPER_MODEL = "TA2"
EDITOR024_R61_GENERALISATION_RESULT_CHANGED = "NO"

EDITOR028_RESULTS_COMMIT = "8d139c67e71cd2d2fca28e98f6214d059a0abc92"
PROTOCOL_FREEZE_SUBJECT = "Freeze EDITOR-029 endpoint and dependence-aware protocol"
ENDPOINT_MODEL_FREEZE_SUBJECT = "Freeze EDITOR-029 endpoint-defined model checkpoints"
RESULTS_COMMIT_SUBJECT = "Freeze EDITOR-029 endpoint and dependence-aware results"
RESULTS_COMMIT_PLACEHOLDER = "PENDING_BY_DESIGN"

C2_OPT_READER = "teacher-initialised task-only control"
F10_READER = "ensemble-guided ODST student without route anchoring"
TA2_READER = "final ensemble-guided, route-anchored student"
TA2_INTERNAL = "final ensemble-guided, route-anchored ODST student"
L1_READER = "matched attention-linear reference"
ODST_EXPANSION = "Oblivious Differentiable Sparsemax Tree"
PR_AUC_EXPANSION = "area under the precision-recall curve"
CI_EXPANSION = "confidence interval"

EP_C2_READER = "endpoint-defined teacher-initialised task-only control"
EP_F10_READER = "endpoint-defined ensemble-guided ODST student without route anchoring"
EP_FINAL_READER = "endpoint-defined final ensemble-guided, route-anchored ODST student"
EP_LINEAR_READER = "endpoint-defined matched attention-linear reference"

HISTORICAL_MODELS = ("C2-OPT", "F10", "TA2", "L1")
ENDPOINT_MODELS = ("EP_C2", "EP_F10", "EP_FINAL", "EP_LINEAR")
SEEDS = PRIMARY_SEEDS  # (42, 52, 62)
FEATURE_ORDER = tuple(COMMON_13_FEATURES)
FEATURE_DIM = 13
SEQUENCE_LENGTH_LOCKED = 20
STRIDE = 1
N_DEOVERLAP_OFFSETS = 20
DEOVERLAP_STEP = 20
PRIMARY_DEOVERLAP_OFFSET = 0

HISTORICAL_MEAN_PR_AUC = MappingProxyType(
    {
        "C2-OPT": 0.9353238885175368,
        "F10": 0.9425948632340028,
        "TA2": 0.9428421883320307,
        "L1": 0.9388809579807144,
    }
)
PARITY_TOLERANCE = 0.0005

STUDENT_SPECS: dict[str, dict[str, Any]] = {
    "EP_C2": {
        "reader": EP_C2_READER,
        "family": "odst",
        "teacher_guidance": False,
        "route_anchor": False,
        "lambda_et1": 0.0,
        "lambda_route": 0.0,
        "historical_counterpart": "C2-OPT",
    },
    "EP_F10": {
        "reader": EP_F10_READER,
        "family": "odst",
        "teacher_guidance": True,
        "route_anchor": False,
        "lambda_et1": ET1_LOGIT_DISTILL_WEIGHT,
        "lambda_route": 0.0,
        "historical_counterpart": "F10",
    },
    "EP_FINAL": {
        "reader": EP_FINAL_READER,
        "family": "odst",
        "teacher_guidance": True,
        "route_anchor": True,
        "lambda_et1": ET1_LOGIT_DISTILL_WEIGHT,
        "lambda_route": LAMBDA_ROUTE,
        "historical_counterpart": "TA2",
    },
    "EP_LINEAR": {
        "reader": EP_LINEAR_READER,
        "family": "linear",
        "teacher_guidance": True,
        "route_anchor": False,
        "lambda_et1": ET1_LOGIT_DISTILL_WEIGHT,
        "lambda_route": 0.0,
        "historical_counterpart": "L1",
    },
}

PART_A_CONTRASTS = (
    ("F10", "C2-OPT", "F10-C2-OPT"),
    ("TA2", "C2-OPT", "TA2-C2-OPT"),
    ("TA2", "F10", "TA2-F10"),
    ("TA2", "L1", "TA2-L1"),
)
PART_B_CONTRASTS = (
    ("EP_F10", "EP_C2", "EP_F10-EP_C2"),
    ("EP_FINAL", "EP_C2", "EP_FINAL-EP_C2"),
    ("EP_FINAL", "EP_F10", "EP_FINAL-EP_F10"),
    ("EP_FINAL", "EP_LINEAR", "EP_FINAL-EP_LINEAR"),
)

LAMBDA_TASK = 1.0
LAMBDA_TEACHER = 0.5
LAMBDA_ROUTE_FINAL = 0.5
assert LAMBDA_TEACHER == ET1_LOGIT_DISTILL_WEIGHT
assert LAMBDA_ROUTE_FINAL == LAMBDA_ROUTE

BOOTSTRAP_SEED = 42
BOOTSTRAP_RESAMPLES = 2000
BOOTSTRAP_SAMPLING_UNIT = "user"
SUPPORTED_OFFSETS_STRONG = 15
SUPPORTED_OFFSETS_CONSISTENT = 11

REVIEW_REL = Path("review/editor029_endpoint_dependence")
OUTPUT_REL = Path("outputs/editor029_endpoint_dependence")
SCALER_JSON_REL = Path("review/editor006a_preinference_freeze/EDITOR006A_SCALER.json")
SHA256_MANIFEST_NAME = "EDITOR029_SHA256_MANIFEST.json"

R52_TRAIN_NPZ = TRAIN_NPZ
R52_VAL_NPZ = VAL_NPZ
R52_DENSE_PARQUET = DENSE_PARQUET
R52_TEST_ACCESSED = "NO"
R51_RERUN = "NO"
R61_RERUN = "NO"
R62_RERUN = "NO"
NEW_SCALER_FIT = "NO"
UNSEEN_USER_GENERALISATION_TESTED = "NO"
REAL_TIME_INTRADAY_PREDICTION_TESTED = "NO"
PRE_EVENT_FORECASTING_TESTED = "NO"
SAME_USER_TEMPORAL_PARTITIONS = "YES"
DO_NOT_START_EDITOR030 = "YES"

FORBIDDEN_CLAIMS = (
    "forecasting malicious activity before day d",
    "real-time intra-day prediction",
    "pre-event warning",
    "causal intervention",
    "unseen-user generalisation",
)

assert SEQUENCE_LENGTH_LOCKED == T_WINDOW == SEQUENCE_LENGTH == 20
assert FEATURE_DIM == N_FEATURES == 13
assert SEEDS == (42, 52, 62)
assert N_DEOVERLAP_OFFSETS == 20
assert DEOVERLAP_STEP == 20
assert list(FEATURE_ORDER) == list(SAFE_FEATURES)
assert BATCH_SIZE == 1024
assert LAMBDA_HISTORICAL_SINGLE_TEACHER_LOGIT == 0.0
assert MODEL_RESCUE_PROGRAMME == "CLOSED"
assert CURRENT_PAPER_MODEL == "TA2"
assert EDITOR024_R61_GENERALISATION_RESULT_CHANGED == "NO"
assert ATTENTION_LINEAR_PRODUCING["learning_rate"] == 1e-3
assert ATTENTION_LINEAR_PRODUCING["pos_weight_multiplier"] == 1.0


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


__all__ = [
    "TASK_ID",
    "EDITOR028_RESULTS_COMMIT",
    "SEEDS",
    "FEATURE_ORDER",
    "HISTORICAL_MEAN_PR_AUC",
    "ENDPOINT_MODELS",
    "HISTORICAL_MODELS",
]
