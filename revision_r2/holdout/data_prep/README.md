# CERT r5.2 data preparation (raw files to the day-level table)

These scripts are the CERT r5.2 preparation pipeline that produced the paper's day-level table on 23 July 2026 (run finished 08:38 UTC; stages match, label_events, unified_stream, daily_intervals, densify, sliding_windows, sequence_tensors). They are copied from the preparation project's `scripts/` folder as it stands now. Two of them (`cert_common13_pipeline.py`, `prepare_cert_common13_pipeline.py`) were last modified at 11:15 UTC the same day, after that run, and no hash of the version that ran was recorded. Whether they still produce the same table is tested downstream: `reproduce_unseen_seed42.py build` compares the rebuilt development tensors with the SHA-256 hashes recorded in `../DATA_MANIFEST.json` when the paper's tensors were made.

For the unseen-user reproduction only the first five stages are needed. The README's step 3 runs those five, so no window or tensor file is built for any period, and none for the TEST period. The paper's split boundaries (TRAIN to 2011-02-18, VALIDATION to 2011-04-10) come from `TRAIN_FRAC = 0.80` and `VAL_FRAC = 0.10` of the 517 calendar days in `cert_common13_pipeline.py`.

**Change made for the public copy (24 Oct 2026).** In `dataset_registry.py`, the authors' machine-specific Windows paths were removed:
- `FORBIDDEN_RAW_SOURCES` (a blocklist of local folders) is now empty.
- `CANONICAL_EXTERNAL_RAW` (fallback raw-data locations) is now empty.

On the authors' PC, one of the blocked folders resolved to the real CERT r5.2 folder, so the first clean-clone test was refused at step 3. Everything else in the file is unchanged. A raw folder passed with `--raw-dir` is still accepted only if it contains the CERT activity CSVs (`logon.csv`, `device.csv`, `file.csv`, `email.csv`, `http.csv`). Neither setting affects how the data are processed.

| File | SHA-256 in the preparation project (23 Oct 2026) | Public copy |
|---|---|---|
| `cert_common13_pipeline.py` | `3c6103f2fa019fc15d445bac7c574472aeb7614345fb84f43488f6759b708958` | identical |
| `cert_ground_truth.py` | `230c19f36077001a6f6132b69421b707e783320afb2f6d0592b8c5a70e2a3349` | one comment redacted: a CERT user ID in an example file name was replaced by `<USERID>` |
| `cert_schema_audit.py` | `611b0965dd6df0c09003a2ea27ad338d1595179d093a39b00f1a7fcd06309f9b` | identical |
| `dataset_registry.py` | `09fe79e409f68afdd934b08654406aaa9aa310c2500fc9f3eb9a195e13d678f4` | local paths removed (see above); public copy `d68e50a6d4f954db6422d84fcf56b25a7d0f8047abf5980c949a994acf20fe9f` |
| `prepare_cert_common13_pipeline.py` | `2cc58770bd1ee4c4dd830f10df9086ea131dea67f65828845ad0eb4db71570c7` | identical |
