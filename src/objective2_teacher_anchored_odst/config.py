"""Fixed teacher-anchored configuration recovered from frozen + T2 protocols."""

from __future__ import annotations

from typing import Any

# Sources (do not retune after inspecting results):
CONFIG_SOURCES = {
    "frozen_runner": "scripts/prototype_v3_node/run_validation.py",
    "t2_full_config": "scripts/objective2_end_to_end_full_confirmation/config.py",
    "prior_t2_failed": "outputs/objective2/end_to_end_full_confirmation/",
    "prior_residual_failed": "outputs/objective2/residual_odst_refinement/",
    "starting_commit": "9cd963f004670814dd5eb711f860c74349587e67",
}

MAX_EPOCHS = 15
PATIENCE = 4
BATCH_SIZE = 1024
POS_WEIGHT_MULT = 0.25
LR_ODST = 3e-4
LR_ENCODER = 3e-5
LR_ATTENTION = 3e-5
GRAD_CLIP_NORM = 1.0
THRESHOLD_RULE = "maximum_validation_f1"
CHECKPOINT_RULE = "maximum_validation_pr_auc"
EARLY_STOPPING_METRIC = "validation_pr_auc"
FUSION_VARIANT = "sparsemax_sigmoid_odst"
SHUFFLE_TRAIN = True

# Fixed consistency weights (do not change).
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

ARCHITECTURE: dict[str, Any] = {
    "input_dim": 13,
    "hidden_size": 64,
    "dropout": 0.2,
    "attention_dim": 64,
    "fusion_variant": FUSION_VARIANT,
    "node_num_layers": 2,
    "node_n_trees": 8,
    "node_depth": 4,
    "node_tree_dim": 1,
    "node_temperature": 1.0,
    "node_dropout": 0.0,
    "leaf_init_std": 0.05,
    "gate_hidden_dim": 32,
}

FROZEN_COMPARATORS: dict[int, dict[str, Any]] = {
    42: {
        "pr_auc": 0.8076217795784956,
        "f1": 0.8055555555555556,
        "precision": 0.8055555555555556,
        "recall": 0.8055555555555556,
        "threshold": 0.74,
        "fp": 49,
        "fn": 49,
        "best_epoch": 12,
        "unused_leaves_pct": 57.8125,
        "routing_entropy_mean": 0.0202913954854011,
        "relative_dir": (
            "outputs/v3_node/seed42_full_20260723_095912/"
            "seed42_full_20260723_095916/sparsemax_sigmoid_odst_seed42"
        ),
        "expected_sha256": "ff7ceb287df27689d3cd52bfee79e1aa617bbf1f72ba5f4769a3c4b7598d0167",
    },
    52: {
        "pr_auc": 0.8588553225257587,
        "f1": 0.8228346456692913,
        "precision": 0.81640625,
        "recall": 0.8293650793650794,
        "threshold": 0.59,
        "fp": 47,
        "fn": 43,
        "best_epoch": 3,
        "unused_leaves_pct": 57.8125,
        "routing_entropy_mean": 0.0337406769394874,
        "relative_dir": (
            "outputs/v3_node/seed52_full_20260723_101933/"
            "seed52_full_20260723_101936/sparsemax_sigmoid_odst_seed52"
        ),
        "expected_sha256": "8de6398b49a802b9676d564600614c84db679def6be2026761f2ed9c1502f182",
    },
    62: {
        "pr_auc": 0.8222442521683742,
        "f1": 0.752895752895753,
        "precision": 0.7330827067669173,
        "recall": 0.7738095238095238,
        "threshold": 0.53,
        "fp": 71,
        "fn": 57,
        "best_epoch": 1,
        "unused_leaves_pct": 40.625,
        "routing_entropy_mean": 0.04891268163919449,
        "relative_dir": (
            "outputs/v3_node/seed62_full_20260723_102938/"
            "seed62_full_20260723_102942/sparsemax_sigmoid_odst_seed62"
        ),
        "expected_sha256": "af898f4845817833d2d30a9f93f034f62e9273df2e523fe3f7720f33e3c051fa",
    },
}

# Prior seed-42 failed joint experiments (saved summaries only; do not rerun).
PRIOR_SEED42_COMPARATORS = {
    "t2_end_to_end": {
        "source": "outputs/objective2/end_to_end_full_confirmation/",
        "best_pr_auc": 0.790,
        "unused_leaves_pct": 85.9,
        "status": "objective2_end_to_end_seed42_failed_viability",
    },
    "residual_odst": {
        "source": "outputs/objective2/residual_odst_refinement/",
        "best_pr_auc": 0.8085050914425638,
        "best_epoch": 1,
        "unused_leaves_pct": 90.625,
        "status": "objective2_residual_odst_seed42_failed_viability",
    },
}

TEACHER_ANCHORED_CONFIG: dict[str, Any] = {
    "study": "teacher_anchored_odst",
    "output_namespace": "outputs/objective2/teacher_anchored_odst",
    "do_not_overwrite": [
        "outputs/objective2/end_to_end_refinement/",
        "outputs/objective2/end_to_end_full_confirmation/",
        "outputs/objective2/residual_odst_refinement/",
    ],
    "config_sources": CONFIG_SOURCES,
    "max_epochs": MAX_EPOCHS,
    "patience": PATIENCE,
    "batch_size": BATCH_SIZE,
    "pos_weight_mult": POS_WEIGHT_MULT,
    "lr_encoder": LR_ENCODER,
    "lr_attention": LR_ATTENTION,
    "lr_odst": LR_ODST,
    "grad_clip_norm": GRAD_CLIP_NORM,
    "logit_consistency_weight": LOGIT_CONSISTENCY_WEIGHT,
    "route_consistency_weight": ROUTE_CONSISTENCY_WEIGHT,
    "loss": "WBCE + 0.5*L_logit + 0.5*L_route",
    "all_student_components_trainable_from_epoch_1": True,
    "threshold_rule": THRESHOLD_RULE,
    "checkpoint_rule": CHECKPOINT_RULE,
    "early_stopping_metric": EARLY_STOPPING_METRIC,
    "architecture": ARCHITECTURE,
    "viability": {
        "pr_auc_margin": VIABILITY_PR_AUC_MARGIN,
        "f1_margin": VIABILITY_F1_MARGIN,
        "cosine_min": VIABILITY_COSINE_MIN,
        "unused_leaves_max_worse_pp": VIABILITY_UNUSED_LEAVES_MAX_WORSE_PP,
        "selected_checkpoint_must_be_joint": True,
    },
    "improvement": {
        "pr_auc_delta": IMPROVEMENT_PR_AUC_DELTA,
        "recall_tolerance": IMPROVEMENT_RECALL_TOLERANCE,
    },
    "frozen_comparators": FROZEN_COMPARATORS,
    "prior_seed42_comparators": PRIOR_SEED42_COMPARATORS,
}
