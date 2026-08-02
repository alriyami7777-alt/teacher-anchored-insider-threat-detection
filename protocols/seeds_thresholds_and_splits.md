# Seeds, Thresholds, and Splits

## Fixed seeds

The retained random seeds for the final teacher-anchored CERT r5.2 students are:

- 42
- 52
- 62

## Validation-selected decision thresholds

These thresholds apply only to the final teacher-anchored CERT r5.2 validation
students:

| Seed | Threshold |
|---:|---:|
| 42 | 0.56 |
| 52 | 0.85 |
| 62 | 0.55 |

They must not be reassigned to other model families, datasets, or evidence
streams. In particular, the earlier guarded-test frozen-encoder ODST reference
used separately recorded validation-selected thresholds.

## Split and interpretation controls

- Thresholds are selected using validation data only.
- Per-user chronology is preserved.
- Sequence windows do not cross chronological partition boundaries.
- The CERT r5.2 partitions contain the same 2,000 users and therefore do not
  test entirely unseen-user generalisation.
- The guarded CERT r5.2 test results apply only to the predefined RF, XGBoost,
  attention-linear, and frozen-encoder ODST reference families.
- Final teacher-anchored student results are train/validation optimisation and
  reproducibility evidence, not final-student guarded-test evidence.
- Results from non-identical model, partition, threshold, or intervention
  settings require an explicit comparability qualification.
