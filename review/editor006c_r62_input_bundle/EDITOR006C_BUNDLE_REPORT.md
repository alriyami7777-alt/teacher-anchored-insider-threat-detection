# EDITOR-006C — Final Model-Free CERT r6.2 Input Bundle

Verdict: **EDITOR006C_R62_INPUT_BUNDLE_READY_WITH_QUALIFICATIONS**

R62_ROLE = PRIMARY_UNTOUCHED_CONFIRMATORY_CANDIDATE
EXTERNAL_EVALUATION_TYPE = UNTOUCHED_CROSS_VERSION_EXTERNAL_COHORT

This task did **not** load any predictive model and did **not** score CERT r6.2.
This is **not** an external-run authorisation.

Large arrays live at `C:\\PhD\\06_Datasets\\derived\\teacher_anchored_r62_editor006c_bundle\\` and are not in Git.

---

## TABLE 1 — SOURCE / CONTRACT PROVENANCE

| Item | Value |
| --- | --- |
| Raw r6.2 root | `C:\\PhD\\06_Datasets\\r6.2\\r6.2` |
| Canonical answers | `C:\\PhD\\07_Projects\\cert-r42-feasibility\\answers\\answers` |
| Size/mtime vs EDITOR-005A | MATCH (no 90 GiB rehash) |
| Scaler SHA-256 | `6a092df8275e15b6e05c685b306f48de72ab55fb1e88ede5ed5899ecd63f3488` |
| Label rule | `R52_LABEL_RULE_EVENT_LEVEL_ANSWER_MATCH` |
| Feature order | frozen common-13 |
| HTTP count | one HTTP row = one event; no URL dedup |
| Active duration | max(minutes(latest-earliest), 0) over five sources |

---

## TABLE 2 — DENSE DAILY BUNDLE

| Field | Value |
| --- | --- |
| shape | (4000, 516, 13) |
| dtype | float32 |
| feature order | total_events, logon_count, device_count, file_count, email_count, http_count, active_duration_minutes, has_logon_activity, has_device_activity, has_file_activity, has_email_activity, has_http_activity, is_active_day |
| NaN | 0 |
| Inf | 0 |
| SHA-256 | `c32bd47eba93c4154a49768cc5d9d910345ad9275b88e61ab9391d53a7207bd2` |
| active user-days | 1394010 |
| scaler | LOAD/TRANSFORM only; r5.2 TRAIN fit; no r6.2 adaptation |

---

## TABLE 3 — LABEL REPRODUCTION

Producing contract: `R52_LABEL_RULE_EVENT_LEVEL_ANSWER_MATCH` (no official-insider-only label filter).

| View | Event-level | Official-insider descriptive |
| --- | ---: | ---: |
| completed-window T=20 stride=1 | **715** | **222** |
| endpoint past-only | **78** | **44** |
| de-overlap offset-0 | **35** | **11** |

Frozen required values reproduced: 715 / 78 / 35 and 222 / 44 / 11.

---

## TABLE 4 — GROUND-TRUTH / SCENARIO METADATA

| Item | Value |
| --- | --- |
| Official mapped insiders | 5: ACM2278, CMP2946, PLJ1771, CDE1846, MBG3183 |
| Official incidents | 5: r6.2-1 … r6.2-5 (1:1 with insiders) |
| effective_malicious_cluster_count | 5 |
| Event-level labelled users | 29 (24 contextual; not extra actors) |
| Answer IDs | 470 MATCHED_ONCE, 0 unmatched, 0 multiple |
| official_incident_id for contextual | null (sentinel empty string) |
| Scenario bits | bit0=r6.2-1 … bit4=r6.2-5 |
| CDE1846_EVENT_DATE_LABEL_CHECK | PASS |
| Inherited Scenario-3 email field mismatch | documented; IDs still 470/470; labels unchanged |

---

## TABLE 5 — WINDOW INDEX / SEQUENCE ORDER

| Field | Value |
| --- | --- |
| window_index shape | (1988000, 2) int32 |
| columns | [user_index, start_day_index] |
| order | user ascending, then start 0..496; no shuffle |
| sequence_id | `{user_id}\|{window_start_date}\|{window_end_date}` |
| sequence_order_sha256 | `21c4dd51f8aefb26fa1987764b0c129fac599fc52653349732a4fd8e39c32b4c` |
| de-overlap retained | 100000 |

---

## TABLE 6 — LARGE BUNDLE COMPONENT HASHES

| file | bytes | shape | dtype | SHA-256 | role |
| --- | ---: | --- | --- | --- | --- |
| `scaled_dense_daily.npy` | 107328128 | [4000, 516, 13] | float32 | `c32bd47eba93c4154a49768cc5d9d910345ad9275b88e61ab9391d53a7207bd2` | scaled common-13 daily design; frozen r5.2 scaler transform-only |
| `malicious_day_labels.npy` | 2064128 | [4000, 516] | uint8 | `78e3202cb79f2c58f9d9903763c2a446c7be0b6008b5d4d7c986d12fe30bbcf8` | event-level answer-match user-day labels (primary producing label) |
| `answer_scenario_day_bitmask.npy` | 2064128 | [4000, 516] | uint8 | `4758148e3957fb9a17797b58f6a56f41274f75635df0dda4cd0e68b903d85e29` | uint8 bits 0-4 = r6.2-1..r6.2-5 |
| `user_ids.npy` | 256128 | [4000] | <U16 | `80e9f043ddf35732eea77a6fbeda916b77402a857570c4620ca802c0ca8a36c2` | lexicographic ascending event-observed user IDs |
| `calendar_dates.npy` | 20768 | [516] | <U10 | `5db6f62535cc8c1c45ac92dc1111c0e842683403569e1312fcec20ef1a3b4309` | contiguous YYYY-MM-DD calendar |
| `official_insider_flags.npy` | 4128 | [4000] | uint8 | `71188e7fde146989765d20030aa679670b35926a118165047cc6f8957fbaec5d` | 1 iff official mapped insider |
| `official_incident_codes.npy` | 128128 | [4000] | <U8 | `ac6c6860c5cf57fd4ae8f2ebe786dbc8966c903c29c496d6ff176096a522033f` | official incident id or sentinel '' for null |
| `window_index.npy` | 15904128 | [1988000, 2] | int32 | `703d14e489617a8b3fbc63f1b10aa9e1d099c0d81c096de2630aec875776a484` | int32 [user_index, start_day_index]; user then start ascending |
| `completed_window_labels.npy` | 1988128 | [1988000] | uint8 | `3082df95fa676c96e9d2579e22dfedea02902cb6bc46e563a8006c36d4bd0984` | any-day event-level label in T=20 window |
| `endpoint_labels.npy` | 1988128 | [1988000] | uint8 | `559f9d0b60b2c3093e26260d88b0c3fa3a12c524407016df2275e14d1ae47aca` | malicious status of decision day only |
| `deoverlap_offset0_mask.npy` | 1988128 | [1988000] | uint8 | `dbb430c9734cd0852e19c17cd0e3ef71b399cdf267d81f331bfc679d126c9121` | start_day_index % 20 == 0 |
| `window_scenario_bitmask.npy` | 1988128 | [1988000] | uint8 | `a6854077dc3a2c75695179bd9c33bbb91dbdf3d60d6db84dbc0383c48ab2a481` | OR of day scenario bits across T=20 |
| `endpoint_scenario_bitmask.npy` | 1988128 | [1988000] | uint8 | `65d753828783e091f09422358ad9baa28cba9de501f528cad94d3e756ef08439` | scenario bitmask on decision day |

---

## TABLE 7 — CONTRACT / HARNESS IDENTITY

| Item | Value |
| --- | --- |
| harness commit | `2a73123b25f9bf9d92b651e07ce06b8fa1ba6017` |
| harness_code_sha256 | `d287a85e03e8c666be5cf06c2329e6d81fbed3ea08cb1563225ac2d92badc451` |
| harness_runner_sha256 | `3965f47a08fa79f17bc2d4c1cbf54fbdcd3ce1d6add6d7f864c123a501f8d17d` |
| contract_bundle_sha256 | `d9f3daf89da4b1d06d22081245a63eac50a0768aece1f1e566187593783e734a` |
| model_allowlist_sha256 | `699c983d1ad98a5dcce7768447dcac4a44f5a5e8fed740b4c8378876efa52e5a` |
| input_bundle_manifest_sha256 | `0e53a750b9682aa0ed71105619c0b31fccf2208f67eb6c80896946c0e8564fec` |

---

## TABLE 8 — STREAMING PROVIDER COMPATIBILITY

Provider: `DenseDailyWindowProvider`. Batch bound: 1024. No model called. No full (N,20,13) tensor.

| checkpoint | slice | batch shape | user | start | completed | endpoint |
| --- | --- | --- | --- | --- | --- | --- |
| first | 0:1024 | [1024, 20, 13] | AAB0162 | 2010-01-02 | 0 | 0 |
| middle | 993280:994304 | [1024, 20, 13] | JRR0769 | 2010-10-03 | 0 | 0 |
| final | 1987584:1988000 | [416, 20, 13] | ZZO2997 | 2010-03-24 | 0 | 0 |

---

## TABLE 9 — PROTOCOL EFFECT REGISTER

| Field | Value |
| --- | --- |
| model_files_opened | [] |
| files_modified_existing | [] |
| predictive_inference_calls | [] |
| model_deserialisation_calls | [] |
| scaler_fit_calls | [] |
| threshold_selection_calls | [] |
| calibration_fit_calls | [] |

---

## TABLE 10 — REMAINING QUALIFICATIONS

* Five collinear insider–incident clusters (not ten independent malicious units).
* Whole-cohort untouched cross-version external test, not an internal r6.2 holdout.
* Event-level label includes 24 contextual users; they are not extra official actors.
* Checkpoint identity does not establish complete from-source reproducibility.
* Unused-leaf / tree-contribution-rho remain manuscript-facing and externally disabled (EDITOR-006B1).
* Inherited Stage 2B-2 one email Scenario-3 field mismatch does not alter event IDs or labels.
* CDE1846 labels come from matched raw-event timestamps, not `/21/2011 11:43:39`.

---

NEXT_ACTION = Independent EDITOR-006C-R review of the bundle, manifest, sequence ordering, hashes, and metadata. Do not score CERT r6.2.
