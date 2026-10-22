# EDITOR-024 protocol freeze

Frozen **before** any CERT r6.1 file content is read.

## Identity

- TASK_ID = EDITOR-024
- TASK_NAME = PROSPECTIVELY RESERVED CERT r6.1 FINAL CONFIRMATION
- EXPERIMENT_TYPE = ONE-PASS FROZEN-MODEL CROSS-RELEASE CONFIRMATION
- TARGET_RELEASE = CERT r6.1
- TARGET_STATUS = PROSPECTIVELY_RESERVED_EMPIRICALLY_UNTOUCHED_WITH_DISCLOSED_PRIOR_EXISTENCE_KNOWLEDGE
- EDITOR023_RESULTS_COMMIT = a480fa2413cf0b70c398081ca5f8f52470a665a3
- MODEL_TRAINING = PROHIBITED
- MODEL_SELECTION = PROHIBITED
- TARGET_ADAPTATION = PROHIBITED
- RESULT_STATUS_AT_START = UNSEEN
- CURRENT_PAPER_MODEL = TA2

This task supersedes the previously proposed r5.1/r6.2 EDITOR-024 protocol, which was never started.
Do not evaluate r5.1 or r6.2 in EDITOR-024.

## Untouchedness

R61_UNTOUCHED_ELIGIBILITY = PASS_WITH_DISCLOSED_PRIOR_EXISTENCE_KNOWLEDGE

Prior knowledge was limited to CERT r6.1 existence, directory/file names, file sizes/timestamps,
answer-bundle filenames, and planned or forbidden code references. No empirical content was examined.

- R61_PRIOR_TRAINING_USE = NO
- R61_PRIOR_MODEL_SELECTION_USE = NO
- R61_PRIOR_DIAGNOSTIC_SCORING = NO
- R61_PRIOR_FEATURE_DISTRIBUTION_INSPECTION = NO
- R61_PRIOR_LABEL_OR_PREVALENCE_INSPECTION = NO
- R61_PRIOR_CALIBRATION_USE = NO
- R61_PRIOR_THRESHOLD_SELECTION_USE = NO
- R61_PRIOR_EXISTENCE_OR_FILENAME_KNOWLEDGE = YES

## Role of CERT r6.1

From this freeze onward, CERT r6.1 is the FINAL_PROSPECTIVELY_RESERVED_CONFIRMATION_TARGET.
It must not become training, validation, hyperparameter-selection, threshold-selection,
calibration, feature-selection, or debugging-by-outcome data.

Scientific hierarchy:

- CERT r5.2 = development, optimisation and validation
- CERT r5.1 = previously observed cross-version diagnostic evidence
- CERT r6.2 = previously observed severe generation-shift stress evidence
- CERT r6.1 = prospectively reserved final confirmation target

Do not use r5.1 or r6.2 results to alter EDITOR-024 after freeze.

## Designated final model

TA2 remains the designated final paper model (final ensemble-guided, route-anchored student)
regardless of r6.1 PR-AUC or comparisons with C2-OPT, F10, or L1.

Internal identifiers (not reader-facing architecture names):

- C2-OPT = teacher-initialised task-only control
- F10 = ensemble-guided ODST student with predictive teacher guidance ON and route anchoring OFF
- TA2 = final ensemble-guided, route-anchored ODST student
- L1 = matched attention-linear reference
- ODST = Oblivious Differentiable Sparsemax Tree

## Frozen model set

Evaluate exactly: C2-OPT, F10, TA2, L1
Seeds exactly: 42, 52, 62

Do not retrain. Do not replace an unfavourable checkpoint. Do not add RF/XGBoost or another model after seeing results.

### Student checkpoints (from EDITOR023_CHECKPOINT_PARITY.json)

- C2-OPT seed 42: `C:\PhD\07_Projects\teacher-anchored-insider-threat-detection-editor011\outputs\editor011_matched_route_confirmation\C2-OPT\seed42\best_student.pt` SHA256 `d64651d25e48b3bcd4cad7d107d3bc55a4c555a2827f3656a087624e94ac4baf`
- C2-OPT seed 52: `C:\PhD\07_Projects\teacher-anchored-insider-threat-detection-editor011\outputs\editor011_matched_route_confirmation\C2-OPT\seed52\best_student.pt` SHA256 `f0eea90099ba7dd3e721efb930e367e868049c94f6542d5b2156d9fe469acb7e`
- C2-OPT seed 62: `C:\PhD\07_Projects\teacher-anchored-insider-threat-detection-editor011\outputs\editor011_matched_route_confirmation\C2-OPT\seed62\best_student.pt` SHA256 `50512aa5392ee7f4d93dc5f84471fc1074baeb757ae9fb5b96caed141ee586da`
- F10 seed 42: `C:\PhD\07_Projects\teacher-anchored-insider-threat-detection-editor012\outputs\editor012_teacher_anchor_rescue\F10_DOPT\seed42\best_student.pt` SHA256 `ea8cd41a1ae3f845719956fd7a49230fa82807ffac87841be5f5ab95c64ac0c2`
- F10 seed 52: `C:\PhD\07_Projects\teacher-anchored-insider-threat-detection-editor012\outputs\editor012_teacher_anchor_rescue\F10_DOPT\seed52\best_student.pt` SHA256 `829135230c5629f0b11161e11d76eba7a15e65bf9d03b5a55ffa297a93ddf959`
- F10 seed 62: `C:\PhD\07_Projects\teacher-anchored-insider-threat-detection-editor012\outputs\editor012_teacher_anchor_rescue\F10_DOPT\seed62\best_student.pt` SHA256 `06313d6f2602de51f8dd6e15e1d1292864fd8cbd158f33977fa42c8a47036aee`
- TA2 seed 42: `C:\PhD\07_Projects\teacher-anchored-insider-threat-detection-editor012\outputs\editor012_teacher_anchor_rescue\F11_DROPT\seed42\best_student.pt` SHA256 `54f6c097af9568a4ee5701ef375559a2f649cec6c1817e578d3e8e01e6d73df8`
- TA2 seed 52: `C:\PhD\07_Projects\teacher-anchored-insider-threat-detection-editor012\outputs\editor012_teacher_anchor_rescue\F11_DROPT\seed52\best_student.pt` SHA256 `7613ba559bcf55827d04129066eb595b677994494609646f8b2463308ed5edb4`
- TA2 seed 62: `C:\PhD\07_Projects\teacher-anchored-insider-threat-detection-editor012\outputs\editor012_teacher_anchor_rescue\F11_DROPT\seed62\best_student.pt` SHA256 `904003dca219435464476cf36abedb11ee4e2f7a11ff09caa3791d685b8f644d`
- L1 seed 42: `C:\PhD\07_Projects\teacher-anchored-insider-threat-detection-editor013\outputs\editor013_odst_value_proof\L1\seed42\best.pt` SHA256 `513e272063250aa209efa2c42b490cc44316c7979fa6b2be5dd8cce4592d1ab2`
- L1 seed 52: `C:\PhD\07_Projects\teacher-anchored-insider-threat-detection-editor013\outputs\editor013_odst_value_proof\L1\seed52\best.pt` SHA256 `a503f6705955da221bdbd1921034e9102b90db6acb5187114276ccaeb474e1c4`
- L1 seed 62: `C:\PhD\07_Projects\teacher-anchored-insider-threat-detection-editor013\outputs\editor013_odst_value_proof\L1\seed62\best.pt` SHA256 `60d5c43692a17ba6971c8d23f74048ac3c4fe0bd1b18889eeb21bbab7bf3d3e9`

## Frozen preprocessing

Do not design an r6.1-specific representation.

- 13 daily behavioural features in frozen order: total_events, logon_count, device_count, file_count, email_count, http_count, active_duration_minutes, has_logon_activity, has_device_activity, has_file_activity, has_email_activity, has_http_activity, is_active_day
- sequence length = 20
- primary stride = 1
- primary view = COMPLETED_WINDOW
- secondary view = DEOVERLAP_OFFSET0 (start_day_index % 20 == 0)
- label rule = R52_LABEL_RULE_EVENT_LEVEL_ANSWER_MATCH / COMPLETED_WINDOW

Do not add psychometric, LDAP, decoy-file, or r6.1-specific features.

Scaler: CERT r5.2 TRAIN only, transform-only.
SCALER_SOURCE = R52_TRAIN
TARGET_SCALER_FIT = NO
SHA256 = 6a092df8275e15b6e05c685b306f48de72ab55fb1e88ede5ed5899ecd63f3488
path = review\editor006a_preinference_freeze\EDITOR006A_SCALER.json

Raw root (content access only after this freeze): `C:\PhD\06_Datasets\r6.1\r6.1`
Answer-bundle candidates (resolved after freeze by filename glob `r6.1-*.csv`):
- `C:\PhD\06_Datasets\answers`
- `C:\PhD\07_Projects\cert-r42-feasibility\answers\answers`

### Reused implementations

- event parsing / daily aggregation / completed-window / de-overlap: `scripts/run_editor007b_r51_bundle.py` and `review/editor006c_r62_input_bundle/run_editor006c_r62_input_bundle.py` at parent a480fa2413cf0b70c398081ca5f8f52470a665a3
- window gather / identifiers: `src/editor006b_harness/input_bundle.py`
- scaler transform: `src/editor006b_harness/input_bundle.py::apply_persisted_scaler`
- label contract: `review/editor006a_preinference_freeze/EDITOR006A_R62_LABEL_CONTRACT.json`

## Frozen thresholds (secondary metrics only)

THRESHOLD_SOURCE = R52_FROZEN
TARGET_THRESHOLD_SEARCH = NO

- C2-OPT seed 42: 0.85
- C2-OPT seed 52: 0.89
- C2-OPT seed 62: 0.17
- F10 seed 42: 0.8400000000000001
- F10 seed 52: 0.79
- F10 seed 62: 0.54
- TA2 seed 42: 0.79
- TA2 seed 52: 0.74
- TA2 seed 62: 0.59
- L1 seed 42: 0.75
- L1 seed 52: 0.73
- L1 seed 62: 0.63

PR-AUC is primary and requires no threshold.

## Primary hypothesis H1

The final TA2 model retains ranking signal on prospectively reserved CERT r6.1.

Primary statistic: mean TA2 PR-AUC - r6.1 prevalence

Classification (do not change after results):

- SUPPORTED = point estimate > 0 AND user-cluster 95% CI lower bound > 0
- CONSISTENT = point estimate > 0 but CI lower bound <= 0
- NOT_SUPPORTED = point estimate <= 0

## Mechanistic comparisons

- TA2-C2-OPT: complete final formulation versus teacher initialisation alone
- F10-C2-OPT: ensemble predictive teacher-guidance contribution
- TA2-F10: incremental route-anchor contribution
- TA2-L1: final ODST formulation versus matched attention-linear reference

Same SUPPORTED / CONSISTENT / NOT_SUPPORTED rule. These comparisons do not select the final model.

## Uncertainty

- sampling unit = r6.1 user
- 2000 valid paired bootstrap replicates
- bootstrap seed = 42
- matched-model contrasts use the same resampled users within each replicate
- discard replicates where PR-AUC cannot be calculated because only one class is present

## Prohibitions

TRAINING_EXECUTED = NO
MODEL_PARAMETERS_UPDATED = NO
TARGET_SCALER_FIT = NO
TARGET_CALIBRATION_FIT = NO
TARGET_THRESHOLD_SEARCH = NO
TARGET_MODEL_SELECTION = NO
TARGET_FEATURE_SELECTION = NO
TARGET_NORMALISATION_FIT = NO
R52_TEST_ACCESSED = NO
R51_RERUN = NO
R62_RERUN = NO

No adversarial-robustness, evasion, poisoning, physical-sensor-failure, or automatic unseen-user-generalisation claims.

The paper may say: cross-release confirmation on a prospectively reserved CERT release.

## Concern-5 ruling (after compatible inference)

- TA2 ranking-transfer SUPPORTED → RESOLVED_WITH_PROSPECTIVELY_RESERVED_CONFIRMATION
- CONSISTENT → PARTIALLY_RESOLVED_WITH_PROSPECTIVELY_RESERVED_CONFIRMATION
- NOT_SUPPORTED → PROSPECTIVELY_TESTED_BUT_GENERALISATION_LIMITED

## Result-chasing prohibition

Once r6.1 content is first opened, no changes to architecture, checkpoints, features, sequence length,
stride, scaler, labels, model set, seeds, metrics, views, thresholds, bootstrap, or claim rules.

A prediction-affecting defect after content access yields EDITOR024_ENGINEERING_BLOCKED_AFTER_TARGET_ACCESS.

## Finalisation order

1. all scientific outputs final
2. completed RUN_MANIFEST
3. RESULT_FREEZE
4. TERMINAL_BLOCK
5. hash all stable target files
6. SHA256_MANIFEST written LAST (does not hash itself)

EDITOR024_RESULTS_COMMIT = PENDING_BY_DESIGN inside frozen files.
