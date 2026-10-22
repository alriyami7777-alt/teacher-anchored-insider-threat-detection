# EDITOR-023 protocol freeze

Frozen before any new-severity result is viewed.

## Identity

- TASK_ID = EDITOR-023
- TASK_NAME = POSITIVE ARCHITECTURE-VALUE CONFIRMATION
- EDITOR022_RESULTS_COMMIT = ac50596ed8c3b480c887640911092e46b4631670
- MODEL_TRAINING = PROHIBITED
- HYPERPARAMETER_TUNING = PROHIBITED
- ARCHITECTURE_SEARCH = PROHIBITED
- RESULT_STATUS_AT_START = UNSEEN_FOR_NEW_CONFIRMATORY_METRICS

This is not a robustness-training rescue. EDITOR-020, EDITOR-021 and EDITOR-022 remain frozen.
Do not train TA2-RP, TA2-SR, or any new model. TA2 itself is the object of evaluation.

## Architecture identity

```
20-day x 13-feature input -> Bi-LSTM -> temporal attention -> attention-pooled representation -> ODST-046 -> binary logit
```

Training formulation (historical; not re-run):

```
task loss + 0.5 x equal-weight ensemble-teacher logit MSE + 0.5 x matched-teacher route consistency
```

No architectural component may be changed. No parameter may be updated. Teachers are not required at inference.

## Comparators (frozen checkpoints only)

- C2-OPT: teacher initialisation without repaired teacher guidance
- F10: same ODST architecture + ensemble teacher-logit guidance + route anchor OFF
- TA2: same ODST architecture + ensemble teacher-logit guidance + route anchor ON
- L1: matched Bi-LSTM + attention representation + ensemble teacher guidance + linear prediction head

No new baseline may be added after results are observed.

## Historical clean results (inputs, not new discoveries)

Official r5.2 validation means:

- C2-OPT = 0.9353238885
- F10 = 0.9425948632
- TA2 = 0.9428421883
- L1 = 0.938880958

Frozen TA2 versus C2 effect (historical input): mean PR-AUC gain approximately 0.007518; primary seeds positive 3/3; user-cluster 95% CI [0.000345, 0.01825]; extended panel 9/10; extended mean gain approximately 0.006157.

## Prospective hypotheses

- H1 teacher guidance predictive value: TA2 clean PR-AUC > C2-OPT clean PR-AUC. Historical status SUPPORTED_STRONG. EDITOR-023 verifies consistency.
- H2 teacher guidance source-degradation value: F10 has smaller aggregate source-channel PR-AUC degradation than C2-OPT. Historical point effect approximately +0.0229.
- H3 teacher guidance Gaussian-noise value: F10 retains more ranking performance under Gaussian input noise than C2-OPT. Historical point effect approximately +0.0092.
- H4 route-anchor structural value: TA2 remains closer than F10 to matched-teacher ODST routes under clean and degraded inputs. Do not require a large clean PR-AUC increment.
- H5 TA2 degraded-input value over matched linear reference: TA2 has better aggregate resilience than L1. Historical directional effects source approximately +0.0124, noise approximately +0.0098.
- H6 explanation stability: TA2 reference-centred signed tree-contribution rankings are more stable under degraded inputs than F10. Do not redefine faithfulness.

## Family A — graded source availability

Channels: ['logon', 'device', 'file', 'email', 'http']

Degradation levels: [0.0, 0.25, 0.5, 0.75, 1.0]

New levels: [0.25, 0.5, 0.75]

Implementation:

```
x_degraded = (1 - d) * x_clean + d * x_historical_ablation
```

d=1.00 exactly reproduces the EDITOR-017 complete ablation. Labels do not enter degradation construction. This is CONTROLLED_SOURCE_CHANNEL_ABLATION / data-quality degradation, not physical sensor failure and not adversarial removal.

## Family B — dense Gaussian-noise curve

Exact existing Gaussian-noise definition. Levels: [0.0, 0.025, 0.05, 0.075, 0.1, 0.15, 0.2]

Historical points that must reproduce EDITOR-017: [0.05, 0.1, 0.2]

New points: [0.025, 0.075, 0.15]

No noise level may be added after results are observed. No adversarial optimisation.

## Primary degradation-curve metric

Retention(severity) = PR_AUC(severity) / PR_AUC(clean)

SOURCE_AURC: trapezoidal_area_under_retention_versus_degradation_d_for_d_in_0.00_0.25_0.50_0.75_1.00_then_equal_mean_across_five_source_channels

NOISE_AURC: trapezoidal_area_under_retention_versus_sigma_for_sigma_in_0.00_0.025_0.05_0.075_0.10_0.15_0.20_divided_by_evaluated_sigma_interval_0.20

Higher is better. Integration and normalisation must not change after viewing results.

## Primary comparisons

['F10-C2', 'TA2-C2', 'TA2-F10', 'TA2-L1']

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
2. Reproduce historical clean PR-AUC (tolerance 0.0005).
3. Reproduce EDITOR-017 full source-ablation (d=1.0).
4. Reproduce historical Gaussian-noise levels 0.05 / 0.10 / 0.20.
5. Reproduce established route metrics for F10/TA2 at historical conditions (tolerance 0.0005).
6. Verify explanation-stability implementation against the existing frozen result (tolerance 0.005).

If any required parity check fails beyond established numerical tolerance: EDITOR023_PARITY_GATE = FAIL. STOP before evaluating new severities.

## Claim boundaries

Even with a positive result, do not claim: ['adversarial robustness', 'evasion resistance', 'poisoning resistance', 'physical sensor failure resistance', 'unseen-user generalisation', 'overall superiority to RF', 'overall superiority to XGBoost', 'clean ODST superiority over attention-linear', 'route faithfulness', 'leaf faithfulness', 'global top-k faithfulness'].

Appropriate language: ['controlled degraded-input resilience', 'data-quality resilience', 'teacher-guidance predictive value', 'teacher-relative route stability', 'explanation stability'].

Forbidden threat terms: ['ADVERSARIAL_ROBUSTNESS', 'EVASION_ROBUSTNESS', 'POISONING_ROBUSTNESS', 'PHYSICAL_SENSOR_FAILURE'].

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
