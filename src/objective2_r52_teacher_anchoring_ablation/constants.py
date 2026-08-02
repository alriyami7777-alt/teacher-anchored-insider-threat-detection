"""Locked protocol shared with r5.2 teacher-anchored C5; ablation configs only vary init/λ."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from objective2_r52_teacher_anchored_reproducibility.constants import (  # noqa: F401
    ARCHITECTURE,
    BATCH_SIZE,
    EXPECTED_TRAIN_POS,
    EXPECTED_VAL_POS,
    GRAD_CLIP_NORM,
    LR_ATTENTION,
    LR_ENCODER,
    LR_ODST,
    MAX_EPOCHS,
    PARITY_SUBSET_SEED,
    PARITY_SUBSET_SIZE,
    PATIENCE,
    POS_WEIGHT_MULT,
    R52_TEACHERS,
    SEEDS_ORDER,
)

OUTPUT_REL = Path("outputs/objective2/r52_teacher_anchoring_ablation_v1")

# C5 predictive artefacts (no retrospective seed removal).
C5_RECORDED_SEED_SUMMARY = Path(
    "scripts/objective2_r52_teacher_anchored_reproducibility/recorded_results/"
    "r52_teacher_anchored_seed_summary.csv"
)

# Primary matrix: C1–C4, C6 must be trained; C5 reused from recorded reproducibility table.
# Sensitivity rows are optional and were pre-specified (not chosen post-hoc).
ABLATION_CONFIGS: dict[str, dict[str, Any]] = {
    "C1": {
        "init": "random",
        "lambda_logit": 0.0,
        "lambda_route": 0.0,
        "purpose": "Plain end-to-end baseline",
        "role": "primary",
        "train": True,
    },
    "C2": {
        "init": "teacher",
        "lambda_logit": 0.0,
        "lambda_route": 0.0,
        "purpose": "Isolates teacher initialisation",
        "role": "primary",
        "train": True,
    },
    "C3": {
        "init": "teacher",
        "lambda_logit": 0.5,
        "lambda_route": 0.0,
        "purpose": "Logit anchoring only",
        "role": "primary",
        "train": True,
    },
    "C4": {
        "init": "teacher",
        "lambda_logit": 0.0,
        "lambda_route": 0.5,
        "purpose": "Route anchoring only",
        "role": "primary",
        "train": True,
    },
    "C5": {
        "init": "teacher",
        "lambda_logit": 0.5,
        "lambda_route": 0.5,
        "purpose": "Proposed (= final students)",
        "role": "primary",
        "train": False,  # reuse recorded C5; optional retrain via --train-c5
    },
    "C6": {
        "init": "random",
        "lambda_logit": 0.5,
        "lambda_route": 0.5,
        "purpose": "Anchoring without teacher init",
        "role": "primary",
        "train": True,
    },
    # Pre-specified sensitivity only (not for selection).
    "C5_lam025": {
        "init": "teacher",
        "lambda_logit": 0.25,
        "lambda_route": 0.25,
        "purpose": "C5 sensitivity λ=0.25 (pre-specified; not chosen post-hoc)",
        "role": "sensitivity",
        "train": True,
        "parent": "C5",
    },
    "C5_lam075": {
        "init": "teacher",
        "lambda_logit": 0.75,
        "lambda_route": 0.75,
        "purpose": "C5 sensitivity λ=0.75 (pre-specified; not chosen post-hoc)",
        "role": "sensitivity",
        "train": True,
        "parent": "C5",
    },
}

PRIMARY_TRAIN_IDS = ("C1", "C2", "C3", "C4", "C6")
PRIMARY_ALL_IDS = ("C1", "C2", "C3", "C4", "C5", "C6")
SENSITIVITY_IDS = ("C5_lam025", "C5_lam075")

METRIC_COLUMNS = (
    "pr_auc",
    "f1",
    "delta_pr_auc",
    "delta_f1",
    "val_logit_consistency",
    "val_route_consistency",
    "route_mae",
    "hard_route_agreement",
    "dominant_leaf_agreement",
    "unused_leaves_pct",
    "unused_leaves_pct_all_layers",
    "tree_contrib_spearman",
    "tree_contrib_top3_jaccard",
    "tree_contrib_top5_jaccard",
    "tree_contrib_top10_jaccard",
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
    "outputs/objective2/r52_odst_confirmation/",
    "outputs/objective2/r52_locked_baselines/",
    "outputs/objective2/teacher_anchored_odst/",
    "outputs/objective2/teacher_anchored_final_audit/",
    "outputs/objective2/r52_teacher_anchored_reproducibility_v1/",
    "outputs/v3_node/",
    "outputs/paper/",
)
