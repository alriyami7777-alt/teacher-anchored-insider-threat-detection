"""Locked temporal-value / partial-history evaluation constants."""

from __future__ import annotations

from pathlib import Path
from typing import Any

OUTPUT_REL = Path("outputs/objective2/temporal_value_analysis_v1")
SHUFFLE_SEED = 2026
SEQ_LEN = 20
N_FEATURES = 13
BATCH_SIZE = 1024
CLEAN_PR_AUC_ATOL = 5e-4
CLEAN_F1_ATOL = 5e-4
T0_T6_PROB_ATOL = 1e-6
PARAM_HASH_MATCH_REQUIRED = True

# Chronology contribution: measurable if either reverse or shuffle drops PR-AUC by this margin.
ORDER_PR_AUC_DROP_MARGIN = 0.005

R52_VAL_REL = Path("data/processed/r5.2/tensors/r52_T20_s1_validation.npz")
R52_TRAIN_REL = Path("data/processed/r5.2/tensors/r52_T20_s1_train.npz")
R42_VAL_REL = Path("data/processed/tensors/r42_T20_s1_validation.npz")
R42_TRAIN_REL = Path("data/processed/tensors/r42_T20_s1_train.npz")

EXPECTED_R52_VAL_SHA256 = "5ac2e7e8fbd50eb62638cdb8c9d444464e02ff2ea20ba55989c36926dd751a5c"
EXPECTED_R52_TRAIN_SHA256 = "b268328d3bf2e98f712d1145958dabe175ce2c07a7c390da4b84a663317ebc2e"

R52_STUDENTS: dict[int, dict[str, Any]] = {
    42: {
        "relative_ckpt": "outputs/objective2/r52_teacher_anchored_reproducibility_v1/seed42/best_student.pt",
        "expected_sha256": "2b6452698dd0da53f0229bc43040a877017ac9299b277f2f98c1d7ca64c1cc42",
        "threshold": 0.56,
        "expected_pr_auc": 0.9335775615746195,
        "expected_f1": 0.9200863930885529,
        "expected_fp": 22.0,
        "expected_fn": 89.0,
        "role": "primary",
        "conditions": ("T0", "T1", "T2", "T3", "T4", "T5", "T6"),
    },
    62: {
        "relative_ckpt": "outputs/objective2/r52_teacher_anchored_reproducibility_v1/seed62/best_student.pt",
        "expected_sha256": "f5e8eb5260113a0aeabfb95ef198e1aa80022a26dfe91f3bf9262acbf5453ec9",
        "threshold": 0.55,
        "expected_pr_auc": 0.9356969431665507,
        "expected_f1": 0.9015471167369902,
        "expected_fp": 53.0,
        "expected_fn": 87.0,
        "role": "limited_confirmation",
        "conditions": ("T0", "T2", "T4", "T6"),
    },
}

R42_OPTIONAL: dict[str, Any] = {
    "seed": 42,
    "relative_ckpt": "outputs/objective2/teacher_anchored_odst/seed42/best_student.pt",
    "conditions": ("T0", "T2"),
    "role": "optional_cross_version_original_vs_shuffled",
}

FORBIDDEN_PATH_MARKERS = (
    "r52_T20_s1_test",
    "r5.2_test",
    "r52_test",
    "r42_T20_s1_test",
    "later-development",
    "later_development",
    "r6.2",
    "r62",
    "processed/r6.2",
)

CONDITION_DEFS: dict[str, dict[str, Any]] = {
    "T0": {"kind": "original", "history_days": 20},
    "T1": {"kind": "reverse", "history_days": 20},
    "T2": {"kind": "shuffle_fixed", "history_days": 20},
    "T3": {"kind": "partial_history", "history_days": 1},
    "T4": {"kind": "partial_history", "history_days": 5},
    "T5": {"kind": "partial_history", "history_days": 10},
    "T6": {"kind": "original", "history_days": 20},
}
