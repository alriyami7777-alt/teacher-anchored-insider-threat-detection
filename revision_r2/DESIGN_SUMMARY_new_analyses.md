# R2 Revision — Design summary of the new analyses

> The binding pre-registration is `revision_r2/holdout/PREREGISTRATION_R2_HOLDOUT.md`. It is frozen and hashed before the split is materialised, and published once scoring is complete. This file is the design summary it was built from. **Decision (Qasim, 21 Oct 2026):** option B, meaning held-out users are evaluated on their VALIDATION + TEST periods. This is the single disclosed second use of the r5.2 TEST partition.

**Manuscript:** Access-2026-42960 — *Teacher-Guided Differentiable Sequence–Ensemble Learning for Explainable Insider Threat Detection*
**Status:** DRAFT 2026-10-21. Nothing in this document has been run yet. The protocol must be frozen (committed, SHA recorded) **before** any holdout data are touched.
**Why it matters:** IEEE Access allows only one resubmission. The holdout is used once. If the design changes after anyone looks at holdout results, it stops being untouched evidence and Reviewer 3's main objection stands.

---

## A. User-disjoint untouched holdout (answers R1-1, R3 main demand, R4-2)

### A1. Question
On CERT r5.2 users that **no model has ever been trained on, tuned on, or checkpoint-selected on**, how does the final teacher-guided ODST (TA2) rank compared with:
(i) the teacher-initialised task-only control,
(ii) matched attention–linear (L1),
(iii) RF-40,
(iv) XGBoost-40?

### A2. User split (fixed before any training)
- Universe: all 2,000 r5.2 users.
- Stratify by insider status (users with ≥1 answer-file malicious day vs. none).
- Split **1,500 development users / 500 holdout users**, i.e. 25% of each stratum, using `numpy.random.default_rng(20261022)` on the sorted user-ID list.
- Write the holdout user list's SHA-256 to the protocol freeze **before** training starts. The holdout list itself is never committed to the public repo (it contains CERT user IDs). Only its hash, counts and positive counts are published.
- Report: number of holdout users, holdout insiders, holdout positive windows, prevalence.

### A3. What is retrained (everything that saw holdout users before)
All previously frozen r5.2 models were trained on TRAIN-period windows of all 2,000 users. So every model is **retrained from scratch on the 1,500 development users only**, with the frozen hyperparameters and **no tuning**:
1. Scaler: fitted on development users' TRAIN-period user-days only.
2. Teachers (seeds 42/52/62): same producing recipe as the frozen teachers.
3. Students: task-only teacher-initialised control, guidance-only, route-only, TA2 (`L = L_cls + 0.5·L_teacher + 0.5·L_route`, `w+` recomputed from the development TRAIN windows by the same formula).
4. L1 attention–linear, RF-40, XGBoost-40: frozen recipes and hyperparameters.
5. **Checkpoint selection:** VALIDATION period of the **development users only**. Holdout users never enter selection.

### A4. Evaluation windows (holdout users only, evaluated once)
- **Primary:** completed-window task, stride-one windows over the holdout users' VALIDATION **and** TEST periods (the r5.2 TEST period is untouched for these new models, and these users were never trained on).
- **Secondary:** de-overlapped offset-0 view, and the endpoint task (same definitions as the paper).
- One pass. No threshold search, recalibration or model selection on holdout data.

### A5. Metrics and statistics (fixed now)
- Primary metric: PR-AUC (average precision), plus ranking excess = PR-AUC − prevalence.
- **Primary contrasts:** TA2 − XGBoost-40 and TA2 − task-only control. Mean over seeds 42/52/62.
- Secondary: TA2 − L1, TA2 − RF-40.
- Inference: paired **user-cluster bootstrap**, 2,000 replicates, protocol seed 42, holdout users resampled with replacement. 95% percentile CIs.
- **Decision rules (written now, applied mechanically):**
  - If the TA2 − XGBoost-40 CI lies below 0: report that XGBoost-40 ranks better on unseen users. Lead with the explanation claim; state the predictive claim as "competitive with/below a strong engineered-tabular baseline".
  - If the CI includes 0: "comparable ranking to XGBoost-40 on unseen users".
  - If the CI lies above 0: report the superiority, bounded to CERT r5.2 unseen users.
  - The same three rules apply to TA2 − task-only.
- Whatever the outcome, report it in the paper. There is no fallback re-run.

### A6. Compute budget and stop rule
- Estimated run count: 3 teachers + 4 student conditions × 3 seeds + L1 × 3 + RF × 3 + XGB × 3 = 27 trainings. ChatGPT's Phase 0 report gives GPU/timing to refine this.
- If a run crashes, it may be restarted with the identical config and seed. No config changes.

---

## B. Unidirectional / causal encoder (answers R1-2)
- Replace the Bi-LSTM with a **unidirectional LSTM, 128 units** (keeps the 128-dim state, so the attention and ODST input sizes are unchanged). Same TA2 objective and hyperparameters, seeds 42/52/62.
- Teachers: use the frozen teachers as-is (their logits are only targets). Note this in the paper.
- Evaluate on the **endpoint-defined task** (where bidirectionality matters most), the completed-window task on the standard r5.2 validation partition, **and** the user-disjoint holdout in A if compute allows.
- Report: PR-AUC and paired user-cluster CI for Bi-LSTM TA2 − Uni-LSTM TA2.
- Label: **exploratory** (not part of the confirmatory claim).

## C. Mapping ODST splits to raw telemetry (answers R1-3)
- Integrated Gradients (Captum), 50 steps, baseline = training-derived scaled median sequence (same reference as the paper's intervention test), from **each tree output** and from the final logit back to the 20×13 input.
- Aggregate |IG| per feature over days and per day over features, for the 484-sequence explanation cohort.
- Report the top features per tree, plus a completeness check (sum of IG ≈ output − baseline output).
- Label: **descriptive / exploratory**. Not presented as faithfulness evidence.

## D. Efficiency (answers R1-4, R2 complexity, R4-6)
- For TA2, L1, task-only, RF-40, XGBoost-40: parameter count (or tree/node count for RF/XGB), FLOPs per sequence (fvcore or thop for neural models; analytical for the ODST head), peak GPU/CPU memory, training wall-clock per epoch and total, inference latency per sequence and throughput at batch 1 and 1,024. Same machine, 3 repeats, report the median.
- Analytical complexity: Bi-LSTM O(T·H²), additive attention O(T·H·d_a), ODST O(M·D·F_in) with M=8 trees, D=4. Teacher ensemble cost appears in **training only**. Teachers are discarded at inference.

## E. Labelling of analyses in the revised paper (answers R4-2, R4-3)
| Analysis | Label |
|---|---|
| A. User-disjoint holdout, primary contrasts | **Confirmatory** (pre-registered here) |
| Eq. (18) r5.2 validation component contrast | Exploratory (validation also used for checkpoint selection) |
| Ten-seed extension | Exploratory stability |
| Non-overlapping offsets | Sensitivity views of one dataset, **not** independent replications |
| Endpoint task | Secondary, end-of-day assessment |
| r6.1 / r5.1 / r6.2 cross-release | Historical one-pass transfer evaluations (r6.1 pre-registered). Reported in full. |
| B, C, D | Exploratory / descriptive |

---
**Approval needed from Qasim before execution:** (1) the 1,500/500 stratified split and seed; (2) including the holdout users' TEST period in the evaluation windows; (3) the decision rules in A5; (4) the compute budget.
