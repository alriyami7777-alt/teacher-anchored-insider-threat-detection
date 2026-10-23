# Results map: every table and figure in the R2 manuscript

Keyed by LaTeX label, because table and figure numbers may still change. The **No.** column is the number in the manuscript source of 22 October 2026 (30 pages).

**Paths.** Paths are relative to `revision_r2/`. `E/` stands for `revision_r2/evidence/` (the redacted frozen evidence export). `../` means the repository root.

**Settings that apply unless a row says otherwise.**
- *Seeds:* neural models use 42, 52 and 62, and results are three-seed means.
- *Thresholds:* each is chosen on validation data only and then frozen.
- *Bootstrap:* paired user-cluster, 2,000 replicates, seed 42, 95% percentile interval. The settings are recorded in `holdout/PREREGISTRATION_R2_HOLDOUT.md`, `phase5/MODELS_AND_METHODS_FROZEN_PHASE5.json` and `phase6/INFERENCE_PROTOCOL_FROZEN.json`, and the code is `bootstrap6.py` / `bootstrap6b.py` / `boot.py`.
- *Historical analyses:* tables and figures from earlier frozen campaigns (EDITOR-xxx) use the settings recorded in their own run manifests.
- *Holdout users:* the 500-user unseen-user cohort is CERT r5.2 users never used for training, tuning or checkpoint selection. It is defined in `holdout/PREREGISTRATION_R2_HOLDOUT.md`.

## Method tables and schematic figures (no computed results)

| Label | No. | Content | Source |
|---|---|---|---|
| `tab:related_work_positioning` | T1 | Literature positioning | Manuscript text |
| `tab:evidence_streams` | T2 | Datasets and their roles | Manuscript text; split counts in `holdout/SPLIT_RECEIPT.json` |
| `fig:user_split` | F1 | User-disjoint split diagram | `paper_figures/plot_user_split.py`; counts from `holdout/SPLIT_RECEIPT.json` |
| `tab:daily_features` | T3 | 13 daily features | `../protocols/data_preparation_time_aware.md`; `../src/` feature builders |
| `fig:data_prep_workflow`, `fig:architecture_pipeline`, `fig:odst_routing`, `fig:teacher_guided_training_architecture` | F2–F5 | Schematic diagrams | Drawn by the authors; no data |
| `alg:teacher_guided` | A1 | Training step | `../src/editor012_rescue/` |
| `tab:training_hyperparameters` | T4 | TRACE training configuration | `holdout/phase4/RECIPES_FROZEN_PHASE4.json`; `phase6/TRAINING_PROTOCOL_FROZEN.json` |
| `tab:analysis_labels` | T5 | Role of each analysis | Manuscript text |
| `tab:software` | T6 | Software and hardware | `ENVIRONMENT.md`, `ENV_EXPORT_2026-10-21.txt` |

## Results

| Label | No. | Result | Output files | Producing code | Settings |
|---|---|---|---|---|---|
| `tab:r52_components` | T7 | TRACE, matched variants and references on r5.2 validation (all 2,000 users) | `../results/tables/r52_validation_all_models.csv`; factorial `E/editor012-teacher-anchor-rescue/.../02_factorial_confirmation/EDITOR012_FACTORIAL_RESULTS.csv`; L1 `E/editor013-odst-value-proof/.../02_validation_confirmation/EDITOR013_VALIDATION_RESULTS.csv`; XGBoost-40/RF-40 per `DISCLOSURES.md` D1 | `../src/editor012_rescue/`, `../src/editor013_odst_value/` | Seeds 42/52/62; validation-selected checkpoints |
| `tab:holdout`, `fig:holdout` | T8, F6 | 17 models on the 500 unseen users | `holdout/phase4/HOLDOUT_RESULTS.csv`, `HOLDOUT_CONTRASTS.csv`, `CHATGPT_PHASE4_REPORT.md` | Figure: `paper_figures/plot_holdout.py`. Training and scoring: `holdout/code/phase2_runtime.py`, `holdout/code/phase4/score.py`; reproduction: `holdout/reproduce/reproduce_unseen_seed42.py` | Retrained on 1,500 development users; scored once; frozen development thresholds; seeds 42/52/62 |
| `tab:operational` | T9 | Insider-level and operational results, unseen users | `phase5/C_INSIDER_DETECTION.csv`, `C_ALERT_EPISODES.csv`, `C_USERS_FLAGGED_PER_DAY.csv`, `C_TOPK_TRIAGE.csv`, `C_SCENARIO_DETECTION.csv`, `C_OPERATIONAL_SUMMARY.csv` | `phase5/reproducibility_code/operational.py` | Per-seed fixed development thresholds |
| `fig:teacher_guidance_component_effects` | F7 | Paired component contrasts, r5.2 validation | Values from `E/editor011-matched-route-confirmation/.../EDITOR011_USER_CLUSTER_BOOTSTRAP.json`, `E/editor012-teacher-anchor-rescue/.../EDITOR012_CLUSTER_BOOTSTRAP.json`, `E/editor023-positive-architecture-value/.../EDITOR023_CLUSTER_BOOTSTRAP.json` | `paper_figures/plot_components_dependence.py` | 2,000 user-cluster replicates (historical manifests) |
| `fig:same_information_comparison` | F8 | Same 20×13 inputs, development-user validation | `phase6/I2_SAME_INFORMATION.png` (identical file), `I2_SAME_INFORMATION_data.csv`, `I2_SAME_INFORMATION.csv`, `I2_PAIRED_CIS.csv` | `phase6/reproducibility_code/report6.py`, `inference6.py` | 48,000 windows, 473 positive |
| `tab:feature_sets` | T10 | Feature-set sensitivity | Reference rows: `analysis/feature_study_evidence.json`, `E/feature-study-local/`. TRACE row and paired CIs: `phase6/T2_FEATURE_SETS_data.csv`, `T2_PAIRED_CIS.csv` | Reference: `E/feature-study-local/` run folders. TRACE: `phase6/reproducibility_code/train6.py`, `inference6.py` | 174 reference fits; TRACE trained on development users |
| `fig:r52_temporal_value_fig` | F9 | Order and history interventions, TRACE | `phase6/I1_TRACE_ORDER_HISTORY.png` (identical file), `I1_TRACE_ORDER_HISTORY_data.csv`, `I1_ORDER_HISTORY.csv`, `I1_PAIRED_CIS.csv` | `phase6/reproducibility_code/inference6.py`, `report6.py` | Inference-time only |
| `tab:representation_unseen` | T11 | H1–H6 representation and explanation tests, unseen users | `phase6b/H1_H5_FULL_CONTRASTS_HOLM.csv`, `H1_H5_RESULTS.json`, `H6_FEATURE_CONTRASTS_HOLM.csv`, `H6_TEMPORAL_CONTRASTS_HOLM.csv`, `H6_TREE_CONTRASTS_HOLM.csv`, `CHATGPT_PHASE6B_REPORT.md` | `phase6b/reproducibility_code/analysis6b.py`, `explain6b.py`, `score6b.py` | Holm correction; exploratory |
| `fig:unseen_interventions` | F10 | Order/history interventions, unseen users | `phase6b/figure_c_interventions.png` (identical file), `figure_c_interventions.csv` | `phase6b/reproducibility_code/report6b.py` | Seeds 42/52/62 |
| `fig:unseen_explanations` | F11 | Three-level explanation test, unseen users | `phase6b/figure_e_three_level_explanation.png` (identical file), `figure_e_three_level_explanation.csv` | `phase6b/reproducibility_code/report6b.py`, `explain6b.py` | 2,344 windows from 448 users |
| `fig:dependence_endpoint_validation` | F12 | Non-overlapping offsets and endpoint labels | `E/editor029-endpoint-dependence-aware/review/editor029_endpoint_dependence/EDITOR029_PARTA_ALL_OFFSETS.csv`, `EDITOR029_ENDPOINT_ALL_OFFSETS.csv` | `paper_figures/plot_components_dependence.py` | 20 offsets; seeds 42/52/62 |
| `fig:temporal_attention_cases` | F13 | Attention for median TP/TN/FP/FN windows | `phase6/I4_ATTENTION_HEATMAP.png` (identical file), `I4_ATTENTION_HEATMAP_data.csv`, `I4_CASES.csv` | `phase6/reproducibility_code/inference6.py`, `report6.py` | Seed 42 |
| `fig:ig_attribution` | F14 | Integrated Gradients by feature and tree | `explanation/integrated_gradients_features.csv` (and `integrated_gradients.json`) | `paper_figures/plot_ig.py` | 50 steps; training-median reference; seeds 42/52/62 |
| `tab:degraded_input_resilience` | T12 | Source-removal and noise AURC, r5.2 validation | `E/editor023-positive-architecture-value/review/editor023_positive_architecture_value/EDITOR023_SOURCE_AURC.json`, `EDITOR023_RESULT_FREEZE.md` | `../src/` (EDITOR-023 campaign) | Historical frozen run |
| `tab:holdout_degradation` | T13 | Degraded-input retention, unseen users | `phase5/B_AURC.csv`, `B_RETENTION_CURVES.csv`, `B_RETENTION_*.png` | `phase5/reproducibility_code/robust.py` | Seeds 42/52/62 |
| `tab:efficiency` | T14 | Parameters, FLOPs, latency, training time | `analysis/efficiency/efficiency_profile.csv`, `*_result.json`; training seconds from `holdout/phase4/TRAINING_LOG_PHASE4.csv` | `analysis/efficiency/efficiency_profile.py` | Seed-42 checkpoints; batch 1,024; median of 3 repeats (50 warm-up, 200 timed batches) |
| `tab:cross_release` | T15 | Zero-shot transfer to r5.1, r6.1 and r6.2 | `phase5/A_TRANSFER_RESULTS.csv`, `A_TRANSFER_CONTRASTS.csv`, `A_FEATURE_SHIFT.csv`. r6.1 column: `E/editor024-r61-final-confirmation/review/editor024_r61_final_confirmation/EDITOR024_R61_PRIMARY_RESULTS.json` | `phase5/reproducibility_code/transfer.py` | r5.2 thresholds and scaler unchanged; single evaluation |

## Supplementary tables

| Label | Output files | Producing code |
|---|---|---|
| `tab:formulation_search` | `../results/tables/formulation_search_editor012_inner.csv`; `E/editor012-teacher-anchor-rescue/.../01_inner_anchor_search/EDITOR012_INNER_ANCHOR_RESULTS.csv` | `../src/editor012_rescue/` |
| `tab:feature_sets_stage2` | `analysis/feature_study_evidence.json`; `E/feature-study-local/experiment_runs/stage2_v06_tl_review_20261009_r1/` | Same folder |
| `tab:supp_aurc` | `phase5/B_AURC.csv` | `phase5/reproducibility_code/robust.py` |
| `tab:supp_aurc_contrasts` | `phase5/B_AURC_CONTRASTS.csv` | `robust.py`, `boot.py` |
| `tab:supp_ranking` | `phase5/D_RANKING_METRICS.csv`, `D_ROC_CONTRASTS.csv` | `phase5/reproducibility_code/ranking_stats.py` |
| `tab:supp_calibration` | `phase5/E_CALIBRATION_METRICS.csv`, `E_RELIABILITY_DATA.csv`, `E_CALIBRATORS.json` | `phase5/reproducibility_code/calibration.py` |
| `tab:supp_holm` | `phase5/F_HOLM_SECONDARY_CONTRASTS.csv` | `phase5/reproducibility_code/ranking_stats.py` |
| `tab:supp_seed` | `phase5/F_SEED_STABILITY.csv` | `ranking_stats.py` |
| `tab:supp_operational` | `phase5/C_*.csv` (as `tab:operational`) | `operational.py` |
| `tab:supp_cross_release`, `tab:supp_cross_dev` | `phase5/A_TRANSFER_RESULTS.csv` | `transfer.py` |
| `tab:supp_cross_ci` | `phase5/A_TRANSFER_CONTRASTS.csv` | `transfer.py`, `boot.py` |
| `tab:supp_feature_shift` | `phase5/A_FEATURE_SHIFT.csv` | `transfer.py` |

## How this map was checked
For each results table, the numbers in the LaTeX source were compared with the listed CSV/JSON files. Five figures (F8, F9, F10, F11 and F13) are byte-identical to the PNG listed.

## Code for the unseen-user and explanation results (added 23 Oct 2026)
- **Unseen-user retraining and scoring (`tab:holdout`, `fig:holdout`):** frozen code in `holdout/code/` (split, data rebuild, training recipes, scoring); data preparation from raw CERT r5.2 in `holdout/data_prep/`; seed-42 checkpoints in `holdout/checkpoints_seed42/`; step-by-step reproduction in the main README section "Reproduce the unseen-user result (seed 42)".
- **Explanation runs (`explanation/`, `explanation_holdout/`):** code in `explanation/code/` (see `explanation/CODE_NOTE.md`).

## Further R2 analyses (Phases 6C, 7 and 8, added 23 Oct 2026)
Each folder has its report (`CHATGPT_PHASE*_REPORT.md`), CSVs, figures, frozen-model and code receipts, and `reproducibility_code/`. Their rows are not yet keyed to manuscript labels; this map will be refreshed when the manuscript cites them.
- `phase6c/`: C1 and C2 analyses (see `CHATGPT_PHASE6C_REPORT.md`), including augmented TRACE and XGBoost-40 runs, retention curves and Holm-corrected contrasts.
- `phase7/`: case-level and operational analyses on the unseen users (P1–P6: case attribution, false alarms, insider timing, daily alert budget, rank-average combination, threshold rules).
- `phase8/`: Q1–Q5 (more seeds, gradients by day, ODST routing and leaf occupancy, explanation randomisation checks, label-free input monitoring).
