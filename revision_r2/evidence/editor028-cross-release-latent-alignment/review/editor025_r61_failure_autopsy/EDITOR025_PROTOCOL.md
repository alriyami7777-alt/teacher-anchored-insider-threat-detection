# EDITOR-025 protocol freeze

Frozen **before** any new EDITOR-025 diagnostic calculation.

## Identity

- TASK_ID = EDITOR-025
- TASK_NAME = CERT r6.1 CROSS-VERSION FAILURE AUTOPSY
- EXPERIMENT_TYPE = READ-ONLY DIAGNOSTIC / ROOT-CAUSE ANALYSIS
- MODEL_TRAINING = PROHIBITED
- MODEL_PARAMETER_UPDATE = PROHIBITED
- RESULT_STATUS_AT_START = NEW_DIAGNOSTICS_UNSEEN
- EDITOR024_RESULTS_COMMIT = 23794a721a2215957da02d513f7e0af473fde4e6

This is a read-only diagnostic / root-cause autopsy. Do not train. Do not update model parameters.

## Internal model labels

Documented before use:

- C2-OPT = teacher-initialised task-only control
- F10 = ensemble-guided ODST student without route anchoring (internal factorial identifier)
- TA2 = final ensemble-guided, route-anchored ODST student (internal identifier only; numeral 2 has no formal expansion)
- L1 = matched attention-linear reference
- ODST = Oblivious Differentiable Sparsemax Tree

## r6.1 role transition

EDITOR-024 remains immutable.

- Before EDITOR-025: R61_ROLE = PROSPECTIVELY_RESERVED_FINAL_CONFIRMATION_TARGET
- EDITOR-024 established: R61_FINAL_TA2_RANKING_TRANSFER = NOT_SUPPORTED
- From EDITOR-025 onward: R61_ROLE = DIAGNOSTIC_DEVELOPMENT_RELEASE

Record:

- EDITOR024_RESULT_REMAINS_IMMUTABLE = YES
- R61_UNTOUCHED_STATUS_HISTORICAL_FOR_EDITOR024 = PRESERVED
- R61_ELIGIBLE_AS_FUTURE_UNTOUCHED_TARGET = NO
- R61_CAN_BE_USED_FOR_EDITOR026_DEVELOPMENT = YES
- R61_CAN_BE_USED_AS_FINAL_UNTOUCHED_CONFIRMATION_AFTER_EDITOR025 = NO

Do not rewrite EDITOR-024. Do not select a replacement untouched confirmation target in EDITOR-025.

## Frozen EDITOR-024 facts (inputs)

- R61_COMPLETED_N = 1988000
- R61_COMPLETED_POSITIVES = 190
- R61_PREVALENCE = 9.557344064386318e-05
- C2-OPT mean PR-AUC = 9.58548433287757e-05
- F10 mean PR-AUC = 9.391288112518778e-05
- TA2 mean PR-AUC = 9.445740146879832e-05
- L1 mean PR-AUC = 9.99715314772706e-05
- F10_TEACHER_RELATIVE_ROUTE_MAE = 0.013852491027299319
- TA2_TEACHER_RELATIVE_ROUTE_MAE = 0.009477296424532945

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

Binary-feature rate shift is the absolute prevalence difference for has_logon_activity, has_device_activity, has_file_activity, has_email_activity, has_http_activity, is_active_day.

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

FALSE_POSITIVE_COHORT = top 10000 highest-scoring negative completed windows (TA2 mean probability across seeds).

REFERENCE_NEGATIVE_COHORT = 10000 negative windows selected deterministically by lowest SHA256(sequence_id).

Descriptive window mean / maximum / final-day feature comparison. Not causal.

## Phase H — representation versus head

Capture the existing attention-pooled representation directly before the final prediction head. Do not modify the model.

Diagnostic sample: all positive windows PLUS 20000 negative windows selected by ascending SHA256(sequence_id). Do not select negatives by model score. Same sampling rule for r5.2 and r6.1.

H1 cosine distance between representation means; relative Frobenius covariance difference.

H2 frozen r5.2 discriminant direction d = mean_pos_R52 - mean_neg_R52. No classifier fitting.

REPRESENTATION_TRANSFER_RATIO = R61 separation / R52 separation (sign preserved; R52 negative-projection SD in the denominator).

H3 attention entropy, maximum weight, temporal centre-of-mass.

Do **not** perform head swapping or untrained hybrids.

## Phase I — predeclared support-clipping diagnostic

Exactly one non-trained input counterfactual: R52_SUPPORT_CLIP.

Clip each continuous/count feature to the frozen r5.2 TRAIN 0.005 / 0.995 quantiles **before** applying the already frozen r5.2 scaling. Binary indicators unchanged. Bounds use no r6.1 labels and no r6.1-derived thresholds.

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

REPRESENTATION_NONPORTABILITY = SUPPORTED if, for at least 3 of 4 frozen models, REPRESENTATION_TRANSFER_RATIO <= 0.25 or the target separation reverses sign.

NOT_SUPPORTED if, for at least 3 of 4 models, ratio > 0.5 and remains directionally positive.

Otherwise MIXED.

## Head-failure ruling

HEAD_SPECIFIC_FAILURE = SUPPORTED only if representation separation remains > 0.5 of r5.2 for at least 3 of 4 models AND output ranking still collapses near prevalence.

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

- LIMITED if max PSI < 0.1 and max |MEAN_SHIFT_Z| < 0.25 and max OOS rate < 0.01 and max binary rate |diff| < 0.05
- SEVERE if max PSI >= 0.25 or max |MEAN_SHIFT_Z| >= 0.5 or max OOS rate >= 0.05 or max binary rate |diff| >= 0.1
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
