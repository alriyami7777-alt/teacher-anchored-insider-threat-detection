# EDITOR-027 PROTOCOL

Frozen before Stage 0. Causal user-relative scale normalisation only. Architecture unchanged.

- Parent SHA (EDITOR-026 results): `83f3f8f6cbe2b75faa176e2840bec84bf84b09d0`
- EDITOR-025 ruling: `RELEASE_LEVEL_REPRESENTATION_SHIFT`
- EDITOR-026 distribution gate: `FAIL` (do not reinterpret as success)
- Intervention: `USER-RELATIVE SCALE NORMALISATION ONLY`

## Feature definitions

- Order (13): total_events, logon_count, device_count, file_count, email_count, http_count, active_duration_minutes, has_logon_activity, has_device_activity, has_file_activity, has_email_activity, has_http_activity, is_active_day
- Volume / duration: total_events, logon_count, device_count, file_count, email_count, http_count, active_duration_minutes
- Binary activity: has_logon_activity, has_device_activity, has_file_activity, has_email_activity, has_http_activity, is_active_day
- Output dimension remains 13. No baseline statistics appended.

## 20-day baseline rule

- Lookback = 20 calendar days.
- For day t use only t-20 ... t-1 for the same user.
- Inactive days remain in the calendar history.
- No future day, other user, label, or release-level target statistic.

## Cold-start rule

- Fewer than 20 prior calendar days: use all available past days.
- No past day: representation value = 0.

## Transform

- Volume: `(log1p(current) - causal median(log1p past)) / max(1.4826 * causal MAD, source-only 25th-percentile floor)`
- Binary: `(current - Jeffreys p_hat) / sqrt(p_hat * (1 - p_hat)), p_hat = (k + 0.5) / (n + 1)`
- MAD constant: `1.4826`
- Scale floor: 0.25 percentile of strictly positive r5.2 TRAIN causal MAD scales; fallback 1.0.
- No clipping. No target quantile/mean/variance alignment.

## r5.2 scaler rule

- Fit only on r5.2 TRAIN SCALE daily values.
- r5.2 validation and r6.1: transform-only.
- Per-user causal history is part of the input representation and is **not** target-wide scaler fitting.

## Stage-0 formulas and gates

- G0A MEAN_ABS_SHIFT_REDUCTION >= 0.5
- G0B MEAN_PSI_REDUCTION_VS_ORIGINAL >= 0.5
- G0C N_FEATURES_LOWER_PSI_VS_ORIGINAL >= 9/13
- G0D MEAN_PSI_REDUCTION_VS_CENTERED >= 0.5
- G0E R52 validation input separation > 0
- G0F/G0G both r6.1 label-view input transfer ratios > 0.5
- Flattened discriminant 260-d; epsilon = 1e-12
- If any Stage-0 gate fails: no training, ruling EDITOR027_SCALE_NORMALISED_REPRESENTATION = NOT_SUPPORTED.

## Teacher reconstruction plan

- Producing T-OPT: `src/editor011_confirmation/train.py::train_teacher`.
- Encoder init: frozen attention-linear recipe from r52_odst_confirmation config.json, retrained on the SCALE representation.
- Attention-linear lr=0.001, pos_weight_multiplier=1.0, ReduceLROnPlateau factor 0.5 patience 2.
- T-OPT: frozen encoder, ODST Adam lr=0.001, max_epochs=15, patience=4, pos_weight_mult=0.25.
- Students: EDITOR-012 train_student (SCALE_C2/SCALE_F10/SCALE_FINAL) and EDITOR-013 train_e2e L1 recipe (SCALE_LINEAR).
- No r6.1 access during teacher or student training.

## Model variants

- SCALE_C2: scale-normalised user-relative teacher-initialised task-only control
- SCALE_F10: scale-normalised user-relative ensemble-guided ODST student without route anchoring
- SCALE_FINAL: scale-normalised user-relative final ensemble-guided, route-anchored ODST student
- SCALE_LINEAR: scale-normalised user-relative matched attention-linear reference
- Seeds exactly: [42, 52, 62]

## r5.2 and r6.1 evaluation

- G1: SCALE_FINAL mean r5.2 val PR-AUC >= 0.9353238885175368
- G2: at least 2/3 seeds >= 0.93
- G3–G7 on both label views; G5 lift >= 10.0
- G8: SCALE_FINAL representation transfer > 0.5 (EDITOR024 view)
- Historical EDITOR-024/025/026 results are immutable. r6.1 cannot serve as a future untouched target.

## Promotion and stopping

- Full G0A–G0G and G1–G8 pass: SUPPORTED_FOR_NEW_FINAL_CONFIRMATION, not an immediate TA2 replacement.
- Do not change the scale floor. Do not change the lookback. Do not try another normalisation formula.
- Do not train on r6.1. Do not select a new untouched target. Do not start EDITOR-028.

Written at 2026-08-19T00:46:24Z.
