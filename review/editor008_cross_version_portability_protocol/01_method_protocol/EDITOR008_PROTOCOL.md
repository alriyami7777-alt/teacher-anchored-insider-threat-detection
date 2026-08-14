# EDITOR-008 Source-Robust Portability Protocol

PROTOCOL FREEZE ONLY. No Generation-2 training or predictive inference is authorised.

Claude ruling incorporated: `CLAUDE_EDITOR008_AUDIT_PASS_WITH_REQUIRED_REVISIONS`.

Target-lock commit (must precede this method freeze): `0eef55cbb00c410626f273a7878e81cb166c310d`

## Prospective target status

`PROSPECTIVE_FINAL_TARGET_CLAIM = NOT_AVAILABLE`

No eligible untouched CERT release was locked in EDITOR-008A. This method freeze is a
**retrospective source-domain / leave-one-version-out portability protocol**.
It does not authorise a prospective untouched-target claim.

## Cross-release limitation

CERT releases belong to the same synthetic benchmark lineage. The Generation-2 experiment
evaluates cross-release transfer within that benchmark family. It does not establish
cross-organisation, cross-population, or real-world external generalisation.

An “untouched target” means `UNOBSERVED_BY_THIS_RESEARCH_PROGRAM_BEFORE_PROSPECTIVE_LOCK`.
It does not mean an independently sampled real-world population.

## Contribution

A prospectively controlled source-robust portability framework for explainable insider-threat
detection, combining version-as-domain multi-source development, domain-robust optimisation,
source-only representation alignment, prevalence-robust portable decision policies,
source-frozen shift diagnosis, and dependence-aware cross-release evaluation.

This is **not** a new Bi-LSTM architecture, **not** an optimizer novelty claim, **not**
evidence that teacher anchoring improves prediction, **not** cross-population generalisation,
**not** real-world deployment validation, and **not** adversarial robustness.

Inherited pathway (fixed): 20-day sequence → Bi-LSTM → temporal attention → predictive head.

## Source domains

- CERT r4.2
- CERT r5.2 TRAIN/VALIDATION only (`R52_TEST = PROHIBITED`)
- CERT r5.1 = `GENERATION2_SOURCE_DEVELOPMENT_DOMAIN` + `PREVIOUSLY_OBSERVED_DIAGNOSTICALLY`
- CERT r6.2 = `GENERATION2_SOURCE_DEVELOPMENT_DOMAIN` + `PREVIOUSLY_OBSERVED_DIAGNOSTICALLY`

`VERSION = DOMAIN`. Weighting is domain-balanced, not sample-balanced. r6.2 is one LOVO
domain only. No r6.2-specific fold, objective, feature remedy, or selection weight.

## Method family

MULTI_SOURCE_DOMAIN_BALANCED_TRAINING + GROUPDRO_STYLE_SOURCE_RISK_OPTIMISATION +
SOURCE_ONLY_CORAL_REPRESENTATION_ALIGNMENT.

GroupDRO and CORAL remain separately ablatable. No target-alignment loss.

## Selection

LEAVE_ONE_SOURCE_VERSION_OUT. Primary metric PR-AUC with prevalence reported beside it.

PRIMARY = best worst held-out-domain PR-AUC rank, then mean rank, then equal-domain mean
PR-AUC, then simpler configuration. Worst-source F1 is **not** the primary threshold rule.

## Decision portability

Operating-point values remain `UNRESOLVED_PENDING_PRETRAINING_NUMERIC_FREEZE`.
Historical r5.2 alert budgets `(0.0005, 0.001, 0.0025, 0.005, 0.01)` are cited but **not**
adopted as Generation-2 numbers. EDITOR-006A F1 thresholds are a descriptive legacy
reference only. `TRAINING_AUTHORISED = NO` until an independently audited source-only
numeric freeze.

## Shift detection

Mandatory diagnostic. Primary: MMD on common-13 features. Secondary: MMD on attended
representations. Detector does not alter predictions. Abstention/OOD is optional;
ungated full-coverage results remain mandatory.

## Ablations

One change per step: A0 ERM → A1 multi-source → A2 GroupDRO → A3 CORAL → A4 portable
decision (scores unchanged) → A5 shift diagnostic (predictions unchanged). Head comparison
and teacher-anchoring are orthogonal.

Teacher anchoring remains `AUXILIARY_FIDELITY_REGULARISER`. r5.2 C2 vs `C5_original_paper`
mechanism evidence remains `UNRESOLVED`.

## Training

**No training is authorised by EDITOR-008.**
