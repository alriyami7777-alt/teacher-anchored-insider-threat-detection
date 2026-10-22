"""Frozen EDITOR-024 identities. No architecture search. No new training."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from editor006b_harness.safety import COMMON_13_FEATURES, EXPECTED_SCALER_SHA256, N_FEATURES, T_WINDOW
from editor012_rescue.constants import PRIMARY_SEEDS
from editor017_robustness.constants import FROZEN_CLEAN_PR_AUC, MODEL_SPECS

TASK_ID = "EDITOR-024"
TASK_NAME = "PROSPECTIVELY RESERVED CERT r6.1 FINAL CONFIRMATION"
EXPERIMENT_TYPE = "ONE-PASS FROZEN-MODEL CROSS-RELEASE CONFIRMATION"
TARGET_RELEASE = "CERT r6.1"
TARGET_STATUS = "PROSPECTIVELY_RESERVED_EMPIRICALLY_UNTOUCHED_WITH_DISCLOSED_PRIOR_EXISTENCE_KNOWLEDGE"
MODEL_TRAINING = "PROHIBITED"
MODEL_SELECTION = "PROHIBITED"
TARGET_ADAPTATION = "PROHIBITED"
RESULT_STATUS_AT_START = "UNSEEN"
DESIGNATED_FINAL_MODEL = "TA2"
CURRENT_PAPER_MODEL = "TA2"
PRIMARY_METRIC = "PR_AUC"
PRIMARY_VIEW = "COMPLETED_WINDOW"
SECONDARY_VIEW = "DEOVERLAP_OFFSET0"
LABEL_SEMANTICS = "COMPLETED_WINDOW"
LABEL_RULE = "R52_LABEL_RULE_EVENT_LEVEL_ANSWER_MATCH"
SEQUENCE_LENGTH = 20
STRIDE_PRIMARY = 1
FEATURE_DIM = 13
BATCH_SIZE = 1024

EDITOR023_RESULTS_COMMIT = "a480fa2413cf0b70c398081ca5f8f52470a665a3"
PROTOCOL_FREEZE_SUBJECT = "Freeze EDITOR-024 r6.1 final confirmation protocol"
RESULTS_COMMIT_SUBJECT = "Freeze EDITOR-024 r6.1 final confirmation results"
RESULTS_COMMIT_PLACEHOLDER = "PENDING_BY_DESIGN"

REVIEW_REL = Path("review/editor024_r61_final_confirmation")
OUTPUT_REL = Path("outputs/editor024_r61_final_confirmation")
EDITOR023_REVIEW_REL = Path("review/editor023_positive_architecture_value")
SCALER_JSON_REL = Path("review/editor006a_preinference_freeze/EDITOR006A_SCALER.json")
LABEL_CONTRACT_REL = Path("review/editor006a_preinference_freeze/EDITOR006A_R62_LABEL_CONTRACT.json")

RAW_R61_ROOT = Path(r"C:\PhD\06_Datasets\r6.1\r6.1")
ANSWER_BUNDLE_CANDIDATES = (
    Path(r"C:\PhD\06_Datasets\answers"),
    Path(r"C:\PhD\07_Projects\cert-r42-feasibility\answers\answers"),
)
SOURCE_TYPES = ("logon", "device", "file", "email", "http")
REQUIRED_HEADER_PREFIX = ("id", "date", "user")

STUDENT_MODELS = ("C2-OPT", "F10", "TA2", "L1")
TEACHER_MODEL = "T-OPT"
ROUTE_MODELS = ("F10", "TA2")
SEEDS = PRIMARY_SEEDS  # (42, 52, 62)
COMPARATOR_SET = STUDENT_MODELS

BOOTSTRAP_SEED = 42
BOOTSTRAP_RESAMPLES = 2000
BOOTSTRAP_SAMPLING_UNIT = "r6.1 user"

FEATURE_ORDER = tuple(COMMON_13_FEATURES)
FEATURE_ALIASES = {
    "has_logon": "has_logon_activity",
    "has_device": "has_device_activity",
    "has_file": "has_file_activity",
    "has_email": "has_email_activity",
    "has_http": "has_http_activity",
}

R61_UNTOUCHED_ELIGIBILITY = "PASS_WITH_DISCLOSED_PRIOR_EXISTENCE_KNOWLEDGE"
UNTOUCHEDNESS_FACTS = {
    "R61_PRIOR_TRAINING_USE": "NO",
    "R61_PRIOR_MODEL_SELECTION_USE": "NO",
    "R61_PRIOR_DIAGNOSTIC_SCORING": "NO",
    "R61_PRIOR_FEATURE_DISTRIBUTION_INSPECTION": "NO",
    "R61_PRIOR_LABEL_OR_PREVALENCE_INSPECTION": "NO",
    "R61_PRIOR_CALIBRATION_USE": "NO",
    "R61_PRIOR_THRESHOLD_SELECTION_USE": "NO",
    "R61_PRIOR_EXISTENCE_OR_FILENAME_KNOWLEDGE": "YES",
}

PREPROCESSING_PROVENANCE = {
    "parent_commit": EDITOR023_RESULTS_COMMIT,
    "event_parsing": {
        "file": "scripts/run_editor007b_r51_bundle.py",
        "functions": ["parse_cert_ts", "looks_like_event_id", "normalize_event_id", "scan_source"],
        "twin_file": "review/editor006c_r62_input_bundle/run_editor006c_r62_input_bundle.py",
    },
    "daily_aggregation": {
        "file": "scripts/run_editor007b_r51_bundle.py",
        "functions": ["scan_source", "main.13-feature construction"],
        "feature_order": list(FEATURE_ORDER),
    },
    "daily_grid_and_windows": {
        "file": "src/editor006b_harness/input_bundle.py",
        "functions": ["DenseDailyWindowProvider", "SequenceIdentifiers"],
        "sequence_length": SEQUENCE_LENGTH,
        "stride": STRIDE_PRIMARY,
    },
    "completed_window_labels": {
        "contract": "review/editor006a_preinference_freeze/EDITOR006A_R62_LABEL_CONTRACT.json",
        "rule": LABEL_RULE,
        "semantics": "y=1 iff any day in the T=20 window has an official answer-matched event",
        "implementation": "scripts/run_editor007b_r51_bundle.py completed_window_labels",
    },
    "deoverlap": {
        "file": "src/editor006b_harness/input_bundle.py",
        "rule": "start_day_index % T_WINDOW == 0",
        "flag": "deoverlap_offset0_flag",
        "implementation": "scripts/run_editor007b_r51_bundle.py deoverlap_offset0_mask",
    },
    "scaler": {
        "file": "review/editor006a_preinference_freeze/EDITOR006A_SCALER.json",
        "function": "src/editor006b_harness/input_bundle.py::apply_persisted_scaler",
        "sha256": EXPECTED_SCALER_SHA256,
        "source": "R52_TRAIN",
        "mode": "transform_only",
    },
}

COMPARATORS = {
    "C2-OPT": "teacher-initialised task-only control",
    "F10": "ensemble-guided ODST student with predictive teacher guidance ON and route anchoring OFF",
    "TA2": "final ensemble-guided, route-anchored ODST student",
    "L1": "matched attention-linear reference",
}

PRIMARY_CONTRASTS = {
    "TA2-C2-OPT": "complete final formulation versus teacher initialisation alone",
    "F10-C2-OPT": "ensemble predictive teacher-guidance contribution",
    "TA2-F10": "incremental route-anchor contribution",
    "TA2-L1": "final ODST formulation versus matched attention-linear reference",
}

H1 = {
    "name": "ta2_ranking_transfer",
    "statement": "The final TA2 model retains ranking signal on prospectively reserved CERT r6.1.",
    "statistic": "mean TA2 PR-AUC - r6.1 prevalence",
}

SHA256_MANIFEST_NAME = "EDITOR024_SHA256_MANIFEST.json"

assert SEQUENCE_LENGTH == T_WINDOW == 20
assert FEATURE_DIM == N_FEATURES == 13
assert STRIDE_PRIMARY == 1
assert SEEDS == (42, 52, 62)
assert STUDENT_MODELS == ("C2-OPT", "F10", "TA2", "L1")
assert DESIGNATED_FINAL_MODEL == "TA2"


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def editor023_review() -> Path:
    return repo_root() / EDITOR023_REVIEW_REL


def load_editor023_json(name: str) -> Any:
    path = editor023_review() / name
    return json.loads(path.read_text(encoding="utf-8"))


def student_checkpoint_records() -> list[dict[str, Any]]:
    packet = load_editor023_json("EDITOR023_CHECKPOINT_PARITY.json")
    return [row for row in packet["records"] if row["model"] in STUDENT_MODELS]


def teacher_checkpoint_records() -> list[dict[str, Any]]:
    packet = load_editor023_json("EDITOR023_CHECKPOINT_PARITY.json")
    return [row for row in packet["records"] if row["model"] == TEACHER_MODEL]


def frozen_thresholds() -> dict[str, dict[str, float]]:
    raw = load_editor023_json("EDITOR023_FROZEN_THRESHOLDS.json")
    out: dict[str, dict[str, float]] = {}
    for model in STUDENT_MODELS:
        out[model] = {str(seed): float(raw[model][str(seed)]) for seed in SEEDS}
    return out


def r52_validation_pr_auc() -> dict[str, dict[int, float]]:
    packet = load_editor023_json("EDITOR023_PROTOCOL.json")
    frozen = packet.get("frozen_clean_pr_auc_per_seed") or FROZEN_CLEAN_PR_AUC
    return {
        model: {int(seed): float(frozen[model][str(seed) if str(seed) in frozen[model] else seed]) for seed in SEEDS}
        for model in STUDENT_MODELS
    }


def model_checkpoint_spec(model: str, seed: int) -> dict[str, Any]:
    return MODEL_SPECS[model]["checkpoints"][seed]


__all__ = [
    "TASK_ID",
    "EDITOR023_RESULTS_COMMIT",
    "DESIGNATED_FINAL_MODEL",
    "STUDENT_MODELS",
    "SEEDS",
    "FEATURE_ORDER",
    "SEQUENCE_LENGTH",
    "STRIDE_PRIMARY",
]
