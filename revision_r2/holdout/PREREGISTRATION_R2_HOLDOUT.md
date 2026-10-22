# R2 user-disjoint holdout preregistration

Frozen UTC: 2026-10-21T15:03:13.663514+00:00

- Universe: all 2,000 CERT r5.2 users. Stratum = insider user (>=1 answer-file malicious day anywhere in r5.2) vs non-insider.
- Split: sort user IDs; within each stratum shuffle with numpy.random.default_rng(20261022) and take round(0.25 × stratum size) as HOLDOUT; total HOLDOUT = 500 (adjust the larger stratum by ±1 only if rounding misses 500; record it). Remaining 1,500 = DEVELOPMENT.
- Retrained on DEVELOPMENT users only (TRAIN period windows; scaler refit on DEVELOPMENT users' TRAIN user-days; class weight w+ recomputed by the same 0.25·N−/N+ rule): T-OPT teachers (seeds 42/52/62, EDITOR-011 producing recipe), F00 task-only teacher-initialised control, F10 guidance-only, F11 = TA2 (L = L_cls + 0.5 L_teacher + 0.5 L_route), L1 teacher-guided attention–linear, RF_40, XGBoost_40 — each seeds 42/52/62, frozen recipes. Checkpoint selection and thresholds on DEVELOPMENT users' VALIDATION period only.
- Secondary (exploratory, R1-2): unidirectional-LSTM variant (hidden 128, so the 128-dim state is unchanged) with its own uni-LSTM T-OPT teachers and uni TA2, seeds 42/52/62, same recipe.
- Evaluation (LATER, not tonight; option B approved by Qasim, to be disclosed to the supervisor before scoring): HOLDOUT users' VALIDATION + TEST periods, stride-1 completed-window windows; secondary de-overlap offset-0 and endpoint views. One pass, frozen thresholds, no recalibration.
- Metrics: PR-AUC (average precision) and ranking excess (PR-AUC − prevalence). Primary contrasts: TA2 − XGBoost_40 and TA2 − F00, 3-seed mean. Secondary: TA2 − L1, TA2 − RF_40, F10 − F00, TA2 − uniTA2. Paired user-cluster bootstrap over HOLDOUT users, 2,000 replicates, rng seed 42, 95% percentile CI.
- Decision rules: CI entirely below 0 → "ranks below"; includes 0 → "comparable / not distinguishable"; entirely above 0 → "ranks above (bounded to unseen CERT r5.2 users)". All outcomes are reported. No re-runs after scoring.

## Pre-split freeze receipt

SHA-256 of all bytes preceding this receipt: `df726d88bd9ceb517af5635f36ef7a6832c6cf927348675c9ae4769773eceb4a`

UTC: 2026-10-21T15:03:13.663514+00:00

No split exists at this timestamp.

## Materialized split receipt (counts and hashes only)

```json
{
  "utc": "2026-10-21T15:07:33.590153+00:00",
  "rng": "one numpy.random.default_rng(20261022), insider then non_insider; sorted before each shuffle",
  "rounding_adjustment_larger_stratum": 0,
  "answer_file_index_count": 99,
  "groups": {
    "HOLDOUT": {
      "users": 500,
      "insider": 25,
      "non_insider": 475,
      "list_sha256": "9aa35a84e0ddb723bf11b1f332bdaad224b2db50bde01c06579e8930356dd001",
      "periods": {
        "train": {
          "windows": 197000,
          "positive_windows": 917
        },
        "validation": {
          "windows": 16000,
          "positive_windows": 255
        }
      }
    },
    "DEVELOPMENT": {
      "users": 1500,
      "insider": 74,
      "non_insider": 1426,
      "list_sha256": "7559b7357eb1b4c7fbb11a23bbee9da6bc2262e8af53163f263e9f91fdc48aad",
      "periods": {
        "train": {
          "windows": 591000,
          "positive_windows": 3040
        },
        "validation": {
          "windows": 48000,
          "positive_windows": 473
        }
      }
    }
  }
}
```

## Amendment 1 (Option C), 22 Oct 2026

Qasim approved Option C on 22 Oct 2026 at 09:51 (+08).
- The evaluation period changes from HOLDOUT VALIDATION + TEST to HOLDOUT users' TRAIN + VALIDATION periods: TRAIN 197,000 windows with 917 positives, plus VALIDATION 16,000 windows with 255 positives.
- The r5.2 TEST period stays sealed for all users, reserved for the PhD thesis.
- Primary view: the HOLDOUT TRAIN + VALIDATION completed windows pooled.
- Secondary views: TRAIN only, VALIDATION only, offset-0 de-overlap, and endpoint label.
- Everything else is unchanged: metrics, primary contrasts, bootstrap (2,000 replicates, seed 42, user-cluster over HOLDOUT users), decision rules, frozen thresholds, no recalibration.
- Rationale: these HOLDOUT users were excluded from every DEVELOPMENT fit, scaler and selection, so their TRAIN-period windows are unseen.
- Supervisor disclosure: Qasim reports that his supervisor, Assoc. Prof. Dr. Mohd Murtadha bin Mohamad, agreed in person on 22 Oct 2026 to using CERT r5.2 user splits for this evaluation.
- Amendment 1 is written before any holdout feature window or prediction exists, consistent with the Phase 2 deferred-scoring records and the absence of Phase 4 execution.

Amendment 1 receipt: SHA-256 of this amendment section's UTF-8 bytes, from its leading newline through its final newline: 7453c022dffb578872bc178ac660888eb3ad65e9cd260d1d764a0745df97eb83
UTC: 2026-10-22T02:08:49.9175396Z

## Amendment 2: additional baselines (secondary, exploratory)

The following recipes are preregistered before any additional baseline training. Existing frozen Phase 2 models and thresholds remain unchanged.

2. All baselines share the following frozen recipe:
   - Data: DEVELOPMENT users' TRAIN windows only (591,000 windows, 3,040 positives).
   - Inputs: the same development scaler and the same standardized 20×13 tensor.
   - Checkpoint selection: DEVELOPMENT VALIDATION AP.
   - Threshold: maximum F1 on DEVELOPMENT VALIDATION.
   - Seeds: 42, 52 and 62.
   - Training (neural models): Adam 1e-3, batch 1024, gradient clip 1.0, maximum 15 epochs, early-stopping patience 4 on development validation AP.
   - Supervised neural models use BCE with w+ = 0.25·N−/N+ (same rule as TA2).
3. Models:
   - B1 BiLSTM_noAttn: BiLSTM with 64 units per direction; concatenate the final forward and backward states; linear output head.
   - B2 BiGRU_Attn: BiGRU with 64 units per direction; additive attention with dimension 64; linear output head.
   - B3 TCN: three residual dilated Conv1d blocks with 64 channels, kernel 3 and dilations 1, 2 and 4; ReLU; dropout 0.1; global average pooling; linear output head.
   - B4 Transformer: input projection 13→64; learned positional embedding of length 20; 2 encoder layers with 4 heads, feed-forward size 128 and dropout 0.1; mean pooling; linear output head.
   - B5 MLP: flatten to 260; layers 260→128→64→1 with ReLU and dropout 0.2.
   - B6 LSTM_AE (unsupervised, after Ketepalli et al. 2022):
     - Train on DEVELOPMENT TRAIN windows labelled benign only, with MSE reconstruction loss.
     - Encoder: LSTM 64. Decoder: LSTM 64 repeated over 20 steps, then a linear layer to 13.
     - Use the same epoch, patience and selection rules (select on development validation AP of the reconstruction-error score).
     - The anomaly score is the mean squared reconstruction error.
   - B7 IsolationForest (unsupervised):
     - Use the 40 parity-gated tabular summaries.
     - Settings: n_estimators=200, max_samples=256, contamination='auto', random_state set to the seed.
     - Fit on all DEVELOPMENT TRAIN windows. The score is −score_samples.
   - B8 LightGBM_40:
     - Use the 40 parity-gated summaries.
     - Settings: n_estimators=300, num_leaves=31, learning_rate=0.05, scale_pos_weight=N−/N+ (development), subsample 0.8 with subsample_freq 1, colsample_bytree 0.8, deterministic=True.
     - If lightgbm cannot be installed into an isolated environment, skip B8 and record why.
4. Time limit: if any single baseline seed exceeds 90 minutes, stop it, record "TIMEOUT", and continue with the next one.
5. Log every run in phase4\TRAINING_LOG_PHASE4.csv with these fields: model, seed, epochs, best epoch, development AP, duration, device.
6. Freeze the models in phase4\MODELS_FROZEN_PHASE4.json, with the checkpoint hashes.



Amendment 2 receipt: SHA-256 of this amendment section's UTF-8 bytes, from its leading newline through its final newline: 318a460dd7d810caf4f808755f829b1fe359107567eac524fadf3d97478491cc
UTC: 2026-10-22T02:09:27.6404967Z
