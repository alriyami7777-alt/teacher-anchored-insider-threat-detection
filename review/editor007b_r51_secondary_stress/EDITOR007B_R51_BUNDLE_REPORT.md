# EDITOR-007B — Model-free CERT r5.1 secondary-stress bundle

Role: **R51_SECONDARY_STRESS_ONLY**

This task did **not** load any predictive model and did **not** score CERT r5.1 or rerun CERT r6.2.
This is **not** a true predictive authorisation.

Large arrays live at `C:\\PhD\\06_Datasets\\derived\\teacher_anchored_r51_editor007b_bundle\\` and are not in Git.

---

## Geometry (derived from data; consistent with EDITOR-004A)

| Field | Value |
| --- | --- |
| users | 2000 |
| calendar_start | 2010-01-02 |
| calendar_end | 2011-06-02 |
| calendar_days | 517 |
| dense_user_days | 1034000 |
| eligible T=20 windows | 996000 |
| n_starts | 498 |
| de-overlap retained (offset 0) | 50000 |

---

## Frozen label / answer anchors

Producing contract: `R52_LABEL_RULE_EVENT_LEVEL_ANSWER_MATCH` (no official-insider-only label filter).
Matching: declared-source-scoped (r5.1 event IDs unique within a CSV, not globally).

| Anchor | Value |
| --- | ---: |
| official malicious answer IDs | 351 |
| MATCHED_ONCE | 351 |
| UNMATCHED | 0 |
| MULTIPLE | 0 |
| official mapped insiders | 4 |
| official incidents | 4 |
| event-level labelled users | 17 |
| completed-window positives | 461 |
| endpoint positives | 58 |
| de-overlap offset-0 positives | 24 |
| official-only completed (descriptive) | 200 |
| official-only endpoint (descriptive) | 44 |
| official-only de-overlap (descriptive) | 11 |

Official insider–incident clusters: **4**. Not 8 independent malicious units.

Contextual event-level users receive null official incident IDs: ACB0270, DKB0259, EHW0689, GJB0268, HCW0681, HRS0274, KSC0148, LHO0687, MAH0683, RNW0269, SDP0271, SKR0266, UNK0265.

---

## Scaler / features

| Item | Value |
| --- | --- |
| scaler SHA-256 | `6a092df8275e15b6e05c685b306f48de72ab55fb1e88ede5ed5899ecd63f3488` |
| scaler | LOAD/TRANSFORM only; r5.2 TRAIN fit; no r5.1 adaptation |
| feature order | total_events, logon_count, device_count, file_count, email_count, http_count, active_duration_minutes, has_logon_activity, has_device_activity, has_file_activity, has_email_activity, has_http_activity, is_active_day |
| HTTP | one row = one event |
| active duration | max(minutes(latest-earliest), 0) over five sources |
| NaN / Inf | 0 / 0 |
| scaled SHA-256 | `019d04f827eba7f2b4d3814307a75bf3d77665791fb091924139f54c8d254794` |
| active user-days | 700764 |

---

## Sequence order

| Field | Value |
| --- | --- |
| window_index | `[user_index, start_day_index]` |
| order | user ascending, then start 0..497; no shuffle |
| sequence_id | `{user_id}\|{window_start_date}\|{window_end_date}` |
| sequence_order_sha256 | `9c5f9f36bded4fb0d70820fe54cd91964a0286fd134bbb806f4562dc15ce7118` |

---

## Component hashes

| file | bytes | shape | dtype | SHA-256 | role |
| --- | ---: | --- | --- | --- | --- |
| `scaled_dense_daily.npy` | 53768128 | [2000, 517, 13] | float32 | `019d04f827eba7f2b4d3814307a75bf3d77665791fb091924139f54c8d254794` | scaled common-13 daily design; frozen r5.2 scaler transform-only |
| `malicious_day_labels.npy` | 1034128 | [2000, 517] | uint8 | `e501687c7cd39ffa641cb023bd96cfc8b86ad03e1f11e8b68ad8ec3a8ede5a25` | event-level answer-match user-day labels (primary producing label) |
| `answer_scenario_day_bitmask.npy` | 1034128 | [2000, 517] | uint8 | `5d344192be9da971135693884da4ff5ba79b145a899ae63daef760a3286b198e` | uint8 bits 0-3 = r5.1-1..r5.1-4 |
| `user_ids.npy` | 128128 | [2000] | <U16 | `861d6a3485a2796f54bdaac5dd829e5e724c8a9da36c0679a6ba090482d6ace3` | lexicographic ascending event-observed user IDs |
| `calendar_dates.npy` | 20808 | [517] | <U10 | `6204f215044b554e1ad94a9186d91e60df5ba86cacaf0bb0d8ec30b23ba0c6cf` | contiguous YYYY-MM-DD calendar |
| `official_insider_flags.npy` | 2128 | [2000] | uint8 | `a60f02e4211938d43e0c0417c8cf2953333cd44a42f2bb9ef363340e1d617864` | 1 iff official mapped insider |
| `official_incident_codes.npy` | 64128 | [2000] | <U8 | `1617bbc2d2a6fe32d9f7faa69051f38d78d5ed6821baa1a8f416c66f7a3039c0` | official incident id or sentinel '' for null |
| `window_index.npy` | 7968128 | [996000, 2] | int32 | `9b918cb35ebe34fa44f2297f6dceea16cf7fc5f945560c4b6ed4ff0e2110ed39` | int32 [user_index, start_day_index]; user then start ascending |
| `completed_window_labels.npy` | 996128 | [996000] | uint8 | `ae322d3ef47e898bef82bb279da8dea4ae314bee8eb1034c03ef0400e50d832a` | any-day event-level label in T=20 window |
| `endpoint_labels.npy` | 996128 | [996000] | uint8 | `fa4e865a4c851badde4d3a768ad493498eed2eb71b6d4d716e5c3e2c809f3443` | malicious status of decision day only |
| `deoverlap_offset0_mask.npy` | 996128 | [996000] | uint8 | `c8a820f2160409b59a345d33507d28f6ec0b8b147cc601bb81f8d771a4354940` | start_day_index % 20 == 0 |
| `window_scenario_bitmask.npy` | 996128 | [996000] | uint8 | `8ec9b57ad3d20865ca3c58aaec994c99bad4fb569d84d3d6973654ebce730c4d` | OR of day scenario bits across T=20 |
| `endpoint_scenario_bitmask.npy` | 996128 | [996000] | uint8 | `063786160dddc44e528cbae305126cf3f65850df623c1ae86c42324154d46ed6` | scenario bitmask on decision day |

input_bundle_manifest_sha256 = `366a1dd742a24b9470326c411dd5b40a7a2424c9c48ae3c5eb4b523f7fe01903`

---

## Feature profile (scaled daily flatten; no model)

| feature | mean | sd | q01 | q50 | q99 | frac\|z\|>3 | frac\|z\|>5 | frac\|z\|>10 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| total_events | -0.003446225603863622 | 1.0015327634415272 | -0.9700122475624084 | -0.4393249750137329 | 2.1894280910491943 | 0.005138297872340426 | 0.0007437137330754352 | 0.0 |
| logon_count | -0.00805707855319435 | 0.9953960687243233 | -1.038452386856079 | 0.12595315277576447 | 4.783575534820557 | 0.01789651837524178 | 0.006812379110251451 | 0.0 |
| device_count | 0.017121756473754315 | 1.0534792334239542 | -0.2647252380847931 | -0.2647252380847931 | 5.510107040405273 | 0.03473017408123791 | 0.021927466150870406 | 0.0 |
| file_count | 0.01270322668261653 | 1.030969362617167 | -0.22539490461349487 | -0.22539490461349487 | 6.529504299163818 | 0.02573791102514507 | 0.020203094777562863 | 0.0 |
| email_count | -0.006848612242908806 | 0.9914412776686378 | -0.935833215713501 | -0.3357752859592438 | 2.7190651893615723 | 0.006230174081237911 | 0.0005667311411992263 | 0.0 |
| http_count | -0.0038946210357812695 | 0.9989981647395033 | -0.932420551776886 | -0.4659331440925598 | 2.1238763332366943 | 0.0052321083172147 | 0.0010357833655705996 | 0.0 |
| active_duration_minutes | -0.028947258185707075 | 0.9890769930649964 | -1.3724658489227295 | 0.31775742769241333 | 2.1193127632141113 | 0.0016518375241779497 | 0.0 | 0.0 |
| has_logon_activity | -0.00894211406835735 | 1.0034290485464892 | -1.4614524841308594 | 0.6842507719993591 | 0.6842507719993591 | 0.0 | 0.0 | 0.0 |
| has_device_activity | 0.015069944883309434 | 1.019268148426758 | -0.3404468595981598 | -0.3404468595981598 | 2.9373159408569336 | 0.0 | 0.0 | 0.0 |
| has_file_activity | 0.01145784215435991 | 1.0168192076042595 | -0.30514442920684814 | -0.30514442920684814 | 3.2771365642547607 | 0.08838007736943908 | 0.0 | 0.0 |
| has_email_activity | -0.008906640649533594 | 1.0034108535398891 | -1.4607197046279907 | 0.6845940351486206 | 0.6845940351486206 | 0.0 | 0.0 | 0.0 |
| has_http_activity | -0.008301379579178831 | 1.0031544711768159 | -1.456202507019043 | 0.686717689037323 | 0.686717689037323 | 0.0 | 0.0 | 0.0 |
| is_active_day | -0.009393458076786949 | 1.0036226156503878 | -1.4647867679595947 | 0.6826932430267334 | 0.6826932430267334 | 0.0 | 0.0 | 0.0 |

No predictive interpretation.

---

## Streaming provider check

Provider: `DenseDailyWindowProvider`. Batch bound: 1024. No model called. No full (N,20,13) tensor.

| checkpoint | slice | batch shape | user | start | completed | endpoint |
| --- | --- | --- | --- | --- | --- | --- |
| first | 0:1024 | [1024, 20, 13] | AAB0739 | 2010-01-02 | 0 | 0 |
| middle | 497664:498688 | [1024, 20, 13] | KCB1272 | 2010-06-13 | 0 | 0 |
| final | 995328:996000 | [672, 20, 13] | ZVD1138 | 2010-11-22 | 0 | 0 |

---

## Future r5.1 views / metrics (predeclared; not executed)

Views: COMPLETED_WINDOW, ENDPOINT_PAST_ONLY, DEOVERLAP_OFFSET0.
Metrics: PR-AUC; F1/precision/recall/FP/FN at frozen threshold; Brier/log-loss only if scores in [0,1].
Mechanism allowed: logit deviation, route MAE, route KL, hard-route agreement, dominant-leaf agreement.
Mechanism disabled: unused-leaf fraction, tree-contribution rho.

---

## Protocol flags

All required flags are false: r62/r51 predictive inference, r5.2 TEST opened, training, threshold selection, scaler fit, calibration fit, model selection, true authorisation.

NEXT_ACTION = Independent review of r5.1 bundle identity, counts, feature profile, and runner SHA. If approved, create one true EDITOR-007C secondary-stress authorisation and score r5.1 exactly once.
