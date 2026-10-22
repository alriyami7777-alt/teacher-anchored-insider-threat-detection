# EDITOR-026 PROTOCOL

Frozen before Stage 0. No representation grid. No architecture search.

- Parent SHA: `1f176bb7bf589da20be8ae9b02a23a4c8f0e0af7`
- EDITOR-025 ruling: `RELEASE_LEVEL_REPRESENTATION_SHIFT`
- Recommended remedy: `USER_RELATIVE_RELEASE_INVARIANT_REPRESENTATION`
- Intervention: `INPUT REPRESENTATION ONLY`

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
- No past day: relative feature value = 0.

## Transform

- Volume: `log1p(current) - median(log1p(past same-user calendar days))`
- Binary: `current - mean(past same-user calendar days)`

## r5.2 scaler rule

- Fit only on r5.2 TRAIN user-relative daily values.
- r5.2 validation and r6.1: transform-only.
- Per-user causal history is part of the input representation and is **not** target-wide scaler fitting.

## Stage-0 formulas and gates

- MEAN_ABS_SHIFT_REDUCTION >= 0.5
- MEAN_PSI_REDUCTION >= 0.5
- N_FEATURES_WITH_LOWER_PSI >= 9/13
- R52 validation input separation > 0
- Both r6.1 label-view input transfer ratios > 0.5
- Flattened discriminant 260-d; epsilon = 1e-12
- If any Stage-0 gate fails: no training, ruling USER_RELATIVE_REPRESENTATION_NOT_SUPPORTED.

## Teacher reconstruction plan

- Producing T-OPT: `src/editor011_confirmation/train.py::train_teacher`.
- Encoder init: frozen attention-linear recipe from r52_odst_confirmation config.json, retrained on the user-relative representation.
- Attention-linear lr=0.001, pos_weight_multiplier=1.0, ReduceLROnPlateau factor 0.5 patience 2.
- T-OPT: frozen encoder, ODST Adam lr=0.001, max_epochs=15, patience=4, pos_weight_mult=0.25.
- Students: EDITOR-012 train_student (UR_C2/UR_F10/UR_FINAL) and EDITOR-013 train_e2e L1 recipe (UR_LINEAR).
- No r6.1 access during teacher or student training.

## Model variants

- UR_C2: user-relative teacher-initialised task-only control
- UR_F10: user-relative ensemble-guided ODST student without route anchoring
- UR_FINAL: user-relative final ensemble-guided, route-anchored ODST student
- UR_LINEAR: user-relative matched attention-linear reference
- Seeds exactly: [42, 52, 62]

## r5.2 and r6.1 evaluation

- G1: UR_FINAL mean r5.2 val PR-AUC >= 0.9353238885175368
- G2: at least 2/3 seeds >= 0.93
- G3–G7 on both label views; G5 lift >= 10.0
- G8: UR_FINAL representation transfer > 0.5 (EDITOR024 view)
- Historical EDITOR-024 result is immutable. r6.1 cannot serve as a future untouched target.

## Promotion and stopping

- Full G1–G8 pass: CANDIDATE_FOR_NEW_FINAL_CONFIRMATION, not an immediate TA2 replacement.
- Do not select a new untouched target. Do not start EDITOR-027. Do not try another lookback.

Written at 2026-08-18T18:39:35Z.
