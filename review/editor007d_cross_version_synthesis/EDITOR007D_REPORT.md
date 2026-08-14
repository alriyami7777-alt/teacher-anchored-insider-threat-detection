# EDITOR-007D — Cross-version diagnostic synthesis (CERT r5.2 → r5.1 → r6.2)

Evidence synthesis only. No model loading, training, threshold selection, calibration, or new evaluation.
r5.1 role remains **R51_SECONDARY_STRESS_ONLY**. r5.1 official insider–incident clusters = **4**. r6.2 = **5**.
The EDITOR-007C1 metadata correction does not change any predictive numerical result.

Preserved 007A gates:

- AUTOMATED_PROTOCOL_GATE = `FAIL_EXACT_NUMERICAL_IDENTITY`
- INDEPENDENT_SCIENTIFIC_ADJUDICATION = `SCIENTIFIC_PARITY_WITH_NUMERICAL_NONIDENTITY`

## TABLE 1 — Dataset / role / prevalence context

| dataset | role | users | days | completed N / pos / prev | endpoint N / pos / prev | de-overlap N / pos / prev | official clusters |
| --- | --- | --- | --- | --- | --- | --- | --- |
| CERT r5.2 VALIDATION | R52_VALIDATION_IN_DOMAIN_REFERENCE | NOT_RECOVERED_FROM_FROZEN_VALIDATION_NPZ | NOT_RECOVERED_FROM_FROZEN_VALIDATION_NPZ | 64000 / 728 / 0.011375 | NA / NA / NA | NA / NA / NA | NA |
| CERT r5.1 SECONDARY_STRESS | R51_SECONDARY_STRESS_ONLY | 2000 | 517 | 996000 / 461 / 0.000462851 | 996000 / 58 / 5.82329e-05 | 50000 / 24 / 0.00048 | 4 |
| CERT r6.2 EXTERNAL | R62_EXTERNAL | 4000 | 516 | 1988000 / 715 / 0.000359658 | 1988000 / 78 / 3.92354e-05 | 100000 / 35 / 0.00035 | 5 |

Overlapping windows are not independent incidents. r5.2 endpoint/de-overlap views are `NOT_COMPARABLE`.

## TABLE 2 — Three-version model portability

COMPLETED_WINDOW three-seed descriptive summary (seeds are not independent experimental units; no standard errors).

| dataset | family | mean PR-AUC | min | max | mean F1 | mean neg. exceedance |
| --- | --- | --- | --- | --- | --- | --- |
| r52_validation | teacher_frozen_odst | 0.930873 | 0.924468 | 0.93474 | 0.908192 | 0.000547899 |
| r51_secondary_stress | teacher_frozen_odst | 0.26153 | 0.224816 | 0.288901 | 0.190992 | 0.00106442 |
| r62_external | teacher_frozen_odst | 0.000492765 | 0.000427406 | 0.000609228 | 0.000926909 | 0.434512 |
| r52_validation | C2 | 0.929042 | 0.924107 | 0.931856 | 0.902331 | 0.000611118 |
| r51_secondary_stress | C2 | 0.268695 | 0.254866 | 0.283505 | 0.174206 | 0.00124321 |
| r62_external | C2 | 0.000455166 | 0.000371793 | 0.000541288 | 0.000933831 | 0.438426 |
| r52_validation | C5_original_paper | 0.931308 | 0.92462 | 0.935712 | 0.909716 | 0.000542631 |
| r51_secondary_stress | C5_original_paper | 0.276932 | 0.264769 | 0.285871 | 0.177187 | 0.00123585 |
| r62_external | C5_original_paper | 0.000431869 | 0.000383041 | 0.000459471 | 0.000925647 | 0.43727 |
| r52_validation | attention_linear | 0.931127 | 0.909651 | 0.945848 | 0.908172 | 0.000547899 |
| r51_secondary_stress | attention_linear | 0.261356 | 0.237189 | 0.287995 | 0.16835 | 0.00124957 |
| r62_external | attention_linear | 0.000511872 | 0.000494348 | 0.000525923 | 0.000935275 | 0.430156 |
| r52_validation | RF_40 | 0.929202 | 0.926858 | 0.933282 | 0.832019 | 0.00100624 |
| r51_secondary_stress | RF_40 | 0.309184 | 0.308103 | 0.310828 | 0.197321 | 0.00103997 |
| r62_external | RF_40 | 0.00651505 | 0.00111719 | 0.0172534 | 0.000865201 | 0.415104 |
| r52_validation | XGBoost_40 | 0.966553 | 0.964976 | 0.967762 | 0.926268 | 0.000769166 |
| r51_secondary_stress | XGBoost_40 | 0.39541 | 0.387105 | 0.399686 | 0.257207 | 0.000885283 |
| r62_external | XGBoost_40 | 0.00775912 | 0.00150693 | 0.0121429 | 0.000934596 | 0.418331 |

Retention versus r5.2 VALIDATION is defined only for COMPLETED_WINDOW. ENDPOINT/DEOVERLAP on r5.2 are `NOT_COMPARABLE`.
AP_PREVALENCE_LIFT_DESCRIPTIVE = PR_AUC / prevalence is DESCRIPTIVE_ONLY.

## TABLE 3 — Threshold exceedance portability

Mean completed-window negative frozen-threshold exceedance: r5.2 validation 0.000670825; r5.1 0.00111972; r6.2 0.428966.
Frozen 006A thresholds are preserved (no retuning). r6.2 negatives cross the frozen boundary for all 18 models.

## TABLE 4 — Positive/negative score-distribution shift

| family | seed | r52 neg exceed | r51 neg exceed | r62 neg exceed | r62−r52 neg mean |
| --- | ---: | --- | --- | --- | --- |
| teacher_frozen_odst | 42 | 0.000347705 | 0.00108383 | 0.424561 | 0.0673031 |
| teacher_frozen_odst | 52 | 0.000442534 | 0.000748338 | 0.428938 | 0.351477 |
| teacher_frozen_odst | 62 | 0.000853458 | 0.00136107 | 0.450038 | 0.0721452 |
| C2 | 42 | 0.000553167 | 0.0017026 | 0.431193 | 0.112986 |
| C2 | 52 | 0.000806044 | 0.00124556 | 0.44094 | 0.389832 |
| C2 | 62 | 0.000474143 | 0.000781486 | 0.443145 | 0.159658 |
| C5_original_paper | 42 | 0.000347705 | 0.00141632 | 0.429932 | 0.0763966 |
| C5_original_paper | 52 | 0.000442534 | 0.000739298 | 0.431152 | 0.361493 |
| C5_original_paper | 62 | 0.000837653 | 0.00155192 | 0.450725 | 0.0832599 |
| attention_linear | 42 | 0.000395119 | 0.0013008 | 0.43086 | 0.451047 |
| attention_linear | 52 | 0.0003319 | 0.00101051 | 0.406081 | 0.450133 |
| attention_linear | 62 | 0.000916677 | 0.00143741 | 0.453527 | 0.467937 |
| RF_40 | 42 | 0.00101151 | 0.00119031 | 0.415188 | 0.348015 |
| RF_40 | 52 | 0.000869263 | 0.000730258 | 0.414713 | 0.341996 |
| RF_40 | 62 | 0.00113794 | 0.00119935 | 0.415409 | 0.341197 |
| XGBoost_40 | 42 | 0.000837653 | 0.000792536 | 0.418587 | 0.415826 |
| XGBoost_40 | 52 | 0.000742825 | 0.00101051 | 0.418932 | 0.416029 |
| XGBoost_40 | 62 | 0.00072702 | 0.000852804 | 0.417474 | 0.413028 |

## TABLE 5 — Common-13 feature shift

| feature | r52 TRAIN mean | r52 VAL mean | r51 mean | r62 mean | abs r51 vs TRAIN | abs r62 vs TRAIN | r62 rank |
| --- | --- | --- | --- | --- | --- | --- | ---: |
| total_events | -0.000708998 | -0.0380219 | -0.00344623 | -0.162087 | 0.00273723 | 0.161378 | 3 |
| logon_count | -0.000690126 | -0.0433259 | -0.00805708 | -0.0426473 | 0.00736695 | 0.0419572 | 5 |
| device_count | 1.20566e-05 | -0.0137835 | 0.0171218 | -0.0235122 | 0.0171097 | 0.0235243 | 9 |
| file_count | -0.000289938 | 0.000775272 | 0.0127032 | 0.0282264 | 0.0129932 | 0.0285163 | 6 |
| email_count | -0.000625368 | -0.0577483 | -0.00684861 | -0.645241 | 0.00622324 | 0.644615 | 1 |
| http_count | -0.00070327 | -0.0306883 | -0.00389462 | -0.0203852 | 0.00319135 | 0.0196819 | 10 |
| active_duration_minutes | -0.00118136 | -0.058363 | -0.0289473 | -0.0546894 | 0.0277659 | 0.0535081 | 4 |
| has_logon_activity | -0.00109161 | -0.0495144 | -0.00894211 | -0.0122607 | 0.0078505 | 0.0111691 | 12 |
| has_device_activity | -8.14094e-06 | -0.0200455 | 0.0150699 | -0.0244334 | 0.0150781 | 0.0244252 | 7 |
| has_file_activity | -4.91034e-05 | -0.0107425 | 0.0114578 | 0.230544 | 0.0115069 | 0.230593 | 2 |
| has_email_activity | -0.00116381 | -0.0492826 | -0.00890664 | -0.0247346 | 0.00774284 | 0.0235708 | 8 |
| has_http_activity | -0.00118349 | -0.0489451 | -0.00830138 | -0.0117674 | 0.00711789 | 0.0105839 | 13 |
| is_active_day | -0.00109015 | -0.0497199 | -0.00939346 | -0.014395 | 0.00830331 | 0.0133049 | 11 |

Largest |r6.2 − r5.2 TRAIN| features: email_count, has_file_activity, total_events. No p-value ranking.

## TABLE 6 — C2 vs C5 predictive comparison

| dataset | seed | view | C2 PR-AUC | C5 PR-AUC | Δ PR-AUC | C2 F1 | C5 F1 | Δ F1 | PR CI class | F1 CI class |
| --- | ---: | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| r51_secondary_stress | 42 | COMPLETED_WINDOW | 0.267714 | 0.280158 | 0.0124437 | 0.145376 | 0.16838 | 0.0230035 | NA | NA |
| r51_secondary_stress | 42 | ENDPOINT_PAST_ONLY | 0.034065 | 0.0397249 | 0.00565985 | 0.024974 | 0.0329268 | 0.00795284 | NA | NA |
| r51_secondary_stress | 42 | DEOVERLAP_OFFSET0 | 0.315863 | 0.333681 | 0.0178179 | 0.138462 | 0.156522 | 0.0180602 | CI_INCLUDES_ZERO | CI_INCLUDES_ZERO |
| r51_secondary_stress | 52 | COMPLETED_WINDOW | 0.283505 | 0.285871 | 0.00236534 | 0.168999 | 0.224036 | 0.0550367 | NA | NA |
| r51_secondary_stress | 52 | ENDPOINT_PAST_ONLY | 0.0501777 | 0.0510036 | 0.000825908 | 0.0302405 | 0.0465608 | 0.0163203 | NA | NA |
| r51_secondary_stress | 52 | DEOVERLAP_OFFSET0 | 0.318373 | 0.330725 | 0.0123524 | 0.209302 | 0.257143 | 0.0478405 | CI_INCLUDES_ZERO | CI_EXCLUDES_ZERO_POSITIVE |
| r51_secondary_stress | 62 | COMPLETED_WINDOW | 0.254866 | 0.264769 | 0.00990281 | 0.208243 | 0.139147 | -0.0690964 | NA | NA |
| r51_secondary_stress | 62 | ENDPOINT_PAST_ONLY | 0.0404498 | 0.0438363 | 0.00338648 | 0.0408163 | 0.0239589 | -0.0168574 | NA | NA |
| r51_secondary_stress | 62 | DEOVERLAP_OFFSET0 | 0.286308 | 0.294675 | 0.00836715 | 0.290323 | 0.183673 | -0.106649 | CI_INCLUDES_ZERO | CI_EXCLUDES_ZERO_NEGATIVE |
| r62_external | 42 | COMPLETED_WINDOW | 0.000452416 | 0.000459471 | 7.05548e-06 | 0.00093471 | 0.000937448 | 2.73798e-06 | NA | NA |
| r62_external | 42 | ENDPOINT_PAST_ONLY | 5.46954e-05 | 5.37852e-05 | -9.10255e-07 | 0.000135295 | 0.000135692 | 3.96607e-07 | NA | NA |
| r62_external | 42 | DEOVERLAP_OFFSET0 | 0.000443428 | 0.000459137 | 1.57095e-05 | 0.000880282 | 0.00088208 | 1.79816e-06 | CI_INCLUDES_ZERO | CI_EXCLUDES_ZERO_POSITIVE |
| r62_external | 52 | COMPLETED_WINDOW | 0.000371793 | 0.000383041 | 1.12484e-05 | 0.000934581 | 0.000918489 | -1.60917e-05 | NA | NA |
| r62_external | 52 | ENDPOINT_PAST_ONLY | 4.69579e-05 | 4.781e-05 | 8.52066e-07 | 0.000134586 | 0.000135309 | 7.23349e-07 | NA | NA |
| r62_external | 52 | DEOVERLAP_OFFSET0 | 0.000374439 | 0.000395369 | 2.09303e-05 | 0.0008608 | 0.000879894 | 1.90948e-05 | CI_INCLUDES_ZERO | CI_EXCLUDES_ZERO_POSITIVE |
| r62_external | 62 | COMPLETED_WINDOW | 0.000541288 | 0.000453094 | -8.81945e-05 | 0.000932203 | 0.000921004 | -1.11988e-05 | NA | NA |
| r62_external | 62 | ENDPOINT_PAST_ONLY | 7.49236e-05 | 5.29723e-05 | -2.19513e-05 | 0.000129377 | 0.000129434 | 5.68324e-08 | NA | NA |
| r62_external | 62 | DEOVERLAP_OFFSET0 | 0.000850736 | 0.000453194 | -0.000397542 | 0.000856319 | 0.000842105 | -1.42135e-05 | CI_INCLUDES_ZERO | CI_EXCLUDES_ZERO_NEGATIVE |

Bootstrap intervals are reused, not recomputed. No significance-star language. A positive point estimate is not predictive superiority.

## TABLE 7 — Teacher-relative mechanism comparison

`R52_MECHANISM_COMPARISON_NOT_INCLUDED_PROVENANCE_INSUFFICIENT`. unused-leaf and tree-rho remain `DISABLED_NOT_REPRODUCIBLE`.

| dataset | seed | C2 logit | C5 logit | rel. red. | C2 route MAE | C5 route MAE | C2 agr. | C5 agr. |
| --- | ---: | --- | --- | --- | --- | --- | --- | --- |
| r51_secondary_stress | 42 | 25.4431 | 0.0121932 | 0.999521 | 0.00223748 | 0.000955613 | 0.99842 | 0.999289 |
| r51_secondary_stress | 52 | 4.03407 | 0.027127 | 0.993276 | 0.00266166 | 0.00102967 | 0.997469 | 0.999034 |
| r51_secondary_stress | 62 | 206.446 | 0.0307949 | 0.999851 | 0.00168822 | 0.000813011 | 0.998964 | 0.99949 |
| r62_external | 42 | 0.512676 | 0.0341598 | 0.93337 | 0.0074346 | 0.00508109 | 0.9961 | 0.996807 |
| r62_external | 52 | 0.079513 | 0.00799834 | 0.899408 | 0.00688433 | 0.00347698 | 0.993267 | 0.996737 |
| r62_external | 62 | 1.79064 | 0.0487084 | 0.972798 | 0.00643641 | 0.00421744 | 0.995902 | 0.997313 |

## TABLE 8 — Scenario/cluster limitations

`SCENARIOS_NOT_CROSS_VERSION_MATCHED_UNITS`

- r5.1 = four official insider–incident clusters
- r6.2 = five official insider–incident clusters
- Scenario detection patterns are within-version descriptive only and are not numerically matched across versions.

## TABLE 9 — Diagnostic rulings

- `GENERAL_CROSS_VERSION_COLLAPSE` = `NOT_SUPPORTED`
- `R51_SUBSTANTIAL_RANKING_TRANSFER` = `SUPPORTED`
- `R62_SEVERE_VERSION_SPECIFIC_FAILURE` = `SUPPORTED`
- `R62_RANKING_COLLAPSE` = `MODEL_FAMILY_DEPENDENT`
- `R62_THRESHOLD_PORTABILITY_FAILURE` = `SUPPORTED`
- `TABULAR_RELATIVE_PORTABILITY` = `SUPPORTED`
- `C5_PREDICTIVE_ADVANTAGE_OVER_C2` = `MIXED`
- `C5_TEACHER_FIDELITY_EFFECT` = `SUPPORTED`
- `PRIMARY_PORTABILITY_PHENOTYPE` = `P2_R62_SEVERE_DISTRIBUTION_AND_DECISION_SHIFT`
- secondary contributors = P3_PRIMARILY_THRESHOLD_CALIBRATION_PORTABILITY_FAILURE, P4_MODEL_FAMILY_SPECIFIC_PORTABILITY_FAILURE

**Q1.** Is the r5.2 → r6.2 failure a general cross-version failure?

NO. r5.1 secondary-stress completed-window neural mean PR-AUC remains far above prevalence, so the r6.2 near-prevalence collapse is not shown to be a general CERT-version failure.

**Q2.** Does r5.1 show substantial cross-version ranking transfer?

YES, descriptively. Neural completed-window mean PR-AUC on r5.1 remains orders of magnitude above prevalence, indicating retained ranking despite large absolute drop from r5.2 validation.

**Q3.** Is r6.2 qualitatively more severe than r5.1?

YES. r6.2 neural completed-window PR-AUC sits near prevalence; r5.1 does not.

**Q4.** Is r6.2 failure predominantly ranking collapse, decision-threshold shift, or both?

BOTH, with family dependence: neural ranking collapses to near prevalence, while all 18 frozen models show a large negative-class frozen-threshold exceedance shift on r6.2. Tabular families retain more ranking than the neural pathway but still fail at the frozen decision boundary.

**Q5.** Do RF/XGBoost retain more ranking portability than the neural pathway?

YES, relatively, on r6.2 completed-window PR-AUC. This is descriptive relative portability, not a claim that tabular models succeed.

**Q6.** Does teacher anchoring show a reproducible predictive advantage over C2 across external versions?

NO as a general predictive-superiority claim. Point deltas are small; several de-overlap PR-AUC intervals include zero; r6.2 deltas sit on a collapsed PR-AUC scale. A positive point estimate is not predictive superiority.

**Q7.** Does teacher anchoring show reproducible teacher-relative mechanism/fidelity preservation across external versions?

YES on the exact-frozen metrics compared here (r5.1 and r6.2). C5 remains closer to the teacher than C2 on logit deviation, route MAE/KL, and agreement. r5.2 validation mechanism values are not included (provenance insufficient).

**Q8.** Which input/score shifts best distinguish r6.2 from r5.1?

Largest |r6.2 mean − r5.2 TRAIN mean| features: email_count, has_file_activity, total_events. r5.1 scaled means remain close to r5.2 TRAIN. Score-side, r6.2 negative frozen-threshold exceedance rises from ~0.0003–0.001 on r5.2 validation to ~0.41–0.45, far above the r5.1 elevation.

**Q9.** What exact failure mechanism should EDITOR-008 attempt to address?

A version-specific r6.2 representation/distribution shift that both destroys neural ranking and moves negatives across frozen r5.2 decision thresholds, while teacher-anchoring fidelity does not restore predictive portability. EDITOR-008 should treat shift detection, source-robust representation, and decision portability as required capabilities, with teacher anchoring auxiliary only. Do not freeze an architecture here.

## TABLE 10 — Current-paper claim impact

| claim | status |
| --- | --- |
| teacher initialisation is load-bearing | SUPPORTED_WITH_QUALIFICATION |
| anchoring constrains teacher-relative logit drift | SUPPORTED_WITH_QUALIFICATION |
| anchoring constrains routing drift | SUPPORTED_WITH_QUALIFICATION |
| anchoring improves predictive performance | NEGATIVE_RESULT |
| ODST is predictively superior to attention-linear | UNSUPPORTED |
| model generalises across CERT versions | NEGATIVE_RESULT |
| frozen thresholds are portable | NEGATIVE_RESULT |
| RF/XGBoost remain strong engineered-tabular references | SUPPORTED_WITH_QUALIFICATION |
| reference-centred explanation evidence | UNSUPPORTED |
| degraded-input evidence | UNSUPPORTED |

## TABLE 11 — Requirements for EDITOR-008

No architecture is frozen in EDITOR-007D.

| requirement | required | support |
| --- | --- | --- |
| SHIFT_DETECTION_REQUIRED | YES | SUPPORTED |
| SOURCE_ROBUST_REPRESENTATION_REQUIRED | YES | SUPPORTED |
| DECISION_PORTABILITY_REQUIRED | YES | SUPPORTED |
| ABSTENTION_OR_OOD_GATING_REQUIRED | YES | SUPPORTED |
| MULTI_SOURCE_DEVELOPMENT_REQUIRED | YES | SUPPORTED |
| TEACHER_ANCHORING_AUXILIARY_ONLY | YES | SUPPORTED |
| TABULAR_BASELINES_MUST_REMAIN | YES | SUPPORTED |
| UNSEEN_FINAL_TARGET_REQUIRED | YES | SUPPORTED |

EDITOR008_TEACHER_ANCHORING_ROLE = `AUXILIARY`

Do not use PROVEN_CAUSAL language for any shift explanation.
