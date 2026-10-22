# Experiment execution lock — F29, inner screening stage

7 October 2026. User instruction: **“lets proceed with the experiments”**.

The current implementation follows the approved `revision_v0.2` F29 author amendments, as recorded in `IMPLEMENTATION_APPROVAL_2026-10-07.json`. The root F27 audit remains a distinct snapshot. No feature semantics or approved primary contrast changes in this execution lock.

## Stage and gates

The full TRAIN run `implementation_runs/full_train_preflight_20261007_r1` supplies verified daily features, separate labels, 28 realized schemas and daily preprocessors. The inner stage validates those content hashes, protocol/catalog hashes, realized transformation identities and all applicable TRAIN gates before fitting. It also verifies historical TRAIN sequence IDs using `460*u+k+1`, without constructing any TEST rows. Window pairing uses `(user,start_date,end_date,ANY_DAY_COMPLETED_WINDOW_T20)`.

This lock enables **84 planned inner XGBoost fits**, 28 representations × seeds 42/52/62. It does not enable outer prediction/evaluation, history, endpoint or ODST arms. The 174-fit base-study maximum is unchanged. The remaining RF/attention-linear fits and outer refits require their own tested executable stage locks before they run. There are no toy fits or separate fitting benchmarks.

## Fixed XGBoost implementation choices

Use XGBoost 3.2.0 from the installed `cert-r42-gpu` environment, CUDA device 0 and four CPU threads. The GPU identified before preparation is NVIDIA GeForce RTX 5070 Laptop GPU, approximately 8 GiB. Training uses 300 boosting rounds, hist, depth 6, eta 0.1, subsample 0.8, colsample_bytree 0.8 and lambda 1. Other explicit parameters are stored in the manifest, including uniform sampling, base_score 0.5, no early stopping and the INNER_TRAIN negative/positive ratio. The complete producing booster configuration is saved for every fit; a CPU fallback fails the fit instead of silently changing the recipe. GPU floating-point results may not be bitwise identical across devices/library versions; the device, package versions and seeds are bound.

Flatten 20-day windows chronologically, with catalog feature order within each day. QuantileDMatrix uses batched inputs of at most 32,768 windows. The selection matrix uses the training matrix as its quantile reference. Daily preprocessing is loaded from the verified INNER_TRAIN-only fit, then applied unchanged to INNER_SELECT. No validation-derived quantiles, medians, scales, class weights or indicators enter this stage.

F13 and F29 are scheduled first, followed by the remaining catalog panel. This ordering changes no candidates or selection rules. All candidates must finish before S13 or Splus is chosen. No failed fit is silently retried, discarded or replaced. A completed fit is reused only if its complete run identity and saved artefact hashes match.

## Metrics, selection and thresholds

Primary screening metric is scikit-learn noninterpolated average precision. Report AP, ROC-AUC, prevalence, AP minus prevalence, confusion counts, precision, recall, F1 and alerts per 1,000 windows. INNER_SELECT operating-point metrics are explicitly development/calibration results.

Choose each threshold over unique float64 probability scores plus positive infinity, using `p >= t`. Compute F1 ties by exact integer cross-products of confusion-count fractions; ties retain the highest threshold. JSON stores positive infinity as the explicit string `+infinity`, not a nonstandard JSON numeric token. Outer stages must transport this threshold without retuning.

S13 candidates are F13, F6_PRIMITIVES, F7_NUMERIC, FLAGS6 and all 13 single-column deletions. Splus candidates are F13, the five family additions and F29. Among candidates whose mean AP over the three seeds is at least best_mean minus 0.002, select the fewest realized channels, then higher mean AP, then the lexicographic ordered feature-name list. There are no missing indicators in the realized TRAIN schemas, so realized and behavioral channel counts agree. No combinations are invented after screening.

## Parser contract bound to existing extracted values

Freeze the previously tested `cert_features.py` parser bytes. Any invalid applicable field poisons only its affected daily feature; no partial denominators are used. No applicable event produces zero. Date/user assignment failure stops extraction. Optional blank recipient/attachment lists are empty, while empty tokens inside a nonempty list are invalid.

Recipient tokens use `[^\s@;]+@[^\s@;]+`, with trimming and lowercasing. This is a recorded-address syntax contract, not deliverability or full RFC validation. A12 includes any explicitly addressed sender and never adds the from field automatically. Attachment tokens use `.+\(\d+\)`; size uses ASCII `[0-9]+`.

The URL contract uses Python urllib.parse.urlsplit, rejects whitespace, missing scheme/netloc/hostname, malformed bracket syntax and invalid ports, then lowercases hostname and strips trailing dots. Bare URLs are rejected. Schemes and user information are accepted; user information is not part of the hostname. IPv4/IPv6 host literals and Unicode host strings are retained as parsed; no IDNA conversion, DNS resolution, public-suffix extraction or DNS-label validation is performed. An underscore-bearing hostname is accepted by this contract. These precise semantics are tested and bound; the extracted TRAIN values are not silently reinterpreted under a stricter parser.

## Remaining stages

Before attention-linear fitting, lock and test the exact network, additive-attention equation/biases, optimizer/loader/device/determinism choices, and INNER_SELECT AP checkpoint selection: strict improvement, earliest tied epoch, patience four, maximum 15 epochs. Outer epoch counts and thresholds are frozen from completed inner work.

Before outer evaluation, bind selected schemas, refit recipes, thresholds, analysis code and the staged VALIDATION preflight. The primary contrast remains XGBoost F29 minus F13, practical gain 0.005 with paired 95% interval excluding zero. Bootstrap remains 2,000 attempted user-cluster draws, seed 42, preserving multiplicities and averaging per-seed AP differences; fewer than 1,900 valid draws is unreliable. These analysis specifications are not a claim that their executable implementation has already been tested.

For nonoverlap sensitivity, starts are partition_start + offset + 20*k, offsets 0–19, complete windows only and identical keys across arms. All offsets reuse saved predictions. Optional history, if separately enabled, retains past context and can still overlap in raw history. The tested index rule yields 4,000 VALIDATION windows at offsets 0–11 and 2,000 at offsets 12–19 without reading validation records.

Unscanned excluded suffix size is null/not_scanned. A date used to detect the first boundary is not a count of the entire suffix. No TEST input is opened, hashed, constructed or evaluated. The frozen IEEE Access evidence is read-only. All new outputs have an explicit development/retrospective evidence role.

## Coordination and costs

The preparation and execution commands acquire `coordination/ACTIVE_WRITER.json`. This is a cooperative lock for this implementation, not control over other applications. Immutable run directories and per-fit completion hashes support recovery without duplicate fitting. Cursor may review source read-only; it must not edit locked files or launch competing experiments.

Record actual fit/inference time and sampled peak process RSS on planned fits. The RSS sample interval is 0.2 seconds; GPU peak memory is not measured by this runner and is explicitly marked unavailable. Matrix preparation occurs once per schema and is separate from per-seed fit time. Raw extraction cost remains in the full preflight record.
