# EDITOR-009 Root-Cause Report

Campaign: EDITOR-009 DEVELOPMENT RESCUE. Diagnostics labelled EDITOR009_DIAGNOSTIC_ONLY are not back-propagated into previous paper evidence.

## Why original C5 failed to produce useful predictive improvement

Three separate producing facts, not one slogan:

1. **Static anchors remain on until the last epoch.** `λ_logit = λ_route = 0.5` with no schedule (`LOGIT_ANCHOR_WEIGHT_STATIC = YES`, `ROUTE_ANCHOR_WEIGHT_STATIC = YES`). Late supervised departure is still penalised.
2. **Logit-anchor gradients oppose the task gradient at the trained C5 point** (cos ≈ −0.25 on a TRAIN batch). Weighted logit-anchor gradient norm exceeds the task gradient (0.29 vs 0.11). Route-anchor gradients are small and not opposed to the task (cos ≈ +0.15). The binding constraint is logit matching, not route matching.
3. **Anchoring is a benign-majority mean.** Prevalence on r5.2 TRAIN is 3957/788000 ≈ 0.502%. Neither anchor is class-balanced, so ~99.5% of the mean is negative windows.

Consequence: C5 stays teacher-rank equivalent (seed-42 logit correlation 0.996; disagreement 0.011%). C2 is allowed to change logit scale (`teacher_logit_deviation` 0.22 vs C5 0.0037) and even corrects 8 teacher errors on seed-42 validation, but C5 reverts 4 of those corrections. Validation PR-AUC of C5 vs C2 remains an essential tie (~+0.0017 on seed 42; not a useful predictive gain). C5 therefore **preserves teacher-relative fidelity and fails to produce a meaningful PR-AUC gain** because the student is not allowed to keep the few ranking changes that C2 makes, and those C2 changes were not helpful enough anyway.

## Why random-init + anchoring collapsed

This is **not** the same mechanism as the C2/C5 tie.

- `ROUTE_INDEX_IDENTITY_ASSUMED = YES`. Concatenated tree index `j` is compared to teacher tree `j`. That correspondence is inherited under teacher init and is **structurally invalid under random init**.
- Permuting C6 student tree indices multiplies route loss by ~26× (`ROUTE_ANCHOR_PERMUTATION_SENSITIVE = YES`). After training, C6 has adapted to the arbitrary raw index; post-hoc Hungarian matching does **not** reduce route loss, because the student already locked onto that index.
- R10 (init-time Hungarian matching, TRAIN-only, frozen assignment) still collapsed (seed-42 val PR-AUC 0.073). Historical C1 (random init, **no** anchors) also collapses to ~0.02–0.06. Random encoder+ODST therefore fails to enter a viable basin even without a mismatched route penalty. Invalid correspondence makes the route term meaningless; it is not the sole cause of collapse.

## Why ODST failed to clearly beat attention-linear

Again a separate mechanism.

- On the same r5.2 validation partition, attention-linear mean PR-AUC (0.9311) already matches teacher/C5 and exceeds C2. Seed 62 attention-linear is 0.9458.
- C5 routing is saturated (`route_probability_saturation` ≈ 0.990; EDITOR009_DIAGNOSTIC_ONLY). Effective capacity is used as a near-hard forest on an already strong attended representation.
- R7 (residual ODST, encoder frozen, zero leaf init) reproduces attention-linear seed-by-seed. That is evidence that **ODST residual headroom on the frozen linear representation is negligible**, not that a new nonlinear ranking was extracted.
- R8 (end-to-end residual) can move slightly past attention-linear on seed 42 but does not dominate C2 on all seeds and costs F1.

## Rescue classifications (predeclared rule, versus C2)

| condition | mean PR-AUC | Δ vs C2 mean | positive seeds | class |
| --- | ---: | ---: | ---: | --- |
| R2 route-only | 0.933616 | +0.00457 | 3/3 | CLEAR_DEVELOPMENT_RESCUE |
| R8 residual e2e | 0.933571 | +0.00453 | 2/3 | CLEAR_DEVELOPMENT_RESCUE |
| R7 residual head-only | 0.931509 | +0.00246 | 2/3 | CLEAR_DEVELOPMENT_RESCUE |

R2 is the paper-relevant rescue: same ODST architecture, drop logit anchoring, keep route anchoring. R7/R8 meet the C2 inequality largely by becoming attention-linear-like.
