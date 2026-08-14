# EDITOR-007C1 — Freeze completed CERT r5.1 secondary-stress evidence and correct cluster-count metadata

Task: **EDITOR-007C1**
Source: **EDITOR-007C** producing outputs (immutable)
Role: **R51_SECONDARY_STRESS_ONLY**

This task does not load a predictive model, does not rerun r5.1 or r6.2, and does not open r5.2 TEST. The frozen 006B harness and 007C runner are not patched.

The original EDITOR-007C producing outputs are preserved unchanged. The paper-facing derivative corrects only a descriptive cluster-count metadata field from five to four. No predictive score, metric, bootstrap estimate, confidence interval, threshold, or model output was recomputed or modified.

---

## TABLE 1 — 007C completion identities

| Identity | Value |
| --- | --- |
| execution status | COMPLETE |
| EXECUTION_ABORTED.json | absent |
| EDITOR-007C authorisation commit | `057b8c39f2133c9b7b031681702900b86d319ce7` |
| authorisation SHA256 | `8e6747e30b5e8e631c4e68bf925108a9a689eb9eaca4d9d86b35ef1b48293693` |
| R51 bundle-manifest SHA256 | `366a1dd742a24b9470326c411dd5b40a7a2424c9c48ae3c5eb4b523f7fe01903` |
| R51 runner SHA256 | `03b3c47aecbcec28fd3cceb0509c70bd6553e74f6d352e3b88697bfec7acab57` |
| R51 sequence-order SHA256 | `9c5f9f36bded4fb0d70820fe54cd91964a0286fd134bbb806f4562dc15ce7118` |
| dataset | CERT r5.1 |
| role | R51_SECONDARY_STRESS_ONLY |
| EXECUTION_STARTED.json | `5eb2c7bcd8b1c72893c1616355597e7d7a5a9efdbcb17a18d0843d3974e24b2c` |
| SCORE_COMPLETE.json | `be50bb77d33a39d01b891f14d48df671c20c26e5cacdd830680efbcf18299b87` |
| ALL_SCORES_COMPLETE.json | `19a0960b8a898a080d853edf8b6722afca98fb55cba1c37b9a9a82c0f401cf70` |
| EDITOR007C_PREDICTIVE_RESULTS.json | `2a3744937e04e8c469d4aa1ed4f43ebd0c31881df76852c2d23c775ec99b08de` |
| EDITOR007C_MECHANISM_RESULTS.json | `f7185f18c9fe35db287dc6c0a5da8478a01b5f3ea03c2f8de90cb21a6a76b360` |
| EDITOR007C_RUN_MANIFEST.json | `0fb9dae25b379c9d8ab098649e782cafbb1b3e6faa6c329308a5a9307ebd52c2` |
| EXECUTION_COMPLETE.json | `0ec389b4a01c0a23d7b7c90bb8d1ad409b02e7a58220b1476260b4c6c3fa609b` |
| EXECUTION_COMPLETE bound hashes | exact equality (independent re-hash) |

Source directory (read-only): `C:\PhD\06_Datasets\derived\teacher_anchored_r51_editor007c_scores\`

---

## TABLE 2 — 18 raw-score hashes

Independent SHA-256 of each `raw_scores/*.npy` equals both `SCORE_COMPLETE.json` (`scores[].sha256`) and `ALL_SCORES_COMPLETE.json` (`models[].score_sha256`). Count = 996000 for every file.

| Family | Seed | Checkpoint SHA256 | Frozen threshold | Score file | Observed SHA256 | Status |
| --- | ---: | --- | ---: | --- | --- | --- |
| teacher_frozen_odst | 42 | `783d0913f85d492ddacec83a274ba2d4f13ad25eaf1a34ebcc64a960bda8ff86` | 0.56 | teacher_seed42.npy | `62f752129e8c49fdbda1c0e60e064de025a33e563f7aee68ba57f28d13c2c652` | PASS |
| teacher_frozen_odst | 52 | `7273327495bbe463cfb3d50fa94c81c82de7b304370a816343046f559fc3d191` | 0.8400000000000001 | teacher_seed52.npy | `3a12ff39f7669ab38f6fc5d71aa65cf93b12789f2d6c67b52e17ab44e7b7d238` | PASS |
| teacher_frozen_odst | 62 | `247d6e71353b49ea0a77a073a8606fbf35b88106faae7dae6ec53361621e9d92` | 0.55 | teacher_seed62.npy | `74c309b3523440df84af7796b4ae9316ebebdff265f35d94b67637e0bf094bf0` | PASS |
| C2 | 42 | `c5b8ab96a6f347afb85708857cef56b4a632f6092dfda9339ab9a3558daf863e` | 0.6 | c2_seed42.npy | `870207bb0840378c589b4e65db0ff2c97f6b89a95b166855dc02f4ef1b26d147` | PASS |
| C2 | 52 | `2215b36edd015f783de86ecb1b40cdd535fb6f082adc16a377574a24a8d0c22b` | 0.8300000000000001 | c2_seed52.npy | `b135c491fdb1e5de50717b39eee8c18c51e8f328c1d8fe60b70142c09518980d` | PASS |
| C2 | 62 | `595a5e57ec78d6d34e2811609dc97514b0703cab807b7dffe873128a92ecc5c2` | 0.6544522184133537 | c2_seed62.npy | `1994cf9ad6bcdee12892824ab540adbbf22355f73619bd93f0355a35ac309fed` | PASS |
| C5_original_paper | 42 | `2b6452698dd0da53f0229bc43040a877017ac9299b277f2f98c1d7ca64c1cc42` | 0.56 | c5_seed42.npy | `36df615fbb02e50b977c86af1bc3d3f39a7f0d0b11f0fdc462f07e8a8c63b6b2` | PASS |
| C5_original_paper | 52 | `9c9d035fe81f54898dee4ecf4d2ecaf8423a21ecc3551793dc16d1980af1eb0d` | 0.85 | c5_seed52.npy | `84c35cd2a1349f303182e3a69b68b544ca767ad3aa6ba32f4eb65cc7002731ca` | PASS |
| C5_original_paper | 62 | `f5e8eb5260113a0aeabfb95ef198e1aa80022a26dfe91f3bf9262acbf5453ec9` | 0.55 | c5_seed62.npy | `66de3b9ca0fdf288dc88e76eb38962ce7e90087dff1c8aebf7124fbd53d91fcc` | PASS |
| attention_linear | 42 | `b807a82343b432343b7e3cbc86ee76cba7011066827f3baa089aa78a02c02b53` | 0.9500000000000001 | attention_linear_seed42.npy | `bba72a0b293967ab098bd174ff850f687f5456bb07875145a7533813d8d6628b` | PASS |
| attention_linear | 52 | `5e5e2a136bedba3d3477d05c5b1215331cb97339b74003bcb60f8cb4885ba86c` | 0.9600000000000001 | attention_linear_seed52.npy | `be455dd9203a77fa47734b0b6c42456e88f2b080981fe58f330066f66f6aa1ef` | PASS |
| attention_linear | 62 | `4543c167fdab3b0376087731571f7b3bcecadd43f8ff05c6b5371f0073ba425a` | 0.9400000000000001 | attention_linear_seed62.npy | `91a46dcdbdbe45da5b13983a792648a1a30b1815ef94e01cabb504b779e0a78c` | PASS |
| RF_40 | 42 | `38b8830acec3b9c399411093ac38ed6bed6dca52a0cf05be9c87178cb05f5780` | 0.38 | rf_seed42.npy | `7523e3c29274f3b4b1ca8093a27b8b1707437a07ca69ef748bb0dfb9a5f7b9f8` | PASS |
| RF_40 | 52 | `6f409fb9df15a76319a16988ed5ee0ca42da0a9c48981240e15edee773d3d89d` | 0.46 | rf_seed52.npy | `7150512e20f9412eb1a3c3edcc7ab076014df01319ff0962504413c1f9548992` | PASS |
| RF_40 | 62 | `b0f4e762e34a3e5f0f07a64130130a7f223bfbc486b9bdcd2d2549210fb36df5` | 0.37 | rf_seed62.npy | `3e5e46fa38ad9203ce23be4abc968ded8035e67c9a309cf66e82ce163fcab877` | PASS |
| XGBoost_40 | 42 | `2109554164abdd002ce0a4377f957c5aa3bc26886a197749ea79fc04d9b94fae` | 0.18000000000000002 | xgb_seed42.npy | `eec4bf79e7ef1370a7718e7c376aa17a9a0d85b46afe9c6f8307d58c1f0b3ebb` | PASS |
| XGBoost_40 | 52 | `0f32857232341cb6a26d6cf55cb2375b8e256e0e0f89519d3059415cac8ad7e6` | 0.16 | xgb_seed52.npy | `bd627daa1bc9e7b89728e3ff2876b6909670fc424c02907174b8a0388db49274` | PASS |
| XGBoost_40 | 62 | `3062488680b8bc05959ddcb0cab948378988564fc82a88213e346ca570b0c7ab` | 0.18000000000000002 | xgb_seed62.npy | `576a950ee252866c07601253d8478d2aeeea181a7bd82f5aaf2709ecde0d551c` | PASS |

**RAW_SCORE_HASHES = 18/18 PASS**

---

## TABLE 3 — Original result artefact hashes

These producing files were not overwritten. SHA-256 values are recorded permanently.

| Artefact | SHA256 | Modified by EDITOR-007C1 |
| --- | --- | --- |
| EDITOR007C_PREDICTIVE_RESULTS.json | `2a3744937e04e8c469d4aa1ed4f43ebd0c31881df76852c2d23c775ec99b08de` | NO |
| EDITOR007C_MECHANISM_RESULTS.json | `f7185f18c9fe35db287dc6c0a5da8478a01b5f3ea03c2f8de90cb21a6a76b360` | NO |
| EDITOR007C_RUN_MANIFEST.json | `0fb9dae25b379c9d8ab098649e782cafbb1b3e6faa6c329308a5a9307ebd52c2` | NO |
| EXECUTION_COMPLETE.json | `0ec389b4a01c0a23d7b7c90bb8d1ad409b02e7a58220b1476260b4c6c3fa609b` | NO |
| SCORE_COMPLETE.json | `be50bb77d33a39d01b891f14d48df671c20c26e5cacdd830680efbcf18299b87` | NO |
| ALL_SCORES_COMPLETE.json | `19a0960b8a898a080d853edf8b6722afca98fb55cba1c37b9a9a82c0f401cf70` | NO |

Paper-facing derivative (new file only): `review/editor007c1_r51_result_freeze/EDITOR007C_PREDICTIVE_RESULTS_PAPER_CORRECTED.json`

---

## TABLE 4 — Metadata-error provenance

The incorrect five-cluster stamp is historical r6.2 wording in the frozen harness return dictionary. It is not a second official-incident census.

| Item | Value |
| --- | --- |
| producing stamp | `src/editor006b_harness/bootstrap.py` `paired_user_cluster_bootstrap` return metadata |
| harness / runner patched? | NO (historical code remains provenance) |
| incorrect value | 5 |
| correct value | 4 |
| incorrect wording | Five official insider–incident clusters are represented. |
| correct wording | Four official insider–incident clusters are represented. |
| 007C runner top-level fields | already 4 / Four (not corrected) |
| `scenario_deoverlap_summary` | already 4 / Four (not corrected) |
| empirical `n_positive_deoverlap_windows` | not cluster metadata; left unchanged |
| EDITOR007C_MECHANISM_RESULTS.json | no five-cluster metadata; overlay only; no paper-corrected derivative |
| EDITOR007C_RUN_MANIFEST.json | no five-cluster metadata; overlay only; no paper-corrected derivative |

Approved JSON paths (six):

1. `deoverlap_user_cluster_bootstrap.42.effective_malicious_cluster_count`
2. `deoverlap_user_cluster_bootstrap.42.frozen_wording`
3. `deoverlap_user_cluster_bootstrap.52.effective_malicious_cluster_count`
4. `deoverlap_user_cluster_bootstrap.52.frozen_wording`
5. `deoverlap_user_cluster_bootstrap.62.effective_malicious_cluster_count`
6. `deoverlap_user_cluster_bootstrap.62.frozen_wording`

Scientific basis: r5.1 has four official mapped insider–incident clusters; contextual event-level positive users are not additional official incidents.

---

## TABLE 5 — Bootstrap numerical-effect audit

Implementation inspected: `src/editor006b_harness/bootstrap.py` `paired_user_cluster_bootstrap`.

| Numerical step | Uses hard-coded 5? | Actual source |
| --- | --- | --- |
| user sampling | NO | `unique = np.unique(users)` then `rng.choice(unique, size=len(unique), replace=True)` |
| bootstrap resampling | NO | resample of observed unique user IDs with replacement |
| positive-window selection | NO | windows belonging to drawn users (`y[sel]`) |
| PR-AUC | NO | `average_precision_score` on resampled labels/scores |
| F1 | NO | `f1_score` at frozen C2/C5 thresholds |
| confidence intervals | NO | 2.5/97.5 percentiles of 2000 finite deltas |
| bootstrap stopping | NO | `while len(deltas_pr) < n_valid`; abort if `attempted > n_valid * 50` |
| number of valid replicates | NO | `n_valid = BOOTSTRAP_VALID_RESAMPLES` (2000) |
| variable `p5` | NO | concatenated C5 model scores, not cluster count 5 |
| return metadata | YES | `effective_malicious_cluster_count: 5` and Five-cluster wording |

**Ruling: `BOOTSTRAP_NUMERICS_UNAFFECTED_METADATA_ONLY`**

`bootstrap_numerical_effect = UNALTERED`

---

## TABLE 6 — Original vs corrected derivative diff

Programmatic tree walk of original `EDITOR007C_PREDICTIVE_RESULTS.json` versus `EDITOR007C_PREDICTIVE_RESULTS_PAPER_CORRECTED.json`.

| Check | Value |
| --- | ---: |
| approved_metadata_fields_changed | 6 |
| numeric_values_changed | 0 |
| unexpected_fields_changed | 0 |
| bootstrap estimates / CIs / thresholds / scenario counts | unchanged |
| family/seed predictive metrics | unchanged |

---

## TABLE 7 — Correct r5.1 malicious-unit interpretation

Taken from already frozen EDITOR-007B evidence (`EDITOR007B_R51_METADATA_VALIDATION.json`, `EDITOR007B_R51_BUNDLE_MANIFEST.json`, `EDITOR007B_R51_COUNT_VALIDATION.json`). Not inferred from EDITOR-007C results.

| Quantity | Value |
| --- | --- |
| official mapped insiders | 4 (`JTC1885`, `LBE0376`, `BGC0686`, `JAK0783`) |
| official incidents | 4 (`r5.1-1`, `r5.1-2`, `r5.1-3`, `r5.1-4`) |
| mapping | one-to-one (4 insiders, 4 incidents) |
| event-level labelled users | 17 |
| contextual event-level users | 13, official incident ID null |
| contextual users as extra official incidents | NO |
| effective_malicious_cluster_count | 4 |
| frozen wording | Four official insider–incident clusters are represented. |
| r5.1 replaces r6.2 | NO |
| r5.1 is primary confirmation | NO |
| C2 remains first-class control | YES |
| unused_leaf_fraction | DISABLED_NOT_REPRODUCIBLE |
| tree_contribution_rho | DISABLED_NOT_REPRODUCIBLE |

No new predictive claim is added. This task freezes evidence only.

---

## Explicit preservation statement

The original EDITOR-007C producing outputs are preserved unchanged. The paper-facing derivative corrects only a descriptive cluster-count metadata field from five to four. No predictive score, metric, bootstrap estimate, confidence interval, threshold, or model output was recomputed or modified.
