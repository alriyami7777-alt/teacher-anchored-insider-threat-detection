# EDITOR-007B — EDITOR-007A scientific-parity adjudication freeze

Frozen ruling: **EDITOR007A_R_SCIENTIFIC_PARITY_WITH_NUMERICAL_NONIDENTITY**

This freeze supersedes the EDITOR-007A *interpretation* of the automated exact-identity gate. It does **not** erase that historical automated result.

## Dual record (both preserved)

| Record | Value |
| --- | --- |
| AUTOMATED_PROTOCOL_GATE | **FAIL_EXACT_NUMERICAL_IDENTITY** |
| Automated decision (historical) | `EDITOR007A_R62_INTERPRETATION_BLOCKED_MECHANICAL_FAILURE` |
| INDEPENDENT_SCIENTIFIC_ADJUDICATION | **SCIENTIFIC_PARITY_WITH_NUMERICAL_NONIDENTITY** |
| Independent ruling | `EDITOR007A_R_SCIENTIFIC_PARITY_WITH_NUMERICAL_NONIDENTITY` |

Do not claim the exact-identity automated gate never failed.

## Key evidence (from frozen EDITOR-007A diagnostics)

- 17/18 r5.2 validation confusion matrices exact.
- C2 seed 62 differs by one FP: replay = 30, producing = 31; FN exact.
- Neural PR-AUC replay differences approximately 1e-6 to 3e-5.
- RF seed 42 difference = one floating-point ULP.
- RF seeds 52/62 and all three XGBoost seeds exact.
- All 18 replay models retain `RAW_ORIENTATION_HIGHER`.
- No score-sign / class-column / loader inversion found.
- No observed replay discrepancy is remotely capable of explaining r5.2 PR-AUC ~0.93 versus r6.2 ~0.0004.
- r6.2 negative frozen-threshold exceedance increases from approximately 0.01 on r5.2 validation to approximately 0.41–0.45.
- Largest observed scaled feature shifts include `email_count`, `has_file_activity`, and `total_events`.

## Scientific ruling

| Flag | Value |
| --- | --- |
| MECHANICAL_CAUSE_CAPABLE_OF_EXPLAINING_R62_COLLAPSE | **NO** |
| R62_INTERPRETATION_MAY_REOPEN | **YES** |
| R51_SECONDARY_STRESS_WARRANTED | **YES** |

## Why CERT r5.1 is allowed

CERT r5.1 was assigned before r6.2 predictive access as **R51_SECONDARY_STRESS_ONLY**.

It is not a replacement primary test, not a rescue dataset chosen because r6.2 failed, and not a new training domain in EDITOR-007B.

Purpose: distinguish among (A) broad cross-version portability failure; (B) r6.2-specific / extreme-rarity shift; (C) ranking transfer with threshold / calibration failure; (D) model-family-specific portability differences.

C2 remains the first-class control. C5 remains teacher initialisation + logit anchoring + route anchoring. Future r5.1 results must not be used to claim that teacher anchoring improves prediction unless independently supported, and even then r5.1 remains secondary-stress evidence.

## This freeze does not authorise scoring

EDITOR-007B does not score CERT r5.1, does not rerun CERT r6.2, and does not create a true r5.1 predictive authorisation.
