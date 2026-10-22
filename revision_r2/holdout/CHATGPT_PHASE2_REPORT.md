# Phase 2: user-disjoint holdout retraining

Started UTC: 2026-10-21T15:18:11.689527+00:00
Updated UTC: 2026-10-21T16:26:16.975736+00:00
Status: finished_models_frozen_not_scored

## Step 0 â€” preregistration and user split

Preregistration was written and SHA-256 frozen before split materialization. The pre-split bytes are preserved in the isolated code folder. One NumPy default_rng(20261022) shuffled sorted insider and then non-insider strata. No rounding adjustment was needed.
HOLDOUT: 500 users (25 insider, 475 non-insider). DEVELOPMENT: 1,500 users (74 insider, 1,426 non-insider). Public receipts contain counts and list hashes; all user IDs are private.
Insider strata were obtained from the 99 nonempty per-user r5.2 answer-file names; no answer activity payload or TEST day was read. The prior producing preparation manifest records successful malicious-event matching for these sources.

## Step 1 â€” CPU data rebuild

DEVELOPMENT TRAIN: 591,000 windows, 3,040 positives. DEVELOPMENT VALIDATION: 48,000 windows, 473 positives. Each window is 20 Ã— 13; The original 40 raw summaries were superseded after the parity audit: the active tabular inputs now use exact producing aggregation of the standardized float32 20×13 tensors.
HOLDOUT label counts only: TRAIN 197,000 windows / 917 positives; VALIDATION 16,000 windows / 255 positives. These were read from label/identity members of the existing allowed TRAIN/VALIDATION archives; the X members were not opened.
Scaler fit on 619,500 DEVELOPMENT TRAIN user-days only. Primary neural w+ = 48.35197368421053. Rebuilt window counts and labels match the original development subset exactly; mismatches: 0. CPU preparation: 96.92 seconds.
Daily-table scanning used development-user and date predicates (2010-01-02 through 2011-04-10); no TEST row was returned or materialized. No holdout feature windows were built.

## Step 2 â€” frozen training recipes and execution

All training runs wait for CHATGPT_PHASE1_REPORT.md to end with PHASE1_COMPLETE. Gate checks occur every 300 seconds. Each failed run receives at most one identical-config retry; dependent items are skipped if the required development checkpoint is unavailable.
The producing T-OPT recipe freezes an attention-linear encoder. Therefore three development-only attention-linear prerequisite models are trained first (and three analogous uni-LSTM prerequisites later), using their original frozen recipe: Adam 0.001, ratio class weight multiplier 1.0, ReduceLROnPlateau factor 0.5/patience 2/min_lr 1e-5, maximum 15 epochs/patience 4. Historical all-user checkpoints are never used.
T-OPT and student recipes retain the producing ODST-046 constructor and initialization; max 15 epochs, patience 4, batch 1024, clip 1.0, primary neural class weight 0.25 Ã— N-/N+. Student encoder/attention learning rates 3e-5 and head learning rate 1e-3. TA2 is task + 0.5 equal-weight three-teacher logit MSE + 0.5 matched-teacher route KL. F00 starts from its matched development T-OPT and uses task loss only. F10 omits route KL. L1 starts with the matched T-OPT encoder and a fresh zero-initialized linear head, plus ensemble logit MSE.
RF_40 retains balanced_subsample; XGBoost_40 retains scale_pos_weight=N-/N+ from development TRAIN, as their producing recipes require. The active tabular summaries aggregate the daily-standardized sequence tensor, exactly as cert-r52-locked-baselines does; no additional 40-feature scaler is fitted. The exploratory uni intervention uses one direction, hidden size 128 and representation dimension 128, with its own development-only teachers.
No hyperparameter search is performed. Validation probabilities, checkpoint selection and maximum-F1 thresholds use DEVELOPMENT VALIDATION only. Every run, config, attempt, epochs, best epoch, development AP, duration and device is recorded in TRAINING_LOG.csv; detailed logs/checkpoints remain private.
Requested run order: T-OPT Ã—3; F00 Ã—3; TA2 Ã—3; XGBoost_40 Ã—3; RF_40 Ã—3; L1 Ã—3; F10 Ã—3; uni T-OPT Ã—3; uniTA2 Ã—3. Necessary precursor training occurs immediately before its T-OPT stage.

Completed requested runs: 27/27. Completed prerequisite runs: 6.

Skipped or failed items: none to date.

Recipe deviation found and corrected before any holdout scoring: v1 tabular summaries used raw values rather than producing standardized float32 values. All six old tabular runs are SUPERSEDED_PARITY. The active v2 models use the exact producing pipeline with the preregistered development-user restriction and scaler refit, and the explicitly preregistered uni architecture intervention. Prerequisite models preserve their original class-weight/scheduler recipe. Diagnostic-only training passes are omitted without changing optimization equations.

## Step 3 â€” model and future-scoring freeze

The future one-pass scoring script is written and hashed, with frozen runtime dependencies. It is never executed by this worker. It requires a recorded supervisor disclosure before later scoring, verifies the frozen hashes, consumes an exclusive one-pass sentinel, and uses the frozen development thresholds without recalibration. Primary view: HOLDOUT VALIDATION + TEST completed windows; secondary offset-0 de-overlap and endpoint-label views. Paired user-cluster bootstrap uses 2,000 replicates, seed 42, 95% percentile intervals and the preregistered decision rules.
No holdout scoring, prediction or performance metric is computed tonight. No TEST tensor is opened. No r5.1, r6.1 or r6.2 data is used. No existing teacher-anchored repository or worktree is changed, and nothing is pushed.

Models freeze: written to MODELS_FROZEN.json; consult its completeness and skipped items.

## Evidence

PREREGISTRATION_R2_HOLDOUT.md; SPLIT_RECEIPT.json; DATA_MANIFEST.json; TRAINING_LOG.csv; PHASE2_STATUS.json; MODELS_FROZEN.json (at finish). All IDs, tensors, source-level tracebacks and checkpoints are under private/.

## Parity gate

Mandatory development-only P1–P4 audit completed UTC 2026-10-21T22:28:43.461700+00:00. Detailed per-column differences, every estimator parameter, both scaler means/stds, source hashes and all model metrics are in PARITY_GATE.json.

P1: confirmed raw-versus-standardized input mismatch in v1. Column order and named formulas were identical, but v1 aggregated raw float64 daily values while the producing pipeline aggregates standardized float32 sequence values. All 40 original producing input columns were reproduced bitwise. Corrected development features reproduce the exact producing function bitwise; their residual difference from the original input is the preregistered development-only scaler refit.

P2: XGBoost_40: original producing DEVELOPMENT AP 0.954024423, saved AP 0.954024423, max probability difference 0 (zero after saved float32 serialization); RF_40: original producing DEVELOPMENT AP 0.934047246, saved AP 0.934047246, max probability difference 2.96e-08 (zero after saved float32 serialization). Frozen original seed-42 models were also tested on v1 raw features and corrected development-scaler features, exclusively for the same 48,000 development validation windows. These diagnostics are not new holdout metrics.

P3: every estimator parameter was compared. Hyperparameter recipes match apart from the authorized development recomputation of XGBoost scale_pos_weight (198.1407632044478 original versus 193.4078947368421 development). No early stopping is used; seeds 42/52/62 and the producing tree counts, depth, class weights, sampling and histogram method are retained. Other corrections: exact producing Python/NumPy/pandas environment for tabular runs, int32 labels, float64 probability conversion before threshold selection, and JSON serialization for XGBoost.

P4: for both TRAIN and VALIDATION, original and development tensors were reconstructed bitwise from the same development raw windows using their respective recorded scalers. Labels, window identity, features and ordering match; only the preregistered scaler refit differs. All neural checkpoint hashes are unchanged.

All six tabular models were retrained, and the six former successful rows were marked SUPERSEDED_PARITY in TRAINING_LOG.csv. Corrected DEVELOPMENT VALIDATION AP: XGBoost_40: seed42=0.923187611, seed52=0.926093180, seed62=0.927420034; RF_40: seed42=0.943516106, seed52=0.939202612, seed62=0.941052066. MODELS_FROZEN_v1.json preserves the old freeze; MODELS_FROZEN.json is v2 with corrected checkpoint and scoring-script hashes. The deferred scorer now enforces this parity gate and uses the exact producing aggregate function. It was not executed. No TEST data or holdout feature/probability row was materialized, scored or used in fitting.

PARITY_GATE_FIXED
