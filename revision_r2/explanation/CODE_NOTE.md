# Code behind `revision_r2/explanation/` and `revision_r2/explanation_holdout/`

`code/` is the Phase 3 explanation project as it ran (Integrated Gradients and TreeSHAP faithfulness), copied unchanged. `code/CODE_HASHES.json` lists the hashes frozen before the run, and `CODE_HASHES.json` and `FINAL_VERIFICATION.json` in this folder record them.

The scripts keep the authors' Windows paths (`C:/PhD/...`) and expect the frozen checkpoints of the original all-user models, which are not distributed. They are published so the method can be inspected, and are not needed for the seed-42 unseen-user reproduction described in the main README.
