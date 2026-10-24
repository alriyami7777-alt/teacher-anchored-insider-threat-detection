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

## Phases 6C, 7 and 8 (added 23 Oct 2026)
| Folder | Source | Code | Notes |
|---|---|---|---|
| `phase6c/` (40 + 10 files) | `phase6c_public_bundle.zip`; byte-identical to `R2_revision\phase6c\` minus `private/`; status `PHASE6C_COMPLETE` | `phase6c\private\code_snapshot\` (code only); 10/10 hashes match the frozen records | 498 user pseudonyms |
| `phase7/` (58 + 10 files) | `phase7_public_bundle.zip`; byte-identical to `R2_revision\phase7\` minus `private/`; status `PHASE7_COMPLETE` | `C:\PhD\00_RESEARCH_CONTROL\phase7_staging`; 10/10 hashes match | 500 user pseudonyms |
| `phase8/` (57 + 18 files) | `phase8_public_bundle.zip`; byte-identical to `R2_revision\phase8\` minus `private/`; status `PHASE8_COMPLETE` | `C:\PhD\00_RESEARCH_CONTROL\phase8_staging` (`.py` files only); 18/18 hashes match | No per-user identifiers |

Audit: no CERT user IDs, CERT data, answer files, binaries or `private/` content. Absolute paths only under prefixes already public (`C:\PhD\00_RESEARCH_CONTROL`, `04_Journal_Papers`, `06_Datasets`, `07_Projects`). Largest files: `phase8/Q2_OUTCOMES.json` (15.6 MB) and `phase7/P4_SELECTED_USER_DAY_ALERTS.csv` (9.4 MB), both below GitHub's limits.

Pseudonyms: every `U_` token has the form `U_` + the first 10 hex digits of SHA-256(CERT user ID), the same scheme as `revision_r2/evidence/`. All 500 distinct pseudonyms were checked against the r5.2 user list and none is a raw ID. The hash is unsalted, so anyone who holds the licensed CERT r5.2 data can map a pseudonym back to its synthetic user ID; it does not reveal IDs to anyone without the dataset.

## Phases 9, 10 and 11 (added 24 Oct 2026)
| Folder | Source | Code | Notes |
|---|---|---|---|
| `phase9/` (120 + 35 files) | `phase9_public.zip`; byte-identical to `R2_revision\phase9\` minus `private/`; report ends `PHASE9_COMPLETE` | `C:\PhD\00_RESEARCH_CONTROL\phase9_staging` (`.py` only); 35/35 hashes match the frozen records (16 in the final code freezes, the rest in other receipts). Imported `r2_holdout` modules are already in `holdout/code/`. | 31 r5.2 pseudonyms |
| `phase10/` (53 + 21 files) | `phase10_public_v2.zip`; byte-identical to `R2_revision\phase10\` minus `private/`; report ends `PHASE10_COMPLETE` | `phase10_staging`; 21/21 match | 4,000 CERT r6.2 user pseudonyms, including the development and held-out lists `R62_*_PSEUDONYMS.txt` |
| `phase11/` (96 + 25 files) | `phase11_public.zip`; byte-identical to `R2_revision\phase11\` minus `private/`; report ends `PHASE11_COMPLETE` | `phase11_staging`; 25/25 match | 4,000 r6.2 pseudonyms |

Excluded:
- `phase10/DEADLINE_EXTENSION_CONTROL_CHANGE.json` and `phase11/NO_LIMIT_COORDINATOR_TRANSITION.json`. These are process-control receipts, not results, and they contain the Python install path under `C:\Users\`.
- Every `private/` folder.

Audit:
- No CERT user IDs, CERT data, answer files, tensors, checkpoints or binaries.
- No tokens, keys, passwords or e-mail addresses.
- Absolute paths appear only under prefixes that are already public.
- The largest new file is under 5 MB.
- "answer" appears only as a file-name string inside hash records (`answer_scenario_day_bitmask.npy`, whose content is not included) and in code.

Pseudonyms:
- All tokens have the form `U_` plus the first 10 hex digits of SHA-256 of the user ID. The r6.2 split receipt states the same rule.
- The 31 Phase 9 pseudonyms all match r5.2 users.
- The r6.2 pseudonyms could not be checked against the r6.2 user list, because that data was not mounted. None of them matches the CERT ID pattern.
- As before, the hash is unsalted. A CERT licensee can map pseudonyms back to synthetic user IDs and, through the insider-status columns, to insider status. Licensees already hold that information in the answer files.
