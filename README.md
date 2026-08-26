# Teacher-Guided Differentiable Sequence–Ensemble Learning for Explainable Insider Threat Detection

This repository is the paper-support and reproducibility repository for the
IEEE Access manuscript of the same title. It is not a general PhD companion
repository.

The repository name retains the original `teacher-anchored-insider-threat-detection`
wording for continuity, although the revised manuscript now uses
"Teacher-Guided".

The repository shares reviewed model and evaluation code, experiment protocols
and configuration templates, result summaries and provenance records,
explanation and robustness procedures, and documented limitations.

It does **not** distribute CERT datasets, answer files, user identifiers, model
checkpoints, large prediction arrays, or private organisational material.

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

## Key limitations

- CERT r5.2 temporal partitions contain the same users, so the evidence does not
  test entirely unseen-user generalisation.
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
- `protocols/` — objective-linked experimental protocols.
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

The initial repository uses a temporary all-rights-reserved notice. A public
open-source licence should be selected only after the code and data-sharing
position have been reviewed.
