# EDITOR-007D1 Freeze Compliance Correction

## 1. Scope

EDITOR-007D1 is a non-numerical compliance and interpretation correction.
Historical `review/editor007d_cross_version_synthesis/` remains frozen.
This directory is the paper-facing derivative handover for EDITOR-008 drafting.

EDITOR-007D1 does not change any frozen r5.1 or r6.2 predictive result, mechanism result, bootstrap interval, score array, feature value, threshold, or dataset label.

## 2. Original EDITOR-007D Freeze

- Original commit: `aadda34ac9d77f67e2f487f55719b45224719c19`
- EDITOR-007C1 ancestor: `3655707631c2a437429538c159e2a6cd50f59c0c`
- Branch at correction: `repository-hardening`
- HEAD at correction start: `aadda34ac9d77f67e2f487f55719b45224719c19`
- Tracked working tree clean: `True`
- Untracked out-of-scope leftovers present (also present after the EDITOR-007D commit): `['EDITOR006B_REVIEW_PACKAGE.zip', 'EDITOR006B_REVIEW_PACKAGE/', 'review/editor004a_r51_model_free_audit/', 'review/editor005a_r62_model_free_audit/']`

This does not prove that the original EDITOR-007D working tree was fully clean before 007D execution. It records only what is verifiable now.

## 3. Numerical Non-Modification Statement

NUMERICAL_PREDICTIVE_VALUES_CHANGED = 0
NUMERICAL_MECHANISM_VALUES_CHANGED = 0
BOOTSTRAP_INTERVALS_CHANGED = 0
FROZEN_THRESHOLDS_CHANGED = 0
HISTORICAL_EDITOR007D_FILES_MODIFIED = NO

## 4. Provenance Completion

`EDITOR007D1_INPUT_CHECKSUMS.json` lists 110 artefacts, including 007A parity/feature/score evidence, 007C1 paper-corrected r5.1 predictive JSON, r5.1/r6.2 mechanism results, feature/count/manifest files, completed-window labels, all 18 r5.1 and 18 r6.2 raw-score arrays, r5.2 validation tensor, all 18 r5.2 replay-score arrays, frozen thresholds, and newly inspected r5.2 C2/C5 and Objective-3 recorded-result files.

## 5. r5.2 C2/C5 Predictive Evidence

Status: **LOCATED**

Source: frozen EDITOR-007A r5.2 VALIDATION replay metrics (scientifically adjudicated as SCIENTIFIC_PARITY_WITH_NUMERICAL_NONIDENTITY; automated gate FAIL_EXACT_NUMERICAL_IDENTITY preserved).

Teacher / C2 / C5 PR-AUC are essentially tied in-domain. C5−C2 deltas are not a superiority claim. No uncertainty interval was invented (`NOT_ATTACHED`). r5.2 TEST was not accessed.

## 6. r5.2 C2/C5 Mechanism Evidence

Status: **UNRESOLVED**

The EDITOR-007D statement `R52_MECHANISM_COMPARISON_NOT_INCLUDED_PROVENANCE_INSUFFICIENT` is not silently overridden.

Ablation C2 seed summaries contain exact-frozen field names and match the 007D C2 checkpoint. Ablation C5 seed summaries also contain those fields, but ablation C5 seed42 SHA256 `a5a08dc24a89014fd1bb92c6c6342ed50511b33804e95246e480e90c4692b214` is not `C5_original_paper` seed42 `2b6452698dd0da53f0229bc43040a877017ac9299b277f2f98c1d7ca64c1cc42`. The reproducibility `C5_original_paper` seed_summary does not record val_logit_consistency / route_mae / hard_route_agreement / dominant_leaf_agreement.

This does not invalidate the supported external r5.1/r6.2 teacher-fidelity result. Values were not reconstructed from manuscript prose.

## 7. Corrected Claim Classifications

Formal status vocabulary is only FULLY_SUPPORTED / QUALIFIED / UNRESOLVED / UNSUPPORTED.

- C5_PREDICTIVE_ADVANTAGE_OVER_C2 = UNSUPPORTED
- POINT_ESTIMATE_PATTERN = MIXED_OR_VERSION_DEPENDENT
- teacher anchoring improves predictive performance = UNSUPPORTED
- architecture generalises strongly = UNSUPPORTED
- architecture fails uniformly = UNSUPPORTED
- r5.1 retains substantial ranking signal = FULLY_SUPPORTED
- r6.2 exhibits severe ranking failure = FULLY_SUPPORTED
- frozen thresholds port to r6.2 = UNSUPPORTED

## 8. Corrected Explainability Interpretation

Supported: reference-centred tree-contribution rankings have intervention-based faithfulness evidence (`r52_odst_centred_faithfulness.csv`; training-median per-tree references; top-k versus random; user-cluster bootstrap).

Unsupported: routes and leaves are independently proven faithful.

Disabled external metrics remain unused-leaf fraction and tree-contribution rho. Those disabled metrics do not invalidate the separate reference-centred intervention evidence.

## 9. Corrected Degraded-Input Interpretation

Located producing Objective-3 recorded results:

- `r52_source_ablation.csv`
- `r52_noise_robustness.csv`

These are controlled degraded-input analyses. They do **not** establish adversarial robustness (UNSUPPORTED).

## 10. Primary Portability Phenotype

PRIMARY_PORTABILITY_PHENOTYPE = P2_R62_SEVERE_DISTRIBUTION_AND_DECISION_SHIFT

r5.1 retains substantial cross-version ranking signal, whereas r6.2 presents a much more severe, model-family-dependent portability failure that co-occurs with major score/decision-boundary and common-feature distribution shifts.

Do not state that a feature shift caused ranking collapse, that a distribution shift destroyed the neural model, that a specific feature caused failure, or that teacher anchoring caused portability.

## 11. EDITOR-008 Capability Requirements

- EDITOR008_SHIFT_DETECTION_REQUIRED = YES
- EDITOR008_SOURCE_ROBUST_REPRESENTATION_REQUIRED = YES
- EDITOR008_DECISION_PORTABILITY_REQUIRED = YES
- EDITOR008_ABSTENTION_OR_OOD_GATING_REQUIRED = CONDITIONAL
- EDITOR008_MULTI_SOURCE_DEVELOPMENT_REQUIRED = CONDITIONAL
- EDITOR008_EXPLAINABILITY_UNDER_SHIFT_REQUIRED = CONDITIONAL
- EDITOR008_TEACHER_ANCHORING_ROLE = AUXILIARY_FIDELITY_REGULARISER
- TABULAR_BASELINES_MUST_REMAIN = YES

No architecture is frozen here.

## 12. Remaining Unresolved Evidence

- Paired r5.2 validation exact-frozen mechanism comparison for C2 vs C5_original_paper.
- PAPER_ARTIFACT_REGISTER still lists several manuscript figures as UNRESOLVED producing-run fields; 007D1 cites the Objective-3 recorded_results CSVs rather than inventing those run IDs.

## 13. Final Gate for EDITOR-008

EDITOR008_PROTOCOL_DRAFTING_AUTHORISED = YES

This authorises drafting and independent audit of EDITOR-008 only.
It does not authorise training.
