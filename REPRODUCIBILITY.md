# Reproducibility Requirements

## Fixed experimental controls

- Sequence length: 20 days.
- Sequence stride: 1 day.
- Daily feature count: 13.
- Primary metric: area under the precision–recall curve.
- Supporting metrics: F1, precision, recall, false positives, false negatives, Brier score, and log loss.
- Validation-selected decision threshold.
- Standard seeds: 42, 52, and 62.
- Chronological per-user splits.
- No cross-boundary sequence windows.
- Independent test data must not be used for threshold selection, architecture selection, or repeated tuning.

## Required provenance for each experiment

Each completed experiment should record:

1. experiment identifier;
2. research objective;
3. Chapter 3 phase;
4. dataset release and split;
5. branch and commit hash;
6. configuration file;
7. random seed;
8. input and split hashes where permitted;
9. threshold-selection rule;
10. output table or figure;
11. evidence status;
12. known limitations.

## Teacher-anchored procedure

The attention-based teacher is used only during student training. The student must be evaluated independently at inference. Any comparison must clearly identify whether it concerns training/validation evidence, a frozen comparator, or an independent test result.

## Reporting rule

Do not combine results from related but non-identical settings without an explicit comparability note.
