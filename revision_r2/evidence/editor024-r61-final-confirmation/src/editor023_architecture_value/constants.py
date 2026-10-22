"""Frozen EDITOR-023 identities. No architecture search. No new training."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from editor012_rescue.constants import PRIMARY_SEEDS
from editor017_robustness.constants import (
    AUTHORITATIVE_GAUSSIAN,
    AUTHORITATIVE_SOURCE_ABLATION,
    BATCH_SIZE,
    CLEAN_METRIC_TOLERANCE,
    CONTROLLED_GAUSSIAN_INPUT_NOISE,
    CONTROLLED_SOURCE_CHANNEL_ABLATION,
    DATA_QUALITY_SENSITIVITY,
    DEGRADED_INPUT_RESILIENCE,
    EXPECTED_SCALER_JSON_SHA256,
    FORBIDDEN_THREAT_TERMS,
    FROZEN_CLEAN_PR_AUC,
    MODEL_SPECS,
    NOISE_PERTURBATION_SEED,
    NOISE_SCENARIO,
    ODST_MODELS,
    PRIMARY_MODELS,
    SCALER_ID,
    SCALER_JSON,
    SOURCE_CHANNELS,
    SOURCE_CONDITIONS,
    TEACHER_RELATIVE_MODELS,
)
from editor020_robustness.constants import (
    EXPECTED_GAUSSIAN_SHA256,
    EXPECTED_SOURCE_ABLATION_SHA256,
)

TASK_ID = "EDITOR-023"
TASK_NAME = "POSITIVE ARCHITECTURE-VALUE CONFIRMATION"
EXPERIMENT_TYPE = "FROZEN-MODEL COMPARATIVE CONFIRMATION AND CONTROLLED DEGRADED-INPUT EVALUATION"
PRIMARY_METRIC = "PR_AUC"
REVIEW_REL = Path("review/editor023_positive_architecture_value")
OUTPUT_REL = Path("outputs/editor023_positive_architecture_value")

EDITOR022_RESULTS_COMMIT = "ac50596ed8c3b480c887640911092e46b4631670"
EDITOR017_REVIEW_REL = Path("review/editor017_explanation_robustness")

BOOTSTRAP_SEED = 42
BOOTSTRAP_RESAMPLES = 2000
PARITY_TOLERANCE = CLEAN_METRIC_TOLERANCE  # 5e-4 for clean PR-AUC vs frozen values
DEGRADED_PARITY_TOLERANCE = 5e-3  # historical degraded reproduction; collapsed rankings are GPU-sensitive
ROUTE_PARITY_TOLERANCE = 5e-4
EXPLANATION_PARITY_TOLERANCE = 5e-3

# Graded source-availability curve. d=1.00 is the EDITOR-017 complete-ablation endpoint.
SOURCE_DEGRADATION_LEVELS = (0.00, 0.25, 0.50, 0.75, 1.00)
SOURCE_DEGRADATION_NEW = (0.25, 0.50, 0.75)
SOURCE_DEGRADATION_HISTORICAL_ENDPOINT = 1.00

# Dense Gaussian-noise curve. Historical EDITOR-017 points must reproduce.
NOISE_LEVELS = (0.00, 0.025, 0.05, 0.075, 0.10, 0.15, 0.20)
NOISE_LEVELS_HISTORICAL = (0.05, 0.10, 0.20)
NOISE_LEVELS_NEW = (0.025, 0.075, 0.15)
NOISE_SIGMA_MIN = 0.00
NOISE_SIGMA_MAX = 0.20

DIRECTIONAL_MODELS = ("F10", "TA2")
SCORING_MODELS = ("T-OPT", "C2-OPT", "F10", "TA2", "L1")

PRIMARY_CONTRASTS = ("F10-C2", "TA2-C2", "TA2-F10", "TA2-L1")

HISTORICAL_OFFICIAL_CLEAN_MEAN = {
    "C2-OPT": 0.9353238885,
    "F10": 0.9425948632,
    "TA2": 0.9428421883,
    "L1": 0.9388809580,
}

HISTORICAL_TA2_VS_C2_CLEAN = {
    "mean_pr_auc_gain": 0.007518,
    "primary_seeds_positive": "3/3",
    "user_cluster_ci95": [0.000345, 0.018250],
    "extended_panel_positive": "9/10",
    "extended_mean_gain": 0.006157,
    "status": "HISTORICAL_INPUT_NOT_A_NEW_EDITOR023_DISCOVERY",
}

HYPOTHESES = {
    "H1": {
        "name": "teacher_guidance_predictive_value",
        "statement": "TA2 clean PR-AUC > C2-OPT clean PR-AUC",
        "historical_status": "SUPPORTED_STRONG",
    },
    "H2": {
        "name": "teacher_guidance_source_degradation_value",
        "statement": "F10 has smaller aggregate source-channel PR-AUC degradation than C2-OPT",
        "historical_point_effect": 0.0229,
    },
    "H3": {
        "name": "teacher_guidance_gaussian_noise_value",
        "statement": "F10 retains more ranking performance under Gaussian input noise than C2-OPT",
        "historical_point_effect": 0.0092,
    },
    "H4": {
        "name": "route_anchor_structural_value",
        "statement": "TA2 remains closer than F10 to matched-teacher ODST routes under clean and degraded inputs",
        "note": "Do not require a large clean PR-AUC increment from route anchoring",
    },
    "H5": {
        "name": "ta2_degraded_input_value_over_matched_linear_reference",
        "statement": "TA2 has better aggregate resilience than L1 under controlled degraded input",
        "historical_source_effect": 0.0124,
        "historical_noise_effect": 0.0098,
    },
    "H6": {
        "name": "explanation_stability",
        "statement": (
            "TA2 reference-centred signed tree-contribution rankings are more stable "
            "under degraded inputs than F10"
        ),
        "explanation_definition": "reference-centred signed tree-contribution vector",
    },
}

CLAIM_BOUNDARIES_FORBIDDEN = (
    "adversarial robustness",
    "evasion resistance",
    "poisoning resistance",
    "physical sensor failure resistance",
    "unseen-user generalisation",
    "overall superiority to RF",
    "overall superiority to XGBoost",
    "clean ODST superiority over attention-linear",
    "route faithfulness",
    "leaf faithfulness",
    "global top-k faithfulness",
)

ALLOWED_LANGUAGE = (
    "controlled degraded-input resilience",
    "data-quality resilience",
    "teacher-guidance predictive value",
    "teacher-relative route stability",
    "explanation stability",
)

RETENTION_THRESHOLDS = (0.90, 0.75)

AURC_SOURCE_DEFINITION = (
    "trapezoidal_area_under_retention_versus_degradation_d_"
    "for_d_in_0.00_0.25_0.50_0.75_1.00_"
    "then_equal_mean_across_five_source_channels"
)
AURC_NOISE_DEFINITION = (
    "trapezoidal_area_under_retention_versus_sigma_"
    "for_sigma_in_0.00_0.025_0.05_0.075_0.10_0.15_0.20_"
    "divided_by_evaluated_sigma_interval_0.20"
)

ARCHITECTURE = "20-day x 13-feature input -> Bi-LSTM -> temporal attention -> attention-pooled representation -> ODST-046 -> binary logit"
TRAINING_FORMULATION = "task loss + 0.5 x equal-weight ensemble-teacher logit MSE + 0.5 x matched-teacher route consistency"

COMPARATORS = {
    "C2-OPT": "teacher initialisation without repaired teacher guidance",
    "F10": "same ODST architecture + ensemble teacher-logit guidance + route anchor OFF",
    "TA2": "same ODST architecture + ensemble teacher-logit guidance + route anchor ON",
    "L1": "matched Bi-LSTM + attention representation + ensemble teacher guidance + linear prediction head",
}

__all__ = [
    "TASK_ID",
    "EDITOR022_RESULTS_COMMIT",
    "SOURCE_DEGRADATION_LEVELS",
    "NOISE_LEVELS",
    "PRIMARY_MODELS",
    "PRIMARY_SEEDS",
    "MODEL_SPECS",
    "HYPOTHESES",
]
