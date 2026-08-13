# EDITOR-007A — Post-006E diagnostic verification

Decision: **EDITOR007A_R62_INTERPRETATION_BLOCKED_MECHANICAL_FAILURE**

This is a diagnostic audit. It does not rerun CERT r6.2, does not execute r5.1
prediction, and does not replace frozen 006E evidence.

## TABLE 1 — 006E frozen evidence

- EDITOR006E_EXECUTION_STATUS = COMPLETE
- authorisation SHA = `e7c169c3f02a6ff28cbcfb32aa4af8830d05e7dc9d5857a46000938e6e8f080f`
- runner SHA = `54f93cb57a66aa384cb3eb5e1fdcbca792009d9058ecdb980cf77be7a2c5b6ba`
- n_sequences = 1988000
- n_models = 18

## TABLE 2 — r6.2 score distribution / orientation

| family | seed | min | max | median | frac>=thr | completed raw AP | completed 1-score AP | ruling |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| teacher_frozen_odst | 42 | 0.41743 | 0.572363 | 0.419809 | 0.424607 | 0.000441662 | 0.000262754 | RAW_ORIENTATION_HIGHER |
| teacher_frozen_odst | 52 | 0.0957021 | 0.881374 | 0.0975688 | 0.428982 | 0.000427406 | 0.000282805 | RAW_ORIENTATION_HIGHER |
| teacher_frozen_odst | 62 | 0.415414 | 0.573966 | 0.418523 | 0.450084 | 0.000609228 | 0.000273232 | RAW_ORIENTATION_HIGHER |
| C2 | 42 | 0.364199 | 0.62094 | 0.366141 | 0.43124 | 0.000452416 | 0.000265273 | RAW_ORIENTATION_HIGHER |
| C2 | 52 | 0.0549281 | 0.922714 | 0.0574647 | 0.440988 | 0.000371793 | 0.000594328 | INVERTED_DIAGNOSTIC_HIGHER |
| C2 | 62 | 0.315181 | 0.666284 | 0.316464 | 0.443193 | 0.000541288 | 0.000266457 | RAW_ORIENTATION_HIGHER |
| C5_original_paper | 42 | 0.416776 | 0.594136 | 0.419379 | 0.429979 | 0.000459471 | 0.000265279 | RAW_ORIENTATION_HIGHER |
| C5_original_paper | 52 | 0.0936695 | 0.90549 | 0.0941479 | 0.431195 | 0.000383041 | 0.000327174 | RAW_ORIENTATION_HIGHER |
| C5_original_paper | 62 | 0.414744 | 0.59986 | 0.41787 | 0.450771 | 0.000453094 | 0.000291522 | RAW_ORIENTATION_HIGHER |
| attention_linear | 42 | 0.000246255 | 0.999981 | 0.132315 | 0.430907 | 0.000515346 | 0.00025866 | RAW_ORIENTATION_HIGHER |
| attention_linear | 52 | 0.000191775 | 0.99999 | 0.103406 | 0.406128 | 0.000525923 | 0.000265937 | RAW_ORIENTATION_HIGHER |
| attention_linear | 62 | 7.87078e-06 | 1 | 0.0353372 | 0.453572 | 0.000494348 | 0.000262333 | RAW_ORIENTATION_HIGHER |
| RF_40 | 42 | 0 | 1 | 0.0199292 | 0.415221 | 0.00117456 | 0.000310113 | RAW_ORIENTATION_HIGHER |
| RF_40 | 52 | 0 | 0.999999 | 0.0149214 | 0.414738 | 0.00111719 | 0.000306914 | RAW_ORIENTATION_HIGHER |
| RF_40 | 62 | 0 | 1 | 0.0196715 | 0.415443 | 0.0172534 | 0.00029204 | RAW_ORIENTATION_HIGHER |
| XGBoost_40 | 42 | 6.33056e-08 | 1 | 0.000203126 | 0.418632 | 0.0121429 | 0.000268808 | RAW_ORIENTATION_HIGHER |
| XGBoost_40 | 52 | 2.03345e-07 | 1 | 0.00028134 | 0.418977 | 0.00150693 | 0.000270588 | RAW_ORIENTATION_HIGHER |
| XGBoost_40 | 62 | 2.4354e-07 | 1 | 0.000181598 | 0.417519 | 0.00962757 | 0.000255346 | RAW_ORIENTATION_HIGHER |

Inverted AP is diagnostic only and is not a corrected result.

## TABLE 3 — r5.2 validation parity references

| family | seed | status | type |
| --- | --- | --- | --- |
| teacher_frozen_odst | 42 | PRODUCING_SCORES_AND_METRICS_RECOVERED | producing_validation_predictions_csv_plus_metric_json |
| teacher_frozen_odst | 52 | PRODUCING_SCORES_AND_METRICS_RECOVERED | producing_validation_predictions_csv_plus_metric_json |
| teacher_frozen_odst | 62 | PRODUCING_SCORES_AND_METRICS_RECOVERED | producing_validation_predictions_csv_plus_metric_json |
| C2 | 42 | PRODUCING_SCORES_AND_METRICS_RECOVERED | producing_validation_predictions_csv_plus_metric_json |
| C2 | 52 | PRODUCING_SCORES_AND_METRICS_RECOVERED | producing_validation_predictions_csv_plus_metric_json |
| C2 | 62 | PRODUCING_SCORES_AND_METRICS_RECOVERED | producing_validation_predictions_csv_plus_metric_json |
| C5_original_paper | 42 | PRODUCING_SCORES_AND_METRICS_RECOVERED | producing_validation_predictions_csv_plus_metric_json |
| C5_original_paper | 52 | PRODUCING_SCORES_AND_METRICS_RECOVERED | producing_validation_predictions_csv_plus_metric_json |
| C5_original_paper | 62 | PRODUCING_SCORES_AND_METRICS_RECOVERED | producing_validation_predictions_csv_plus_metric_json |
| attention_linear | 42 | PRODUCING_SCORES_AND_METRICS_RECOVERED | producing_validation_predictions_csv_plus_metric_json |
| attention_linear | 52 | PRODUCING_SCORES_AND_METRICS_RECOVERED | producing_validation_predictions_csv_plus_metric_json |
| attention_linear | 62 | PRODUCING_SCORES_AND_METRICS_RECOVERED | producing_validation_predictions_csv_plus_metric_json |
| RF_40 | 42 | PRODUCING_METRICS_RECOVERED | producing_unrounded_metric_json |
| RF_40 | 52 | PRODUCING_METRICS_RECOVERED | producing_unrounded_metric_json |
| RF_40 | 62 | PRODUCING_METRICS_RECOVERED | producing_unrounded_metric_json |
| XGBoost_40 | 42 | PRODUCING_METRICS_RECOVERED | producing_unrounded_metric_json |
| XGBoost_40 | 52 | PRODUCING_METRICS_RECOVERED | producing_unrounded_metric_json |
| XGBoost_40 | 62 | PRODUCING_METRICS_RECOVERED | producing_unrounded_metric_json |

## TABLE 4 — r5.2 validation parity results

Gate: **R52_PARITY_FAIL**

| family | seed | parity | replay PR-AUC | producing PR-AUC | PR-AUC abs diff | FP exact | FN exact |
| --- | --- | --- | --- | --- | --- | --- | --- |
| teacher_frozen_odst | 42 | PARITY_FAIL | 0.9334097971 | 0.9334002969575846 | 9.500122479577655e-06 | True | True |
| teacher_frozen_odst | 52 | PARITY_FAIL | 0.9244683742 | 0.9244539797126647 | 1.4394501230419188e-05 | True | True |
| teacher_frozen_odst | 62 | PARITY_FAIL | 0.9347401735 | 0.9347250477760537 | 1.5125681705585592e-05 | True | True |
| C2 | 42 | PARITY_FAIL | 0.931856282 | 0.9318417313473917 | 1.455066792965809e-05 | True | True |
| C2 | 52 | PARITY_FAIL | 0.9241070336 | 0.9241053967437384 | 1.6368532107513545e-06 | True | True |
| C2 | 62 | PARITY_FAIL | 0.9311632461 | 0.9311900972327212 | 2.6851092178037383e-05 | False | True |
| C5_original_paper | 42 | PARITY_FAIL | 0.9335913825 | 0.9335775615746195 | 1.3820883967952113e-05 | True | True |
| C5_original_paper | 52 | PARITY_FAIL | 0.9246196011 | 0.9246065839750892 | 1.3017159525841038e-05 | True | True |
| C5_original_paper | 62 | PARITY_FAIL | 0.9357124093 | 0.9356969431665507 | 1.546614318470585e-05 | True | True |
| attention_linear | 42 | PARITY_FAIL | 0.9378816468 | 0.9378754065901991 | 6.240163821225053e-06 | True | True |
| attention_linear | 52 | PARITY_FAIL | 0.9096510435 | 0.9096388064417843 | 1.2237047641416865e-05 | True | True |
| attention_linear | 62 | PARITY_FAIL | 0.9458481408 | 0.9458398600054988 | 8.280777933133976e-06 | True | True |
| RF_40 | 42 | PARITY_FAIL | 0.9332817385 | 0.93328173852944 | 3.3306690738754696e-16 | True | True |
| RF_40 | 52 | RESULT_PARITY_EXACT | 0.9274669637 | 0.9274669636876686 | 0.0 | True | True |
| RF_40 | 62 | RESULT_PARITY_EXACT | 0.9268576618 | 0.9268576618039058 | 0.0 | True | True |
| XGBoost_40 | 42 | RESULT_PARITY_EXACT | 0.9669215203 | 0.9669215203190463 | 0.0 | True | True |
| XGBoost_40 | 52 | RESULT_PARITY_EXACT | 0.9649758249 | 0.9649758249486352 | 0.0 | True | True |
| XGBoost_40 | 62 | RESULT_PARITY_EXACT | 0.9677620096 | 0.9677620095743968 | 0.0 | True | True |

## TABLE 5 — r5.2 vs r6.2 feature shift

| feature | r52_train_mean | r52_val_mean | r62_mean | r62-r52_train |
| --- | --- | --- | --- | --- |
| total_events | -0.000708998 | -0.0380219 | -0.162087 | -0.161378 |
| logon_count | -0.000690126 | -0.0433259 | -0.0426473 | -0.0419572 |
| device_count | 1.20566e-05 | -0.0137835 | -0.0235122 | -0.0235243 |
| file_count | -0.000289938 | 0.000775272 | 0.0282264 | 0.0285163 |
| email_count | -0.000625368 | -0.0577483 | -0.645241 | -0.644615 |
| http_count | -0.00070327 | -0.0306883 | -0.0203852 | -0.0196819 |
| active_duration_minutes | -0.00118136 | -0.058363 | -0.0546894 | -0.0535081 |
| has_logon_activity | -0.00109161 | -0.0495144 | -0.0122607 | -0.0111691 |
| has_device_activity | -8.14094e-06 | -0.0200455 | -0.0244334 | -0.0244252 |
| has_file_activity | -4.91034e-05 | -0.0107425 | 0.230544 | 0.230593 |
| has_email_activity | -0.00116381 | -0.0492826 | -0.0247346 | -0.0235708 |
| has_http_activity | -0.00118349 | -0.0489451 | -0.0117674 | -0.0105839 |
| is_active_day | -0.00109015 | -0.0497199 | -0.014395 | -0.0133049 |

No p-values. No significance language.

## TABLE 6 — r5.2 vs r6.2 score-distribution shift

| family | seed | r52 neg mean | r62 neg mean | delta neg mean | r52 exceed | r62 exceed |
| --- | --- | --- | --- | --- | --- | --- |
| teacher_frozen_odst | 42 | 0.418644 | 0.485948 | 0.0673031 | 0.01025 | 0.424607 |
| teacher_frozen_odst | 52 | 0.100478 | 0.451954 | 0.351477 | 0.0102188 | 0.428982 |
| teacher_frozen_odst | 62 | 0.416329 | 0.488474 | 0.0721452 | 0.0108906 | 0.450084 |
| C2 | 42 | 0.36589 | 0.478877 | 0.112986 | 0.0105313 | 0.43124 |
| C2 | 52 | 0.060408 | 0.45024 | 0.389832 | 0.0108125 | 0.440988 |
| C2 | 62 | 0.31607 | 0.475729 | 0.159658 | 0.0100156 | 0.443193 |
| C5_original_paper | 42 | 0.417977 | 0.494373 | 0.0763966 | 0.0103281 | 0.429979 |
| C5_original_paper | 52 | 0.0981818 | 0.459675 | 0.361493 | 0.01025 | 0.431195 |
| C5_original_paper | 62 | 0.415736 | 0.498996 | 0.0832599 | 0.0108437 | 0.450771 |
| attention_linear | 42 | 0.0187942 | 0.469841 | 0.451047 | 0.0103906 | 0.430907 |
| attention_linear | 52 | 0.0185632 | 0.468696 | 0.450133 | 0.00998438 | 0.406128 |
| attention_linear | 62 | 0.0047794 | 0.472716 | 0.467937 | 0.0109844 | 0.453572 |
| RF_40 | 42 | 0.00226308 | 0.350278 | 0.348015 | 0.00989063 | 0.415221 |
| RF_40 | 52 | 0.00242702 | 0.344423 | 0.341996 | 0.00946875 | 0.414738 |
| RF_40 | 62 | 0.00225324 | 0.34345 | 0.341197 | 0.0100625 | 0.415443 |
| XGBoost_40 | 42 | 0.000599386 | 0.416425 | 0.415826 | 0.0112969 | 0.418632 |
| XGBoost_40 | 52 | 0.000569139 | 0.416598 | 0.416029 | 0.0111562 | 0.418977 |
| XGBoost_40 | 62 | 0.000585104 | 0.413613 | 0.413028 | 0.0112344 | 0.417519 |

## TABLE 7 — threshold exceedance shift

See TABLE 6 exceedance columns. Frozen thresholds were not retuned.

## TABLE 8 — diagnostic interpretation

- Q1. Does the frozen 006E execution path reproduce r5.2 validation behaviour? Not under the exact unrounded-metric identity rule. Parity gate=R52_PARITY_FAIL. Replay confusion counts match producing evidence for 17/18 models; C2 seed 62 differs by FP=1. Neural PR-AUC differs by about 1e-6 to 3e-5 versus producing JSON; RF seed 42 differs by one unit in the last place. Five classical models have RESULT_PARITY_EXACT. This identity miss cannot numerically explain the r6.2 PR-AUC collapse.
- Q2. Is the neural r6.2 collapse compatible with a score-orientation/sign error? No systematic r5.2 sign/loader error: replay raw AP is higher for 18/18 and inverted-higher for 0/18. Teacher r6.2 completed-window raw AP is also higher than 1-score AP, so the neural r6.2 collapse is not explained by flipping the score. C2 seed 52 (all views) and C5 seed 52 (de-overlap only) show r6.2 inverted-diagnostic-higher ranking; that is a diagnostic ranking reversal, not a corrected result. Formal SCORE_ORIENTATION remains UNRESOLVED because R52_PARITY_PASS was not reached.
- Q3. Did the r6.2 negative score distribution move relative to r5.2 validation? Yes: r6.2 negative-class mean scores moved relative to r5.2 VALIDATION for the frozen 18 models (min delta=0.0673031, max delta=0.467937).
- Q4. Do the frozen thresholds sit in materially different parts of the r6.2 score distributions? Yes: frozen r5.2 thresholds occupy different regions of the r6.2 score distributions than of r5.2 VALIDATION (see TABLE 7 exceedance rates).
- Q5. Which of the 13 input features exhibit the largest cross-version shifts? Largest absolute scaled mean shifts vs r5.2 TRAIN: email_count (delta=-0.644615); has_file_activity (delta=0.230593); total_events (delta=-0.161378); active_duration_minutes (delta=-0.0535081); logon_count (delta=-0.0419572)
- Q6. Is XGBoost/RF ranking retention accompanied by threshold/probability-scale failure? Frozen 006E completed-window results for RF/XGBoost show ranking far below the r5.2 VALIDATION producing level, with very large false-positive counts at the frozen thresholds. That is compatible with threshold/probability-scale non-portability even if some ranking above prevalence remains. RF_40 seed 42: PR-AUC=0.001174560711377733 FP=825097 precision=0.0004385438889151369 RF_40 seed 52: PR-AUC=0.0011171867801702388 FP=824153 precision=0.00042086112795633717 RF_40 seed 62: PR-AUC=0.017253394539005595 FP=825537 precision=0.00043952052306574647 XGBoost_40 seed 42: PR-AUC=0.012142874649416489 FP=831852 precision=0.0004674126845469041 XGBoost_40 seed 52: PR-AUC=0.0015069321120279413 FP=832537 precision=0.0004670282834249381 XGBoost_40 seed 62: PR-AUC=0.009627565598946357 FP=829639 precision=0.0004686588886158057
- Q7. Genuine generalisation failure, mechanical failure, or unresolved? Interpretation of r6.2 is blocked by a mechanical failure. Do not use r6.2 results in the manuscript yet. Do not run r5.1.

## TABLE 9 — decision gate

**EDITOR007A_R62_INTERPRETATION_BLOCKED_MECHANICAL_FAILURE**

## TABLE 10 — r5.1 secondary-stress status

R51_SECONDARY_STRESS_WARRANTED = NO

r5.1 predictive inference was not executed.

## Final verdict

EDITOR007A_R62_INTERPRETATION_BLOCKED_MECHANICAL_FAILURE

EDITOR006E_EVIDENCE_FREEZE = PASS
R52_VALIDATION_PARITY = FAIL
SCORE_ORIENTATION = UNRESOLVED
R62_INVERTED_SCORE_DIAGNOSTIC = UNRESOLVED
FEATURE_SHIFT_AUDIT = COMPLETE
SCORE_DISTRIBUTION_SHIFT_AUDIT = COMPLETE
MECHANICAL_CAUSE_FOUND = YES
R51_SECONDARY_STRESS_WARRANTED = NO
R62_PREDICTIVE_INFERENCE_RERUN = NO
R51_PREDICTIVE_INFERENCE_EXECUTED = NO
NEXT_ACTION = Do not use r6.2 results in the manuscript yet. Do not run r5.1. Exact discrepancy: R52_PARITY_FAIL under unrounded PR-AUC identity (neural abs diff about 1e-6 to 3e-5; RF seed 42 ULP 3.33e-16) plus C2 seed 62 FP off by 1 (replay 30 vs producing 31). Confusion counts match for the other 17/18. All 18 r5.2 replays have RAW_ORIENTATION_HIGHER. This identity miss does not numerically explain the r6.2 collapse.
