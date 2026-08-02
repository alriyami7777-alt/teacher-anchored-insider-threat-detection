"""Locked constants for r5.2 calibration + operational alert-burden audit."""

from __future__ import annotations

from pathlib import Path
from typing import Any

OUTPUT_REL = Path("outputs/objective2/r52_calibration_alert_burden_v1")
RECORDED_REL = Path(
    "scripts/objective2_r52_calibration_alert_burden/recorded_results"
)

BASE_COMMIT = "c0b5589"
BRANCH = "objective2-r52-calibration-alert-burden"

EVIDENCE_TA = Path("read_only_evidence/r52_teacher_anchored_reproducibility_v1")
EVIDENCE_AL = Path("read_only_evidence/r52_odst_confirmation")
EVIDENCE_SI = Path("read_only_evidence/r52_same_information_baselines_v1")
EVIDENCE_LS_META = Path("read_only_evidence/r52_low_and_slow_metadata_audit_v1")

VAL_REL = Path("data/processed/r5.2/tensors/r52_T20_s1_validation.npz")
EXPECTED_VAL_SHA256 = "5ac2e7e8fbd50eb62638cdb8c9d444464e02ff2ea20ba55989c36926dd751a5c"
N_VALIDATION = 64000

SEEDS = (42, 52, 62)
N_FOLDS = 5
N_BOOTSTRAP_TARGET = 2000
N_BOOTSTRAP_MAX_ATTEMPTS = 5000
BOOTSTRAP_SEED = 2026
CLEAN_ATOL = 5e-4
# OOF fold-specific calibrators can stitch cross-fold reordering when T≪1.
# Within-fold ranking is asserted exactly; global PR-AUC may move slightly
# (ODST compressed logits observed |ΔPR-AUC| up to ≈0.0104 under temperature OOF).
RANK_ATOL = 1.5e-2
# Soft guidance for global OOF Spearman; below this is recorded as a study limit.
RANK_SPEARMAN_MIN = 0.90
N_ECE_BINS = 10
LOGIT_CLIP = 1e-7
BUDGETS = (0.0005, 0.001, 0.0025, 0.005, 0.01)

MODEL_ODST = "teacher_anchored_odst"
MODEL_AL = "attention_linear"
MODEL_XGB = "xgboost"
MODELS_PRIMARY = (MODEL_ODST, MODEL_AL)

METHOD_UNCAL = "uncalibrated"
METHOD_TEMP = "temperature"
METHOD_PLATT = "platt"

TEACHER_ANCHORED: dict[int, dict[str, Any]] = {
    42: {
        "pred_rel": "seed42/validation_predictions.csv",
        "summary_rel": "seed42/seed_summary.json",
        "ckpt_rel": "seed42/best_student.pt",
        "expected_sha256": "2b6452698dd0da53f0229bc43040a877017ac9299b277f2f98c1d7ca64c1cc42",
        "threshold": 0.56,
        "expected_pr_auc": 0.9335775615746195,
        "expected_f1": 0.9200863930885529,
    },
    52: {
        "pred_rel": "seed52/validation_predictions.csv",
        "summary_rel": "seed52/seed_summary.json",
        "ckpt_rel": "seed52/best_student.pt",
        "expected_sha256": "9c9d035fe81f54898dee4ecf4d2ecaf8423a21ecc3551793dc16d1980af1eb0d",
        "threshold": 0.85,
        "expected_pr_auc": 0.9246065839750892,
        "expected_f1": 0.9075144508670521,
    },
    62: {
        "pred_rel": "seed62/validation_predictions.csv",
        "summary_rel": "seed62/seed_summary.json",
        "ckpt_rel": "seed62/best_student.pt",
        "expected_sha256": "f5e8eb5260113a0aeabfb95ef198e1aa80022a26dfe91f3bf9262acbf5453ec9",
        "threshold": 0.55,
        "expected_pr_auc": 0.9356969431665507,
        "expected_f1": 0.9015471167369902,
    },
}

ATTENTION_LINEAR: dict[int, dict[str, Any]] = {
    42: {
        "dir_rel": "attention_linear_seed42",
        "threshold": 0.95,
        "expected_sha256": "b807a82343b432343b7e3cbc86ee76cba7011066827f3baa089aa78a02c02b53",
    },
    52: {
        "dir_rel": "attention_linear_seed52",
        "threshold": 0.96,
        "expected_sha256": "5e5e2a136bedba3d3477d05c5b1215331cb97339b74003bcb60f8cb4885ba86c",
    },
    62: {
        "dir_rel": "attention_linear_seed62",
        "threshold": 0.94,
        "expected_sha256": "4543c167fdab3b0376087731571f7b3bcecadd43f8ff05c6b5371f0073ba425a",
    },
}

XGBOOST: dict[int, dict[str, Any]] = {
    42: {"dir_rel": "xgboost_seed42", "threshold": 0.58},
    52: {"dir_rel": "xgboost_seed52", "threshold": 0.59},
    62: {"dir_rel": "xgboost_seed62", "threshold": 0.50},
}

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
    "outputs/objective2/r52_matched_temporal_learning_v1/",
    "outputs/objective2/r52_same_information_bootstrap_audit_v1/",
    "outputs/objective2/r52_low_and_slow_metadata_audit_v1/",
    "outputs/objective2/r52_low_and_slow_subset_evaluation_v1/",
    "outputs/objective2/r52_odst_vs_attention_linear_value_audit_v1/",
    "outputs/paper/",
    "read_only_evidence/",
)

STATUS_COMPLETE = "objective2_r52_calibration_alert_burden_complete"
STATUS_COMPLETE_LIMITS = "objective2_r52_calibration_alert_burden_complete_with_limits"
STATUS_NOT_IMPROVED = "objective2_r52_calibration_not_improved_alert_burden_complete"
STATUS_PROVENANCE = "objective2_r52_calibration_alert_burden_blocked_provenance"
STATUS_METADATA = "objective2_r52_calibration_alert_burden_blocked_metadata"
STATUS_INCOMPLETE = "objective2_r52_calibration_alert_burden_incomplete"
STATUS_SAFETY = "objective2_r52_calibration_alert_burden_stopped_safety_failure"

CLASS_IMPROVED_CONSISTENT = "calibration_improved_consistently"
CLASS_IMPROVED_SEED_VAR = "calibration_improved_with_seed_variation"
CLASS_SLOPE_INTERCEPT = "calibration_slope_improved_but_intercept_remains"
CLASS_NOT_IMPROVED = "calibration_not_improved"
CLASS_UNVERIFIABLE = "calibration_unverifiable"

PREFERRED_FRAMING = (
    "The grouped calibration and alert-burden audit separated probability quality "
    "from ranking performance and quantified how overlapping sequence alerts "
    "translated into distinct users and consolidated alert episodes."
)

INCIDENT_CANDIDATE_PATHS = (
    Path("read_only_evidence/r52_low_and_slow_metadata_audit_v1/low_and_slow_positive_sequence_metadata.csv"),
    Path(
        "scripts/objective2_r52_low_and_slow_metadata_audit/recorded_results/"
        "low_and_slow_positive_sequence_metadata.csv"
    ),
)
