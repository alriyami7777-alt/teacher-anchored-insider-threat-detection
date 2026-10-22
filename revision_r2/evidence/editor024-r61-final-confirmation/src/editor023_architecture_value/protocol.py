"""EDITOR-023 protocol freeze. Written before any new-severity result is viewed."""

from __future__ import annotations

from typing import Any

from editor012_rescue.constants import (
    EXPECTED_TRAIN_SHA256,
    EXPECTED_USER_MAPPING_SHA256,
    EXPECTED_VAL_SHA256,
    PRIMARY_SEEDS,
)
from editor012_rescue.safety import TRAIN_NPZ, VAL_NPZ
from editor017_robustness.constants import FROZEN_CLEAN_PR_AUC, MODEL_SPECS
from editor017_robustness.models import producing_pins, recover_frozen_thresholds
from editor017_robustness.perturbations import perturbation_module_hashes, protocol_lock
from editor020_robustness.constants import EXPECTED_GAUSSIAN_SHA256, EXPECTED_SOURCE_ABLATION_SHA256

from .constants import (
    ALLOWED_LANGUAGE,
    ARCHITECTURE,
    AURC_NOISE_DEFINITION,
    AURC_SOURCE_DEFINITION,
    CLAIM_BOUNDARIES_FORBIDDEN,
    COMPARATORS,
    EDITOR017_REVIEW_REL,
    EDITOR022_RESULTS_COMMIT,
    EXPLANATION_PARITY_TOLERANCE,
    EXPECTED_SCALER_JSON_SHA256,
    FORBIDDEN_THREAT_TERMS,
    HISTORICAL_OFFICIAL_CLEAN_MEAN,
    HISTORICAL_TA2_VS_C2_CLEAN,
    HYPOTHESES,
    NOISE_LEVELS,
    NOISE_LEVELS_HISTORICAL,
    NOISE_LEVELS_NEW,
    PARITY_TOLERANCE,
    PRIMARY_CONTRASTS,
    PRIMARY_MODELS,
    REVIEW_REL,
    ROUTE_PARITY_TOLERANCE,
    SCALER_JSON,
    SOURCE_CHANNELS,
    SOURCE_DEGRADATION_LEVELS,
    SOURCE_DEGRADATION_NEW,
    TASK_ID,
    TASK_NAME,
    TRAINING_FORMULATION,
)
from .io_util import write_json
from .safety import REPO_ROOT, REVIEW_ROOT, utc_now


def protocol_markdown() -> str:
    return f"""# EDITOR-023 protocol freeze

Frozen before any new-severity result is viewed.

## Identity

- TASK_ID = {TASK_ID}
- TASK_NAME = {TASK_NAME}
- EDITOR022_RESULTS_COMMIT = {EDITOR022_RESULTS_COMMIT}
- MODEL_TRAINING = PROHIBITED
- HYPERPARAMETER_TUNING = PROHIBITED
- ARCHITECTURE_SEARCH = PROHIBITED
- RESULT_STATUS_AT_START = UNSEEN_FOR_NEW_CONFIRMATORY_METRICS

This is not a robustness-training rescue. EDITOR-020, EDITOR-021 and EDITOR-022 remain frozen.
Do not train TA2-RP, TA2-SR, or any new model. TA2 itself is the object of evaluation.

## Architecture identity

```
{ARCHITECTURE}
```

Training formulation (historical; not re-run):

```
{TRAINING_FORMULATION}
```

No architectural component may be changed. No parameter may be updated. Teachers are not required at inference.

## Comparators (frozen checkpoints only)

- C2-OPT: {COMPARATORS['C2-OPT']}
- F10: {COMPARATORS['F10']}
- TA2: {COMPARATORS['TA2']}
- L1: {COMPARATORS['L1']}

No new baseline may be added after results are observed.

## Historical clean results (inputs, not new discoveries)

Official r5.2 validation means:

- C2-OPT = {HISTORICAL_OFFICIAL_CLEAN_MEAN['C2-OPT']}
- F10 = {HISTORICAL_OFFICIAL_CLEAN_MEAN['F10']}
- TA2 = {HISTORICAL_OFFICIAL_CLEAN_MEAN['TA2']}
- L1 = {HISTORICAL_OFFICIAL_CLEAN_MEAN['L1']}

Frozen TA2 versus C2 effect (historical input): mean PR-AUC gain approximately {HISTORICAL_TA2_VS_C2_CLEAN['mean_pr_auc_gain']}; primary seeds positive {HISTORICAL_TA2_VS_C2_CLEAN['primary_seeds_positive']}; user-cluster 95% CI {HISTORICAL_TA2_VS_C2_CLEAN['user_cluster_ci95']}; extended panel {HISTORICAL_TA2_VS_C2_CLEAN['extended_panel_positive']}; extended mean gain approximately {HISTORICAL_TA2_VS_C2_CLEAN['extended_mean_gain']}.

## Prospective hypotheses

- H1 teacher guidance predictive value: TA2 clean PR-AUC > C2-OPT clean PR-AUC. Historical status SUPPORTED_STRONG. EDITOR-023 verifies consistency.
- H2 teacher guidance source-degradation value: F10 has smaller aggregate source-channel PR-AUC degradation than C2-OPT. Historical point effect approximately +0.0229.
- H3 teacher guidance Gaussian-noise value: F10 retains more ranking performance under Gaussian input noise than C2-OPT. Historical point effect approximately +0.0092.
- H4 route-anchor structural value: TA2 remains closer than F10 to matched-teacher ODST routes under clean and degraded inputs. Do not require a large clean PR-AUC increment.
- H5 TA2 degraded-input value over matched linear reference: TA2 has better aggregate resilience than L1. Historical directional effects source approximately +0.0124, noise approximately +0.0098.
- H6 explanation stability: TA2 reference-centred signed tree-contribution rankings are more stable under degraded inputs than F10. Do not redefine faithfulness.

## Family A — graded source availability

Channels: {list(SOURCE_CHANNELS)}

Degradation levels: {list(SOURCE_DEGRADATION_LEVELS)}

New levels: {list(SOURCE_DEGRADATION_NEW)}

Implementation:

```
x_degraded = (1 - d) * x_clean + d * x_historical_ablation
```

d=1.00 exactly reproduces the EDITOR-017 complete ablation. Labels do not enter degradation construction. This is CONTROLLED_SOURCE_CHANNEL_ABLATION / data-quality degradation, not physical sensor failure and not adversarial removal.

## Family B — dense Gaussian-noise curve

Exact existing Gaussian-noise definition. Levels: {list(NOISE_LEVELS)}

Historical points that must reproduce EDITOR-017: {list(NOISE_LEVELS_HISTORICAL)}

New points: {list(NOISE_LEVELS_NEW)}

No noise level may be added after results are observed. No adversarial optimisation.

## Primary degradation-curve metric

Retention(severity) = PR_AUC(severity) / PR_AUC(clean)

SOURCE_AURC: {AURC_SOURCE_DEFINITION}

NOISE_AURC: {AURC_NOISE_DEFINITION}

Higher is better. Integration and normalisation must not change after viewing results.

## Primary comparisons

{list(PRIMARY_CONTRASTS)}

- F10 - C2 = ensemble teacher-guidance effect
- TA2 - C2 = complete repaired teacher-anchored formulation effect
- TA2 - F10 = incremental route-anchor effect
- TA2 - L1 = ODST-based model versus matched teacher-guided linear reference

Do not use TA2-vs-L1 to claim clean predictive superiority unless supported.

## Success criteria

Teacher guidance (strong degraded-input support): F10 > C2 on SOURCE_AURC AND/OR NOISE_AURC, with paired user-cluster 95% CI lower bound > 0 for at least one family and non-negative point direction for the other.

Complete TA2 formulation: TA2 > C2 for both SOURCE_AURC and NOISE_AURC point estimates, with at least one family CI excluding zero.

Route anchoring: TA2 teacher-relative route MAE < F10 under both clean and aggregate degraded conditions. Predictive TA2-vs-F10 superiority is NOT required.

ODST degraded-input value: TA2 > L1 on both SOURCE_AURC and NOISE_AURC point estimates and at least one family has paired user-cluster 95% CI lower bound > 0.

Do not require every component to win every metric.

## Failure-profile analysis (descriptive)

For every model: worst source, second-worst source, severity at which retention first falls below 0.90, severity at which retention first falls below 0.75. Do not create thresholds if the curve never crosses them.

## Route-stability curves

F10 and TA2 only, established route identity: teacher-relative route MAE, teacher-relative route KL, hard-route agreement, dominant-leaf agreement. Primary comparison TA2 - F10. Favourable: lower MAE/KL, higher agreement. Do not compare route identities across unrelated architectures.

## Explanation-stability curves

Established reference-centred signed tree-contribution vector for F10 and TA2. Rank-stability statistic is tree_contribution_spearman. Primary comparison TA2 versus F10. Do not introduce a new explanation definition. Do not claim global top-k faithfulness, route faithfulness, or leaf faithfulness.

## Calibration under degradation (secondary)

Brier score and log loss at each frozen model and degradation level. No recalibration, temperature fitting, or threshold fitting. Contrasts: TA2-C2, TA2-L1, F10-C2. Lower is better.

## Dependence-aware statistics

Sampling unit = validation user. 2000 valid replicates. Bootstrap seed = 42. Do not treat the three seeds as independent observations. Where a metric cannot validly be bootstrapped with the existing implementation, state that explicitly instead of substituting an IID-window bootstrap.

## Seed-level direction

For every primary comparison report number of primary seeds favourable / 3. Do not discard an unfavourable seed. No additional seed may be added after seeing the three-seed result. The historical extended 10-seed panel is existing evidence and must not be mixed numerically with the new three-seed degraded-input curve.

## Data safety

Authorised: r5.2 TRAIN metadata for existing scaler/reference definitions; r5.2 VALIDATION for frozen-model evaluation.

Prohibited: r5.2 TEST; r5.1 predictive rerun; r6.2 predictive rerun.

Required flags: R52_TEST_ACCESSED=NO; R52_TEST_PREDICTIONS_GENERATED=NO; R51_RERUN=NO; R62_RERUN=NO; MODEL_PARAMETERS_UPDATED=NO; THRESHOLD_RETUNED=NO; CALIBRATION_REFIT=NO.

## Parity gates (must pass before new severities)

1. Hash-gate every C2/F10/TA2/L1 checkpoint.
2. Reproduce historical clean PR-AUC (tolerance {PARITY_TOLERANCE}).
3. Reproduce EDITOR-017 full source-ablation (d=1.0).
4. Reproduce historical Gaussian-noise levels 0.05 / 0.10 / 0.20.
5. Reproduce established route metrics for F10/TA2 at historical conditions (tolerance {ROUTE_PARITY_TOLERANCE}).
6. Verify explanation-stability implementation against the existing frozen result (tolerance {EXPLANATION_PARITY_TOLERANCE}).

If any required parity check fails beyond established numerical tolerance: EDITOR023_PARITY_GATE = FAIL. STOP before evaluating new severities.

## Claim boundaries

Even with a positive result, do not claim: {list(CLAIM_BOUNDARIES_FORBIDDEN)}.

Appropriate language: {list(ALLOWED_LANGUAGE)}.

Forbidden threat terms: {list(FORBIDDEN_THREAT_TERMS)}.

## No outcome chasing

Do not remove unfavourable degradation levels, drop an unfavourable source, change curve weighting, change AURC definition, alter bootstrap rules, change comparison after seeing results, invent a composite after results, add new noise severities, or add new seeds. If a hypothesis fails, report it.

## Architecture-value ruling keys

- TEACHER_GUIDANCE_CLEAN_VALUE = SUPPORTED_STRONG | PRESERVED | CONTRADICTED
- TEACHER_GUIDANCE_DEGRADED_INPUT_VALUE = SUPPORTED_STRONG | SUPPORTED | CONSISTENT | NOT_SUPPORTED
- ROUTE_ANCHOR_STRUCTURAL_VALUE = SUPPORTED | NOT_SUPPORTED
- TA2_ODST_DEGRADED_INPUT_VALUE_OVER_LINEAR = SUPPORTED | CONSISTENT | NOT_SUPPORTED
- TA2_OVERALL_ARCHITECTURE_VALUE = SUPPORTED | SUPPORTED_WITH_QUALIFICATION | NOT_SUPPORTED

SUPPORTED does not require TA2 to beat every comparator on every metric.

CURRENT_PAPER_MODEL remains TA2.

## Finalisation order

1. final scientific files
2. completed RUN_MANIFEST
3. RESULT_FREEZE
4. TERMINAL_BLOCK
5. compute hashes
6. SHA256_MANIFEST written LAST

The SHA manifest must not hash itself.
"""


def freeze_protocol(*, y_val: Any | None = None) -> dict[str, Any]:
    review = REVIEW_ROOT
    review.mkdir(parents=True, exist_ok=True)
    hashes = perturbation_module_hashes(REPO_ROOT)
    if hashes["objective3_missing_source_robustness.py"] != EXPECTED_SOURCE_ABLATION_SHA256:
        raise RuntimeError("source-ablation implementation hash mismatch")
    if hashes["objective3_perturbations.py"] != EXPECTED_GAUSSIAN_SHA256:
        raise RuntimeError("Gaussian implementation hash mismatch")

    protocol = {
        "task_id": TASK_ID,
        "task_name": TASK_NAME,
        "EDITOR022_RESULTS_COMMIT": EDITOR022_RESULTS_COMMIT,
        "evaluation_mode": "frozen_checkpoint_only",
        "model_training": "PROHIBITED",
        "hyperparameter_tuning": "PROHIBITED",
        "architecture_search": "PROHIBITED",
        "result_status_at_start": "UNSEEN_FOR_NEW_CONFIRMATORY_METRICS",
        "architecture": ARCHITECTURE,
        "training_formulation": TRAINING_FORMULATION,
        "comparators": COMPARATORS,
        "models": list(PRIMARY_MODELS),
        "seeds": list(PRIMARY_SEEDS),
        "source_channels": list(SOURCE_CHANNELS),
        "source_degradation_levels": list(SOURCE_DEGRADATION_LEVELS),
        "source_interpolation": "x_degraded=(1-d)*x_clean+d*x_historical_ablation",
        "d1_equals_editor017_complete_ablation": True,
        "noise_levels": list(NOISE_LEVELS),
        "noise_levels_historical": list(NOISE_LEVELS_HISTORICAL),
        "noise_levels_new": list(NOISE_LEVELS_NEW),
        "aurc_source_definition": AURC_SOURCE_DEFINITION,
        "aurc_noise_definition": AURC_NOISE_DEFINITION,
        "primary_contrasts": list(PRIMARY_CONTRASTS),
        "hypotheses": HYPOTHESES,
        "historical_official_clean_mean": HISTORICAL_OFFICIAL_CLEAN_MEAN,
        "historical_ta2_vs_c2_clean": HISTORICAL_TA2_VS_C2_CLEAN,
        "frozen_clean_pr_auc_per_seed": {
            alias: {str(s): FROZEN_CLEAN_PR_AUC[alias][s] for s in PRIMARY_SEEDS} for alias in PRIMARY_MODELS
        },
        "bootstrap": {
            "n_resamples": 2000,
            "rng_seed": 42,
            "sampling_unit": "validation user",
            "mapping_sha256": EXPECTED_USER_MAPPING_SHA256,
            "three_seeds_are_not_independent_experimental_units": True,
        },
        "parity": {
            "clean_tolerance": PARITY_TOLERANCE,
            "route_tolerance": ROUTE_PARITY_TOLERANCE,
            "explanation_tolerance": EXPLANATION_PARITY_TOLERANCE,
            "editor017_review": str(EDITOR017_REVIEW_REL),
        },
        "perturbation_lock": protocol_lock(),
        "perturbation_module_hashes": hashes,
        "expected_source_sha256": EXPECTED_SOURCE_ABLATION_SHA256,
        "expected_gaussian_sha256": EXPECTED_GAUSSIAN_SHA256,
        "scaler_sha256": EXPECTED_SCALER_JSON_SHA256,
        "train_npz_sha256": EXPECTED_TRAIN_SHA256,
        "validation_npz_sha256": EXPECTED_VAL_SHA256,
        "producing_pins": producing_pins(),
        "partitions": {"train": "AUTHORISED", "validation": "AUTHORISED", "test": "HARD_DENY"},
        "r52_test_opened": False,
        "r51_rerun": False,
        "r62_rerun": False,
        "threshold_retuning": False,
        "calibration_refit": False,
        "parameter_update": False,
        "terminology_lock": {
            "allowed": list(ALLOWED_LANGUAGE),
            "forbidden": list(FORBIDDEN_THREAT_TERMS),
            "claim_boundaries_forbidden": list(CLAIM_BOUNDARIES_FORBIDDEN),
        },
        "current_paper_model": "TA2",
        "no_outcome_chasing": True,
        "written_at": utc_now(),
    }
    write_json(review / "EDITOR023_PROTOCOL.json", protocol)
    (review / "EDITOR023_PROTOCOL.md").write_text(protocol_markdown(), encoding="utf-8")

    checksums = {
        "train_npz": EXPECTED_TRAIN_SHA256,
        "validation_npz": EXPECTED_VAL_SHA256,
        "scaler_json": EXPECTED_SCALER_JSON_SHA256,
        "user_mapping": EXPECTED_USER_MAPPING_SHA256,
        "producing_pins": producing_pins(),
        "perturbation_modules": hashes,
        "checkpoints": {
            f"{alias}/{seed}": MODEL_SPECS[alias]["checkpoints"][seed]["sha256"]
            for alias in list(PRIMARY_MODELS) + ["T-OPT"]
            for seed in PRIMARY_SEEDS
        },
        "train_exists": TRAIN_NPZ.is_file(),
        "validation_exists": VAL_NPZ.is_file(),
        "scaler_exists": SCALER_JSON.is_file(),
    }
    write_json(review / "EDITOR023_INPUT_CHECKSUMS.json", checksums)

    thresholds = None
    if y_val is not None:
        thresholds = recover_frozen_thresholds(y_val)
        write_json(
            review / "EDITOR023_FROZEN_THRESHOLDS.json",
            {alias: {str(s): t for s, t in seeds.items()} for alias, seeds in thresholds.items()},
        )
    return {"protocol": protocol, "checksums": checksums, "thresholds": thresholds}
