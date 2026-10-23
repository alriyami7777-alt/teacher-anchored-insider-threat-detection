# Seed-42 checkpoints for the unseen-user check

Three frozen models from the unseen-user evaluation (`tab:holdout`), seed 42 only:

| Folder | Model | Frozen threshold |
|---|---|---|
| `checkpoints/TA2/seed42/best.pt` | TRACE (internal name TA2) | in `../phase4/MODELS_FROZEN_PHASE4.json` |
| `checkpoints/F00/seed42/best.pt` | Task-only control (F00) | same |
| `checkpoints/XGBoost_40/seed42/best.json` | XGBoost-40 (saved as `model.json` in the original run; renamed only) | same |

Each file is byte-identical to the checkpoint scored in the paper. `SHA256SUMS.txt` lists the hashes, and `reproduce_unseen_seed42.py score --route load` checks them against `../phase4/MODELS_FROZEN_PHASE4.json` before use.

Contents: model weights, the training configuration and the selected threshold. No CERT records, user identifiers or file paths (checked before publication). The models were trained only on the 1,500 development users.
