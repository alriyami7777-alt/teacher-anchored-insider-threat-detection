"""Locked constants for the same-information baseline comparison."""

from __future__ import annotations

from pathlib import Path
from typing import Any

OUTPUT_REL = Path("outputs/objective2/r52_same_information_baselines_v1")
SEEDS = (42, 52, 62)
SEQ_LEN = 20
N_FEATURES = 13
FLAT_DIM = SEQ_LEN * N_FEATURES  # 260

TENSOR_DIR_REL = Path("data/processed/r5.2/tensors")
TRAIN_NAME = "r52_T20_s1_train.npz"
VAL_NAME = "r52_T20_s1_validation.npz"
EXPECTED_TRAIN_SHA256 = "b268328d3bf2e98f712d1145958dabe175ce2c07a7c390da4b84a663317ebc2e"
EXPECTED_VAL_SHA256 = "5ac2e7e8fbd50eb62638cdb8c9d444464e02ff2ea20ba55989c36926dd751a5c"
EXPECTED_TRAIN_SHAPE = (788000, 20, 13)
EXPECTED_VAL_SHAPE = (64000, 20, 13)
EXPECTED_TRAIN_POS = 3957
EXPECTED_VAL_POS = 728

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

# Authoritative evidence (read-only junctions or absolute paths).
EVIDENCE_TA_REL = Path("read_only_evidence/r52_teacher_anchored_reproducibility_v1")
EVIDENCE_AL_REL = Path("read_only_evidence/r52_odst_confirmation")
EVIDENCE_LB_REL = Path("read_only_evidence/r52_locked_baselines")

# Locked teacher-anchored student checkpoints / expected validation metrics (r5.2).
TEACHER_ANCHORED: dict[int, dict[str, Any]] = {
    42: {
        "pred_rel": "seed42/validation_predictions.csv",
        "summary_rel": "seed42/seed_summary.json",
        "ckpt_rel": "seed42/best_student.pt",
        "expected_sha256": "2b6452698dd0da53f0229bc43040a877017ac9299b277f2f98c1d7ca64c1cc42",
        "pr_auc": 0.9335775615746195,
        "f1": 0.9200863930885529,
        "precision": 0.9667170953101362,
        "recall": 0.8777472527472527,
        "threshold": 0.56,
        "fp": 22.0,
        "fn": 89.0,
    },
    52: {
        "pred_rel": "seed52/validation_predictions.csv",
        "summary_rel": "seed52/seed_summary.json",
        "ckpt_rel": "seed52/best_student.pt",
        "expected_sha256": "9c9d035fe81f54898dee4ecf4d2ecaf8423a21ecc3551793dc16d1980af1eb0d",
        "pr_auc": 0.9246065839750892,
        "threshold": 0.85,
    },
    62: {
        "pred_rel": "seed62/validation_predictions.csv",
        "summary_rel": "seed62/seed_summary.json",
        "ckpt_rel": "seed62/best_student.pt",
        "expected_sha256": "f5e8eb5260113a0aeabfb95ef198e1aa80022a26dfe91f3bf9262acbf5453ec9",
        "pr_auc": 0.9356969431665507,
        "f1": 0.9015471167369902,
        "threshold": 0.55,
        "fp": 53.0,
        "fn": 87.0,
    },
}

ATTENTION_LINEAR: dict[int, dict[str, Any]] = {
    42: {
        "dir_rel": "attention_linear_seed42",
        "ckpt_sha256": "b807a82343b432343b7e3cbc86ee76cba7011066827f3baa089aa78a02c02b53",
    },
    52: {"dir_rel": "attention_linear_seed52"},
    62: {"dir_rel": "attention_linear_seed62"},
}

# Recovered locked RF / XGBoost hyperparameters (representation-independent params transfer).
XGBOOST_LOCKED = {
    "n_estimators": 300,
    "max_depth": 6,
    "learning_rate": 0.1,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "reg_lambda": 1.0,
    "objective": "binary:logistic",
    "eval_metric": "aucpr",
    "n_jobs": -1,
    "tree_method": "hist",
    "class_weight_mode": "scale_pos_weight = n_neg/n_pos on training labels only",
    "note": (
        "Hyperparameters recovered from r4.2/r5.2 locked conventional baseline protocol. "
        "colsample_bytree operates on the 260 flattened columns rather than 40 engineered features; "
        "no retuning performed."
    ),
}

RANDOM_FOREST_LOCKED = {
    "n_estimators": 200,
    "max_depth": 20,
    "min_samples_leaf": 2,
    "n_jobs": -1,
    "class_weight": "balanced_subsample",
    "note": (
        "Hyperparameters recovered from locked conventional baseline protocol. "
        "Tree structure params are representation-independent; feature subsampling "
        "implicitly acts over 260 columns instead of 40."
    ),
}

# Fixed logistic regression (declared before results; no solver/C search).
LOGISTIC_REGRESSION_LOCKED = {
    "model_class": "sklearn.linear_model.SGDClassifier",
    "loss": "log_loss",
    "penalty": "l2",
    "alpha": 0.0001,
    "max_iter": 30,
    "tol": 1e-3,
    "learning_rate": "optimal",
    "class_weight": "balanced",
    "preprocessing": "StandardScaler fit on r5.2 train only",
    "note": (
        "Fixed large-n logistic baseline via SGD with log loss (no C/solver search). "
        "Declared before results because batch lbfgs/saga was computationally impractical "
        "on 788k x 260 without changing the scientific protocol."
    ),
}

# Fixed shallow MLP (no approved prior MLP for 260-flat exists; declared before results).
MLP_LOCKED = {
    "architecture": "Flatten260 -> Linear(260,128) -> ReLU -> Dropout(0.2) -> Linear(128,64) -> ReLU -> Dropout(0.2) -> Linear(64,1)",
    "hidden_layers": [128, 64],
    "dropout": 0.2,
    "activation": "relu",
    "optimizer": "Adam",
    "learning_rate": 1e-3,
    "weight_decay": 0.0,
    "batch_size": 1024,
    "max_epochs": 15,
    "patience": 4,
    "grad_clip_norm": 1.0,
    "pos_weight_multiplier": 1.0,
    "loss": "BCEWithLogitsLoss(pos_weight=(n_neg/n_pos)*mult from train only)",
    "early_stopping_metric": "validation_pr_auc",
    "checkpoint_selection_metric": "validation_pr_auc",
    "preprocessing": "StandardScaler fit on r5.2 train only",
    "device_policy": "cuda if available else cpu; classical models remain on CPU",
    "note": "No prior approved flat-MLP configuration existed; this fixed shallow config was declared before any results.",
}

THRESHOLD_POLICY = {
    "criterion": "max_validation_f1",
    "candidates": "linspace(0.01,0.99,99) union quantile(p_val, linspace(0.01,0.99,50))",
    "primary_ranking_metric": "PR-AUC",
    "comparison_label": "r5.2 validation comparison",
    "not_independent_test": True,
}

BOOTSTRAP_POLICY = {
    "grouping": "user",
    "n_bootstrap": 1000,
    "seed": 42,
    "metrics": ["pr_auc", "f1"],
    "note": "Paired user-level bootstrap; sliding windows are not treated as independent observations.",
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
    "outputs/objective2/r52_odst_confirmation/",
    "outputs/objective2/r52_locked_baselines/",
    "outputs/objective2/r52_teacher_anchored_reproducibility_v1/",
    "outputs/objective2/teacher_anchored_odst/",
    "outputs/objective2/teacher_anchored_final_audit/",
    "outputs/objective2/temporal_value_analysis_v1/",
    "outputs/v3_node/",
    "outputs/paper/",
    "read_only_evidence/",
)

STATUS_GPU_BLOCKED = "objective2_same_information_prepared_gpu_blocked"
STATUS_COMPLETE = "objective2_same_information_comparison_complete"
STATUS_PARTITION_MISMATCH = "objective2_same_information_comparison_blocked_partition_mismatch"
STATUS_FEATURE_MISMATCH = "objective2_same_information_comparison_blocked_feature_mismatch"
STATUS_CONFIG_BLOCKED = "objective2_same_information_comparison_blocked_configuration"
STATUS_INCOMPLETE = "objective2_same_information_comparison_incomplete"
STATUS_SAFETY = "objective2_same_information_comparison_stopped_safety_failure"

CANDIDATE_TAG = "objective2-teacher-anchored-candidate-v1"
OBJ2_AUDIT_COMMIT = "b8272df572b50aa6d153f898a8a51e33366ef869"
R52_TA_PACKAGE_COMMIT = "f05a423"
R52_TA_STAMP_COMMIT = "5109e38"
TEMPORAL_COMMITS = ("948144a", "5739547")

PANEL_A_MODELS = (
    "logistic_regression_flat260",
    "mlp_flat260",
    "random_forest_flat260",
    "xgboost_flat260",
    "attention_linear_seq",
    "teacher_anchored_odst_seq",
)

PANEL_B_MODELS = (
    "engineered_random_forest_40",
    "engineered_xgboost_40",
    "teacher_anchored_odst_seq_context",
)
