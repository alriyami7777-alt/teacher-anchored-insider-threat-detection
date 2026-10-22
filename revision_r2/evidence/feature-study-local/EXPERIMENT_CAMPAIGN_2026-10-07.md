# Authorized experiment campaign — 7 October 2026

This is a launch and continuation record, not a completed-results report. All new measurements belong to the F29 feature selection and expansion study under `revision_v0.2`. They must remain separate from the frozen IEEE Access evidence. TEST evaluation and the optional history arm are excluded.

## Verified before launch

- Full TRAIN extraction and exact F13 parity passed in `implementation_runs/full_train_preflight_20261007_r1`.
- All 84 registered inner XGBoost fits completed in `experiment_runs/inner_xgb_20261007_r1`. S13 selected `LOCO_active_duration_minutes` (12 channels); Splus selected `FAM_actions` (17 channels). Selection used INNER_SELECT only.
- Validation feature/key/label parity passed in `implementation_runs/validation_preflight_20261007_r1`: 16,640,000 exact scaled F13 values, 64,000 windows, 728 positive windows, matching raw rebuilt labels and legacy IDs. This gate generated no model predictions.
- Nine secondary/outer unit tests passed. The secondary preparation stage independently reran its five model/cache/gate tests and locked input, source, configuration and runtime hashes before training.

## Running campaign

Coordinator: `implementation/run_campaign.py`.

Campaign directory: `experiment_runs/campaign_20261007_r1`.

Secondary run: `experiment_runs/secondary_20261007_r1`.

Outer XGBoost run: `experiment_runs/outer_xgb_20261007_r1` (created only when its stage begins).

Stages execute sequentially: secondary preparation; 30 RF/attention inner fits; 30 outer XGBoost fits and paired analyses; 30 RF/attention outer fits; secondary paired analyses. These stages plus the completed 84 inner XGBoost fits total 174. Source files are now frozen by the secondary manifest. Do not edit them while the campaign runs.

Each stage has a numbered `.log`, a `*_START.json`, and, once finished, a `*_END.json` in the campaign directory. The coordinator writes `COMPLETE.json` only after all five stages succeed; failures write `FAILED.json` and halt progression. Failed fits are retained without automatic retries. Partial work must not be relabeled complete or silently rerun.

## Safe continuation

Read `coordination/campaign/ACTIVE_WRITER.json`, `coordination/ACTIVE_WRITER.json`, and the numbered stage logs first. Verify the recorded processes and completion evidence before taking any recovery action. A live writer means observe the existing campaign; do not launch another. These are cooperative locks, not protection against unrelated software that ignores them. The CERT re-audit chat was idle at launch; this chat owns experiment execution.

The initial terminal session is 96082. The process command uses `C:\Users\User\miniconda3\envs\cert-r42-gpu\python.exe`. Stage logs persist independently of the conversation. Keeping the computer awake is necessary for continued local execution. No scheduled notification or separate monitoring automation has been created.

## Interpretation and review

The sole primary contrast is outer XGBoost F29 minus F13. INNER_SELECT scores are development results and cannot establish outer improvement. Final validation comparisons remain retrospective because this validation set has been used historically. All operating-point metrics use frozen transported thresholds. See `SECONDARY_EXECUTION_LOCK.md` for exact stage rules.

`CURSOR_EXPERIMENT_REVIEW.md` is the optional read-only reviewer handoff. Cursor has not reviewed or certified this campaign. A reviewer must not train, edit locked sources, access TEST, or start a second writer.
