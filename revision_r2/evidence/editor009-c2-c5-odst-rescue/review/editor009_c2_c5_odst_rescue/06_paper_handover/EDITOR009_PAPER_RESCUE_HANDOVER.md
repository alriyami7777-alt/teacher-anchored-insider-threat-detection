# EDITOR-009 Paper Rescue Handover

Campaign: **EDITOR-009 DEVELOPMENT RESCUE**

Gate: **RESCUE_SUCCESS_CANDIDATE_FOUND**

r5.2 TEST was not accessed. r5.1 and r6.2 were not run. Historical C5 remains historical C5.

## Best rescue condition

**Identifier:** `EDITOR009_R2_ROUTE_ANCHOR_ONLY`

This is authorised candidate R2 (teacher initialisation + task loss + current route anchor + **no logit anchor**). It is the historical C4 condition, reused under a new EDITOR-009 identifier. It is **not** C5.

Exact optimisation delta versus original C5:

- C5: `L = L_task + 0.5 L_logit + 0.5 L_route`
- R2: `L = L_task + 0.5 L_route`  (`λ_logit = 0`)

Architecture is unchanged (Bi-LSTM + attention + sparsemax-sigmoid ODST, 2×8 trees, depth 4).

Frozen checkpoints (do not confuse with deny-listed ablation C5):

| seed | checkpoint | SHA-256 |
| --- | --- | --- |
| 42 | `.../r52_teacher_anchoring_ablation_v1/C4/seed42/best_student.pt` | `4a429acab3b29438a8fa35611496a32f3a4461e5f09eaef9de7824f3bebe0be5` |
| 52 | `.../C4/seed52/best_student.pt` | `0ebf358de21b05524199550679a86b7c1772f5fbc414a12bad9374406974215a` |
| 62 | `.../C4/seed62/best_student.pt` | `a9012a8e78be56c64c97f8f358b50e558d2da0d4441ad537622db8c0c1772fdb` |

### Development PR-AUC (CERT r5.2 VALIDATION)

| seed | R2 | C2 | C5_original_paper | attention-linear | teacher |
| --- | ---: | ---: | ---: | ---: | ---: |
| 42 | 0.936268 | 0.931842 | 0.933578 | 0.937875 | 0.933400 |
| 52 | 0.927663 | 0.924105 | 0.924607 | 0.909639 | 0.924454 |
| 62 | 0.936917 | 0.931190 | 0.935697 | 0.945840 | 0.934725 |
| mean | **0.933616** | 0.929046 | 0.931294 | 0.931118 | 0.930860 |

- Δ vs C2: +0.00443 / +0.00356 / +0.00573; **mean +0.00457; 3/3 seeds positive**
- Δ vs attention-linear: −0.00161 / +0.01802 / −0.00892; mean +0.00250; **1/3 seeds positive**
- F1 does not deteriorate materially versus C2 (0.916/0.906/0.901 vs 0.912/0.903/0.893)

Classification under the predeclared rule: **CLEAR_DEVELOPMENT_RESCUE** versus C2. This is **not** a claim of superiority over attention-linear, and it is **not** final-test evidence.

## Other promoted candidates (mechanism qualification)

R7 (residual ODST, encoder frozen) and R8 (residual ODST end-to-end) also meet the letter of CLEAR_DEVELOPMENT_RESCUE versus C2 (mean PR-AUC > C2; positive on 2/3 seeds).

They should **not** be described as a repaired teacher-anchored ODST:

- R7 seed-wise PR-AUC tracks frozen attention-linear (42: 0.9377≈0.9379; 52: 0.9112≈0.9096; 62: 0.9456≈0.9458). Residual ODST starts at zero leaf responses; best epoch is often 1. This is the linear reference plus a near-null residual, not new nonlinear ranking signal.
- R8 can slightly exceed attention-linear on seed 42 (0.9384 vs 0.9379) but F1 falls (0.909 vs C2 0.912 / AL 0.919) and seed 52 remains below C2.

If the paper's core architecture and explanation role must be preserved, **R2 is the only promoted candidate that stays inside teacher-anchored ODST**.

## What did not rescue prediction

- Annealed C5 weights (R3/R4): seed-42 PR-AUC ≈ C5, not a stable gain over C2 after promotion ranking.
- Selective teacher-correct anchoring (R5) and class-balanced anchoring (R6): small seed-42 gains over C2 (~+0.0027) that were not in the top-three promotion set and were not three-seed confirmed.
- Correspondence-aware random-init (R10): still collapsed (val PR-AUC 0.073). Random-init failure is not repaired by Hungarian tree matching. Historical C1 (random, no anchors) also collapses, so invalid route index identity is not the sole cause.

## Next recommended experiment

Freeze `EDITOR009_R2_ROUTE_ANCHOR_ONLY` as a distinct condition (do not relabel historical C5). Do **not** open r5.2 TEST in the next step until that freeze is complete. A separate, optional confirmation may keep R8 as an architecture-delta residual head; that is not the teacher-anchored ODST rescue.
