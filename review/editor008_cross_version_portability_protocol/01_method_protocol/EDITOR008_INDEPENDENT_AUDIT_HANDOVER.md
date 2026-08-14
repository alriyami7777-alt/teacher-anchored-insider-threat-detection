# EDITOR-008 Independent Audit Handover

Independent review is required before implementation or training.

## Claude ruling incorporated

`CLAUDE_EDITOR008_AUDIT_PASS_WITH_REQUIRED_REVISIONS` = YES

All required revisions from that audit are incorporated in this freeze, including:
prevalence-robust decision policies instead of worst-source F1; explicit cross-release
limitation; diagnostic-to-design firewall; one-change-per-step ablation; teacher anchoring
as auxiliary only; and Phase-A target lock before method specification.

## Target-lock commit

`EDITOR008_TARGET_LOCK_COMMIT = 0eef55cbb00c410626f273a7878e81cb166c310d`

`TARGET_LOCK_PRECEDES_METHOD_FREEZE = YES`

## Complete release inventory

See `00_target_lock/EDITOR008_UNTOUCHED_TARGET_INVENTORY.json`.

Discovered: r2, r3.1, r3.2, r4.1, r4.2, r5.1, r5.2 TRAIN/VALIDATION, r5.2 TEST, r6.1, r6.2.

## All eligible final targets

`ELIGIBLE_UNTOUCHED_TARGETS = []`

`FINAL_UNTOUCHED_TARGETS = []`

`FINAL_TARGET_COUNT = 0`

`FINAL_TARGET_SELECTION_RULE = NO_PROSPECTIVE_TARGET_AVAILABLE`

`PROSPECTIVE_FINAL_TARGET_CLAIM = NOT_AVAILABLE`

## Source-domain roles

CERT r4.2, CERT r5.2 TRAIN/VALIDATION, CERT r5.1, CERT r6.2 are Generation-2 source
development domains. r5.1 and r6.2 are previously observed diagnostically and cannot be
presented as prospective untouched targets. r5.2 TEST is PROHIBITED.

## Cross-release limitation

CERT releases belong to the same synthetic benchmark lineage. Cross-release transfer
within that family is not cross-organisation, cross-population, or real-world
external generalisation.

## Diagnostic-to-design firewall

r62-specific feature targeting, email_count / has_file_activity / total_events remedies,
r62-specific thresholds, hyperparameters, and selection weights are PROHIBITED.

## Inherited architecture status

BiLSTM-attention is inherited, not a new contribution. ODST is an explanation-oriented
differentiable head. Attention-linear is the primary neural efficiency/calibration reference.

## GroupDRO role

Control worst-source/domain risk. Initial weights symmetric. Sample count does not set
domain importance. Natural worst-source emphasis permitted; r6.2-designed domination prohibited.

## CORAL role

Reduce source-domain representation covariance discrepancy. Source-only. Preferred location:
attended representation. No target-alignment loss.

## LOVO design

For every source release d: train on all other source domains; hold out d as development
evidence only.

## Domain-balanced selection rule

PRIMARY = best worst held-out-domain PR-AUC rank; then mean rank; then equal-domain mean
PR-AUC; then simpler configuration. Pooled window count and r62-specific priority prohibited.

## Portable decision policies

Preferred: fixed alert budget, then fixed-FPR source-frozen threshold, then legacy F1 as
descriptive reference only. Worst-source F1 primary threshold = REMOVED.

## Numeric operating-point status

`DECISION_OPERATING_POINT_VALUES = UNRESOLVED_PENDING_PRETRAINING_NUMERIC_FREEZE`

Historical r5.2 budgets cited, not adopted. `TRAINING_AUTHORISED = NO`.

## MMD shift detector

Primary RAW common-13 MMD; secondary attended-representation MMD; source-only RBF median
heuristic; envelope = max inter-source MMD unless another source-only envelope is justified
before training. Detector does not alter predictions.

## Ablation ladder

A0→A1→A2→A3→A4→A5, one change per step. A4 does not change model scores. A5 does not change
predictions. Heads and teacher anchoring are orthogonal.

## Teacher anchoring role

`AUXILIARY_FIDELITY_REGULARISER`. T0/T1/T2 on matched ODST. Initialisation-only control
required. r5.2 C2 vs C5_original_paper mechanism remains UNRESOLVED.

## Mandatory baselines

SINGLE_SOURCE_NEURAL_ERM, MULTI_SOURCE_NEURAL_ERM, ATTENTION_LINEAR, ODST, RF, XGBOOST.

## Statistical dependence protocol

Overlapping windows are correlated observations. Seeds are reproducibility repetitions.
User-cluster-aware (and incident-cluster-aware where reliable) resampling. Tiny cluster
counts must be reported; otherwise inferential claims are not supported.

## Explainability-under-shift protocol

Secondary prospective analysis. Reference-centred top-k vs random intervention faithfulness
with source/training centring. Routes/leaves independently faithful = UNSUPPORTED.
Adversarial robustness = UNSUPPORTED.

## No-target-tuning contract

All target label, feature-distribution, score-distribution, threshold, scaler, calibration,
hyperparameter, and model-selection uses before final freeze are PROHIBITED. Target failure
cannot trigger rescue training.

## Unresolved parameters

Generation-2 alert-budget rate; fixed-FPR anchor; GroupDRO numeric hyperparameters; CORAL
penalty weight; optional abstention threshold. All `REQUIRES_PRETRAINING_NUMERIC_FREEZE`.

## Success/failure gates

RANKING_PORTABILITY, DECISION_PORTABILITY, SHIFT_DIAGNOSIS, TEACHER_FIDELITY,
PREDICTIVE_SUPERIORITY, and EXPLAINABILITY remain separate findings.

## Independent review request

This packet authorises **independent audit of the EDITOR-008 protocol only**.
It does **not** authorise implementation execution, training, inference, numeric operating-point
adoption, or Generation-2 result generation.
