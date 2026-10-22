# PHASE 3 — explanation evidence

Completed UTC: 2026-10-21T21:28:37.556813+00:00

## Scope and frozen cohort

Used only the original frozen TA2/F11 and XGBoost_40 models, seeds 42, 52, 62. No training, GitHub push, TEST data, r5.1, r6.1 or r6.2 data, or Phase 2 holdout scoring. Existing repositories and worktrees were read only.

GPU start was gated on `PHASE2_COMPLETE_MODELS_FROZEN_NOT_SCORED` as the final nonblank text of `C:\PhD\04_Journal_Papers\Latest IEEE Access Paper July 2026\R2_revision\holdout\CHATGPT_PHASE2_REPORT.md`. The gate record and report hash are in GPU_GATE_RELEASE.json.

The cohort is all **64,000 original r5.2 VALIDATION windows from 2,000 users**, with 728 malicious and 63,272 benign labels (31 users with malicious windows; 32 windows per user). Sign eligibility is applied separately by seed, k, model and sign. All exclusions are in faithfulness.csv; paired comparisons use jointly eligible windows.

Definition: `C:\PhD\07_Projects\teacher-anchored-insider-threat-detection-editor023/src/editor017_robustness/campaign.py`, `run_campaign`, with `recover_user_mapping` and `editor012_rescue/data.py::load_train_validation`; identities and counts: `src/editor012_rescue/constants.py`. Local signed selection: `src/editor015_residual/explain.py::directional_table`.

EDITOR-017 commit: c75321a627ecc7539d1a759764d7ce395895179a. EDITOR-023 commit: a480fa2413cf0b70c398081ca5f8f52470a665a3. EDITOR-023 uses the same validation population and training references for its explanation stability analysis; its source does not define a new 484-window cohort.

**Manuscript inconsistency:** 484 windows / 151 users is an r4.2 definition in `src/objective3_missing_source_robustness.py` (242 malicious / 242 benign), not the r5.2 EDITOR-017/023 population. Claude explicitly clarified using the actual r5.2 cohort. No r4.2 tensors or checkpoints were loaded.

## Step 1 — Integrated Gradients

50 intervals with composite trapezoid integration (51 evaluation nodes), from each raw tree output and final logit to the 20×13 scaled input. Baseline: original r5.2 TRAIN median over all day rows per feature, broadcast over 20 days, matching the paper feature intervention convention. TRAIN_REFERENCES.json records all values. No validation statistic defines the reference.

Completeness median relative errors (overall; denominator floored at 1e-6):

- Seed 42: tree_1=0.00068971, tree_2=0.00147329, tree_3=0.000601751, tree_4=0.00232369, tree_5=0.000551821, tree_6=0.000598, tree_7=0.000634107, tree_8=0.000534619, final_logit=0.000464025
- Seed 52: tree_1=0.000410768, tree_2=0.000649935, tree_3=0.00726572, tree_4=0.00122609, tree_5=0.000731874, tree_6=0.000465592, tree_7=0.000477208, tree_8=0.000264784, final_logit=0.000508934
- Seed 62: tree_1=0.0011953, tree_2=0.000891799, tree_3=0.00101197, tree_4=0.000834022, tree_5=0.00126951, tree_6=0.000535235, tree_7=0.00339206, tree_8=0.000896394, final_logit=0.000924105

Source-level Spearman correlation with file > device > logon > web > email (final-logit IG):

- Seed 42: overall=0.8999999999999998, malicious=0.9999999999999999, benign=0.8999999999999998
- Seed 52: overall=0.8999999999999998, malicious=0.9999999999999999, benign=0.8999999999999998
- Seed 62: overall=0.8999999999999998, malicious=0.9999999999999999, benign=0.8999999999999998

Full errors, absolute residuals, near-zero denominator counts, malicious/benign aggregates, top-three features per tree and source-level Spearman correlations are in integrated_gradients.json and the three IG CSVs. Figure: integrated_gradients.png (300 dpi). The five-source comparison uses direct count/presence channels; total events, duration and active-day flags are shared and excluded, with their attribution mass reported separately.

## Step 2 — local input faithfulness

Both signs were evaluated in each label stratum. The expected change is logit decrease for positive inputs and increase for negative inputs. Zero changes fail directionality. Random controls average 200 independent same-sign random k-subsets per sequence (duplicates retain their sampling multiplicity). Margin changes are divided by the population SD of each model/seed across original validation logits. CIs use 2,000 paired whole-user cluster bootstrap replicates, RNG 42, with window weighting after cluster resampling.

Exploratory primary contrast: TA2 minus XGBoost directional accuracy at feature k=3, class-supporting sign (positive for malicious labels; negative for benign). Equal-seed mean uses jointly eligible windows in all three seeds:

- overall: 0.359604, 95% CI [0.341026, 0.379981], n=63441 paired windows.
- malicious: 0.064649, 95% CI [0.026094, 0.108716], n=727 paired windows.

All seed/sign/k/stratum outcomes, random gaps, exclusions and CIs appear in faithfulness.csv/json, primary_comparison.csv, and faithfulness.png (300 dpi). The primary comparison has different input resolution: 13 TA2 raw features versus 40 XGBoost summaries, as requested. A parallel XGBoost analysis grouping summaries to 13 raw features is in raw_feature_sensitivity.csv. Source-level analysis uses five comparable direct source groups. These are local input interventions, not a physical source-removal simulation; derived-feature constraints are not recomputed. No outcome was selected or suppressed based on which model performed better.

### Random-control gaps and feature-resolution sensitivity

The primary result above compares 13 TA2 raw features with 40 XGBoost summaries, as requested. It must not be read as an overall model or explanation superiority claim. The additional outcomes are material:

- For the primary 13-versus-40 comparison, the TA2-minus-XGBoost difference in directional-accuracy improvement over the same-sign random control is **+3.20 percentage points overall** (95% CI +1.47 to +5.06) and **−0.21 points on malicious windows** (95% CI −4.77 to +4.94). The malicious random-adjusted comparison is inconclusive.
- When XGBoost summaries are grouped into 13 raw features, the directional-accuracy difference is **+17.96 points overall** (95% CI +16.71 to +19.19; n=63,437 jointly eligible windows) and **−0.37 points on malicious windows** (95% CI −0.98 to 0.00; n=723). The malicious-window TA2 advantage does not persist at matched raw-feature resolution.
- In that 13-versus-13 sensitivity, the difference in improvement over the random control is **−9.22 points overall** (95% CI −10.20 to −8.19), favouring XGBoost; on malicious windows it is **−2.83 points** (95% CI −5.80 to +0.39), with the interval including zero.

These sensitivity analyses and sign conventions were included in the frozen protocol before results were computed. All seedwise outcomes and both signs remain available in the CSV/JSON results. The primary endpoint remains unchanged. The final faithfulness.png displays the primary and sensitivity comparisons with their paired CIs; the original positive-evidence k-profile is retained as faithfulness_positive_evidence_profile.png. This presentation-only step reads frozen aggregate results and does not change any numerical outcome.

## Step 3 — HOLDOUT preparation only

holdout_explanation_scoring.py was written and SHA-256 hashed, and was not run. Its hash is in HOLDOUT_EXPLANATION_SCRIPT_HASH.txt. It requires explicit scoring execution and a hash-bound scoring manifest; it selects all malicious HOLDOUT windows plus an equal-sized random benign sample, RNG 20261022. It requires training-only references and validation-only logit spreads from the retrained models and does not derive those from HOLDOUT data. The dependency hashes are also recorded so the same engine can be verified at scoring time. No Phase 2 HOLDOUT data or models were opened by this phase.

## Validation and limitations

Synthetic CPU tests cover exact linear IG, completeness, sign handling, replacement semantics, same-sign random controls, grouping, user clustering, paired comparison, the GPU gate, and pseudonymisation. Frozen TA2 logit and XGBoost probability parity, TreeSHAP additivity, and checkpoint hashes were checked during execution; details are in faithfulness.json. Complete protocol and source hashes were frozen before results were computed. Sparse sign eligibility and any large 50-step IG completeness errors must be considered when interpreting the results; all are disclosed. No extra Qasim approval was required and no requested outcome was skipped.

Post-run verification: all six original checkpoint hashes and all 13 inspected source hashes remained unchanged; code/output copies and the frozen protocol hash match; the original validation population and pseudonym format were verified; all 1,404 metric rows are present and all nonempty confidence intervals contain 2,000 valid bootstrap replicates. Exported IG completeness and all three TreeSHAP margin additivity checks reproduce from the saved arrays. Text outputs contain no CERT user-ID patterns. The two final figures were visually inspected and confirmed at 300 dpi. See FINAL_VERIFICATION.json. Final-logit median IG relative errors are 0.0464%, 0.0509%, and 0.0924% for seeds 42, 52, and 62, respectively.

PHASE3_COMPLETE
