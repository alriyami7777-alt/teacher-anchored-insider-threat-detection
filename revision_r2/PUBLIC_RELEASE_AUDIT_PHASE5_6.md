# Pre-push audit: `revision_r2/phase5` and `revision_r2/phase6` (22 Oct 2026)

## What was copied
| Folder | Source on the author's PC | Files |
|---|---|---|
| `phase5/` | `R2_revision\phase5\` top-level files (report, CSVs, JSON, figures). `private/` and `matplotlib_cache/` excluded. | 58 |
| `phase5/reproducibility_code/` | `r2_holdout\phase5\*.py` (the code the Phase 5 report names) | 10 |
| `phase6/` | `phase6_public_bundle.zip`, unpacked. Checked byte-for-byte against `R2_revision\phase6\` minus `private/`: identical, nothing missing. | 66 |

Phase 6B is **not** included: it was still training (seed 62) and `PHASE6B_COMPLETE` did not exist.

## Code-hash check
Each `reproducibility_code/*.py` was hashed (SHA-256) and compared with the hashes frozen in the run's own protocol files.
- Phase 5: 10/10 match `MODELS_AND_METHODS_FROZEN_PHASE5.json` / `PHASE5_RESULTS.json`.
- Phase 6: 11/11 recorded files match `TRAINING_PROTOCOL_FROZEN.json`, `INFERENCE_PROTOCOL_FROZEN.json` and `POSTTRAIN_CODE_FROZEN.json`. Four helper scripts (`editorial_qa6.py`, `final_context6.py`, `freeze_posttrain6.py`, `freeze_training6.py`) write those freeze files and are not themselves hashed in them.

## Audit result (`tools/audit_public_copy.py`)
| Check | Result |
|---|---|
| CERT user IDs (pattern `AAA0000`) | none |
| CERT raw data, answer files, `r5.2` TEST material | none. "answer" appears only in prose ("answer-file incidents") and in SHA-256 entries naming derived bitmask files, with no content. |
| Checkpoints / arrays / pickles / archives | none |
| `private/` content | none |
| Files > 10 MB | none (largest: `phase5/PHASE5_RESULTS.json`, 3.9 MB) |
| Absolute paths | `C:\PhD\...` in provenance keys and hashed-input lists. Prefixes `04_Journal_Papers`, `06_Datasets`, `07_Projects` were already public in commit `475a4c1`. **New:** `C:\PhD\00_RESEARCH_CONTROL\phase6_staging\` (folder where the Phase 6 code was staged; appears as hash keys only). No user name, home directory or e-mail. Left unedited so the frozen JSON hashes stay valid. |

## Line endings
The repository's `.gitattributes` normalises text files to LF. The `.py` files were already LF, so their hashes above hold in a clone. The JSON, CSV and Markdown outputs were written with CRLF on Windows; in a clone they are LF, so a byte-level hash of those outputs will differ from one taken on the author's PC. Their content is unchanged.

## Phase 6B (added 22 Oct 2026, 22:15)
| Item | Result |
|---|---|
| Source | `phase6b_public_bundle.zip` (40 files), byte-identical to `R2_revision\phase6b\` top-level files; `private/` excluded. `STATUS.json` stage = `PHASE6B_COMPLETE`, all checks passed. |
| Code | `phase6b/reproducibility_code/`: 11 scripts from `phase6b\private\code_snapshot\` (code only). 11/11 SHA-256 match the hashes frozen in the Phase 6B JSON records. |
| Audit | No CERT user IDs, CERT raw/answer data, binaries, `private/` content or files >10 MB. Absolute paths only under `C:\PhD\04_Journal_Papers` and `C:\PhD\07_Projects`, already public. |
| Line endings | Two scripts (`bootstrap6b.py`, `common6b.py`) have mixed line endings. `revision_r2/.gitattributes` marks every `reproducibility_code/*.py` as `-text`, so clones keep the exact bytes and the hashes hold. |

## `analysis/` and `paper_figures/` (added 22 Oct 2026)
- `analysis/efficiency/`: `efficiency_profile.py`, `efficiency_profile.csv` and the five `*_result.json` files. Left out: console logs (contain the Python install path under `C:\Users\`), `*_partial.json` duplicates, `efficiency_profile.json` (Python executable path) and `model_complexity_and_training.csv` (GPU serial UUID). Their table values are all in the result JSONs.
- `analysis/feature_study_evidence.json`, `phase1_verification.json`, `xgb40_vs_ta2_validation_bootstrap.py/.json`: paths only under `C:\PhD\07_Projects`.
- `paper_figures/`: four plotting scripts copied from the current manuscript source. `plot_user_split.py` writes to a sandbox path (`/home/claude/...`), not a personal path.
- Audit: no CERT user IDs, CERT data, binaries or `private/` content.

## Unseen-user code, data preparation, explanation code and seed-42 checkpoints (added 23 Oct 2026)
| Folder | Source on the author's PC | Notes |
|---|---|---|
| `holdout/code/` (249 files) | `C:\PhD\07_Projects\r2_holdout` without `phase4/.venv`, `phase5/` (already in `phase5/reproducibility_code/`) and caches | 242 files match the hashes in `holdout/MODELS_FROZEN.json` and `holdout/phase4/MODELS_FROZEN_PHASE4.json` (`reproduce_unseen_seed42.py check`). Two files redacted, listed in `holdout/code/REDACTIONS.json`: a path to a local prompt file in `phase2_prepare.py`, and a CERT user ID in a comment of `src/cert_ground_truth.py`. |
| `holdout/data_prep/` (5 scripts) | `C:\PhD\07_Projects\cert-r52-preparation\scripts` | Same user-ID comment redacted in `cert_ground_truth.py`. Provenance limits in `holdout/data_prep/README.md`. |
| `holdout/reproduce/` | New | Written for the clean-clone test. Dry-run on the author's own r5.2 day-level table: the split reproduced both list hashes in `SPLIT_RECEIPT.json`, and all six development tensors (X, X40, y for TRAIN and VALIDATION) matched `DATA_MANIFEST.json` byte for byte. The XGBoost-40 load-route scoring path was also run there; the neural load route needs PyTorch, which that sandbox could not install. |
| `holdout/MODELS_FROZEN.json`, `DATA_MANIFEST.json`, `CONFIGS_FROZEN.json` | `R2_revision\holdout\` | Hash records used by the checks. Paths only under `C:\PhD\04_Journal_Papers` and `C:\PhD\07_Projects`. Not published: `ENVIRONMENT_PHASE2.json` and `PARITY_GATE.json` (contain `C:\Users\` paths), `SUPERVISOR_DISCLOSURE_PHASE4.json`, `PREFLIGHT_CHECKS.json`. |
| `holdout/checkpoints_seed42/` | `R2_revision\holdout\private\checkpoints\{TA2,F00}\seed42\best.pt`, `...\checkpoints_parity_v2\XGBoost_40\seed42\model.json` | Published with Qasim's approval (23 Oct). Byte-identical to the frozen hashes. Pickle strings and raw bytes checked: model weights, configuration and threshold only; no user IDs, no file paths. |
| `explanation/code/` | `C:\PhD\07_Projects\r2_explanation` without `.venv` | 5/5 files listed in its `CODE_HASHES.json` match. Paths only under `C:\PhD`. |

Audit: no CERT user IDs (after the two redactions), no CERT data, answer files, tensors or `private/` content. The only binaries are the two seed-42 `.pt` checkpoints. `revision_r2/.gitattributes` keeps all of these folders byte-exact in clones.
