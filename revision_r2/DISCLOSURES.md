# Disclosures for the IEEE Access revision (Access-2026-42960)

This file reports, in one place, results and selection steps that exist in this repository but were **not reported in the submitted manuscript**. Reviewer 3 asked for them to be disclosed. Every number below is copied from a frozen evidence file. The file path is given, and the branch is `editor015-residual-complementarity` unless stated otherwise. Machine-readable copies are in `results/tables/`.

## D1. XGBoost-40 on the same r5.2 validation partition

On the same 64,000-window r5.2 VALIDATION partition (728 positives), the engineered-tabular XGBoost on 40 window summaries ranks **above** the final teacher-guided ODST (TA2) on every seed.

| Model | Seed 42 | Seed 52 | Seed 62 | Mean PR-AUC |
|---|---|---|---|---|
| XGBoost-40 | 0.966922 | 0.964976 | 0.967762 | **0.966553** |
| TA2 (final, F11) | 0.945410 | 0.933707 | 0.949410 | 0.942842 |
| L1 teacher-guided attention–linear | 0.936869 | 0.936066 | 0.943708 | 0.938881 |
| Teacher-initialised task-only control (F00) | 0.944321 | 0.921471 | 0.940180 | 0.935324 |
| Frozen-encoder ODST (historical) | 0.933410 | 0.924468 | 0.934740 | 0.930873 |
| Attention–linear (historical) | 0.937882 | 0.909651 | 0.945848 | 0.931127 |
| RF-40 | 0.933282 | 0.927467 | 0.926858 | 0.929202 |

XGBoost-40 − TA2 = **+0.023711** (mean of per-seed differences +0.021512 / +0.031269 / +0.018352). TA2's validation PR-AUC is also the criterion that selected its checkpoint, so this comparison, if anything, favours TA2.
Sources: `review/editor007a_post006e_diagnostics/EDITOR007A_R52_VALIDATION_PARITY.csv`; `review/editor012_teacher_anchor_rescue/02_factorial_confirmation/EDITOR012_FACTORIAL_RESULTS.csv`; L1 from `review/editor013_odst_value_proof/02_validation_confirmation/EDITOR013_VALIDATION_RESULTS.csv`.

## D2. Formulation search before the Table 4 factorial

1. **Inner anchor search (EDITOR-012).** Six prediction-guidance formulations (A0–A5) were trained **without** the route term. The route term (λ = 0.5) was then added to the best two (A0, A3). That makes **8 candidates** in total. All were trained on seed 42 only, from the seed-42 teacher checkpoint. Training used INNER_TRAIN and selection used INNER_SELECT, a per-user chronological 80/20 calendar split of r5.2 TRAIN (622,000 / 128,000 windows; 38,000 boundary windows dropped). Official r5.2 VALIDATION was not used. Every candidate's score is in `results/tables/formulation_search_editor012_inner.csv`. **No candidate beat the incumbent A0 (ET1) formulation (0.936892), so none was promoted.**
2. **Upstream searches.** A0 (equal-weight ensemble logit MSE, λ = 0.5) and the ODST-046 head (2 layers × 4 trees, depth 4) were fixed by earlier campaigns, EDITOR-010 (ODST grid) and EDITOR-011 (ODST-046 lock and T-OPT teachers). Their result folders are being published on their own branches (see the README evidence map).
3. **Final F10-vs-F11 choice on official validation.** The factorial (F00, F10, F01, F11) was locked before results. TA2 = F11 (guidance + route) was then chosen over F10 (guidance only) by the larger mean validation gain over F00: 0.007518 vs 0.007271. The paired user-cluster bootstrap for F11 − F10 is +0.000262, 95% CI [−0.000518, 0.001374]. **The two are statistically indistinguishable, and the choice was made on the partition the paper reports.**
   Source: `review/editor012_teacher_anchor_rescue/02_factorial_confirmation/EDITOR012_PRIMARY_EFFECTS.json`, `05_statistics/EDITOR012_CLUSTER_BOOTSTRAP.json`, `src/editor012_rescue/campaign.py`.
4. **Later head searches (EDITOR-013/014/015, inner splits only).** None promoted a replacement. Linear heads with distillation were competitive with or better than TA2 on the inner splits; for example, in EDITOR-015, L1 scored 0.938174 vs TA2 0.931890 on INNER_SELECT.

## D3. Cross-release runs on CERT r5.1 and r6.2 (historical, frozen pre-TA2 model family)

The frozen pre-repair family (teacher-frozen ODST, C2, C5, attention–linear, RF-40, XGBoost-40; 18 models) was evaluated once on r5.1 and r6.2. Frozen r5.2 thresholds were used, with no target-side fitting. **TA2 itself was not evaluated on r5.1 or r6.2.**

| Release | Windows | Positives | Prevalence | Neural mean PR-AUC (range of family means) | XGBoost-40 | RF-40 | Recorded verdict |
|---|---|---|---|---|---|---|---|
| r5.1 | 996,000 | 461 | 0.000463 | 0.2614–0.2769 | 0.3954 | 0.3092 | Substantial ranking transfer **supported** |
| r6.2 | 1,988,000 | 715 | 0.000360 | 0.000432–0.000512 | 0.00776 | 0.00652 | Severe version-specific failure **supported** |

On r6.2, 42.9% of negative windows exceed the frozen decision thresholds, against 0.07% on r5.2 validation. Per-model, per-seed and per-view values (completed-window, endpoint, de-overlap offset 0) are in `results/tables/cross_version_r51_r62_frozen_family.csv`.
Sources: `review/editor007d_cross_version_synthesis/EDITOR007D_MODEL_PORTABILITY.csv`, `EDITOR007D_REPORT.md`, `review/editor007c1_r51_result_freeze/`.

## D4. The ten-seed extension depends on three teacher starts

The seven extra seeds start from the teacher checkpoints of seeds 42/52/62 in rotation, so the ten seeds are **not independent**. TA2 − control is positive in 9/10 seeds (mean +0.006157). Grouped by teacher start, the mean gain is +0.000863 from teacher 42 (n = 4), +0.011904 from teacher 52 (n = 3) and +0.007469 from teacher 62 (n = 3). Seed 52 supplies 54% of the three-seed effect.
Source: `review/editor012_teacher_anchor_rescue/03_extended_stability/`.

## D5. Environment record

`requirements.txt` was a placeholder until this revision. It is now pinned from the exported training environment (Python 3.11.9, PyTorch 2.11.0+cu128, NumPy 2.4.6, scikit-learn 1.9.0, XGBoost 3.2.0), which matches the frozen EDITOR-023/024 run manifests; see `revision_r2/ENVIRONMENT.md`. The version line in the submitted manuscript (Python 3.11.15, PyTorch 2.12.1+cu130) described a different Conda environment and is corrected in the revision.
