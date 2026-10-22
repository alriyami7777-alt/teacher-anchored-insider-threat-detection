# EDITOR-010 paper rescue handover

Gate: **MULTI_FACTOR_RESCUE_FOUND**

Best rescue condition: `P4_ET1` — ODST-046 head (4 trees × depth 4, temperature 0.5, head LR 1e-3) trained with producing WBCE plus equal-weight ensemble-teacher logit distillation. Route anchoring was OFF.

## What improved

| Comparator | Mean PR-AUC | Best-candidate Δ |
|---|---|---|
| P4_ET1 | 0.93952 | — |
| C2 | 0.92905 | +0.01047 |
| C5_original_paper | 0.93129 | +0.00823 |
| attention-linear | 0.93113 | +0.00839 |

- Positive ΔPR-AUC vs C2 on **3/3** seeds (CLEAR_DEVELOPMENT_RESCUE).
- Positive ΔPR-AUC vs attention-linear on **2/3** seeds.
- User-cluster bootstrap 95% CI vs C2: **[-0.023, +0.066]** (includes 0).
- User-cluster bootstrap 95% CI vs attention-linear: **[-0.030, +0.059]** (includes 0).

Cluster-aware intervals do **not** establish a significant user-clustered difference. The seed-count rescue rule is met; inferential support is weak.

## Where the gain came from

Primary factors, in order of evidence:

1. **ODST configuration / optimisation** — producing 8-tree, τ=1.0, lr=3e-4 is not near-optimum on INNER_SELECT. Best inner config is smaller, sharper, and uses a higher head LR (`ODST-046`).
2. **Teacher-quality / distillation** — ET1 was executed because the equal-weight teacher ensemble PR-AUC (0.93735) exceeded the best single teacher (0.93473). The increment is below the 0.01 consistency margin, so teacher *diversity* is **not** supported. Distilling the ensemble logits still produced the most reproducible full-r5.2 student.
3. **Not rare-event objective redesign** — class balancing, focal loss, and pairwise ranking did not consistently beat O0 across the tested heads.

Do **not** claim teacher *anchoring* caused the gain. ET1 has no route anchoring and does not isolate logit anchoring against a matched non-distilled twin on the same full-r5.2 encoder seeds. P1 (same ODST-046, O0, no distill) also met CLEAR_DEVELOPMENT_RESCUE but only 2/3 seeds vs C2 and regressed on seed 52.

## Flags

- `ODST_PREDICTIVE_HEADROOM_DEMONSTRATED = NO` — ranking-aware ODST did not beat attention-linear by a material, consistent margin.
- `TEACHER_DIVERSITY_HEADROOM = NOT_SUPPORTED` — ensemble − best teacher = +0.0026.
- `STRONGER_TEACHER_DISTILLATION_RESCUE = SUPPORTED` — ET1 mean PR-AUC > C2 on 3/3 seeds.
- An improved ODST **without** anchoring exists (`P1` / `ODST-046` + O0). That separates **ODST configuration** from **teacher anchoring**. Combining them belongs in a later prospectively controlled experiment.

## Process

Official r5.2 VALIDATION was opened for promoted candidates only after the INNER_SELECT promotion freeze.
r5.2 TEST was not accessed.
EDITOR-009 results were not read during EDITOR-010 selection.
No merge was performed.
