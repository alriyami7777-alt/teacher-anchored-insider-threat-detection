# Study Status

Last consolidated status: 26 August 2026.

## Submission status

- Current IEEE Access submission: Access-2026-42960
- Original prescreened manuscript: Access-2026-37987
- Revised title: Teacher-Guided Differentiable Sequence–Ensemble Learning for
  Explainable Insider Threat Detection
- Status: resubmitted, under editorial consideration

## Scope

This is the paper-support and reproducibility repository for the IEEE Access
manuscript. Evidence is recorded in two layers.

- **Current** — evidence supporting the revised resubmission. Full provenance is
  recorded in `docs/IEEE_ACCESS_RESUBMISSION_FREEZE_2026-08-25.md`.
- **Historical** — earlier frozen configurations and results, retained as valid
  records of the stage that produced them. They are not restated as current
  claims.

CERT r6.2 is outside the current manuscript. The current evidence streams are
CERT r4.2 development evidence, CERT r5.2 historical guarded-reference evidence
plus final train/validation evidence, and CERT r6.1 one-pass cross-release
evidence.

## Objective 1 — Time-aware preprocessing

### Completed

- CERT r4.2 multi-source event audit and sequence preparation.
- Dense per-user daily timelines retaining inactive days.
- Twenty-day sequences with stride one and no cross-boundary windows.

### Outside the current manuscript

- CERT r6.2 model-free readiness, provenance, ground-truth package audit,
  exact-matching strategy, and Stage 2B-1A logon matching at commit 330ac6a.
  Retained as historical material; no model-performance claim.
- Full CERT r6.2 preprocessing and model-ready sequence generation.

## Objective 2 — Unified sequence–ensemble modelling

### Completed, current

- Final CERT r5.2 train/validation evidence for the teacher-guided,
  route-regularised ODST across seeds 42, 52 and 62.
- Factorial separation of teacher-informed initialisation, ensemble-teacher
  prediction guidance, and matched-teacher route regularisation.
- Dependence-aware de-overlapped confirmation.
- Endpoint-defined evaluation.
- Prospectively reserved CERT r6.1 one-pass cross-release evaluation.

### Completed, historical

- CERT r4.2 architecture feasibility and ablation work.
- CERT r5.2 frozen-encoder confirmation.
- CERT r5.2 one-pass independent test for eligible baselines and the
  frozen-encoder ODST comparator.
- Same-information attention–linear and ODST comparison.
- Component latency audit.
- Reduced-tree viability audit against the historical sixteen-tree
  configuration.

### Qualified findings

- Ensemble-teacher prediction guidance supplies the supported clean predictive
  improvement beyond teacher-informed initialisation: mean validation PR-AUC
  0.942842 against 0.935324, a difference of +0.007518 with paired user-cluster
  95% confidence interval [0.000345, 0.018250].
- Route-only clean improvement is not supported. Matched-teacher route
  regularisation mainly constrains route drift and improves structural and
  degraded-input behaviour.
- Clean predictive superiority of ODST over attention–linear is not
  established. ODST is retained as an explanation-oriented differentiable head.
- Randomly initialised students were not rescued under the evaluated
  teacher-guided protocol.
- CERT r6.1 ranking transfer of the final model is not supported.
- The historical eight-tree ODST reduced parameters but was 7.4% slower than the
  sixteen-tree candidate under the audited implementation of that stage. Seeds
  52 and 62 were therefore not run.
- ODST accounted for approximately 72–73% of device-resident inference time in
  the component audit.

## Objective 3 — Explanation and robustness

### Completed

- Attention faithfulness analysis.
- Reference-centred ODST explanation analysis.
- Multi-seed r5.2 portability confirmation.
- Controlled missing-source and continuous-noise degraded-input analyses.
- Route, tree, and leaf stability analysis with documented comparability limits.

### Qualified findings

- The local signed reference-centred tree-contribution intervention is
  supported. Routes, reached leaves, tree outputs and memberships are traceable
  internal evidence only. General global top-k tree-ranking faithfulness is not
  supported.
- Raw-ranking sensitivity results remain documented.
- Source dependencies differed between CERT releases.
- Missing-source and noise evidence is controlled degraded-input and
  data-quality sensitivity analysis, not adversarial robustness.

## Final conclusions

Current paper conclusions are bounded by the frozen evidence recorded in
`docs/IEEE_ACCESS_RESUBMISSION_FREEZE_2026-08-25.md`. No current paper claim
should be changed without later frozen evidence or an IEEE-requested revision.
