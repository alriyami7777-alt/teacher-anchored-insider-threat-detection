# Protocol: CERT r5.2 Evaluation

> **Status note:** This document is a historical July 2026 protocol scaffold retained for provenance. It predates the repaired teacher-guided IEEE Access resubmission and is not the current paper protocol. Current paper-facing claims and producing evidence are governed by the later frozen EDITOR protocols and resubmission freeze record.

**Aim:** Confirm model behaviour on CERT r5.2 under locked controls.


## Controls

- Seeds 42, 52, and 62.
- Validation-selected threshold.
- No repeated use of the independent test set.
- Same-information comparisons reported separately from 40-feature structured baselines.
- Frozen-encoder and teacher-anchored results must not be conflated.

## Interpretation

Small student–teacher differences may support reproducibility or stabilisation. They must not be described as substantial performance improvements.
