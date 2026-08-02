"""Locked constants for matched temporal-learning comparison."""

from __future__ import annotations

from pathlib import Path
from typing import Any

OUTPUT_REL = Path("outputs/objective2/r52_matched_temporal_learning_v1")
SOURCE_SAME_INFO = Path("read_only_evidence/r52_same_information_baselines_v1")
SOURCE_TA = Path("read_only_evidence/r52_teacher_anchored_reproducibility_v1")
SOURCE_AL = Path("read_only_evidence/r52_odst_confirmation")
SOURCE_TEMPORAL = Path("read_only_evidence/temporal_value_analysis_v1")
SOURCE_BOOTSTRAP = Path("read_only_evidence/bootstrap_audit_v1")

VAL_REL = Path("data/processed/r5.2/tensors/r52_T20_s1_validation.npz")
TRAIN_REL = Path("data/processed/r5.2/tensors/r52_T20_s1_train.npz")
EXPECTED_VAL_SHA256 = "5ac2e7e8fbd50eb62638cdb8c9d444464e02ff2ea20ba55989c36926dd751a5c"
EXPECTED_TRAIN_SHA256 = "b268328d3bf2e98f712d1145958dabe175ce2c07a7c390da4b84a663317ebc2e"

SOURCE_SAME_INFO_COMMIT = "b1689a92711e475ddc632038470f36096f17ce9a"
SOURCE_BOOTSTRAP_COMMIT = "c1cf3f66c826f2f22ebc9807ca27776040d84f69"

SEEDS = (42, 52, 62)
SEQ_LEN = 20
N_FEATURES = 13
FLAT_DIM = 260
SHUFFLE_SEED = 2026
BATCH_SIZE = 1024
CLEAN_PR_AUC_ATOL = 5e-4
CLEAN_F1_ATOL = 5e-4
ORDER_PR_AUC_MARGIN = 0.005

N_BOOTSTRAP_TARGET = 2000
N_BOOTSTRAP_MAX_ATTEMPTS = 5000
BOOTSTRAP_SEED = 2026

CONDITIONS = ("T0", "T1", "T2", "T3", "T4", "T5", "T6")

SAFE_FEATURES = (
    "total_events",
    "logon_count",
    "device_count",
    "file_count",
    "email_count",
    "http_count",
    "active_duration_minutes",
    "has_logon_activity",
    "has_device_activity",
    "has_file_activity",
    "has_email_activity",
    "has_http_activity",
    "is_active_day",
)

TEACHER_ANCHORED: dict[int, dict[str, Any]] = {
    42: {
        "ckpt_rel": "seed42/best_student.pt",
        "summary_rel": "seed42/seed_summary.json",
        "expected_sha256": "2b6452698dd0da53f0229bc43040a877017ac9299b277f2f98c1d7ca64c1cc42",
        "threshold": 0.56,
        "expected_pr_auc": 0.9335775615746195,
        "expected_f1": 0.9200863930885529,
    },
    52: {
        "ckpt_rel": "seed52/best_student.pt",
        "summary_rel": "seed52/seed_summary.json",
        "expected_sha256": "9c9d035fe81f54898dee4ecf4d2ecaf8423a21ecc3551793dc16d1980af1eb0d",
        "threshold": None,
        "expected_pr_auc": None,
        "expected_f1": None,
    },
    62: {
        "ckpt_rel": "seed62/best_student.pt",
        "summary_rel": "seed62/seed_summary.json",
        "expected_sha256": "f5e8eb5260113a0aeabfb95ef198e1aa80022a26dfe91f3bf9262acbf5453ec9",
        "threshold": 0.55,
        "expected_pr_auc": 0.9356969431665507,
        "expected_f1": 0.9015471167369902,
    },
}

ATTENTION_LINEAR: dict[int, dict[str, Any]] = {
    42: {
        "dir_rel": "attention_linear_seed42",
        "expected_sha256": "b807a82343b432343b7e3cbc86ee76cba7011066827f3baa089aa78a02c02b53",
    },
    52: {
        "dir_rel": "attention_linear_seed52",
        "expected_sha256": "5e5e2a136bedba3d3477d05c5b1215331cb97339b74003bcb60f8cb4885ba86c",
    },
    62: {
        "dir_rel": "attention_linear_seed62",
        "expected_sha256": "4543c167fdab3b0376087731571f7b3bcecadd43f8ff05c6b5371f0073ba425a",
    },
}

FLAT_MODELS = ("xgboost_flat260", "random_forest_flat260", "mlp_flat260")
SEQ_MODELS = ("teacher_anchored_odst_seq", "attention_linear_seq")
MAIN_MODELS = SEQ_MODELS + FLAT_MODELS

# Predeclared conclusion bands (locked before evaluation).
CHRONOLOGY_BANDS = {
    "margin_pr_auc": ORDER_PR_AUC_MARGIN,
    "supported_if": "max(delta_reverse, delta_shuffle) >= margin AND (ci_supports_positive OR reported_numerical_uncertain)",
}

PARTIAL_HISTORY_BANDS = {
    "strong_if_delta_1_to_20_pr_auc": 0.05,
    "moderate_if_delta_1_to_20_pr_auc": 0.02,
    "limited_if_delta_1_to_20_pr_auc": 0.005,
}

BETWEEN_MODEL_COMPARISONS = (
    ("teacher_anchored_odst_seq", "xgboost_flat260"),
    ("teacher_anchored_odst_seq", "random_forest_flat260"),
    ("teacher_anchored_odst_seq", "mlp_flat260"),
    ("teacher_anchored_odst_seq", "attention_linear_seq"),
    ("attention_linear_seq", "xgboost_flat260"),
)

FORBIDDEN_PATH_MARKERS = (
    "r52_T20_s1_test",
    "r5.2_test",
    "r52_test",
    "/test.npz",
    "r42_T20_s1_test",
    "later-development",
    "later_development",
    "r6.2",
    "r62",
    "processed/r6.2",
)

FORBIDDEN_WRITE_PREFIXES = (
    "outputs/objective3/",
    "outputs/objective2/r52_same_information_baselines_v1/",
    "outputs/objective2/r52_teacher_anchored_reproducibility_v1/",
    "outputs/objective2/temporal_value_analysis_v1/",
    "outputs/objective2/r52_same_information_bootstrap_audit_v1/",
    "outputs/paper/",
    "read_only_evidence/",
)

STATUS_COMPLETE = "objective2_matched_temporal_learning_complete"
STATUS_LIMITS = "objective2_matched_temporal_learning_complete_with_limits"
STATUS_PROVENANCE = "objective2_matched_temporal_blocked_model_provenance"
STATUS_PARTITION = "objective2_matched_temporal_blocked_partition_mismatch"
STATUS_FEATURE = "objective2_matched_temporal_blocked_feature_mismatch"
STATUS_CLEAN = "objective2_matched_temporal_blocked_clean_parity"
STATUS_INCOMPLETE = "objective2_matched_temporal_learning_incomplete"
STATUS_SAFETY = "objective2_matched_temporal_stopped_safety_failure"
