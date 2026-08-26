# IEEE Access Resubmission Freeze — 25 August 2026

This note records the frozen state of the revised IEEE Access submission. It is
current-facing documentation. It does not modify, reinterpret or supersede any
historical frozen evidence, and in particular it does not modify the July 2026
manuscript checkpoint under `paper/manuscript/`.

## A. Submission identity

| Field | Value |
|---|---|
| Original manuscript ID | Access-2026-37987 |
| Original title | Teacher-Anchored Differentiable Sequence–Ensemble Learning for Insider Threat Detection |
| Revised title | Teacher-Guided Differentiable Sequence–Ensemble Learning for Explainable Insider Threat Detection |
| Resubmission | Completed |
| New manuscript ID | Access-2026-42960 |
| Revised manuscript length | 16 pages |
| Repository name | `teacher-anchored-insider-threat-detection`, retained unchanged for continuity |

```
RESUBMISSION_STATUS   = SUBMITTED
ORIGINAL_MANUSCRIPT_ID = Access-2026-37987
NEW_MANUSCRIPT_ID      = Access-2026-42960
```

The new manuscript ID was assigned after this freeze package was prepared.
The freeze-note filename retains its 2026-08-25 date for continuity.

## B. Evidence hierarchy

In descending authority:

1. Frozen implementation and evidence artefacts.
2. Producing configurations and run manifests.
3. Verified result tables.
4. Current manuscript wording.
5. Earlier README and status wording.

Where manuscript wording and frozen evidence disagree, frozen evidence governs.

## C. Historical and current model distinction

Two ODST configurations exist in this repository. Both are valid frozen records
of the stage that produced them, and neither supersedes the other as history.

| | Historical | Current |
|---|---|---|
| Recorded in | `paper/manuscript/` checkpoint of 29 July 2026; `EDITOR006B_STRICT_LOAD_RESULTS.json` | `EDITOR012_FACTORIAL_LOCK.json` and successors |
| Layers | 2 | 2 |
| Trees per layer | 8 | 4 |
| **Total trees** | **16** | **8** |
| Depth | 4 | 4 |
| Identity | pre-EDITOR configuration | ODST-046 |

In the historical checkpoint an eight-tree variant existed only as a rejected
ablation of the sixteen-tree model. That historical eight-tree ablation is not
the current eight-tree ODST-046 head. The two must not be conflated.

## D. Central repaired CERT r5.2 evidence

Mean validation PR-AUC over seeds 42, 52 and 62.

| Condition | Alias | Mean validation PR-AUC |
|---|---|---|
| F00 | C2-OPT, teacher-initialised task-only | 0.935324 |
| F10 | D-OPT, ensemble prediction guidance only | 0.942595 |
| F01 | R2-OPT, route regularisation only | 0.937496 |
| F11 | DR-OPT, final | 0.942842 |

- Final minus teacher-initialised task-only: **+0.007518**, positive on 3 of 3
  primary seeds.
- Paired user-cluster 95% confidence interval: **[0.000345, 0.018250]**.
- Interpretation: supported predictive value beyond teacher-informed
  initialisation.
- Route-only clean improvement: **NOT SUPPORTED**.
- Clean superiority of ODST over attention–linear: **NOT SUPPORTED**.
- Route fidelity: the final formulation restores teacher-relative routes
  relative to prediction-guidance-only, mean absolute error 0.002415 against
  0.007547, with a negligible predictive increment of +0.000247 whose confidence
  interval includes zero. Route regularisation is a structural-fidelity
  regulariser, not the predictive mechanism.

Provenance: branch `editor012-teacher-anchor-rescue`, commit `4bcf522`. Paths:
`review/editor012_teacher_anchor_rescue/02_factorial_confirmation/EDITOR012_PRIMARY_EFFECTS.json`,
`review/editor012_teacher_anchor_rescue/05_statistics/EDITOR012_CLUSTER_BOOTSTRAP.json`,
`review/editor012_teacher_anchor_rescue/07_paper_handover/EDITOR012_PAPER_RESCUE_HANDOVER.md`.

## E. Random-start negative result

Randomly initialised students were not rescued under the evaluated
teacher-guided protocol. Teacher-informed initialisation remains an important
optimisation condition. No claim of arbitrary-start optimisation stability is
made.

Provenance: `EDITOR_ISSUE_RANDOM_INIT_COLLAPSE` recorded as
`MECHANISTICALLY_EXPLAINED` in
`review/editor012_teacher_anchor_rescue/06_editor_response/EDITOR012_EDITOR_RESPONSE_EVIDENCE.json`.

## F. Historical CERT r5.2 test and final validation separation

The CERT r5.2 one-pass test evidence is historical guarded-reference evidence.
It applies to the eligible baselines and the frozen-encoder ODST comparator
under the recorded protocol. It must not be assigned to the final model.

The current CERT r5.2 evidence for the final model is train/validation evidence.

## G. Dependence-aware evidence

Completed-window non-overlapping analysis, primary offset 0:

- n = 4,000; positives = 47
- Final model PR-AUC = 0.947970
- Median across 20 offsets = 0.948755
- Final model above prevalence in 20 of 20 offsets

Status: **DEPENDENCE CONCERN RESOLVED WITH QUALIFICATION**. The principal
ranking signal survives direct de-overlapping. Component-level contrasts become
less certain, and not all pairwise model differences were independently
re-established.

Provenance: branch `editor029-endpoint-dependence-aware`, commit `28475d5`.
Paths: `review/editor029_endpoint_dependence/EDITOR029_PARTA_OFFSET0_RESULTS.json`,
`review/editor029_endpoint_dependence/EDITOR029_RUN_MANIFEST.json`,
`review/editor029_endpoint_dependence/EDITOR029_PARTA_RULING.json`.

## H. Endpoint-defined evidence

| Split | Sequences | Positives | Positive users | Prevalence |
|---|---|---|---|---|
| Train | 788,000 | 1,035 | 84 | 0.0013134517766497462 |
| Validation | 64,000 | 140 | 24 | 0.0021875 |

- Full endpoint final PR-AUC: `0.651843968810364`, paper-rounded **0.651844**.
- Non-overlapping offset-0 endpoint PR-AUC: `0.5717432867919343`, paper-rounded
  **0.571743**, at n = 4,000 with 13 positives.
- Endpoint positive weighting: 190.08816425120773 under the frozen formula
  `(n_neg / n_pos) * 0.25`.
- Data gate: PASS.

Interpretation: supports **end-of-day detection and assessment**. Does not
establish causal detection, pre-event forecasting, or real-time intra-day
prediction.

Provenance: branch `editor029-endpoint-dependence-aware`, commit `28475d5`.
Paths: `review/editor029_endpoint_dependence/EDITOR029_ENDPOINT_DATA_MANIFEST.json`,
`review/editor029_endpoint_dependence/EDITOR029_ENDPOINT_DEOVERLAP_OFFSET0.json`,
`review/editor029_endpoint_dependence/EDITOR029_RUN_MANIFEST.json`.

## I. Explanation boundary

- **Supported:** local signed reference-centred tree-contribution intervention.
- **Traceable only:** routes, reached leaves, tree outputs, memberships.
- **Not supported:** general global top-k tree-ranking faithfulness.

The earlier global top-k faithfulness claim is not reinstated.

## J. Controlled degraded-input boundary

Source-ablation and Gaussian-noise experiments are controlled degraded-input and
data-quality sensitivity analyses supporting structural stability. They are not
adversarial, evasion or poisoning robustness experiments and must not be
described as such.

## K. CERT r6.1 cross-release result

| Quantity | Value |
|---|---|
| Windows | 1,988,000 |
| Positives | 190 |
| Prevalence | 9.557344064386318e-05 |
| Final model PR-AUC | 9.445740146879832e-05 |

Frozen rulings: `R61_FINAL_TA2_RANKING_TRANSFER = NOT_SUPPORTED`;
`R61_TEACHER_GUIDANCE_VALUE = NOT_SUPPORTED`;
`R61_TA2_OVER_LINEAR_VALUE = NOT_SUPPORTED`;
`R61_ROUTE_ANCHOR_VALUE = CONSISTENT`;
`R61_ROUTE_STRUCTURAL_VALUE = SUPPORTED`;
`FINAL_PROSPECTIVELY_RESERVED_EVALUATION_COMPLETED = YES`;
`designated_final_model_unchanged = true`.

Approved frozen wording: "The prospectively reserved cross-release evaluation
exposed limited transfer to CERT r6.1 despite strong r5.2 validation
performance."

The supported route-structural result does not imply predictive transfer.
Representation shift between releases is recorded as the stronger post-result
diagnostic finding, not as a proven causal explanation.

Provenance: branch `editor024-r61-final-confirmation`, commit `23794a7`. Paths:
`review/editor024_r61_final_confirmation/EDITOR024_CLAIM_RULING.json`,
`review/editor024_r61_final_confirmation/EDITOR024_R61_PRIMARY_RESULTS.json`,
`review/editor024_r61_final_confirmation/EDITOR024_R61_PRIMARY_SUMMARY.csv`,
`review/editor024_r61_final_confirmation/EDITOR024_RESULT_FREEZE.md`.
Diagnostic follow-up: branch `editor025-r61-failure-autopsy`, commit `1f176bb`.

CERT r6.2 is outside the current manuscript.

## L. Same-user limitation

CERT r5.2 temporal partitions contain the same users. The reported evidence does
not test entirely unseen-user generalisation.

## M. Final architecture and training lock

Architecture, ODST-046:

| Component | Setting |
|---|---|
| Input | 20 × 13 |
| Temporal encoder | Single-layer bidirectional LSTM, hidden size 64 per direction |
| Temporal state | 128 dimensions |
| Dropout | p = 0.2, after Bi-LSTM hidden states, before temporal attention |
| Attention | Additive, hidden dimension 64 |
| ODST layers | 2 |
| Trees per layer | 4 |
| Total trees | 8 |
| Depth | 4 |
| ODST head dropout | 0.0 |
| Routing | sparsemax/sigmoid, temperature 0.5 |
| Tree dimension | 1 |
| Second-layer input | 132 |
| Readout | Mean of all 8 tree outputs before the sigmoid |

Second-layer input dimension: `132 = 128 + 4`, that is 128 context dimensions
plus 4 first-layer tree outputs. Status: **DERIVED_FROM_FROZEN_ARCHITECTURE**.
The literal value 132 is not itself a stored configuration field; both
components are frozen.

Training lock:

| Setting | Value |
|---|---|
| Seeds | 42, 52, 62 |
| Initialisation | Teacher-informed; matched students begin from same-seed teacher bytes |
| Prediction guidance | Equal weight from the three frozen teachers |
| Route target | Matched seed-specific teacher |
| Objective | `L = L_cls + 0.5·L_teacher + 0.5·L_route` |
| Batch size | 1024 |
| Encoder learning rate | 3e-5 |
| Attention learning rate | 3e-5 |
| ODST learning rate | 1e-3 |

Positive-class weighting. The value **49.535191** is
**DERIVED_FROM_FROZEN_COUNTS_AND_FORMULA** and is not a directly stored
configuration literal. It follows from the frozen teacher weighting
198.1407632044478 and the frozen student multiplier 0.25 under the frozen
formula `(n_neg / n_pos) * 0.25`:

```
198.1407632044478 × 0.25 = 49.53519080111195  ->  49.535191
```

The implied class counts, 3,957 positives and 784,043 negatives within the
frozen total of 788,000, are likewise derived and are not stored literals.

Provenance for the architecture and training lock: branch
`editor029-endpoint-dependence-aware`, commit `28475d5`. Paths:
`review/editor012_teacher_anchor_rescue/00_protocol/EDITOR012_FACTORIAL_LOCK.json`,
`review/editor012_teacher_anchor_rescue/EDITOR012_RUN_MANIFEST.json`,
`review/editor014_temporal_odst_value/00_protocol/EDITOR014_TEMPORAL_STATE_AUDIT.json`,
`review/editor029_endpoint_dependence/EDITOR029_PROTOCOL.json`,
`review/editor028_latent_alignment/EDITOR028_TEACHER_PROVENANCE.json`.

## N. Internal identifier mapping

| Identifier | Meaning |
|---|---|
| TA2 | Internal paper-handover identifier for the final repaired formulation |
| F11 | Factorial cell: ensemble prediction guidance enabled and route regularisation enabled |
| DR-OPT | Alias of the F11 condition |

All three denote the same final model: the teacher-guided, route-regularised
ODST. TA2 is recorded in the frozen evidence as a `temporary_identifier`
assigned at the EDITOR-012 paper handover. No expansion of the numeric suffix is
defined, and none should be invented. Related factorial identifiers are
F00 / C2-OPT, F10 / D-OPT and F01 / R2-OPT.

Reader-facing text should use "final teacher-guided, route-regularised ODST"
rather than leading with these internal identifiers.

## O. Historical checkpoint integrity note

Status: **PRE_EXISTING_HISTORICAL_CHECKPOINT_HASH_MISMATCH**

The 29 July 2026 manuscript checkpoint records 30 file hashes in
`paper/manuscript/SHA256SUMS.txt`. Twenty-nine verify. One does not:

| Field | Value |
|---|---|
| File | `paper/manuscript/source/README.md` |
| Actual SHA256 | `E9AA7CDA5E7F8734FCABD4CF5209675C19618F11A1F0B0538C520241764DF531` |
| Recorded SHA256 | `A9F06F6D2B35B4CD54E8D787094A69F8D23975CDCB09842280C0452412CC71F3` |
| Freeze commit | `45ea0a7` |

Findings:

- The mismatch already existed at freeze commit `45ea0a7`; the file and the
  manifest entered the repository in that same commit.
- No commit on any ref contains a version of the file matching the recorded
  hash.
- Line-ending conversion is excluded. The file is LF-only with a UTF-8 byte
  order mark, and `.gitattributes` was introduced in the same commit.
- The later 30 July 2026 checkpoint, commit `1933543` on branch
  `import-overleaf-2026-07-30-1900`, is internally consistent: its recorded and
  actual hashes agree.

The historical manifest is **not** repaired or regenerated. The discrepancy is
recorded here and the historical files remain unchanged.

## P. Freeze rule

No current paper claim should be changed without later frozen evidence or an
IEEE-requested revision. Historical frozen evidence, experiment manifests,
commit registries, branch names and experiment identifiers are preserved
unchanged.
