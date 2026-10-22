# CERT Feature Selection and Expansion Study
## Draft experimental protocol for review

Version 0.2 — 7 October 2026 — **DRAFT FOR REVIEW. TRAINING NOT AUTHORISED.**

This study asks which of the existing 13 daily inputs contribute useful predictive information and whether additional behavioural measurements improve detection. The recommended first experiment compares the existing 13 inputs with 29 inputs on CERT r5.2, using a fixed learner and identical windows. A separate 37-input arm adds historical context and therefore answers a different question.

This revision responds to Claude audit independent_claude_20261007T1215SGT_r1. It is an author response and a new review draft, not an independently approved protocol. The v0.1 inputs and original audit are preserved. Proposed choices below have not been accepted as an execution plan.

The IEEE Access study remains frozen. Every future run belongs to this new study and must identify its dataset, label task, feature schema, split, model recipe, seed and evidence role. This draft is a protocol, not evidence that any feature improves detection.

### 1. Evidence inspected and preservation boundary

The original inspection covered the common-13 extractor and feature definitions, raw r5.2 headers and the first 1,000 rows per activity log, preparation manifests, saved split and tensor summaries, scaler metadata, final-model configurations, factorial result tables, bootstrap summaries, earlier feature-occlusion outputs and same-information baseline outputs. This revision additionally reproduces bounded file/device checks and records them in VERIFICATION_CHECKS.json. No model was fitted or used for new inference. The test tensor was neither opened nor hashed. Existing aggregate test counts were read in historical manifests; they are not new test evaluation.

At the original inspection, the paper-support repository was recorded clean at commit `f15fcd4cf5056dd24a3678bc53ca7081f9786424`. Its current source and configuration directories are principally documentation, so its README alone is insufficient to reconstruct a run. Its `dataset_split_hashes.csv` and `result_provenance.csv` have only headers. The detailed producing evidence is in preparation and experimental directories. Correction to v0.1: the feasibility feature list and tensor summary are populated (274 and 410 bytes) and match the preparation copies. The preparation project's outputs and data paths are junctions into the feasibility project. The v0.1 one-byte claim was incorrect and contradicted its own saved manifest. [E01–E08]

Four current hashes were checked against recorded expectations:

- r5.2 TRAIN tensor: `b268328d3bf2e98f712d1145958dabe175ce2c07a7c390da4b84a663317ebc2e`.
- r5.2 VALIDATION tensor: `5ac2e7e8fbd50eb62638cdb8c9d444464e02ff2ea20ba55989c36926dd751a5c`.
- Dense daily table: `ce1436b28c3ba5e1fbe83e307f5705189152253ab9ab634262e0c652d36414db`.
- Saved scaler JSON: `6a092df8275e15b6e05c685b306f48de72ab55fb1e88ede5ed5899ecd63f3488`.

The tensor headers also confirm float32 arrays of 788,000 × 20 × 13 and 64,000 × 20 × 13. Hash agreement establishes identity with the recorded artefacts, not independent validation of every event or label. Checkpoint bytes and all raw data files were not exhaustively verified in this inspection. [E08–E10]

Keep these evidence roles distinct:

- r4.2: historical development.
- r5.2 historical guarded test: only the reference models to which those results were originally attached.
- Final r5.2 students: train/validation evidence. The saved factorial means are 0.935324 for the teacher-initialised task-only control, 0.942595 for guidance without route regularisation, 0.937496 for route-only and 0.942842 for the complete model. The last-minus-control observed difference is 0.007518; the recorded paired user-cluster interval is [0.000345, 0.018250]. The bootstrap file also reports the mean of resampled differences; that is not the observed point estimate. These values were checked against the saved seed table; no predictions were recomputed. [E11–E13]
- r6.1: already accessed cross-release evidence with unsupported ranking transfer. It is not a fresh holdout for this project.
- r6.2 and r5.1: do not assume untouched status from release names or old registry descriptions. The workspace contains previous evaluation work.

Do not modify the IEEE manuscript, figures, frozen outputs, tensors, model checkpoints, thresholds or historical interpretations. Write new artefacts only under this project's own root, with explicit input paths and fail-if-exists run directories. Never invoke the old preparation entrypoint unchanged: it can overwrite derived files and builds all three splits. The user-requested protocol review must precede any training. [E02–E04]

### 2. What the current 13 inputs actually mean

The canonical order is:

1. `total_events`.
2. `logon_count`.
3. `device_count`.
4. `file_count`.
5. `email_count`.
6. `http_count`.
7. `active_duration_minutes`.
8. `has_logon_activity`.
9. `has_device_activity`.
10. `has_file_activity`.
11. `has_email_activity`.
12. `has_http_activity`.
13. `is_active_day`.

The five counts count source rows, not necessarily successful logins, unique files, outbound messages or browsing sessions. The sampled logon vocabulary includes Logon and Logoff; device includes Connect and Disconnect; email includes Send and Receive. Duration is the nonnegative difference in minute boundaries between the first and last event of the day, not session duration or time worked. Each source flag tests whether its count is positive. Inactive calendar days are filled with zeros. [E03–E05]

**Structural finding:** seven columns add no new information given the other six. Total events is the sum of the five source counts; five source flags and the active-day flag are deterministic functions of those counts. The six primitive measurements are the five counts plus duration. This follows from the extractor; it does not establish that removing the redundant columns preserves a fitted model's performance. Redundant encodings can change optimisation and inductive bias.

Dropping one count while retaining total and the other four counts still permits exact reconstruction of the dropped count. Single-column deletion therefore measures the value of that encoding conditional on retained features, not the importance of the underlying event source.

### 3. Labels, calendar, splits and preprocessing

The r5.2 pipeline creates a global user-by-calendar grid for 2,000 observed users across 517 days, 2010-01-02 through 2011-06-02. It produces 1,034,000 daily rows, including 340,351 inactive rows. This is a retrospective closed cohort, not an online employee-enrolment policy. Do not silently substitute per-employment calendars.

Daily labels indicate at least one matched malicious event; the primary historical window label is the maximum daily label over 20 days. The answer-matching record contains 10,328 answer records but 10,326 unique matched events, with duplicate-answer evidence recorded separately. Preserve event-key set membership and never multiply event counts through a nonunique answer join. Label-derived fields, answers, scenario IDs and identifiers must never be model inputs. [E04–E06,E21]

The saved global chronological split is 80/10/remainder by calendar day. Twenty-day, stride-one windows are constructed wholly inside each split:

- TRAIN: 2010-01-02 through 2011-02-18; 413 days; 788,000 windows; 3,957 any-day positives.
- VALIDATION: 2011-02-19 through 2011-04-10; 51 days; 64,000 windows; 728 any-day positives.
- TEST: 2011-04-11 through 2011-06-02; historical manifest records 68,000 windows and 275 positives. **Excluded from the proposed work.**

All 2,000 users occur in each temporal partition. These counts do not establish unseen-user performance. Do not randomly split the overlapping windows.

The original scaler fits the 826,000 TRAIN daily rows once, in float64, using population standard deviation (`ddof=0`); zero scales become one and transformed values are float32. Binary columns are also standardised. Fitting on flattened overlapping windows would change the weighting and is not equivalent. Preserve the frozen scaler for reproduction only; fit a new scaler on the eligible training days for each new model-development partition. In particular, the full-TRAIN scaler is not eligible for inner model selection. No scaling, imputation, feature ranking or class weighting may learn from the outer validation partition. [E09,E14]

Use the any-day completed-window task for the primary feature comparison to preserve comparability. Report it as retrospective end-of-day assessment. An endpoint-positive task (only the final day malicious) is a separate, optional retraining/evaluation arm with its own labels and imbalance weights. The freeze records 140 positive validation endpoints versus 728 any-day windows; these tasks must not be pooled. Neither supports pre-event forecasting.

### 4. Proposed additional features

The accompanying `feature_catalog_v0.2.json` specifies all 37 candidate inputs, sources, formulas, units and status. The existing 13 remain unchanged.

**First expansion: 16 same-day additions, producing F29.**

- Timing, four: outside-08:00-to-18:00 event count; corresponding event fraction; number of occupied hourly bins; largest hourly share of daily events. The timing rule is before 08:00 or at/after 18:00 on the recorded, timezone-unspecified clock. It does not estimate employee-specific work hours.
- Workstations, two: number of distinct PCs; largest PC share of events with a known PC.
- Actions, four: Logon rows; Connect rows; File Write rows; file rows marked as going to removable media.
- Email, four: Send rows; distinct recipients across to/cc/bcc on Send rows; summed size on Send rows; attachment-entry count on Send rows.
- Web, two: distinct parsed hostnames; largest hostname share of HTTP rows with a valid hostname.

These fields are present in the inspected r5.2 raw headers. Bounded early-TRAIN samples confirm the named activity values, True/False removable flags and semicolon-delimited recipient/attachment fields. They do not prove full-data vocabulary coverage or parser correctness. The r5.2 readme defines message size in bytes, excluding attachments. Validate semicolon-delimited attachment entries against the declared name(size) grammar; counting entries does not count unique files or attachment bytes. Logon-type rows include screen unlocks and omit some intentionally unrecorded logons. A hostname is not a registrable domain. The same readme's file-log field list is incomplete relative to the observed r5.2 header, so its broad file-copy description must not override verified action fields.

The dataset generator deliberately makes some timing and removable-device behaviours significant. Results therefore remain CERT-specific. Retain all 16 candidate slots in this review draft, without calling them 16 independent measurements. The reproduced first-200,000-file-row sample has 90,695 File Write rows and identical to-removable=True membership, but full eligible-training equivalence is unverified. Retain A10 pending an INNER_TRAIN-only equivalence check before executable lock; any removal needs a declared schema amendment before fitting. Retain A08: 618 of 25,317 sampled device user-days, excluding the partial final sample date, have twice the connect count unequal to device_count. An aggregate near-50% connect share is insufficient evidence of daily redundancy. Do not adopt F27 automatically: removing only A10 would yield F28, while removing both A08 and A10 would yield F27.

No new transforms for heavy tails, clipping, winsorisation or log1p are added to the same-day arm. All remain subject to the existing train-only standardisation rule; log1p is confined to the declared history formulas.

The existing unified stream retains only a small set of columns and discards fields needed for several additions. Extract the new features from the raw logs or independently verified enriched source tables; do not assume the current stream contains recipients, size, attachments, URLs or removable-media flags. Join daily features by unique user/date keys and preserve the original row population. [E04,E15]

**Separate history expansion: eight additions, producing F37.**

For each of the five counts and duration, calculate current log1p(value) minus its mean over up to 30 preceding calendar days. Add preceding-30-day active-day fraction and history coverage (available preceding days / 30). Exclude the current day from each reference history. History does not reset at partition boundaries. Use only preceding unlabelled daily activity, bounded by the fixed calendar start 2010-01-02; no labels, model outputs or learned preprocessing parameters enter these history values. Past INNER_TRAIN days may inform INNER_SELECT histories, and past TRAIN days may inform VALIDATION histories. This causal carry-in is intentional: sequence label/window membership remains partition-local, but raw feature-history support can cross into the preceding period. Compute histories before scaling. With no preceding calendar day use zero deviation/fraction and zero coverage. Missing required historical daily values make the affected history feature missing; do not silently shorten the reference denominator. Inactive days remain valid zero-activity days, not missing data.

Under the superseded reset policy, 93.75% of outer-validation windows contained partial-history days, versus 7.61% of full-TRAIN windows. With causal carry-in, only the first 30 days of the entire available calendar have partial calendar coverage; all inner-selection and outer-validation windows have complete calendar coverage. Coverage is an availability quantity, not a perfect split identifier.

F37 can use up to 50 calendar days of information for a 20-day input window. Its comparison must be labelled extended-history value, not an equal-history feature comparison. The coverage channel is a technical availability control, not behavioural evidence. Report a coverage-only control if this arm runs, so a calendar-position effect is not mistaken for behavioural history value.

Counts, ratios and concentration statistics may be dependent. That is acceptable for candidate features; dependence must be reflected in selection and interpretation. Do not include raw user/PC/address/filename/URL strings as predictors.

Defer psychometrics, LDAP employment outcomes, decoy-file indicators, content/keyword models, external-recipient classification, lifetime novelty and cross-source session matching. They introduce additional semantic, availability or portability assumptions that have not been reviewed here.

### 5. Missing data and extraction acceptance

A zero means no applicable observed event; it must not silently mean an unavailable log, malformed timestamp or failed parser. Before fitting, create TRAIN-only quality reports for missing columns, unexpected categorical values, malformed booleans/URLs/addresses, duplicate event IDs and nonnumeric sizes.

Require complete source availability for the declared cohort. If an applicable row has a malformed required field, mark the affected daily feature missing, including partial-coverage cases; do not compute a silently reduced count or denominator. For workstation features an inactive day is zero, but any unknown PC on an active day makes affected PC features missing. For web features no HTTP rows is zero, but a malformed URL on an HTTP row makes affected host features missing. Invalid timestamps that prevent reliable day attribution stop extraction for review.

Impute from the eligible training daily rows only. Freeze the indicator set from INNER_TRAIN before any fit and reuse that set in full-TRAIN refits; refit medians/scales on eligible full-TRAIN rows only. A feature with all INNER_TRAIN values missing cannot receive a median: halt for a documented schema revision before fitting. If an unseen missing-value pattern occurs in INNER_SELECT or later VALIDATION without a declared indicator, use the frozen eligible-training median, add no columns and report its count. Report per-feature invalid and imputed user-day counts for every partition without an arbitrary outcome-dependent rerun threshold. Do not retune or suppress results based on validation missingness. Feature-dependent indicators follow their parent channel when that channel is removed. Indicators change model-input dimensions beyond the F13/F29/F37 behavioural-slot names and require an explicit ordered-schema revision before fitting. If no INNER_TRAIN missingness occurs, no indicators are added. Blank attachment lists are valid zero counts; null or unparseable size is not zero bytes.

**Frozen calendar and extraction gates.** Use constants, never MIN/MAX-derived bounds or a recalculated 80/10 split: available calendar 2010-01-02 through 2011-04-10 (464 days); TRAIN ends 2011-02-18 (413 days); INNER_TRAIN ends 2010-11-27 (330 days); INNER_SELECT is 2010-11-28 through 2011-02-18 (83 days); VALIDATION is 2011-02-19 through 2011-04-10 (51 days). Before schema lock, structural/quality scans use INNER_TRAIN only. After selection freeze, full-TRAIN extraction/refitting is permitted only under the later user authorisation. New VALIDATION extraction/scoring occurs only after the complete comparison is locked and authorised. TEST tensors remain denied.

At raw-file ingestion, parse the date first and discard rows outside the currently authorised interval before feature aggregation, label joining or content inspection; every row on/after 2011-04-11 is excluded. Do not assume file ordering permits stopping at the first excluded date unless ordering has been independently established. Streaming may traverse raw record bytes and dates outside the eligible interval; this is not held-out feature construction or profiling and must be described accurately. Record rejection counts without behavioural summaries. Invalid dates fail closed. Filter any frozen daily-table projection to the authorised interval before records are exposed; a whole-file identity hash does not grant row access.

Bind the 2,000-user cohort from eligible TRAIN metadata/daily records, and create a separate SHA-256 over a sorted unique UTF-8 JSON list with fixed serialization. Do not derive the cohort from held-out activity. The historical 851385f9c926cf945b3c74b5c9442e3ccb94cf1d9dabb98106a29cbfea01c5c0 checksum is a newline-joined ordered 64,000-row validation user vector, not a unique 2,000-user list. Keep that checksum's historical role; do not use it as the new cohort-list hash. Cohort identity and row-order parity remain implementation-preflight checks, not claims verified by this draft.

Keep calendar construction, label joins, event-count rules and window IDs identical across feature sets. Do not drop rows separately by feature set. Check reconstructed F13 values against the frozen daily representation on permitted dates, then check expected scaled tolerances against the permitted tensors. Require equal labels and ordered row keys for every comparison. Feature selection must remove every lag/summary column derived from a selected daily channel.

### 6. Questions and planned experimental arms

Primary hypothesis: F29 improves average precision over F13 for the preregistered XGBoost recipe on the same r5.2 windows. A null or negative result is a valid outcome.

The bounded inner screening panel fits the fixed XGBoost recipe to 28 feature configurations, each with seeds 42, 52 and 62, on INNER_TRAIN and evaluates them on INNER_SELECT:

- F13 baseline.
- F6_PRIMITIVES: five source counts plus duration.
- F7_NUMERIC: F6_PRIMITIVES plus total events.
- FLAGS6: five activity flags plus active-day flag.
- Thirteen leave-one-column-out versions of F13.
- Five source-withdrawal versions.
- Five versions adding one same-day feature family to F13.
- F29 with all 16 same-day additions.

Single-column deletions require complete retraining and measure conditional encoding value. Under the verified algebra, 12 deletions remove reconstructible encodings; duration is the one nonreconstructible primitive in the leave-one-column-out panel. The deletion and single-family panels are exploratory INNER_SELECT evidence, not separately confirmed contribution rankings. Source withdrawal requires recomputing total events, duration, active-day status and any other dependent features from retained logs; set withdrawn source counts/flags to constant zero and retain original labels and calendar. Withdrawals apply to F13 only. Keep the 13 positions in order; constant columns have mean zero and scale one and therefore stay exactly zero. Keep colsample_bytree=0.8 and disclose that sampled constant positions can change effective split opportunities. On eligible training partitions, report the number of positive windows with no retained-source labelled malicious events. Call this absence of retained labelled events, not proof that detection is impossible; other behavioural traces may remain. This diagnostic is separate from feature construction and never enters X. This deliberately measures performance under withheld source information. Removing a source's count and flag while leaving its contribution in total or duration is not an acceptable source-withdrawal experiment.

Do not use a teacher trained on a withdrawn source or omitted feature in these primary ablations; it can pass the removed information back through its targets.

Define two selected schemas using only mean inner-select AP across the three seeds:

- S13: among F13, F6_PRIMITIVES, F7_NUMERIC, FLAGS6 and 13 single-column deletions, choose the fewest columns whose mean AP is within 0.002 of the best candidate.
- Splus: apply the same rule to F13, its five single-family additions and F29.

Resolve remaining ties by higher mean AP, then lexicographic ordered feature-name list. The 0.002 tolerance is a proposed simplification preference, not a significance threshold. S13 and Splus are selected once with XGBoost; their RF/attention-linear results measure transfer of that selected subset, not each learner's optimal subset. This is a bounded candidate-library selection rule, not exhaustive optimal-subset search. Never combine individually favourable deletions without a new joint experiment. Do not let historical occlusion rankings choose these subsets.

The outer reporting panel fits F13, F6_PRIMITIVES, S13, F29 and Splus with XGBoost, random forest and attention-linear, three seeds each. Deduplicate identical experiment representations. An ordered column-list hash alone is insufficient: all source-withdrawal arms retain the F13 column names but change values. Use the ordered columns, source mask, recomputation rules, history policy and missingness/preprocessing identity together. Label tasks, row sets, learner configuration and seed also belong in a full run cache key. Screening needs at most 84 fits; the outer panel at most 45, including each full-training refit. Required inner RF threshold fits and attention-linear calibration/epoch fits add at most 30. These panels total at most 159 fits. This v0.2 draft additionally proposes five locked outer XGBoost source-withdrawal contrasts, one per source and three seeds, with thresholds from their screening fits: 15 additional fits, bringing the proposed primary-study maximum to 174. They address the event-source contribution question on outer validation and remain exploratory paired contrasts; they do not replace F29-minus-F13 as the single primary contrast. This budget expansion is a review proposal, not execution authorisation. Wall-clock and memory costs remain unmeasured.

The history arm, if approved, adds F37 and a precisely defined F29_PLUS_COVERAGE schema (F29 plus A24 only) under the same learners and seeds. Each of these two representations needs inner fits for all three learners and seeds plus full-TRAIN refits: at most 36 additional fits. Neither this optional arm nor endpoint/ODST work is included in the 174-fit proposal. It must not replace the declared F29 primary contrast after seeing results.

### 7. Split isolation and fitting rules

Use the historical r5.2 TRAIN calendar for development. Its first 330 days, ending 2010-11-27, form INNER_TRAIN; the remaining 83 days, starting 2010-11-28, form INNER_SELECT. The recorded 20-day construction gives 622,000 inner-training windows and 128,000 inner-selection windows, with 38,000 crossing windows excluded. Recorded any-day positives are 2,457 and 1,214 respectively. Reverify these after rebuilding rather than treating constants as proof. [E14]

Fit preprocessing, class weights and any vocabulary on INNER_TRAIN alone. Use INNER_SELECT for the bounded feature selection, attention-linear stopping and threshold calibration. It may support development decisions but is not an unbiased evaluation sample.

Before accessing new outer-validation predictions, freeze feature choices, model settings, epoch counts, thresholds, comparisons and analysis code. Fit new outer models on all 413 TRAIN days; refit their scalers using those days only. For attention-linear use the median best epoch across its three inner fits for that schema, rounded upward, with a minimum of one and maximum of 15. Do not early-stop or choose checkpoints on outer validation.

For each model/schema/seed, choose a threshold on its inner-select predictions that maximises F1 over all unique scores plus an all-negative option; break ties toward the higher threshold. Freeze it for the corresponding outer refit. Report alert burden even if refitting changes score calibration. Never retune thresholds on outer validation or inside bootstrap draws. Enumerate thresholds using float64 probabilities and p >= t; the all-negative choice is positive infinity and ties favour the larger threshold. Label all outer precision/recall/F1/confusion/workload results TRANSPORTED_THRESHOLD: inner-trained models and full-TRAIN refits differ in scaler, training period, class ratio and potentially stopping epoch. These are secondary operating-point measurements, not calibrated deployment guarantees. For attention-linear, the threshold comes from that seed's best inner checkpoint even though the full fit uses the schema's median inner best epoch. No extra inner-model-on-validation sensitivity is included in this draft.

The outer r5.2 validation set has already informed substantial historical research. New locked comparisons there are **retrospective validation evidence**, not untouched confirmation. No splitting or relabelling of the already accessed data can make it prospectively unseen. A later confirmatory study needs an independently audited, unaccessed dataset or newly collected period and a separately reviewed access protocol. No r5.2 TEST access is proposed.

### 8. Model recipes and teacher-guided boundary

All settings below are proposed locks for the new study, not claims of exact recreation of archived models. Do not tune each feature set separately.

- XGBoost: chronological flattening of 20 × F into 20F inputs; 300 trees, depth 6, learning rate 0.1, subsample 0.8, colsample_bytree 0.8, reg_lambda 1, hist tree method, binary logistic objective; training-only negative/positive ratio as scale_pos_weight. These values follow the inspected historical baseline constants. Pin remaining defaults, package version and thread count before execution. [E16]
- Random forest: the same flattened inputs; 200 trees, depth 20, minimum leaf size 2, balanced_subsample; explicitly set max_features=1.0 for this new protocol. This is a deliberate bagged-tree setting with no random feature subsampling; it differs from the earlier default-sqrt forest. Keep the new recipe explicit. Costs cannot be inferred reliably by multiplying an old runtime by a feature-count ratio. Estimate resources without fitting during protocol review; measure actual costs only in later authorised runs. A switch to a fixed fraction such as 0.33 needs a reviewed recipe change before fitting.
- Attention-linear: 20 × F input; one bidirectional LSTM layer with 64 units per direction; dropout 0.2 after hidden states; additive attention dimension 64; linear binary readout. New random initialisation for every schema/seed; Adam, learning rate 0.001, weight decay 0, batch 1,024, maximum 15 epochs, patience 4, gradient norm clipping 1; BCE positive weight 0.25 × training negatives/positives. The from-scratch learning rate is a proposed new-study setting, not the frozen teacher-guided fine-tuning rate.

Use train-only daily standardisation consistently before neural/flattened inputs. Baseline tensor identity checks and new inner scaling serve different purposes. Save each transformation. No oversampling or synthetic minority generation is proposed.

The historical 40 window-summary tree features, the 260 flattened inputs and the 20 × 13 neural inputs are different representations. The inspected r4.2 script defines forty summaries: four aggregates for seven numeric channels and two aggregates for six flags. This is not independent inspection of an r5.2 engineered-40 implementation. With fixed 20-day windows, each flag proportion is its active-day count divided by 20. They are not forty independent daily measurements. The saved same-information results concern earlier models and must not be reassigned to the final eight-tree model. [E16–E18]

The frozen final ODST uses two layers of four trees each, depth four, and averages eight tree outputs. Its teacher-informed initialisation is load-bearing. Simply resizing a 13-input checkpoint or reusing a full-information teacher in a reduced-feature arm confounds the feature question. [E10–E13]

An ODST extension is a separately reviewed second stage after the primary feature study. It must specify a teacher trained on each eligible schema using only that arm's training data, matched initialisation and teacher-target construction, plus task-only and guided controls. All such teachers/students are new models. The frozen checkpoints may serve as read-only historical references, but their old scores cannot supply a new-feature baseline. This draft does not authorise an improvised checkpoint-resizing experiment.

### 9. Metrics, uncertainty and decision rules

Primary metric is noninterpolated average precision, implemented by `average_precision_score`, which the inspected evaluation code calls PR-AUC. Do not substitute trapezoidal precision-recall area. [E19; official metric documentation below]

For every arm save per-seed AP, ROC-AUC, prevalence, AP minus prevalence, precision, recall, F1, confusion counts and alerts per 1,000 eligible windows at the transported, frozen threshold. Earlier baseline F1 used validation-selected thresholds and must not be treated as directly comparable to these new thresholded results. Measure extraction time, fit time, peak memory and inference time under a declared hardware/thread configuration. Costs from older checkpoints do not transfer automatically.

Estimate uncertainty with 2,000 paired user-cluster bootstrap draws, random seed 42. Use identical sampled users for both arms and retain all their windows. In each draw compute each seed's AP difference and then average those differences; do not average prediction scores unless a separate ensemble is preregistered. Report percentile intervals, invalid single-class draws and their handling. Require at least 1,900 valid draws; otherwise mark the interval unreliable and report the failure. Seeds quantify training variability and are not independent data samples. Cluster multiplicity must be preserved under sampling with replacement. Use exactly 2,000 attempted draws, flag one-class draws as invalid and report the valid count; do not keep resampling until a target result is obtained. Intervals are conditional on the fitted models and observed calendar. They do not integrate the feature-selection process, the distribution of future retraining runs or common time shocks. The recorded validation set has 31 users with positive windows, so precision may be limited, but a prior contrast's confidence-interval width does not establish power or a detectable-effect threshold for the new contrast.

The single primary contrast is outer XGBoost F29 minus F13. Call it an improvement on this retrospective validation task only if the observed AP gain is at least 0.005 and its paired 95% interval excludes zero. Otherwise report inconclusive, smaller-than-target or adverse evidence as applicable. The 0.005 practical margin is a proposed review decision, not an established property of CERT. An inconclusive interval is not evidence of equivalence or no effect; do not assert that effects below approximately 0.01 must be undetectable based on the older study.

For the secondary reduction question, use a proposed AP noninferiority margin of 0.005 for S13 versus F13; report the one-sided 95% lower bound and feature/cost reduction. Label this and all individual ablations/family/model comparisons exploratory. Their intervals are descriptive, not a collection of unadjusted confirmatory findings. If reviewers want confirmatory claims for multiple contrasts, freeze a multiplicity procedure and the complete family before execution.

Repeat the ranking comparisons on nonoverlapping completed windows: primary offset zero, then all 20 offsets as sensitivity. Select windows separately within each user and evaluation partition; count positives and negatives at each offset. Offsets are correlated and must not be treated as 20 independent replications. This checks overlap sensitivity but cannot repair historical validation reuse.

Existing train-median feature occlusion measures reliance of an already fitted historical model under perturbed inputs. It does not establish the benefit of retraining without a feature, and attention weights/tree routes are not automatically source-feature importance. Grouped permutation can be an optional descriptive diagnostic, but independent cell shuffling would break temporal and deterministic relationships. [E20; official permutation-importance guidance below]

### 10. Required artefacts and release gates

Before training, the user must review this protocol and proposed features. After review, implementation proceeds in this order:

1. Resolve feature semantics, missingness handling, dataset scope, primary learner and numerical margins; record approval and a versioned schema.
2. Implement extraction and partition guards only in this new project. Verify on synthetic fixtures and permitted TRAIN data using independently computed assertions over actual window dates, not generating-loop Boolean flags:  event counts, action mapping, recipient/attachment parsing, malformed inputs, inactive days, history exclusion of current/future days, causal history carry-in and calendar-start handling, duplicate label joins and prevention of test access. Event identity is (event_type, id), since IDs are only guaranteed unique within a log. Project any labelled source parquet onto an explicit predictor allowlist before aggregation; label-derived columns must not reach the feature builder. Pin Python and relevant library versions (numpy, pandas, pyarrow, duckdb, xgboost, scikit-learn, torch), CPU/GPU choice, thread counts, RNG seeds and determinism flags before executable lock. Flatten lag-major with feature channels in catalog order.
3. Validate exact raw F13 parity, ordered row-key/label equality, tensor shape and scaling tolerances. Bind source-code hashes, raw-file identities, split/key hashes, feature order, environment and expected run count to a machine-readable run manifest. Check every output path is inside the new project after resolving junctions.
4. Freeze the executable configurations, preprocessing policies, selection algorithm, metric definition and statistical comparisons. Train only after the protocol/feature review and successful preflight.
5. Produce one result register separating historical reference, new inner selection, new retrospective validation, optional history and optional endpoint evidence. Preserve failed runs and null findings.
6. Before any new confirmation/test access, obtain a separate reviewed plan naming the dataset, its prior-access history and one-pass evaluation rules.

Each run should save configuration, code/environment identity, data/schema/split hashes, preprocessing, model/checkpoint hash, training history, stopping epoch, seed, thresholds, predictions keyed by sequence/user/end date, metrics, cost measurements and failure status. Keep identifiers local and out of manuscript-facing tables.

**Decisions for review:** r5.2-only first phase; 16 same-day additions before the eight history additions; 28-configuration XGBoost screening and the proposed 15-fit outer-withdrawal extension (174 fits total); XGBoost primary with RF/attention-linear checks; margins 0.002 for simplification and 0.005 for practical improvement/noninferiority; separate ODST, endpoint and future-confirmation stages. Causal history carry-in, F29 retention pending duplicate review, fixed RF max_features=1.0 and the outer-withdrawal extension are proposed defaults for review. None has yet been approved as an execution plan. The original independent verdict remains REVISE_BEFORE_IMPLEMENTATION until the auditor/user reviews these corrections; this response does not self-certify approval.

### 11. Evidence index

Paths, current SHA-256 values, historical expected hashes and verification status are recorded in `evidence_manifest_v0.2.json`. The short identifiers used above refer to:

- E01: paper-support README and verified Git state.
- E02: IEEE Access resubmission freeze.
- E03: common-13 feature definitions.
- E04: common-13 pipeline, including extraction, densification, splitting and scaling.
- E05: populated preparation feature list.
- E06: preparation run manifest.
- E07: saved split summary.
- E08: populated tensor summary.
- E09: saved TRAIN-only scaler.
- E10: final-study input checksums.
- E11: final factorial seed results.
- E12: paired user-cluster bootstrap summary.
- E13: final run manifest and model/training constants.
- E14: inner split implementation and frozen protocol.
- E15: dataset path/version registry; E03 contains field-level schema notes. The revision verification record contains fresh bounded file/device checks.
- E16: same-information baseline constants/configuration.
- E17: same-information saved results/manifest.
- E18: historical r4.2 40-feature window-summary implementation; r5.2 producing code not verified here.
- E19: final-study AP metric implementation.
- E20: earlier feature-occlusion output.
- E21: saved duplicate-answer audit.
- E22: header-only paper provenance files and populated, matching feasibility summaries.
- E23: current train/validation tensors and dense-daily identity checks.
- E24: r4.2 saved tensor summary for historical context.
- E25–E29 in the revision manifest: dataset readme, independent audit artefacts, historical mapping-hash implementation and revision checks.

Method references supplement, rather than replace, the local evidence: [average precision definition](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.average_precision_score.html), [correlated-feature permutation limitations](https://scikit-learn.org/stable/modules/permutation_importance), and [training-only preprocessing and leakage](https://scikit-learn.org/1.7/common_pitfalls.html). Their roles are metric definition and general methodological guidance, not support for any CERT performance claim.

