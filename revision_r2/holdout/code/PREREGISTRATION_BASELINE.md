# R2 user-disjoint holdout preregistration

Frozen UTC: 2026-10-21T15:03:13.663514+00:00

- Universe: all 2,000 CERT r5.2 users. Stratum = insider user (>=1 answer-file malicious day anywhere in r5.2) vs non-insider.
- Split: sort user IDs; within each stratum shuffle with numpy.random.default_rng(20261022) and take round(0.25 × stratum size) as HOLDOUT; total HOLDOUT = 500 (adjust the larger stratum by ±1 only if rounding misses 500; record it). Remaining 1,500 = DEVELOPMENT.
- Retrained on DEVELOPMENT users only (TRAIN period windows; scaler refit on DEVELOPMENT users' TRAIN user-days; class weight w+ recomputed by the same 0.25·N−/N+ rule): T-OPT teachers (seeds 42/52/62, EDITOR-011 producing recipe), F00 task-only teacher-initialised control, F10 guidance-only, F11 = TA2 (L = L_cls + 0.5 L_teacher + 0.5 L_route), L1 teacher-guided attention–linear, RF_40, XGBoost_40 — each seeds 42/52/62, frozen recipes. Checkpoint selection and thresholds on DEVELOPMENT users' VALIDATION period only.
- Secondary (exploratory, R1-2): unidirectional-LSTM variant (hidden 128, so the 128-dim state is unchanged) with its own uni-LSTM T-OPT teachers and uni TA2, seeds 42/52/62, same recipe.
- Evaluation (LATER, not tonight; option B approved by Qasim, to be disclosed to the supervisor before scoring): HOLDOUT users' VALIDATION + TEST periods, stride-1 completed-window windows; secondary de-overlap offset-0 and endpoint views. One pass, frozen thresholds, no recalibration.
- Metrics: PR-AUC (average precision) and ranking excess (PR-AUC − prevalence). Primary contrasts: TA2 − XGBoost_40 and TA2 − F00, 3-seed mean. Secondary: TA2 − L1, TA2 − RF_40, F10 − F00, TA2 − uniTA2. Paired user-cluster bootstrap over HOLDOUT users, 2,000 replicates, rng seed 42, 95% percentile CI.
- Decision rules: CI entirely below 0 → "ranks below"; includes 0 → "comparable / not distinguishable"; entirely above 0 → "ranks above (bounded to unseen CERT r5.2 users)". All outcomes are reported. No re-runs after scoring.
