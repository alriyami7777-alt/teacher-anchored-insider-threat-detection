"""Frozen EDITOR-017 identities. No architecture search. No new training."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from editor012_rescue.constants import (
    BATCH_SIZE,
    C2OPT_CHECKPOINTS,
    ENCODER_ARCH,
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
    FEATURE_DIM,
    ODST046,
    PRIMARY_SEEDS,
    SAFE_FEATURES,
    SEQUENCE_LENGTH,
    TOPT_CHECKPOINTS,
)
from editor013_odst_value.constants import F10_CHECKPOINTS, F11_CHECKPOINTS, N_TREES_TOTAL
from editor014_temporal_odst.constants import L1_CHECKPOINTS
from editor015_residual.constants import DIRECTIONAL_KS

TASK_ID = "EDITOR-017"
PRIMARY_METRIC = "PR_AUC"
REVIEW_REL = Path("review/editor017_explanation_robustness")
OUTPUT_REL = Path("outputs/editor017_explanation_robustness")

EDITOR012_RESULTS_COMMIT = "4bcf522a502ed98e5dd393a80bd9da7fffd51964"
EDITOR013_RESULTS_COMMIT = "09c4bb97b143810147feef08f31a8d8d042a6726"
EDITOR014_RESULTS_COMMIT = "c3343462dc3b35d20907da6ad017f5f853852f84"
EDITOR015_RESULTS_COMMIT = "d8e1d04b8c199f56cab9956f62c16cd4301f0bac"
EDITOR016_RESULTS_COMMIT = "07b90867dc83ac42a4f3dce538ee7eca0cedb230"
BASE_COMMIT = EDITOR016_RESULTS_COMMIT

EDITOR011_WORKTREE = Path(r"C:\PhD\07_Projects\teacher-anchored-insider-threat-detection-editor011")
EDITOR012_WORKTREE = Path(r"C:\PhD\07_Projects\teacher-anchored-insider-threat-detection-editor012")
EDITOR013_WORKTREE = Path(r"C:\PhD\07_Projects\teacher-anchored-insider-threat-detection-editor013")
EDITOR015_WORKTREE = Path(r"C:\PhD\07_Projects\teacher-anchored-insider-threat-detection-editor015")
EDITOR016_WORKTREE = Path(r"C:\PhD\07_Projects\teacher-anchored-insider-threat-detection-editor016")
PAPER_ROBUSTNESS_WORKTREE = Path(r"C:\PhD\07_Projects\cert-r42-paper-explainability-robustness")
R52_PORTABILITY_WORKTREE = Path(r"C:\PhD\07_Projects\cert-r52-objective3-portability-confirmation")
FEASIBILITY_WORKTREE = Path(r"C:\PhD\07_Projects\cert-r42-feasibility")

BOOTSTRAP_SEED = 42
BOOTSTRAP_RESAMPLES = 2000
CLEAN_METRIC_TOLERANCE = 5e-4
N_TREES = N_TREES_TOTAL

# Frozen interpretation — overwrite only on genuine mechanical contradiction.
TEACHER_GUIDANCE_VS_INITIALISATION = "SUPPORTED_STRONG"
ROUTE_ANCHOR_INCREMENTAL_PREDICTIVE_EFFECT = "NOT_SUPPORTED"
ROUTE_FIDELITY_EFFECT = "SUPPORTED"
ODST_PREDICTIVE_SUPERIORITY_OVER_LINEAR = "NOT_SUPPORTED"
TA2_LOCAL_DIRECTIONAL_TREE_FAITHFULNESS = "SUPPORTED_FROM_EDITOR015"
TA2_GLOBAL_TOPK_PR_AUC_FAITHFULNESS = "NOT_SUPPORTED"
GLOBAL_TOPK_PR_AUC_FAITHFULNESS = "NOT_SUPPORTED"
ROUTE_TRACEABILITY = "SUPPORTED"
LEAF_TRACEABILITY = "SUPPORTED"

# Terminology lock.
CONTROLLED_SOURCE_CHANNEL_ABLATION = "CONTROLLED_SOURCE_CHANNEL_ABLATION"
CONTROLLED_GAUSSIAN_INPUT_NOISE = "CONTROLLED_GAUSSIAN_INPUT_NOISE"
DEGRADED_INPUT_RESILIENCE = "DEGRADED_INPUT_RESILIENCE"
DATA_QUALITY_SENSITIVITY = "DATA_QUALITY_SENSITIVITY"
FORBIDDEN_THREAT_TERMS = (
    "ADVERSARIAL_ROBUSTNESS",
    "EVASION_ROBUSTNESS",
    "POISONING_ROBUSTNESS",
    "PHYSICAL_SENSOR_FAILURE",
)

SOURCE_CHANNELS = ("logon", "device", "file", "email", "http")
SOURCE_CONDITIONS = tuple(f"without_{src}" for src in SOURCE_CHANNELS)
NOISE_LEVELS = (0.05, 0.10, 0.20)
NOISE_LEVELS_WITH_CLEAN = (0.00, 0.05, 0.10, 0.20)
NOISE_PERTURBATION_SEED = 101
NOISE_SCENARIO = "gaussian_noise_continuous"

# Frozen before any model result is viewed.
# OLS slope of PR-AUC on the ordered authorised severity sequence including clean.
NOISE_SLOPE_LEVELS = NOISE_LEVELS_WITH_CLEAN
NOISE_SLOPE_DEFINITION = (
    "ordinary_least_squares_slope_of_PR_AUC_on_noise_level_"
    "using_ordered_points_0.00_0.05_0.10_0.20"
)

SCALER_JSON = Path(__file__).resolve().parents[2] / "review" / "editor006a_preinference_freeze" / "EDITOR006A_SCALER.json"
EXPECTED_SCALER_JSON_SHA256 = "6a092df8275e15b6e05c685b306f48de72ab55fb1e88ede5ed5899ecd63f3488"
SCALER_ID = "r52_T20_s1_trainonly_standardscaler_v1"

AUTHORITATIVE_SOURCE_ABLATION = {
    "implementation_id": "objective3_missing_source_robustness.apply_missing_source_condition",
    "module": "src/objective3_missing_source_robustness.py",
    "function": "apply_missing_source_condition",
    "feature_treatment": "inverse_scale_raw_zero_then_forward_scale",
    "reference_value": "raw_0.0_maps_to_scaled_minus_mean_over_scale",
    "scaler": SCALER_ID,
    "total_events_recomputed": True,
    "is_active_day_recomputed": True,
    "active_duration_rule": "zero_if_day_inactive_else_retain_residual_multi_source_span",
    "labels_change": False,
    "intervention_class": CONTROLLED_SOURCE_CHANNEL_ABLATION,
    "not_physical_source_absence": True,
    "source_list": list(SOURCE_CHANNELS),
    "source_selection": "predeclared_five_channels_no_result_driven_choice",
}

AUTHORITATIVE_GAUSSIAN = {
    "implementation_id": "objective3_perturbations.gaussian_noise_continuous",
    "module": "src/objective3_perturbations.py",
    "function": "apply_paired_perturbation",
    "inner_function": "gaussian_noise_continuous",
    "distribution": "bounded_gaussian_elementwise",
    "scale_definition": "std_equals_level_times_max_abs_x_1e-3_clip_pm_level_times_scale_floor_at_0",
    "binary_features": "untouched_indices_7_to_12",
    "continuous_features": "indices_0_to_6_only",
    "levels": list(NOISE_LEVELS),
    "perturbation_seed": NOISE_PERTURBATION_SEED,
    "rng": "apply_paired_perturbation_sha256_derived_per_level",
    "labels_change": False,
    "total_events_recomputed": False,
    "active_duration_changed_by_rule": False,
    "validation_derived_parameter": False,
}

FROZEN_CLEAN_PR_AUC = {
    "C2-OPT": {42: 0.9443205892331505, 52: 0.9214711755922543, 62: 0.9401799007272055},
    "F10": {42: 0.9441007472746944, 52: 0.9361330144482553, 62: 0.9475508279790588},
    "TA2": {42: 0.9454098053584642, 52: 0.9337067425514769, 62: 0.9494100170861509},
    "L1": {42: 0.9368690603400606, 52: 0.9360656904165168, 62: 0.9437081231855656},
    "T-OPT": {42: 0.9423486577182849, 52: 0.9228451512846401, 62: 0.9405909178207581},
}

MODEL_SPECS: dict[str, dict[str, Any]] = {
    "C2-OPT": {
        "model_id": "M0",
        "alias": "C2-OPT",
        "family": "odst",
        "identity": "teacher_initialisation_only_task_loss_only",
        "teacher_guidance": False,
        "route_anchor": False,
        "checkpoints": C2OPT_CHECKPOINTS,
        "val_logits": {
            seed: EDITOR011_WORKTREE
            / f"outputs/editor011_matched_route_confirmation/C2-OPT/seed{seed}/val_logits.npy"
            for seed in PRIMARY_SEEDS
        },
    },
    "F10": {
        "model_id": "M1",
        "alias": "F10",
        "family": "odst",
        "identity": "ODST-046_equal_weight_teacher_ensemble_guidance_route_anchor_OFF",
        "teacher_guidance": True,
        "route_anchor": False,
        "checkpoints": F10_CHECKPOINTS,
        "val_logits": {seed: F10_CHECKPOINTS[seed]["val_logits"] for seed in PRIMARY_SEEDS},
    },
    "TA2": {
        "model_id": "M2",
        "alias": "TA2",
        "family": "odst",
        "identity": "ODST-046_equal_weight_teacher_ensemble_guidance_route_anchor_ON",
        "teacher_guidance": True,
        "route_anchor": True,
        "checkpoints": F11_CHECKPOINTS,
        "val_logits": {seed: F11_CHECKPOINTS[seed]["val_logits"] for seed in PRIMARY_SEEDS},
    },
    "L1": {
        "model_id": "M3",
        "alias": "L1",
        "family": "linear",
        "identity": "matched_teacher_guided_attention_linear",
        "teacher_guidance": True,
        "route_anchor": False,
        "checkpoints": L1_CHECKPOINTS,
        "val_logits": {seed: L1_CHECKPOINTS[seed]["val_logits"] for seed in PRIMARY_SEEDS},
    },
    "T-OPT": {
        "model_id": "T-OPT",
        "alias": "T-OPT",
        "family": "odst",
        "identity": "matched_teacher_TOPT",
        "teacher_guidance": False,
        "route_anchor": False,
        "checkpoints": TOPT_CHECKPOINTS,
        "val_logits": {
            seed: EDITOR011_WORKTREE
            / f"outputs/editor011_matched_route_confirmation/T-OPT/seed{seed}/val_logits.npy"
            for seed in PRIMARY_SEEDS
        },
    },
}

PRIMARY_MODELS = ("C2-OPT", "F10", "TA2", "L1")
ODST_MODELS = ("C2-OPT", "F10", "TA2")
DIRECTIONAL_MODELS = ("F10", "TA2")
TEACHER_RELATIVE_MODELS = ("F10", "TA2")

__all__ = [
    "TASK_ID",
    "PRIMARY_SEEDS",
    "SOURCE_CHANNELS",
    "SOURCE_CONDITIONS",
    "NOISE_LEVELS",
    "NOISE_PERTURBATION_SEED",
    "AUTHORITATIVE_SOURCE_ABLATION",
    "AUTHORITATIVE_GAUSSIAN",
    "MODEL_SPECS",
    "PRIMARY_MODELS",
    "TEACHER_GUIDANCE_VS_INITIALISATION",
    "GLOBAL_TOPK_PR_AUC_FAITHFULNESS",
]
