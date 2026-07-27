# Study Status

Last consolidated status: 27 July 2026.

## Objective 1 â€” Time-aware preprocessing

**Chapter 3 phase:** Phase 1, data preparation and temporal representation.

### Completed

- CERT r4.2 multi-source event audit and sequence preparation.
- Dense per-user daily timelines retaining inactive days.
- Twenty-day sequences with stride one and no cross-boundary windows.
- CERT r6.2 model-free readiness, provenance, ground-truth package audit, exact-matching strategy, and Stage 2B-1A logon matching at commit 330ac6a.

### Planned

- Full CERT r6.2 preprocessing and model-ready sequence generation after the preregistered readiness stage.

## Objective 2 â€” Unified sequenceâ€“ensemble modelling

**Chapter 3 phase:** Phase 2, model development and comparative evaluation.

### Completed

- CERT r4.2 architecture feasibility and ablation work.
- CERT r5.2 frozen-encoder confirmation.
- CERT r5.2 one-pass independent test for eligible baselines and the frozen-encoder ODST comparator.
- Teacher-anchored train/validation reproducibility for seeds 42, 52, and 62.
- Same-information attentionâ€“linear and ODST comparison.
- Component latency audit.
- Eight-tree seed-42 viability audit.

### Qualified findings

- The teacher-anchored student produced small and consistent train/validation differences relative to its attention teacher. This supports stabilisation and reproducibility, not a large performance-gain claim.
- The eight-tree ODST reduced parameters but was 7.4% slower than the sixteen-tree candidate under the audited implementation. Seeds 52 and 62 were therefore not run.
- ODST accounted for approximately 72â€“73% of device-resident inference time in the component audit.

### Planned

- Any outstanding independent evaluation of the final teacher-anchored student.
- Preregistered CERT r6.2 model stress testing.

## Objective 3 â€” Explanation and robustness

**Chapter 3 phase:** Phase 3, explainability and robustness assessment.

### Completed

- Attention faithfulness analysis.
- Reference-centred ODST explanation analysis.
- Multi-seed r5.2 portability confirmation.
- Controlled missing-source and continuous-noise robustness analyses.
- Route, tree, and leaf stability analysis with documented comparability limits.

### Qualified findings

- Explanation conclusions apply to the stated reference-centred procedure.
- Raw-ranking sensitivity results remain documented.
- Source dependencies differed between CERT releases.
- Missing-source evidence represents controlled ablation rather than a full deployment simulation.

## Final conclusions

Final thesis conclusions remain subject to completion of the planned independent and r6.2 experiments.

