# EDITOR-006A — r6.2 External-Evaluation Contract and Artefact Freeze

TASK ID: EDITOR-006A
Generated (UTC): 2026-08-13T04:46:45Z
Verdict: **EDITOR006A_PREINFERENCE_FREEZE_COMPLETE_WITH_QUALIFICATIONS**

R62_ROLE = PRIMARY_UNTOUCHED_CONFIRMATORY_CANDIDATE
R51_ROLE = R51_SECONDARY_STRESS_ONLY
EXTERNAL_EVALUATION_TYPE = UNTOUCHED_CROSS_VERSION_EXTERNAL_COHORT

This freeze does **not** call r6.2 an internally held-out r6.2 test split.

Declarations:
- predictive models loaded = false
- predictive inference executed = false
- model metrics computed = false
- training / retraining / fine-tuning / calibration / threshold selection = false
- scaler fit on r6.2 = false
- frozen r5.2-derived models unchanged
- dataset roles unchanged
- estimability gates not relaxed
- raw CERT files not overwritten
- future external test not run

## TABLE 1 — r5.2 LABEL-PROVENANCE RULING

| Item | Ruling |
| --- | --- |
| A. user-day malicious if ANY official-answer-matched event for that user that day? | YES |
| B. contextual observable users (not official insiders) can receive positive day/window labels? | YES |
| C. labels restricted to official insiders only? | NO |
| Exact contract | R52_LABEL_RULE_EVENT_LEVEL_ANSWER_MATCH |
| Producing implementation | cert-r52-preparation/scripts/cert_common13_pipeline.py |
| label_activity_log | is_malicious = raw id ∈ matched answer IDs; no insider filter |
| Daily aggregation | is_malicious_interval iff any matched event that raw user-day |
| Sequence label | y=1 iff any day in T=20 is malicious |
| r5.2 official mapped insiders (insiders.csv dataset=5.2) | 99 |
| r5.2 answer users (per-user files + in-file user field) | 198 |
| r5.2 answer users beyond official insiders | 99 |
| Chosen because it matches r5.2 producing code | NOT because it yields more r6.2 positives |

## TABLE 2 — r6.2 LABEL CONTRACT

| Quantity | Frozen value | Role |
| --- | --- | --- |
| Completed-window positives (event-level) | 715 | FROZEN model-free count for predictive eval |
| Endpoint positives (event-level) | 78 | FROZEN |
| De-overlap offset-0 positives (event-level) | 35 | FROZEN; ≥30 gate PASS |
| Completed-window official-insider-attributed | 222 | Descriptive only |
| Endpoint official-insider-attributed | 44 | Descriptive only |
| De-overlap offset-0 official-insider-only (exact) | 11 | Descriptive only; not ≈11 |
| Official mapped insiders (user gate) | 5 | GATE; unchanged |
| Official incidents (incident gate) | 5 | GATE; unchanged |
| Evaluation type | UNTOUCHED_CROSS_VERSION_EXTERNAL_COHORT | Not an internally held-out r6.2 split |

Official-only de-overlap per insider (exact, model-free from answer-file user+timestamp on calendar 2010-01-02…2011-06-01, non-overlapping T=20, offset 0): `{"ACM2278": 1, "CDE1846": 4, "CMP2946": 4, "MBG3183": 1, "PLJ1771": 1}`

Answer-timestamp reconstruction agrees with EDITOR-005A frozen 715 / 78 / 35 and official 222 / 44: **True**

## TABLE 3 — INSIDER/INCIDENT DEPENDENCE

| Item | Value |
| --- | --- |
| official mapped insiders | 5 |
| official incidents | 5 |
| mapping | one-to-one (ACM2278↔r6.2-1, CMP2946↔r6.2-2, PLJ1771↔r6.2-3, CDE1846↔r6.2-4, MBG3183↔r6.2-5) |
| effective malicious cluster count | 5 |
| frozen wording | Five official insider–incident clusters are represented. |
| user-clustered vs incident-clustered | NOT two independent levels of resolution |
| do not describe as | ten independent malicious units |

## TABLE 4 — SCALER FREEZE

| Item | Value |
| --- | --- |
| scaler_id | r52_T20_s1_trainonly_standardscaler_v1 |
| dataset_fitted_on | CERT r5.2 TRAIN ONLY |
| n_train_daily_rows | 826000 |
| ddof | 0 |
| output dtype | float32 |
| external-data fit | none |
| expected SHA-256 | 6a092df8275e15b6e05c685b306f48de72ab55fb1e88ede5ed5899ecd63f3488 |
| observed SHA-256 | 6a092df8275e15b6e05c685b306f48de72ab55fb1e88ede5ed5899ecd63f3488 |
| status | PASS |
| path | C:\PhD\07_Projects\teacher-anchored-insider-threat-detection\review\editor006a_preinference_freeze\EDITOR006A_SCALER.json |

## TABLE 5 — HTTP SEMANTIC COMPATIBILITY

| Item | Value |
| --- | --- |
| r5.2 http_count producing rule | COUNT of HTTP rows for that user-day; one row = one event |
| URL/content deduplication | none (SQL SUM event_type='http') |
| r5.2 HTTP header | id,date,user,pc,url,content |
| r6.2 HTTP header | id,date,user,pc,url,activity,content |
| schema note | r6.2 adds `activity`; does not change row=event counting |
| semantic equivalence | PASS |

## TABLE 6 — DATA-QUALITY CAVEATS

| Caveat | Labels changed? | Status |
| --- | --- | --- |
| scenario-4 malformed insiders.csv start `/21/2011 11:43:39` | NO | frozen; not a matching filter |
| inherited Stage 2B-2 one-email-field mismatch | NO | 470/470 IDs MATCHED_ONCE |
| CDE1846 days from matched event timestamps, not malformed summary date | NO | PASS |

CDE1846 unique malicious calendar days from scenario-4 answer event timestamps: 2011-02-21, 2011-03-17, 2011-03-22, 2011-03-29, 2011-04-06, 2011-04-07, 2011-04-11, 2011-04-15, 2011-04-25

## TABLE 7 — 18-MODEL HASH FREEZE

| family | seed | expected SHA-256 | observed SHA-256 | status |
| --- | --- | --- | --- | --- |
| teacher_frozen_odst | 42 | 783d0913f85d492ddacec83a274ba2d4f13ad25eaf1a34ebcc64a960bda8ff86 | 783d0913f85d492ddacec83a274ba2d4f13ad25eaf1a34ebcc64a960bda8ff86 | MATCH |
| teacher_frozen_odst | 52 | 7273327495bbe463cfb3d50fa94c81c82de7b304370a816343046f559fc3d191 | 7273327495bbe463cfb3d50fa94c81c82de7b304370a816343046f559fc3d191 | MATCH |
| teacher_frozen_odst | 62 | 247d6e71353b49ea0a77a073a8606fbf35b88106faae7dae6ec53361621e9d92 | 247d6e71353b49ea0a77a073a8606fbf35b88106faae7dae6ec53361621e9d92 | MATCH |
| C2 | 42 | c5b8ab96a6f347afb85708857cef56b4a632f6092dfda9339ab9a3558daf863e | c5b8ab96a6f347afb85708857cef56b4a632f6092dfda9339ab9a3558daf863e | MATCH |
| C2 | 52 | 2215b36edd015f783de86ecb1b40cdd535fb6f082adc16a377574a24a8d0c22b | 2215b36edd015f783de86ecb1b40cdd535fb6f082adc16a377574a24a8d0c22b | MATCH |
| C2 | 62 | 595a5e57ec78d6d34e2811609dc97514b0703cab807b7dffe873128a92ecc5c2 | 595a5e57ec78d6d34e2811609dc97514b0703cab807b7dffe873128a92ecc5c2 | MATCH |
| C5_original_paper | 42 | 2b6452698dd0da53f0229bc43040a877017ac9299b277f2f98c1d7ca64c1cc42 | 2b6452698dd0da53f0229bc43040a877017ac9299b277f2f98c1d7ca64c1cc42 | MATCH |
| C5_original_paper | 52 | 9c9d035fe81f54898dee4ecf4d2ecaf8423a21ecc3551793dc16d1980af1eb0d | 9c9d035fe81f54898dee4ecf4d2ecaf8423a21ecc3551793dc16d1980af1eb0d | MATCH |
| C5_original_paper | 62 | f5e8eb5260113a0aeabfb95ef198e1aa80022a26dfe91f3bf9262acbf5453ec9 | f5e8eb5260113a0aeabfb95ef198e1aa80022a26dfe91f3bf9262acbf5453ec9 | MATCH |
| attention_linear | 42 | b807a82343b432343b7e3cbc86ee76cba7011066827f3baa089aa78a02c02b53 | b807a82343b432343b7e3cbc86ee76cba7011066827f3baa089aa78a02c02b53 | MATCH |
| attention_linear | 52 | 5e5e2a136bedba3d3477d05c5b1215331cb97339b74003bcb60f8cb4885ba86c | 5e5e2a136bedba3d3477d05c5b1215331cb97339b74003bcb60f8cb4885ba86c | MATCH |
| attention_linear | 62 | 4543c167fdab3b0376087731571f7b3bcecadd43f8ff05c6b5371f0073ba425a | 4543c167fdab3b0376087731571f7b3bcecadd43f8ff05c6b5371f0073ba425a | MATCH |
| RF_40 | 42 | 38b8830acec3b9c399411093ac38ed6bed6dca52a0cf05be9c87178cb05f5780 | 38b8830acec3b9c399411093ac38ed6bed6dca52a0cf05be9c87178cb05f5780 | MATCH |
| RF_40 | 52 | 6f409fb9df15a76319a16988ed5ee0ca42da0a9c48981240e15edee773d3d89d | 6f409fb9df15a76319a16988ed5ee0ca42da0a9c48981240e15edee773d3d89d | MATCH |
| RF_40 | 62 | b0f4e762e34a3e5f0f07a64130130a7f223bfbc486b9bdcd2d2549210fb36df5 | b0f4e762e34a3e5f0f07a64130130a7f223bfbc486b9bdcd2d2549210fb36df5 | MATCH |
| XGBoost_40 | 42 | 2109554164abdd002ce0a4377f957c5aa3bc26886a197749ea79fc04d9b94fae | 2109554164abdd002ce0a4377f957c5aa3bc26886a197749ea79fc04d9b94fae | MATCH |
| XGBoost_40 | 52 | 0f32857232341cb6a26d6cf55cb2375b8e256e0e0f89519d3059415cac8ad7e6 | 0f32857232341cb6a26d6cf55cb2375b8e256e0e0f89519d3059415cac8ad7e6 | MATCH |
| XGBoost_40 | 62 | 3062488680b8bc05959ddcb0cab948378988564fc82a88213e346ca570b0c7ab | 3062488680b8bc05959ddcb0cab948378988564fc82a88213e346ca570b0c7ab | MATCH |

Allow-list status: **PASS**

## TABLE 8 — C5 DENY-LIST

| family | seed | denied SHA-256 | observed SHA-256 | status |
| --- | --- | --- | --- | --- |
| C5_ablation_retrained_DO_NOT_USE | 42 | a5a08dc24a89014fd1bb92c6c6342ed50511b33804e95246e480e90c4692b214 | a5a08dc24a89014fd1bb92c6c6342ed50511b33804e95246e480e90c4692b214 | MATCH_DENY_HASH |
| C5_ablation_retrained_DO_NOT_USE | 52 | 3203455562ec6ff4018cc5cb3299bc2530bc8eff95aa523e6b7746f43731d971 | 3203455562ec6ff4018cc5cb3299bc2530bc8eff95aa523e6b7746f43731d971 | MATCH_DENY_HASH |
| C5_ablation_retrained_DO_NOT_USE | 62 | 54f879d6b163185073ea586fa50a68edf89b603c269c6208c8b48156dccd4e22 | 54f879d6b163185073ea586fa50a68edf89b603c269c6208c8b48156dccd4e22 | MATCH_DENY_HASH |

The future harness must abort if any denied hash is supplied. Do not confuse original paper C5 with ablation-retrained C5.

## TABLE 9 — THRESHOLD FREEZE

| family | seed | threshold (exact) | source |
| --- | --- | --- | --- |
| teacher_frozen_odst | 42 | 0.56 | r52_test_freeze_manifest_v2.json |
| teacher_frozen_odst | 52 | 0.8400000000000001 | r52_test_freeze_manifest_v2.json |
| teacher_frozen_odst | 62 | 0.55 | r52_test_freeze_manifest_v2.json |
| C2 | 42 | 0.6 | C2/seed42/seed_summary.json best_threshold |
| C2 | 52 | 0.8300000000000001 | C2/seed52/seed_summary.json best_threshold |
| C2 | 62 | 0.6544522184133537 | C2/seed62/seed_summary.json best_threshold |
| C5_original_paper | 42 | 0.56 | original C5 seed42/seed_summary.json best_threshold |
| C5_original_paper | 52 | 0.85 | original C5 seed52/seed_summary.json best_threshold |
| C5_original_paper | 62 | 0.55 | original C5 seed62/seed_summary.json best_threshold |
| attention_linear | 42 | 0.9500000000000001 | r52_test_freeze_manifest_v2.json |
| attention_linear | 52 | 0.9600000000000001 | r52_test_freeze_manifest_v2.json |
| attention_linear | 62 | 0.9400000000000001 | r52_test_freeze_manifest_v2.json |
| RF_40 | 42 | 0.38 | r52_test_freeze_manifest_v2.json |
| RF_40 | 52 | 0.46 | r52_test_freeze_manifest_v2.json |
| RF_40 | 62 | 0.37 | r52_test_freeze_manifest_v2.json |
| XGBoost_40 | 42 | 0.18000000000000002 | r52_test_freeze_manifest_v2.json |
| XGBoost_40 | 52 | 0.16 | r52_test_freeze_manifest_v2.json |
| XGBoost_40 | 62 | 0.18000000000000002 | r52_test_freeze_manifest_v2.json |

C2 seed 62 = `0.6544522184133537` (unrounded). Future evaluator LOADS thresholds only.

## TABLE 10 — RF/XGB INPUT CONTRACT

| Item | Value |
| --- | --- |
| pipeline | raw r6.2 → common-13 daily → frozen r5.2 scaler → float32 T=20 → aggregate_common13_windows → 40 features → frozen RF/XGB |
| aggregator source | C:\PhD\07_Projects\cert-r52-locked-baselines\scripts\r52_locked_baselines\data.py |
| aggregator SHA-256 | dd47330f82791bc7c56d3d6019ce80bcd6ca31f497b9fffeabc9165f35b1b2f9 |
| pretest-freeze-v2 data.py SHA-256 | dd47330f82791bc7c56d3d6019ce80bcd6ca31f497b9fffeabc9165f35b1b2f9 |
| hash match vs pretest freeze | True |
| consumes scaled 20×13 | YES |
| feature count | 40 |
| feature order available | YES (LOCKED_AGG_FEATURES / feature_names.json) |
| semantic equivalence | PASS |

Exact 40-feature order:

```
[
  "total_events_sum",
  "total_events_mean",
  "total_events_max",
  "total_events_std",
  "logon_count_sum",
  "logon_count_mean",
  "logon_count_max",
  "logon_count_std",
  "device_count_sum",
  "device_count_mean",
  "device_count_max",
  "device_count_std",
  "file_count_sum",
  "file_count_mean",
  "file_count_max",
  "file_count_std",
  "email_count_sum",
  "email_count_mean",
  "email_count_max",
  "email_count_std",
  "http_count_sum",
  "http_count_mean",
  "http_count_max",
  "http_count_std",
  "active_duration_minutes_sum",
  "active_duration_minutes_mean",
  "active_duration_minutes_max",
  "active_duration_minutes_std",
  "has_logon_activity_active_days",
  "has_logon_activity_active_proportion",
  "has_device_activity_active_days",
  "has_device_activity_active_proportion",
  "has_file_activity_active_days",
  "has_file_activity_active_proportion",
  "has_email_activity_active_days",
  "has_email_activity_active_proportion",
  "has_http_activity_active_days",
  "has_http_activity_active_proportion",
  "is_active_day_active_days",
  "is_active_day_active_proportion"
]
```

## TABLE 11 — REMAINING BLOCKERS

| Item | Value |
| --- | --- |
| HARD BLOCKs | none |
| Qualifications (not blockers) | Paper-support registry still points at warmup commit 330ac6a (completed_through_stage2b1a); actual warmup HEAD is later and is recorded honestly, not rewritten.; Inherited Stage 2B-2 one-email-field mismatch; 470/470 malicious IDs remain MATCHED_ONCE.; insiders.csv scenario-4 start field is malformed (`/21/2011 11:43:39`); CDE1846 labels use matched event-record timestamps (first event 02/21/2011 11:43:39), not that summary field.; r6.2 HTTP has an extra `activity` column relative to r5.2; http_count remains one row = one event with no URL/content deduplication (HTTP semantic PASS).; No r6.2 internal partition was selected (candidates A–D remain UNRESOLVED); frozen counts are whole-cohort.; Checkpoint/data identity is frozen by SHA-256; that is not a claim of full from-source reproducibility of uncommitted historical producers.; Official-insider-only de-overlap is reported descriptively and does not replace the frozen EVENT_LEVEL counts 715 / 78 / 35. |
| Predictive harness this task | NOT built / NOT run |
| r6.2 predictive inference | NOT authorised |
| NEXT_ACTION | STOP. Do not build or run the predictive harness in this task. EDITOR-006B may build a strict hash-gated inference-only harness on synthetic/development fixtures only. No CERT r6.2 predictive inference is authorised. |

## Provenance hygiene

- Paper-support registry pointer: `330ac6a` (`r62_model_free_matching_stage2b1a` / `completed_through_stage2b1a`).
- Actual warmup HEAD: `6b45cbc07d3cc2f80df75814329aa086756c717b` branch `objective1-r62-model-free-warmup`.
- Paper-support HEAD: `b1eee6a11dd35e8b87840ce0974d2d8bf6368a3c` branch `repository-hardening`.
- This task does not rewrite git history or pretend an uncommitted historical producer was committed.
- Checkpoint/data identity (SHA-256) is distinct from full from-source reproducibility.

## FINAL VERDICT

EDITOR006A_PREINFERENCE_FREEZE_COMPLETE_WITH_QUALIFICATIONS

R62_LABEL_RULE = R52_LABEL_RULE_EVENT_LEVEL_ANSWER_MATCH
MODEL_ALLOWLIST_STATUS = PASS
SCALER_FREEZE_STATUS = PASS
HTTP_CONTRACT_STATUS = PASS
THRESHOLD_FREEZE_STATUS = PASS
REMAINING_BLOCKERS = none
NEXT_ACTION = STOP. Do not build or run the predictive harness in this task. EDITOR-006B may build a strict hash-gated inference-only harness on synthetic/development fixtures only. No CERT r6.2 predictive inference is authorised.
