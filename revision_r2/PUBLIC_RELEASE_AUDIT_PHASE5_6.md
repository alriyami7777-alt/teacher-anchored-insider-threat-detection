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
