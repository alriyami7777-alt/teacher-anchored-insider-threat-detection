"""CERT r5.2 teacher-anchored reproducibility — locked from r4.2 candidate."""

from __future__ import annotations

from pathlib import Path
from typing import Any

# Frozen r4.2 teacher-anchored procedure (do not retune).
MAX_EPOCHS = 15
PATIENCE = 4
BATCH_SIZE = 1024
POS_WEIGHT_MULT = 0.25
LR_ODST = 3e-4
LR_ENCODER = 3e-5
LR_ATTENTION = 3e-5
GRAD_CLIP_NORM = 1.0
LOGIT_CONSISTENCY_WEIGHT = 0.5
ROUTE_CONSISTENCY_WEIGHT = 0.5
ROUTE_EPS = 1e-6
LOGIT_VAR_EPS = 1e-6
PARITY_ATOL = 1e-5
PARITY_RTOL = 1e-5
PARITY_SUBSET_SIZE = 256
PARITY_SUBSET_SEED = 42
VIABILITY_PR_AUC_MARGIN = 0.020
VIABILITY_F1_MARGIN = 0.030
VIABILITY_COSINE_MIN = 0.980
VIABILITY_UNUSED_LEAVES_MAX_WORSE_PP = 10.0
IMPROVEMENT_PR_AUC_DELTA = 0.010
IMPROVEMENT_RECALL_TOLERANCE = 0.02

OUTPUT_REL = Path("outputs/objective2/r52_teacher_anchored_reproducibility_v1")
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

ARCHITECTURE: dict[str, Any] = {
    "input_dim": 13,
    "hidden_size": 64,
    "dropout": 0.2,
    "attention_dim": 64,
    "fusion_variant": "sparsemax_sigmoid_odst",
    "node_num_layers": 2,
    "node_n_trees": 8,
    "node_depth": 4,
    "node_tree_dim": 1,
    "node_temperature": 1.0,
    "node_dropout": 0.0,
    "leaf_init_std": 0.05,
    "gate_hidden_dim": 32,
}

# r5.2 frozen teachers (Stage-B locked ODST confirmation; validation-selected).
R52_TEACHERS: dict[int, dict[str, Any]] = {
    42: {
        "relative_dir": "outputs/objective2/r52_odst_confirmation/odst_seed42",
        "expected_sha256": "783d0913f85d492ddacec83a274ba2d4f13ad25eaf1a34ebcc64a960bda8ff86",
        "pr_auc": 0.9334002969575846,
        "f1": 0.9161849710982659,
        "precision": 0.9664634146341463,
        "recall": 0.8708791208791209,
        "threshold": 0.56,
        "fp": 22,
        "fn": 94,
        "best_epoch": 1,
        "unused_leaves_pct": 43.75,
        "routing_entropy_mean": 0.04346504807472229,
    },
    52: {
        "relative_dir": "outputs/objective2/r52_odst_confirmation/odst_seed52",
        "expected_sha256": "7273327495bbe463cfb3d50fa94c81c82de7b304370a816343046f559fc3d191",
        "pr_auc": 0.9244539797126647,
        "f1": 0.9059334298118669,
        "precision": 0.9571865443425076,
        "recall": 0.8598901098901099,
        "threshold": 0.8400000000000001,
        "fp": 28,
        "fn": 102,
        "best_epoch": 11,
        "unused_leaves_pct": 59.375,
        "routing_entropy_mean": 0.01220835279673338,
    },
    62: {
        "relative_dir": "outputs/objective2/r52_odst_confirmation/odst_seed62",
        "expected_sha256": "247d6e71353b49ea0a77a073a8606fbf35b88106faae7dae6ec53361621e9d92",
        "pr_auc": 0.9347250477760537,
        "f1": 0.9024561403508772,
        "precision": 0.9225251076040172,
        "recall": 0.8832417582417582,
        "threshold": 0.55,
        "fp": 54,
        "fn": 85,
        "best_epoch": 1,
        "unused_leaves_pct": 44.53125,
        "routing_entropy_mean": 0.02811765857040882,
    },
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
    "outputs/objective2/teacher_anchored_odst/",
    "outputs/objective2/teacher_anchored_final_audit/",
    "outputs/v3_node/",
    "outputs/paper/",
)

SEEDS_ORDER = (42, 52, 62)

CANDIDATE_TAG = "objective2-teacher-anchored-candidate-v1"
OBJ2_AUDIT_COMMIT = "b8272df572b50aa6d153f898a8a51e33366ef869"
TA_SOURCE_COMMIT = "965f1477e3eee920e6a6eef406ec24247429c5c7"
