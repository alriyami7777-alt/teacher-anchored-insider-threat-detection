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
checkpoints (except the three seed-42 checkpoints in `revision_r2/holdout/checkpoints_seed42/`, published for the
unseen-user check), large prediction arrays, or private organisational material.

## Revision R2 (IEEE Access, Access-2026-42960): where to find each result

**Table-by-table and figure-by-figure map:** [`revision_r2/RESULTS_MAP.md`](revision_r2/RESULTS_MAP.md) lists every table and figure in the R2 manuscript by LaTeX label, with its output files, producing code, seeds and settings. New R2 analyses are in `revision_r2/phase5/` (cross-release, robustness, operational, calibration, statistics), `revision_r2/phase6/` (TRACE re-runs), `revision_r2/phase6b/` (representation and explanation tests on unseen users), `revision_r2/phase6c/`, `revision_r2/phase7/` (case-level and operational analyses) and `revision_r2/phase8/` (further seeds, routing and explanation checks, input monitoring), `revision_r2/phase9/` (limitation tests L1–L8: target-side restandardisation, feature removal, lead time, route interventions, seed averaging, attribution baselines, evasion and poisoning), `revision_r2/phase10/` (CERT r6.2 cross-release tests: threshold-only refitting and training within r6.2 on a user-disjoint split) and `revision_r2/phase11/` (CERT r6.2 on its own terms: pooled and within-release training, four-fold user-level evaluation and daily alert budgets), `revision_r2/analysis/` (efficiency profile, feature-study record) and `revision_r2/paper_figures/` (plotting scripts). Each phase folder has its report, CSVs, figures and `reproducibility_code/`; the pre-push audit is `revision_r2/PUBLIC_RELEASE_AUDIT_PHASE5_6.md`.

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

## Reproduce the unseen-user result (seed 42)

This section reproduces the paper's unseen-user evaluation (`tab:holdout`) for seed 42. It covers TRACE, the task-only control (F00) and XGBoost-40, each scored on the 500 held-out CERT r5.2 users.

There are two routes:
- **Load:** score the published seed-42 checkpoints. After the data preparation (step 3), this runs on a CPU in minutes.
- **Retrain:** rebuild the models from the frozen recipes. This needs an NVIDIA GPU. The nine training runs took about 13 minutes in total on the authors' laptop RTX 5070 (`revision_r2/holdout/TRAINING_LOG.csv`).

The work uses the frozen code under `revision_r2/holdout/code/`, run through `revision_r2/holdout/reproduce/reproduce_unseen_seed42.py`.

**The r5.2 TEST period is never used.**
- Step 3 turns the whole raw release into a day-level table, because the raw files are not split by date.
- After that, every step reads only days from 2010-01-02 to 2011-04-10 (the TRAIN and VALIDATION periods).
- No TEST-period window is built, scored or summarised.

### 0. What you need
- **The CERT r5.2 release folder.** It contains `logon.csv`, `device.csv`, `file.csv`, `email.csv` and `http.csv`. Below it is called `R52_RAW`.
- **The CERT answers package folder.** It contains `insiders.csv` and the folders `r5.2-1` … `r5.2-4`. Below it is called `ANSWERS`.
- **Python 3.11** and enough free disk for the intermediate Parquet files of step 3 (event-level, event-stream and daily tables).
- **A private work folder outside the clone.** Below it is called `WORK`. It will hold user IDs, tensors and checkpoints. Never commit or upload it.
  - **`WORK` must not be the clone folder or any folder inside it.** Clone the repository somewhere else, for example `C:\Repro\teacher-guided-insider-threat-detection` with `WORK` = `C:\Repro\work`. `reproduce_unseen_seed42.py` refuses to run if `WORK` is inside the clone.

In the commands below, replace `R52_RAW`, `ANSWERS` and `WORK` with full paths on your machine. The commands are for Windows PowerShell. On Linux or macOS, use `/` in paths, `\` instead of the backtick at line ends, and `export NAME=value` instead of `$env:NAME = "value"`.

### 1. Clone
```powershell
git clone https://github.com/alriyami7777-alt/teacher-guided-insider-threat-detection.git
cd teacher-guided-insider-threat-detection
git checkout ieee-access-r2-revision
```

### 2. Fresh environment
Windows PowerShell:
```powershell
py -3.11 -m venv .venv-r2
.\.venv-r2\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cu128
```
On Linux, use `python3.11 -m venv .venv-r2` and `source .venv-r2/bin/activate`, then the same `pip install` line. The pinned CUDA build of PyTorch also runs on a machine without a GPU, which is enough for the load route. macOS has no CUDA build: there, install `torch==2.11.0` from PyPI and the remaining lines of `requirements.txt`.

### 3. Build the day-level table from the raw CERT r5.2 files (CPU; the longest step)
```powershell
python revision_r2/holdout/data_prep/prepare_cert_common13_pipeline.py --dataset-version 5.2 `
  --raw-dir "R52_RAW" --answers-dir "ANSWERS" `
  --processed-dir "WORK\processed" --output-dir "WORK\prep_reports" `
  --stages match,label_events,unified_stream,daily_intervals,densify
```
- `--raw-dir` must be the folder that directly contains `logon.csv`, `device.csv`, `file.csv`, `email.csv` and `http.csv`.
- This step writes `WORK\processed\interval_level\r52_user_day_intervals_dense.parquet`.
- The `match` stage reads the answers package to label malicious events. That is the only use of answer-file content.
- The scripts are the preparation pipeline used for the paper's data on 23 July 2026; see `revision_r2/holdout/data_prep/README.md` for their provenance. Step 6's `build` checks the result against the hashes of the paper's own tensors.

### 4. Point the reproduction script at the data
```powershell
$env:R2_WORK = "WORK"
$env:CERT_R52_DENSE = "WORK\processed\interval_level\r52_user_day_intervals_dense.parquet"
$env:CERT_R52_ANSWERS = "ANSWERS"
cd revision_r2/holdout/reproduce
python reproduce_unseen_seed42.py check
```
- `check` confirms that the published code matches the SHA-256 hashes recorded when it ran (`MODELS_FROZEN.json`, `phase4/MODELS_FROZEN_PHASE4.json`).
- Two files show as `REDACTED`, as listed in `revision_r2/holdout/code/REDACTIONS.json`.

### 5. Rebuild the pre-registered 1,500 / 500 user split
```powershell
python reproduce_unseen_seed42.py split
```
- Both lines should report `list_sha256 MATCHES SPLIT_RECEIPT.json`.
- The split rule is in `revision_r2/holdout/PREREGISTRATION_R2_HOLDOUT.md`.
- The user lists are written only to `WORK`.

### 6a. Load route
```powershell
python reproduce_unseen_seed42.py build
python reproduce_unseen_seed42.py score --route load
```
- `build` refits the scaler on the development users and rebuilds their TRAIN and VALIDATION tensors (CPU, about 1 GB of disk). It reports whether each tensor matches the hash recorded in `revision_r2/holdout/DATA_MANIFEST.json`. All six should match; a mismatch means step 3 produced a different day-level table.
- `score` checks each checkpoint in `revision_r2/holdout/checkpoints_seed42/` against its frozen hash before use.

### 6b. Retrain route (NVIDIA GPU required)
```powershell
python reproduce_unseen_seed42.py build
python reproduce_unseen_seed42.py train
python reproduce_unseen_seed42.py score --route retrain
```
Skip `build` if you already ran it in 6a. `train` runs the frozen recipe in this order:
1. Three attention–linear precursors (seeds 42, 52, 62).
2. Three teachers (T-OPT; TRACE is guided by all three).
3. F00, TRACE and XGBoost-40 for seed 42.

GPU training is not bit-for-bit deterministic, so retrained scores can differ slightly from the loaded ones.

### 7. Output
`WORK\results\unseen_users_seed42_<route>.csv` has one row per model. It gives:
- the number of windows and positive windows;
- PR-AUC (average precision over all windows of the 500 held-out users);
- the frozen threshold, with precision, recall and alerts per 1,000 windows at that threshold;
- the number of held-out insiders and normal users;
- how many insiders were detected (at least one positive window at or above the threshold);
- how many normal users were flagged.

### Notes
- **Cohort definition:** the held-out cohort is the TRAIN and VALIDATION periods of the 500 users, built as in the paper's scoring script `revision_r2/holdout/code/phase4/score.py`.
- **Frozen code is unchanged:** `reproduce_unseen_seed42.py` imports the frozen modules unchanged. It points their hard-coded Windows paths at `WORK` and refuses to run if a frozen module is loaded from outside the clone.
- **Phase 3 explanation code:** published for reference in `revision_r2/explanation/code/`. It is not needed for this result.

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
