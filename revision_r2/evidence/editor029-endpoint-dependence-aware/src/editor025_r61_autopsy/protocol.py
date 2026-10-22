"""Write the EDITOR-025 protocol freeze artefacts. No new r6.1 diagnostic calculations."""

from __future__ import annotations

from typing import Any

from editor006b_harness.safety import EXPECTED_SCALER_SHA256

from .constants import (
    BINARY_FEATURES,
    BINARY_RATE_DIFF_MODERATE,
    BINARY_RATE_DIFF_SEVERE,
    C2_OPT_READER,
    COUNT_FEATURES,
    EDITOR024_RESULTS_COMMIT,
    EXPERIMENT_TYPE,
    F10_READER,
    FALSE_POSITIVE_COHORT_N,
    FEATURE_ORDER,
    HEAD_SURVIVAL_RATIO,
    L1_READER,
    MEAN_SHIFT_Z_MODERATE,
    MEAN_SHIFT_Z_SEVERE,
    MODEL_TRAINING,
    ODST_READER,
    OOS_RATE_MODERATE,
    OOS_RATE_SEVERE,
    PSI_LIMITED_MAX,
    PSI_SEVERE_MIN,
    R61_CAN_BE_USED_AS_FINAL_UNTOUCHED_CONFIRMATION_AFTER_EDITOR025,
    R61_CAN_BE_USED_FOR_EDITOR026_DEVELOPMENT,
    R61_COMPLETED_N,
    R61_COMPLETED_POSITIVES,
    R61_ELIGIBLE_AS_FUTURE_UNTOUCHED_TARGET,
    R61_FINAL_TA2_RANKING_TRANSFER,
    R61_MEAN_PR_AUC,
    R61_PREVALENCE,
    R61_ROLE_BEFORE,
    R61_ROLE_FROM_EDITOR025,
    REFERENCE_NEGATIVE_COHORT_N,
    REPRESENTATION_NEGATIVE_N,
    REPRESENTATION_NONPORTABILITY_HIGH,
    REPRESENTATION_NONPORTABILITY_LOW,
    RESULT_STATUS_AT_START,
    REVIEW_REL,
    SEEDS,
    STUDENT_MODELS,
    SUPPORT_CLIP_HIGH_QUANTILE,
    SUPPORT_CLIP_LEVELS,
    SUPPORT_CLIP_LOW_QUANTILE,
    SUPPORT_CLIP_VIEW_NAME,
    TA2_READER,
    TASK_ID,
    TASK_NAME,
    TOPK_FRACTIONS,
    TOPK_MULTIPLIERS,
    EDITOR024_RESULT_REMAINS_IMMUTABLE,
    F10_TEACHER_RELATIVE_ROUTE_MAE,
    TA2_TEACHER_RELATIVE_ROUTE_MAE,
)
from .io_util import write_json, write_text
from .safety import REVIEW_ROOT, utc_now
from .training_gate import assert_no_training


def protocol_payload() -> dict[str, Any]:
    assert_no_training()
    return {
        "task_id": TASK_ID,
        "task_name": TASK_NAME,
        "experiment_type": EXPERIMENT_TYPE,
        "model_training": MODEL_TRAINING,
        "model_parameter_update": "PROHIBITED",
        "result_status_at_start": RESULT_STATUS_AT_START,
        "EDITOR024_RESULTS_COMMIT": EDITOR024_RESULTS_COMMIT,
        "EDITOR024_RESULT_REMAINS_IMMUTABLE": EDITOR024_RESULT_REMAINS_IMMUTABLE,
        "R61_UNTOUCHED_STATUS_HISTORICAL_FOR_EDITOR024": "PRESERVED",
        "R61_ELIGIBLE_AS_FUTURE_UNTOUCHED_TARGET": R61_ELIGIBLE_AS_FUTURE_UNTOUCHED_TARGET,
        "R61_ROLE_BEFORE": R61_ROLE_BEFORE,
        "R61_ROLE_FROM_EDITOR025": R61_ROLE_FROM_EDITOR025,
        "R61_CAN_BE_USED_FOR_EDITOR026_DEVELOPMENT": R61_CAN_BE_USED_FOR_EDITOR026_DEVELOPMENT,
        "R61_CAN_BE_USED_AS_FINAL_UNTOUCHED_CONFIRMATION_AFTER_EDITOR025": (
            R61_CAN_BE_USED_AS_FINAL_UNTOUCHED_CONFIRMATION_AFTER_EDITOR025
        ),
        "internal_model_labels": {
            "C2-OPT": C2_OPT_READER,
            "F10": F10_READER,
            "TA2": TA2_READER,
            "L1": L1_READER,
            "ODST": ODST_READER,
            "F10_is_internal_factorial_identifier": True,
            "TA2_numeral_has_no_formal_expansion": True,
        },
        "models": list(STUDENT_MODELS),
        "seeds": list(SEEDS),
        "feature_order": list(FEATURE_ORDER),
        "count_features": list(COUNT_FEATURES),
        "binary_features": list(BINARY_FEATURES),
        "frozen_editor024_facts": {
            "R61_COMPLETED_N": R61_COMPLETED_N,
            "R61_COMPLETED_POSITIVES": R61_COMPLETED_POSITIVES,
            "R61_PREVALENCE": R61_PREVALENCE,
            "mean_pr_auc": R61_MEAN_PR_AUC,
            "F10_TEACHER_RELATIVE_ROUTE_MAE": F10_TEACHER_RELATIVE_ROUTE_MAE,
            "TA2_TEACHER_RELATIVE_ROUTE_MAE": TA2_TEACHER_RELATIVE_ROUTE_MAE,
            "R61_FINAL_TA2_RANKING_TRANSFER": R61_FINAL_TA2_RANKING_TRANSFER,
            "do_not_alter": True,
        },
        "reuse_first": {
            "editor024_bundle": "outputs/editor024_r61_final_confirmation/bundle/",
            "editor024_raw_predictions": "outputs/editor024_r61_final_confirmation/raw_predictions/",
            "raw_r61_logs": "stream only if label provenance cannot be resolved from answers and frozen bundle",
        },
        "phase_e_frozen_capture": {
            "topk_multipliers": list(TOPK_MULTIPLIERS),
            "topk_fractions": list(TOPK_FRACTIONS),
        },
        "phase_g": {
            "FALSE_POSITIVE_COHORT": FALSE_POSITIVE_COHORT_N,
            "REFERENCE_NEGATIVE_COHORT": REFERENCE_NEGATIVE_COHORT_N,
            "reference_selection": "lowest SHA256(sequence_id)",
        },
        "phase_h": {
            "negatives": REPRESENTATION_NEGATIVE_N,
            "negative_selection": "ascending SHA256(sequence_id)",
            "score_dependent_sampling": False,
            "head_swapping": "PROHIBITED",
        },
        "phase_i": {
            "view_name": SUPPORT_CLIP_VIEW_NAME,
            "low_quantile": SUPPORT_CLIP_LOW_QUANTILE,
            "high_quantile": SUPPORT_CLIP_HIGH_QUANTILE,
            "n_clip_levels": 1,
            "clip_levels": list(SUPPORT_CLIP_LEVELS),
            "bounds_source": "R52_TRAIN",
            "clip_before_frozen_r52_scaling": True,
            "binary_indicators_unchanged": True,
            "trainable_parameters": 0,
        },
        "psi": {
            "bins": "deciles determined only from r5.2 TRAIN",
            "conventional_limited_max": PSI_LIMITED_MAX,
            "conventional_severe_min": PSI_SEVERE_MIN,
        },
        "covariate_shift_conventional": {
            "MEAN_SHIFT_Z_MODERATE": MEAN_SHIFT_Z_MODERATE,
            "MEAN_SHIFT_Z_SEVERE": MEAN_SHIFT_Z_SEVERE,
            "OOS_RATE_MODERATE": OOS_RATE_MODERATE,
            "OOS_RATE_SEVERE": OOS_RATE_SEVERE,
            "BINARY_RATE_DIFF_MODERATE": BINARY_RATE_DIFF_MODERATE,
            "BINARY_RATE_DIFF_SEVERE": BINARY_RATE_DIFF_SEVERE,
            "PSI_LIMITED_MAX": PSI_LIMITED_MAX,
            "PSI_SEVERE_MIN": PSI_SEVERE_MIN,
            "post_hoc_threshold_search": False,
        },
        "representation_ruling": {
            "SUPPORTED_if_at_least_3_of_4_models_transfer_ratio_le": REPRESENTATION_NONPORTABILITY_LOW,
            "or_target_separation_reverses_sign": True,
            "NOT_SUPPORTED_if_at_least_3_of_4_models_transfer_ratio_gt": REPRESENTATION_NONPORTABILITY_HIGH,
            "and_directionally_positive": True,
            "otherwise": "MIXED",
        },
        "head_failure_ruling": {
            "SUPPORTED_only_if_representation_separation_gt": HEAD_SURVIVAL_RATIO,
            "of_r52_for_at_least_3_of_4_models_AND_output_ranking_collapses_near_prevalence": True,
        },
        "root_cause_priority": [
            "LABEL_PIPELINE_OR_GROUND_TRUTH",
            "MIXED_LABEL_AND_REPRESENTATION",
            "RELEASE_LEVEL_REPRESENTATION_SHIFT",
            "PREDICTION_HEAD_NONPORTABILITY",
            "MIXED_REPRESENTATION_AND_HEAD",
            "UNRESOLVED",
        ],
        "remedy_families": [
            "GROUND_TRUTH_AND_LABEL_PIPELINE_REPAIR",
            "USER_RELATIVE_RELEASE_INVARIANT_REPRESENTATION",
            "MULTI_RELEASE_REPRESENTATION_LEARNING",
            "HEAD_PORTABILITY_REDESIGN",
            "LABEL_REPAIR_THEN_REPRESENTATION_REDESIGN",
            "NO_REMEDY_YET_ROOT_CAUSE_UNRESOLVED",
        ],
        "prohibitions": {
            "TRAINING_EXECUTED": "NO",
            "MODEL_PARAMETERS_UPDATED": "NO",
            "R51_RERUN": "NO",
            "R62_RERUN": "NO",
            "TARGET_MEAN_ALIGNMENT": "NO",
            "TARGET_VARIANCE_ALIGNMENT": "NO",
            "QUANTILE_MAPPING": "NO",
            "CORAL": "NO",
            "DOMAIN_ADAPTATION": "NO",
            "TARGET_NORMALISATION": "NO",
            "TARGET_CALIBRATION": "NO",
            "ADDITIONAL_CLIPPING_LEVELS": "NO",
            "HEAD_SWAPPING": "NO",
            "EDITOR024_REWRITE": "NO",
        },
        "scaler_sha256": EXPECTED_SCALER_SHA256,
        "review_rel": str(REVIEW_REL),
        "written_at": utc_now(),
        "new_diagnostic_calculations_authorised": False,
    }


def protocol_markdown(payload: dict[str, Any]) -> str:
    labels = payload["internal_model_labels"]
    facts = payload["frozen_editor024_facts"]
    return f"""# EDITOR-025 protocol freeze

Frozen **before** any new EDITOR-025 diagnostic calculation.

## Identity

- TASK_ID = {TASK_ID}
- TASK_NAME = {TASK_NAME}
- EXPERIMENT_TYPE = {EXPERIMENT_TYPE}
- MODEL_TRAINING = {MODEL_TRAINING}
- MODEL_PARAMETER_UPDATE = PROHIBITED
- RESULT_STATUS_AT_START = {RESULT_STATUS_AT_START}
- EDITOR024_RESULTS_COMMIT = {EDITOR024_RESULTS_COMMIT}

This is a read-only diagnostic / root-cause autopsy. Do not train. Do not update model parameters.

## Internal model labels

Documented before use:

- C2-OPT = {labels["C2-OPT"]}
- F10 = {labels["F10"]} (internal factorial identifier)
- TA2 = {labels["TA2"]} (internal identifier only; numeral 2 has no formal expansion)
- L1 = {labels["L1"]}
- ODST = {labels["ODST"]}

## r6.1 role transition

EDITOR-024 remains immutable.

- Before EDITOR-025: R61_ROLE = {payload["R61_ROLE_BEFORE"]}
- EDITOR-024 established: R61_FINAL_TA2_RANKING_TRANSFER = {facts["R61_FINAL_TA2_RANKING_TRANSFER"]}
- From EDITOR-025 onward: R61_ROLE = {payload["R61_ROLE_FROM_EDITOR025"]}

Record:

- EDITOR024_RESULT_REMAINS_IMMUTABLE = {payload["EDITOR024_RESULT_REMAINS_IMMUTABLE"]}
- R61_UNTOUCHED_STATUS_HISTORICAL_FOR_EDITOR024 = {payload["R61_UNTOUCHED_STATUS_HISTORICAL_FOR_EDITOR024"]}
- R61_ELIGIBLE_AS_FUTURE_UNTOUCHED_TARGET = {payload["R61_ELIGIBLE_AS_FUTURE_UNTOUCHED_TARGET"]}
- R61_CAN_BE_USED_FOR_EDITOR026_DEVELOPMENT = {payload["R61_CAN_BE_USED_FOR_EDITOR026_DEVELOPMENT"]}
- R61_CAN_BE_USED_AS_FINAL_UNTOUCHED_CONFIRMATION_AFTER_EDITOR025 = {payload["R61_CAN_BE_USED_AS_FINAL_UNTOUCHED_CONFIRMATION_AFTER_EDITOR025"]}

Do not rewrite EDITOR-024. Do not select a replacement untouched confirmation target in EDITOR-025.

## Frozen EDITOR-024 facts (inputs)

- R61_COMPLETED_N = {facts["R61_COMPLETED_N"]}
- R61_COMPLETED_POSITIVES = {facts["R61_COMPLETED_POSITIVES"]}
- R61_PREVALENCE = {facts["R61_PREVALENCE"]}
- C2-OPT mean PR-AUC = {facts["mean_pr_auc"]["C2-OPT"]}
- F10 mean PR-AUC = {facts["mean_pr_auc"]["F10"]}
- TA2 mean PR-AUC = {facts["mean_pr_auc"]["TA2"]}
- L1 mean PR-AUC = {facts["mean_pr_auc"]["L1"]}
- F10_TEACHER_RELATIVE_ROUTE_MAE = {facts["F10_TEACHER_RELATIVE_ROUTE_MAE"]}
- TA2_TEACHER_RELATIVE_ROUTE_MAE = {facts["TA2_TEACHER_RELATIVE_ROUTE_MAE"]}

Do not alter these results. Route structural value remained supported.

## Reuse EDITOR-024 artefacts first

Do not automatically re-read the ~88 GB raw r6.1 logs.

Reuse `outputs/editor024_r61_final_confirmation/bundle/` and `raw_predictions/` plus the frozen EDITOR-024 review files.

Raw r6.1 event files may be streamed again **only if required to resolve label provenance that cannot be resolved from the answer files and frozen bundle**.

Historical comparators CERT r5.1 and CERT r6.2: frozen evidence only. Do not rerun models on r5.1 or r6.2.

r5.2 development/validation data may be used for read-only reference calculations and frozen-model forward inference.

## Primary questions

Q1. Are the r6.1 ground-truth labels complete and semantically compatible with the r5.2 label rule?
Q2. Is there severe release-level shift in the frozen 13-feature representation?
Q3. Do the frozen model scores saturate or shift globally on benign r6.1 windows?
Q4. Does positive/negative separation collapse already in the Bi-LSTM/attention representation, or mainly after the prediction head?
Q5. Is failure concentrated in specific malicious scenarios/users or broad across r6.1?
Q6. Does the r6.1 failure resemble the previously frozen r6.2 generation-shift phenotype?
Q7. Which single remedy family is best supported by the evidence?

## Phase A — ground-truth / label autopsy (highest priority)

Inventory `r6.1-1.csv` ... `r6.1-5.csv` and `insiders.csv` at all known local CERT answer locations.

Report exists/path/SHA256/scenario/row count/parsed answer-event count. Do not download or invent missing answer files.

Crosswalk every parsed answer record. Explain the 5-versus-9 user discrepancy from evidence.

If `r6.1-4.csv` is absent locally: R61_SCENARIO4_ANSWER_AVAILABLE = NO and R61_GROUND_TRUTH_COVERAGE_COMPLETE = NO unless authoritative local documentation establishes that no separate answer file should exist. Do not assume omission is intentional.

Diagnostic label view `SCENARIO_INSIDER_CONSISTENT` is constructed only if official `insiders.csv` plus answer records permit it unambiguously: an answer event contributes a positive event/day only when its actor/user matches the official insider assigned to that scenario. This does not overwrite EDITOR-024. If fields are ambiguous: SCENARIO_INSIDER_CONSISTENT = UNRESOLVED. Do not invent labels.

If the diagnostic view is valid, rescore already frozen C2/F10/TA2/L1 raw predictions under it. No new model inference is required for that rescore.

## Phase B — 13-feature release-shift autopsy

Compare r6.1 with r5.2 using the exact frozen 13-feature representation, separately for all user-days and active user-days only.

MEAN_SHIFT_Z is the difference of means in frozen r5.2 TRAIN scaler units.

PSI_R61_VS_R52 uses decile bins determined **only from r5.2 TRAIN**.

Out-of-support uses r5.2 TRAIN 0.5th and 99.5th percentiles.

Binary-feature rate shift is the absolute prevalence difference for {", ".join(BINARY_FEATURES)}.

## Phase C — frozen r5.1/r6.2 shift comparison

Do not rerun r5.1/r6.2. Use EDITOR007D_FEATURE_SHIFT.json and other frozen summaries.

Descriptive correlations of feature-shift vectors. No causal statement.

## Phase D — score-distribution failure

Logit and probability quantiles for positive and negative r6.1 windows, all models/seeds.

NEGATIVE_THRESHOLD_EXCEEDANCE is the fraction of negatives above the frozen r5.2 threshold.

Compare with frozen r5.2 validation score distributions (frozen val_logits where available; otherwise frozen-model r5.2 validation inference after this freeze). No training.

## Phase E — ranking-failure profile

Prospectively frozen capture thresholds:

- top N, 5N, 10N where N = number of positives
- top 0.1% and top 1% of all windows

Do not choose a more favourable top-k later.

## Phase F — user / scenario failure profile

Official insiders/scenarios and additional positive-labelled users.

If a scenario has no authoritative positive labels: NOT_EVALUABLE. Do not treat absence as model failure.

## Phase G — false-positive phenotype

FALSE_POSITIVE_COHORT = top {FALSE_POSITIVE_COHORT_N} highest-scoring negative completed windows (TA2 mean probability across seeds).

REFERENCE_NEGATIVE_COHORT = {REFERENCE_NEGATIVE_COHORT_N} negative windows selected deterministically by lowest SHA256(sequence_id).

Descriptive window mean / maximum / final-day feature comparison. Not causal.

## Phase H — representation versus head

Capture the existing attention-pooled representation directly before the final prediction head. Do not modify the model.

Diagnostic sample: all positive windows PLUS {REPRESENTATION_NEGATIVE_N} negative windows selected by ascending SHA256(sequence_id). Do not select negatives by model score. Same sampling rule for r5.2 and r6.1.

H1 cosine distance between representation means; relative Frobenius covariance difference.

H2 frozen r5.2 discriminant direction d = mean_pos_R52 - mean_neg_R52. No classifier fitting.

REPRESENTATION_TRANSFER_RATIO = R61 separation / R52 separation (sign preserved; R52 negative-projection SD in the denominator).

H3 attention entropy, maximum weight, temporal centre-of-mass.

Do **not** perform head swapping or untrained hybrids.

## Phase I — predeclared support-clipping diagnostic

Exactly one non-trained input counterfactual: {SUPPORT_CLIP_VIEW_NAME}.

Clip each continuous/count feature to the frozen r5.2 TRAIN {SUPPORT_CLIP_LOW_QUANTILE} / {SUPPORT_CLIP_HIGH_QUANTILE} quantiles **before** applying the already frozen r5.2 scaling. Binary indicators unchanged. Bounds use no r6.1 labels and no r6.1-derived thresholds.

No additional clipping level exists. This view is diagnostic only. Do not promote it as a model fix. No trainable parameters.

## Prohibited unplanned target adaptation

Do not introduce after results: target mean/variance alignment, quantile mapping, CORAL, domain adaptation, target normalisation, target calibration, or new clipping levels.

## Label-integrity ruling

R61_LABEL_INTEGRITY in:

- PASS
- PARTIAL_GROUND_TRUTH_COVERAGE
- SEMANTIC_MISMATCH
- PARTIAL_COVERAGE_AND_SEMANTIC_MISMATCH
- UNRESOLVED

PASS: all expected scenario answer evidence is present and answer-event user semantics are compatible with the frozen event-level label rule.

PARTIAL_GROUND_TRUTH_COVERAGE: at least one official scenario lacks authoritative answer-event coverage.

SEMANTIC_MISMATCH: the event-level answer rule systematically labels users other than the official scenario insider in a way that changes the intended insider-detection target. Do not declare this merely because another username appears; establish the semantic mismatch from authoritative fields.

## Representation ruling

REPRESENTATION_NONPORTABILITY = SUPPORTED if, for at least 3 of 4 frozen models, REPRESENTATION_TRANSFER_RATIO <= {REPRESENTATION_NONPORTABILITY_LOW} or the target separation reverses sign.

NOT_SUPPORTED if, for at least 3 of 4 models, ratio > {REPRESENTATION_NONPORTABILITY_HIGH} and remains directionally positive.

Otherwise MIXED.

## Head-failure ruling

HEAD_SPECIFIC_FAILURE = SUPPORTED only if representation separation remains > {HEAD_SURVIVAL_RATIO} of r5.2 for at least 3 of 4 models AND output ranking still collapses near prevalence.

Otherwise NOT_SUPPORTED or MIXED. Because all four existing heads failed, do not assume head failure beforehand.

## Release-shift ruling

R61_COVARIATE_SHIFT = SEVERE | MODERATE | LIMITED using the conventional descriptors frozen above (PSI, mean-shift, out-of-support, binary-rate) plus r6.1/r6.2 shift-vector similarity. Do not infer thresholds post hoc. Retain the raw measures.

## Root-cause hierarchy (Section 26)

Exactly one of:

- LABEL_PIPELINE_OR_GROUND_TRUTH
- RELEASE_LEVEL_REPRESENTATION_SHIFT
- PREDICTION_HEAD_NONPORTABILITY
- MIXED_LABEL_AND_REPRESENTATION
- MIXED_REPRESENTATION_AND_HEAD
- UNRESOLVED

Case 1: label integrity is SEMANTIC_MISMATCH or PARTIAL_GROUND_TRUTH_COVERAGE and the diagnostic authoritative-label rescore materially changes the collapse interpretation → LABEL_PIPELINE_OR_GROUND_TRUTH, or MIXED_LABEL_AND_REPRESENTATION if representation collapse also remains.

Case 2: labels pass/do not explain the collapse and REPRESENTATION_NONPORTABILITY = SUPPORTED → RELEASE_LEVEL_REPRESENTATION_SHIFT unless strong evidence also identifies head-specific failure.

Case 3: representation separation largely survives but output ranking collapses → PREDICTION_HEAD_NONPORTABILITY.

Case 4: otherwise UNRESOLVED.

Do not choose the cause based on which future remedy is easiest.

Material change of collapse interpretation: diagnostic-label ranking excess raises TA2 (or at least 3 of 4 models) from approximately prevalence-level ranking to ranking excess > prevalence (i.e. PR-AUC > 2 × prevalence).

## Next-remedy decision (Section 27)

Exactly one of:

- GROUND_TRUTH_AND_LABEL_PIPELINE_REPAIR
- USER_RELATIVE_RELEASE_INVARIANT_REPRESENTATION
- MULTI_RELEASE_REPRESENTATION_LEARNING
- HEAD_PORTABILITY_REDESIGN
- LABEL_REPAIR_THEN_REPRESENTATION_REDESIGN
- NO_REMEDY_YET_ROOT_CAUSE_UNRESOLVED

Ground-truth / label problem dominant → GROUND_TRUTH_AND_LABEL_PIPELINE_REPAIR. No model retraining until ground truth is authoritative.

If labels also fail and representation collapse remains → LABEL_REPAIR_THEN_REPRESENTATION_REDESIGN.

Representation shift dominant → USER_RELATIVE_RELEASE_INVARIANT_REPRESENTATION if absolute count/activity levels are the primary shifted quantities (preserve Bi-LSTM, temporal attention, ODST, teacher guidance, route anchoring; redesign input representation toward causal user-relative behavioural deviation).

Broad generation shift remains after that user-relative diagnosis → MULTI_RELEASE_REPRESENTATION_LEARNING.

Representation survives but output head fails → HEAD_PORTABILITY_REDESIGN. Do not automatically select a new tree architecture.

## Covariate-shift conventional mapping (frozen)

- LIMITED if max PSI < {PSI_LIMITED_MAX} and max |MEAN_SHIFT_Z| < {MEAN_SHIFT_Z_MODERATE} and max OOS rate < {OOS_RATE_MODERATE} and max binary rate |diff| < {BINARY_RATE_DIFF_MODERATE}
- SEVERE if max PSI >= {PSI_SEVERE_MIN} or max |MEAN_SHIFT_Z| >= {MEAN_SHIFT_Z_SEVERE} or max OOS rate >= {OOS_RATE_SEVERE} or max binary rate |diff| >= {BINARY_RATE_DIFF_SEVERE}
- otherwise MODERATE

## Finalisation order

1. all scientific outputs final
2. completed RUN_MANIFEST
3. RESULT_FREEZE
4. TERMINAL_BLOCK
5. hash all stable target files
6. SHA256_MANIFEST written LAST (does not hash itself)

EDITOR025_RESULTS_COMMIT = PENDING_BY_DESIGN inside frozen files.

Do not start EDITOR-026 automatically. Do not train a new model. Do not modify EDITOR-024.
"""


def freeze_protocol() -> dict[str, Any]:
    REVIEW_ROOT.mkdir(parents=True, exist_ok=True)
    payload = protocol_payload()
    write_json(REVIEW_ROOT / "EDITOR025_PROTOCOL.json", payload)
    write_text(REVIEW_ROOT / "EDITOR025_PROTOCOL.md", protocol_markdown(payload))
    return payload
