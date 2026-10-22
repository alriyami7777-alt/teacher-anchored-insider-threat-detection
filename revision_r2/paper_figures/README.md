# Plotting scripts used for the current R2 manuscript figures

These are the exact scripts that drew four figures in the R2 manuscript. Inputs are files already in this repository.

| Script | Figure label | Input | Command |
|---|---|---|---|
| `plot_holdout.py` | `fig:holdout` | `revision_r2/holdout/phase4/HOLDOUT_RESULTS.csv` (rows with `view == pooled_completed`) | `python plot_holdout.py ../holdout/phase4/HOLDOUT_RESULTS.csv fig_holdout_unseen_users.pdf` |
| `plot_ig.py` | `fig:ig_attribution` | `revision_r2/explanation/integrated_gradients_features.csv` | `python plot_ig.py ../explanation/integrated_gradients_features.csv fig_ig_attribution.pdf` |
| `plot_components_dependence.py` | `fig:teacher_guidance_component_effects`, `fig:dependence_endpoint_validation` | Component contrasts are typed in from the frozen bootstrap files (EDITOR011/012/023, see `RESULTS_MAP.md`). The offset curves read `EDITOR029_PARTA_ALL_OFFSETS.csv` and `EDITOR029_ENDPOINT_ALL_OFFSETS.csv` from `revision_r2/evidence/editor029-endpoint-dependence-aware/review/editor029_endpoint_dependence/`; copy them next to the script with the prefix `f8_` before running. | `python plot_components_dependence.py` |
| `plot_user_split.py` | `fig:user_split` | None (counts typed in from `revision_r2/holdout/SPLIT_RECEIPT.json`). Its two `savefig` lines hold the author's sandbox output path; change them to a local path. | `python plot_user_split.py` |
