# Teacher-Guided Differentiable Sequence–Ensemble Learning for Explainable Insider Threat Detection

This repository supports the IEEE Access submission **Access-2026-42960**,
*Teacher-Guided Differentiable Sequence–Ensemble Learning for Explainable
Insider Threat Detection* (Alriyami and Mohamad). It holds the code, protocols,
frozen results and provenance records for that paper only. Results added for
the second-round revision (R2) are in `revision_r2/`.

The repository was renamed on 22 October 2026 from
`teacher-anchored-insider-threat-detection` to
`teacher-guided-insider-threat-detection` to match the revised manuscript
title. GitHub redirects the old URL, so links in earlier versions of the
manuscript still resolve.

The repository shares reviewed model and evaluation code, experiment protocols
and configuration templates, result summaries and provenance records,
explanation and robustness procedures, and documented limitations.

It does **not** distribute CERT datasets, answer files, raw user identifiers (exported evidence uses pseudonyms), model
checkpoints, large prediction arrays, or private organisational material.

## Revision R2 (IEEE Access, Access-2026-42960): where to find each result

**Table-by-table and figure-by-figure map:** [`revision_r2/RESULTS_MAP.md`](revision_r2/RESULTS_MAP.md) lists every table and figure in the R2 manuscript by LaTeX label, with its output files, producing code, seeds and settings. New R2 analyses are in `revision_r2/phase5/` (cross-release, robustness, operational, calibration, statistics), `revision_r2/phase6/` (TRACE re-runs), `revision_r2/phase6b/` (representation and explanation tests on unseen users), `revision_r2/analysis/` (efficiency profile, feature-study record) and `revision_r2/paper_figures/` (plotting scripts). Each phase folder has its report, CSVs, figures and `reproducibility_code/`; the pre-push audit is `revision_r2/PUBLIC_RELEASE_AUDIT_PHASE5_6.md`.

The final model is called **TRACE** in the revised manuscript (internal label TA2/F11 in the evidence files).

| Paper item | Repository location |
|---|---|
| Pre-registered user-disjoint holdout protocol, with Amendment 1 (TRAIN + VALIDATION periods; r5.2 TEST sealed) and Amendment 2 (eight additional baselines), each SHA-256 receipted | `revision_r2/holdout/PREREGISTRATION_R2_HOLDOUT.md` |
| Split receipt (counts and list hashes only) | `revision_r2/holdout/SPLIT_RECEIPT.json` |
| Training logs and frozen-model hashes | `revision_r2/holdout/TRAINING_LOG.csv`, `revision_r2/holdout/phase4/TRAINING_LOG_PHASE4.csv`, `MODELS_FROZEN_PHASE4.json` |
| Table 10 / Fig. 10 (unseen users, 17 models, all views) | `revision_r2/holdout/phase4/HOLDOUT_RESULTS.csv`, `HOLDOUT_CONTRASTS.csv`, `CHATGPT_PHASE4_REPORT.md`; plotting script `revision_r2/holdout/figures/plot_holdout.py` |
| Integrated Gradients and TreeSHAP faithfulness (Section IV-E) | `revision_r2/explanation/` (validation cohort) and `revision_r2/explanation_holdout/` (unseen users) |
| Frozen evidence behind every other table and figure (redacted: user IDs replaced by `U_` + first 10 hex digits of SHA-256) | `revision_r2/evidence/` with `EXPORT_MANIFEST.csv` and `FINAL_SCAN.json` |
| Supplementary material source | `revision_r2/Supplementary_Material.tex` |
| Disclosures (model-selection history, AI use, exclusions) | `revision_r2/DISCLOSURES.md`, `revision_r2/EXCLUDED_FROM_PUBLIC_COPY.md` |

CERT data, answer files, raw user identifiers and model checkpoints are not distributed. Some run logs contain local Windows paths of the authors' workstation; they carry no data.

## Current architecture

Input sequences are 20 days × 13 daily behavioural features.

| Stage | Configuration |
|---|---|
| Temporal encoder | Single-layer bidirectional LSTM, hidden size 64 per direction, 128-dimensional temporal state |
| Dropout | p = 0.2, after the Bi-LSTM hidden states and before temporal attention |
| Temporal attention | Additive attention, hidden dimension 64 |
| Tree head (ODST-046) | 2 layers × 4 trees per layer = 8 trees in total, depth 4, head dropout 0.0, sparsemax/sigmoid routing, routing temperature 0.5 |
| Second-layer input | 132 dimensions = 128 context dimensions + 4 first-layer tree outputs |
| Readout | Mean of all 8 tree outputs before the sigmoid |

The current eight-tree head is distinct from the sixteen-tree configuration in
the historical July 2026 manuscript checkpoint. Both are valid frozen records of
the stage that produced them.

## Teacher-guided optimisation

Students are trained on CERT r5.2 with seeds 42, 52 and 62 under
`L = L_cls + 0.5·L_teacher + 0.5·L_route`, batch size 1024, encoder and
attention learning rate 3e-5, and ODST learning rate 1e-3.

Component roles, as separated by the frozen factorial:

- Teacher-informed initialisation remains an important optimisation condition.
  Randomly initialised students were not rescued under the evaluated
  teacher-guided protocol.
- Ensemble-teacher prediction guidance, taken with equal weight from the three
  frozen teachers, supplies the supported clean predictive improvement beyond
  teacher-informed initialisation.
- Matched-teacher route regularisation, in which the matched seed-specific
  teacher supplies the route target, mainly constrains route drift and improves
  structural and degraded-input behaviour.
- ODST is an explanation-oriented differentiable head. Clean predictive
  superiority over attention–linear was not established.

Attention–linear remains a strong matched neural reference, and random forest
and XGBoost remain strong engineered-tabular comparators.

## Evidence streams

- **CERT r4.2** — development evidence.
- **CERT r5.2** — historical guarded-reference evidence, plus the final
  train/validation evidence.
- **CERT r6.1** — one-pass cross-release evidence.

CERT r6.2 is outside the current manuscript.

## Key supported findings

**Final CERT r5.2 validation, mean over seeds 42, 52 and 62.**

| Model | Mean validation PR-AUC |
|---|---|
| Teacher-initialised task-only ODST | 0.935324 |
| Final teacher-guided, route-regularised ODST | 0.942842 |

The difference is +0.007518, with a paired user-cluster 95% confidence interval
of [0.000345, 0.018250]. This supports predictive value beyond teacher-informed
initialisation. A route-only clean improvement is **not supported**, and clean
superiority of ODST over attention–linear is **not supported**.

**Dependence-aware confirmation.** On completed-window non-overlapping data at
primary offset 0 (n = 4,000; 47 positives), the final model reached PR-AUC
0.947970, with a median of 0.948755 across 20 offsets and performance above
prevalence in 20 of 20 offsets. The principal ranking signal survives direct
de-overlapping, while component-level contrasts become less certain: dependence
concern resolved with qualification. Not all pairwise model differences were
independently re-established.

**Endpoint-defined evaluation.** Training used 788,000 sequences with 1,035
positives across 84 users. Validation used 64,000 sequences with 140 positives
across 24 users, at prevalence 0.0021875. The final full endpoint PR-AUC was
0.651844, and the non-overlapping offset-0 endpoint PR-AUC was 0.571743
(n = 4,000; 13 positives). This supports end-of-day detection and assessment. It
does not establish causal detection, pre-event forecasting, or real-time
intra-day prediction.

**CERT r6.1 cross-release boundary.** On 1,988,000 windows with 190 positives,
at prevalence 9.557344e-05, the final model reached PR-AUC 9.445740e-05. Ranking
transfer to CERT r6.1 is **not supported**: the prospectively reserved
cross-release evaluation exposed limited transfer to CERT r6.1 despite strong
r5.2 validation performance. The route-structural result remains supported and
does not imply predictive transfer.

## IEEE Access revision R2 (Access-2026-42960): where every result lives

This section answers the reviewers' request that the repository support every analysis reported in the paper.

| Paper result | Frozen source (branch @ commit : path) | Copy in this branch |
|---|---|---|
| r5.2 validation factorial, Eq. (18), ten-seed extension | `editor012-teacher-anchor-rescue` @ `4bcf522` : `review/editor012_teacher_anchor_rescue/` | `results/tables/r52_validation_all_models.csv`, `results/tables/ten_seed_extension_extra_seeds.csv` |
| Formulation search before the factorial (8 candidates) | same : `01_inner_anchor_search/` | `results/tables/formulation_search_editor012_inner.csv` |
| XGBoost-40 / RF-40 on the same r5.2 validation partition | `editor015-residual-complementarity` @ `d8e1d04` : `review/editor007a_post006e_diagnostics/EDITOR007A_R52_VALIDATION_PARITY.csv` | `results/tables/r52_validation_all_models.csv` |
| CERT r5.1 and r6.2 (frozen pre-TA2 family) | same : `review/editor007d_cross_version_synthesis/` | `results/tables/cross_version_r51_r62_frozen_family.csv` |
| Non-overlapping and endpoint analyses | `editor029-endpoint-dependence-aware` @ `28475d5` : `review/editor029_endpoint_dependence/` | `evidence/` (redacted export) |
| CERT r6.1 cross-release | `editor024-r61-final-confirmation` @ `23794a7` : `review/editor024_r61_final_confirmation/` | `evidence/` (redacted export) |
| Explanation and degraded-input analyses | `editor017-…` @ `c75321a`, `editor023-…` @ `a480fa2` | `evidence/` (redacted export) |
| User-disjoint untouched holdout (pre-registered) | new, see `revision_r2/` | `revision_r2/holdout/` |

- **Disclosures** of results and selection steps that the submitted manuscript did not report: `revision_r2/DISCLOSURES.md`.
- **Claim-to-evidence matrix:** `review/CLAIM_EVIDENCE_MATRIX.csv`.
- **Pinned environment:** `requirements.txt`, `revision_r2/ENVIRONMENT.md`.
- **CERT user identifiers** (synthetic, from the public CERT generator) are pseudonymised in the `evidence/` export: each identifier is replaced consistently by `U_` + the first 10 hex characters of its SHA-256. This is pseudonymisation, not irreversible anonymisation. `evidence/EXPORT_MANIFEST.csv` records the SHA-256 of every original and exported file, so each exported file can be matched to its frozen original. Binary arrays, predictions and checkpoints are listed but not published.
- **Historical branches.** `editor015-residual-complementarity` is a superseded working branch, kept unchanged for transparency.

## Key limitations

- CERT r5.2 temporal partitions contain the same users. Unseen-user generalisation
  is tested only by the R2 pre-registered user-disjoint holdout (`revision_r2/`).
- Explanation support is bounded. The local signed reference-centred
  tree-contribution intervention is supported. Routes, reached leaves, tree
  outputs and memberships are traceable internal evidence only. General global
  top-k tree-ranking faithfulness is not supported.
- Missing-source and Gaussian-noise experiments are controlled degraded-input
  and data-quality sensitivity analyses, not adversarial robustness experiments.
- Overlapping sequence windows are correlated observations.

See `KNOWN_LIMITATIONS.md` for the complete list.

## Repository map

- `docs/IEEE_ACCESS_RESUBMISSION_FREEZE_2026-08-25.md` — current resubmission freeze record.
- `STATUS.md` — current evidence classification.
- `REPRODUCIBILITY.md` — reproducibility requirements.
- `DATA_AVAILABILITY.md` — dataset restrictions and expected local layout.
- `KNOWN_LIMITATIONS.md` — protocol and interpretation limits.
- `protocols/` — experimental protocols for the analyses reported in the paper.
- `manifests/` — experiment registry and result provenance.
- `paper/manuscript/` — historical manuscript checkpoint, retained unchanged.
- `results/tables/` — compact manuscript-facing result tables.
- `src/` and `scripts/` — reviewed implementation only.

## Important interpretation rule

Interpret results according to their recorded evidence role: development,
historical guarded-test, final validation, sensitivity, or cross-release
evidence. Each result must carry that role explicitly, and roles must not be
substituted for one another.

## Local setup

See `SETUP_WINDOWS.md`.

## Licence

Code and documentation: MIT (see `LICENSE`). The CERT Insider Threat datasets are **not** redistributed here; they remain subject to their providers' terms.
