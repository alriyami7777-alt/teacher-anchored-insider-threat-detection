# EDITOR-006B1 — Focused Hardening of the Frozen External-Inference Harness

Verdict: **EDITOR006B1_HARDENING_COMPLETE_WITH_QUALIFICATIONS**

This task applied a small auditable delta to the EDITOR-006B harness. It did **not** run CERT r6.2 predictive inference, did **not** open an r6.2 input bundle, did **not** create a valid external-authorisation file, and did **not** overwrite `review/editor006b_harness/`.

Fixture scores are engineering validation only and are not scientific results.

---

## TABLE 1 — HARDENING DELTA

| Finding | Status | Exact changed files |
| --- | --- | --- |
| H1 authorization binding | **RESOLVED** | `src/editor006b_harness/cli.py`, `tests/test_editor006b_external_gate.py`, `scripts/run_editor006b_harness.py` |
| H2 streaming inference | **RESOLVED** | `src/editor006b_harness/input_bundle.py` (`DenseDailyWindowProvider`), `src/editor006b_harness/scoring.py` (`write_scores_phase_streaming`, `stream_scores_from_provider`), `tests/test_editor006b_hardening_streaming.py` |
| H3 mechanism exactness | **RESOLVED** | `src/editor006b_harness/mechanism.py` (removed mean-mass unused-leaf and `tree_contribution_pearson_proxy`; paper-facing registry is EXACT_FROZEN only), `tests/test_editor006b_hardening_mechanism.py` |
| H4 source hash pinning | **RESOLVED** | `src/editor006b_harness/safety.py` (expected producing SHAs), `src/editor006b_harness/model_loaders.py` (`producing_source_preflight` before import/construction), `tests/test_editor006b_hardening_source.py` |
| H5 scenario metadata | **RESOLVED** | `src/editor006b_harness/input_bundle.py` (`official_incident_id`, `answer_scenario_ids`, `endpoint_answer_scenario_ids`), `src/editor006b_harness/scoring.py` (`SEQUENCE_METADATA.json`), `src/editor006b_harness/metrics.py`, `tests/test_editor006b_hardening_metadata.py` |

Qualifications (do not reopen H1–H5 as unresolved):

1. Unused-leaf fraction and tree-contribution rho are **DISABLED_NOT_REPRODUCIBLE** rather than reimplemented. The producing C1–C6 ablation used mean leaf mass `< 1e-4`, which is not the paper max-over-samples definition; training-median tree references are not pinned for external C2/C5 analysis. Mean-mass and scalar-logit Pearson were not substituted.
2. EDITOR-006B1 still refuses to open any r6.2 bundle even after schema checks. No genuine r6.2 authorisation artefact was written.
3. Paper-support copies of `architecture.py` / `odst.py` remain hash-mismatched versus producing files. The harness continues to import the authentic producing paths and now **aborts** if those SHAs drift.
4. Scaler closed-loop was re-run on the r5.2 TRAIN NPZ (`exact_equality=True`). Parquet reconstruction was not repeated in this delta (already PASS in EDITOR-006B).

---

## TABLE 2 — SOURCE-HASH PREFLIGHT

| component | source path | expected SHA | observed SHA | status |
| --- | --- | --- | --- | --- |
| teacher_c2_c5_architecture | `C:\PhD\07_Projects\cert-r42-feasibility\scripts\prototype_v3_node\architecture.py` | `9867b0c266f3b735d138e2d8d53f0d3f5c5c644e25302c10c25e2f4677560abd` | `9867b0c266f3b735d138e2d8d53f0d3f5c5c644e25302c10c25e2f4677560abd` | MATCH |
| odst_implementation | `C:\PhD\07_Projects\cert-r42-feasibility\scripts\prototype_v3_node\odst.py` | `95764ce80a7c80529108d8d6b72f6bd06896c39d065f7e475c12dce8421417bb` | `95764ce80a7c80529108d8d6b72f6bd06896c39d065f7e475c12dce8421417bb` | MATCH |
| attention_linear | `C:\PhD\07_Projects\cert-r42-feasibility\scripts\models\sequence_ensemble.py` | `43f16bce9c09305c7578d319dadf4c23c6c18cbe70fd7dcc1fda0114c86d6475` | `43f16bce9c09305c7578d319dadf4c23c6c18cbe70fd7dcc1fda0114c86d6475` | MATCH |
| rf_xgb_aggregator | `C:\PhD\07_Projects\cert-r52-locked-baselines\scripts\r52_locked_baselines\data.py` | `dd47330f82791bc7c56d3d6019ce80bcd6ca31f497b9fffeabc9165f35b1b2f9` | `dd47330f82791bc7c56d3d6019ce80bcd6ca31f497b9fffeabc9165f35b1b2f9` | MATCH |

Gate executes **before** architecture/model construction. Tampered synthetic source fixture → abort; matching SHA → continue.

---

## TABLE 3 — EXTERNAL AUTHORIZATION TESTS

| Case | Result | Bundle open invoked |
| --- | --- | --- |
| missing bundle hash | PASS (abort) | never |
| wrong bundle hash | PASS (abort) | never |
| wrong task ID | PASS (abort) | never |
| wrong dataset ID | PASS (abort) | never |
| wrong contract hash | PASS (abort) | never |
| wrong harness hash | PASS (abort) | never |
| wrong allow-list hash | PASS (abort) | never |
| `predictive_external_run_authorised=false` | PASS (abort) | never |
| malformed timestamp | PASS (abort) | never |
| absent authorisation | PASS (abort) | never |

Order enforced: read auth → validate schema → validate expected hashes/ids → only then open. EDITOR-006B1 `open_external_input_bundle()` always refuses. No valid r6.2 authorisation file was created.

Canonical required fields:

`task_id`, `dataset_id`, `input_bundle_manifest_sha256`, `contract_bundle_sha256`, `harness_code_sha256`, `model_allowlist_sha256`, `authorised_timestamp`, `predictive_external_run_authorised`

Exact-value checks (not mere presence) for the six id/hash fields. `authorised_timestamp` must be non-empty ISO-8601.

---

## TABLE 4 — STREAMING / MEMORY-SAFETY TESTS

| Test | Result |
| --- | --- |
| H05 provider called batchwise; no full `(N,20,13)` | PASS |
| H06 RF/XGB aggregator receives at most one batch | PASS |
| H07 output order preserved; repeated run deterministic | PASS |

External path: memmap-backed `(users, days, 13)` float32 → deterministic index batches → gather `B×20×13` → score → discard. Classical models aggregate **the batch only**. Silent append/resume is refused unless explicitly manifest-bound. Final row count must equal expected sequence count. Development-array scoring remains for small fixtures.

---

## TABLE 5 — MECHANISM METRIC REGISTRY

No PROXY metric is paper-facing.

| metric_name | status | paper-facing |
| --- | --- | --- |
| student_teacher_logit_deviation | EXACT_FROZEN | yes |
| route_mae | EXACT_FROZEN | yes |
| route_kl | EXACT_FROZEN | yes |
| hard_route_agreement | EXACT_FROZEN | yes |
| dominant_leaf_agreement | EXACT_FROZEN | yes |
| unused_leaf_fraction | DISABLED_NOT_REPRODUCIBLE | no |
| tree_contribution_rho | DISABLED_NOT_REPRODUCIBLE | no |

Primary incremental anchoring remains logit deviation, route MAE, route KL, and hard-route agreement. No claim that C5 improves them externally. No tree-ranking monotonicity claim. `tree_contribution_pearson_proxy` was removed.

---

## TABLE 6 — METADATA CONTRACT

Required future fields:

`sequence_id`, `user_id`, `window_start_date`, `window_end_date`, `decision_date`, `completed_window_label`, `endpoint_label`, `deoverlap_offset0_flag`, `official_insider_flag`, `official_incident_id`, `answer_scenario_ids`, `endpoint_answer_scenario_ids`

Distinction preserved: **`official_incident_id` ≠ contextual scenario evidence**.

Synthetic fixture includes official-insider positive, contextual non-insider positive (`official_incident_id=null`), benign user, single-scenario window, and multi-scenario window (`{1,4}`). Metadata survives input → score-phase `SEQUENCE_METADATA.json` → analysis load.

---

## TABLE 7 — REGRESSION TESTS

| Code | Status | Notes |
| --- | --- | --- |
| T01–T04 | PASS | freeze contracts |
| T05 | PASS | 18 hashes MATCH (re-run) |
| T06 | PASS | C5 deny-list |
| T07 | PASS | unknown hash |
| T08 | PASS | tamper |
| T09–T10 | PASS | scaler SHA + TRAIN NPZ inverse-retransform |
| T11 | PASS | aggregator SHA |
| T12–T13 | PASS | C2 seed-62 threshold bound |
| T14–T18 | PASS | strict=True / weights_only / RF / XGB |
| T19–T21 | PASS | synthetic 18-model scores |
| T22–T23 | PASS | determinism + state immutability |
| T24, T27–T29 | PASS | identifiers / endpoint / de-overlap |
| T25–T26 | PASS | raw scores before metrics |
| T30–T32 | PASS | no training/optimiser/threshold search |
| T33–T34 | PASS | r5.2 VALIDATION first-256 scored; TEST not opened |
| T35–T37 | PASS | external gate (stricter field names) |
| T38 | PASS | mechanism module (disabled metrics recorded) |
| T39–T40 | PASS | git snapshot; `diff --check` clean (untracked tree) |
| H01–H15 | PASS | this delta |

---

## TABLE 8 — GIT DELTA

Branch: `repository-hardening`  
HEAD: `b1eee6a11dd35e8b87840ce0974d2d8bf6368a3c`

`git diff --check`: (empty; working tree has no tracked modifications)

`git diff --stat`: (empty; EDITOR-006B/006B1 files remain untracked)

`git status --short` after this task includes the prior 006A/006B untracked review trees plus:

```
?? scripts/run_editor006b_harness.py
?? src/editor006b_harness/
?? tests/conftest.py
?? tests/test_editor006b_*.py
?? review/editor006b1_hardening/
```

No commit was created.

---

## FINAL VERDICT

EDITOR006B1_HARDENING_COMPLETE_WITH_QUALIFICATIONS

AUTHORIZATION_BINDING = PASS
STREAMING_EXTERNAL_SCORER = PASS
SOURCE_HASH_GATE = PASS
MECHANISM_REGISTRY = PASS
SCENARIO_METADATA_CONTRACT = PASS
ORIGINAL_T01_T40_REGRESSION = PASS
NEW_H01_H15_TESTS = PASS
R62_PREDICTIVE_INFERENCE_EXECUTED = NO
R62_PREDICTIVE_INFERENCE_AUTHORISED = NO
NEXT_ACTION = Independent review of the EDITOR-006B → EDITOR-006B1 delta only. Only after that review may EDITOR-006C materialise the model-free final r6.2 input bundle.
