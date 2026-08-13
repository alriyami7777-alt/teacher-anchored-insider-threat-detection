# EDITOR-006D1 — Final execution-path hardening of the frozen CERT r6.2 one-pass runner

Verdict: **EDITOR006D1_EXECUTION_PATH_READY_WITH_QUALIFICATIONS**

This task hardened `scripts/run_editor006e_r62_one_pass.py` only. Frozen harness
modules, the scientific r6.2 bundle, and the EDITOR-006C1 final release manifest
were not modified.

It did **not** score CERT r6.2 and did **not** create a true predictive
authorisation.

## Identities

| Item | Value |
| --- | --- |
| Reviewed 006D base commit | `1926b333f473654d543afc78eb9ddaf849b9320b` |
| Reviewed 006D runner SHA256 | `f9c33800a5340701c908e7d37fcd0c9fc810c6e550005df2440bb0c1dd4d8061` |
| NEW_EXTERNAL_RUNNER_SHA256 | `54f93cb57a66aa384cb3eb5e1fdcbca792009d9058ecdb980cf77be7a2c5b6ba` |
| FINAL_RELEASE_MANIFEST_SHA256 | `56d3aae461835009471ccb22b1511530bb40e41a294c8bb1640943eaf14354ba` |
| HARNESS_CODE_SHA256 | `d287a85e03e8c666be5cf06c2329e6d81fbed3ea08cb1563225ac2d92badc451` |
| HARNESS_RUNNER_SHA256 | `3965f47a08fa79f17bc2d4c1cbf54fbdcd3ce1d6add6d7f864c123a501f8d17d` |
| CONTRACT_BUNDLE_SHA256 | `d9f3daf89da4b1d06d22081245a63eac50a0768aece1f1e566187593783e734a` |
| MODEL_ALLOWLIST_SHA256 | `699c983d1ad98a5dcce7768447dcac4a44f5a5e8fed740b4c8378876efa52e5a` |
| SEQUENCE_ORDER_SHA256 | `21c4dd51f8aefb26fa1987764b0c129fac599fc52653349732a4fd8e39c32b4c` |
| EDITOR006C_RELEASE_COMMIT | `b4b19d44b31c4b9d054fa0d782f80e65a18dac4b` |
| Builder identity (inherited) | `REVIEWED_POSTRUN_COPY_NOT_PROVEN_EXECUTED` |

`EDITOR006D1_RUNNER_RELEASE_COMMIT` is the git commit that lands this directory
together with the hardened runner. Re-hash the runner after that commit; it must
remain `54f93cb57a66aa384cb3eb5e1fdcbca792009d9058ecdb980cf77be7a2c5b6ba`.

## Corrections

### H1 — Verify actual bundle bytes before execution

After authorisation, identity hashes, and empty output directory, and before
`EXECUTION_STARTED.json`, model deserialisation, or any forward pass, the runner
SHA-256s and byte-sizes the 13 on-disk files named in
`EDITOR006C_FINAL_RELEASE_MANIFEST.json` under the derived bundle directory.

Mismatch or a missing file raises `BUNDLE_COMPONENT_IDENTITY_MISMATCH` and
aborts. Tests use copied synthetic fixtures only; the real 13 arrays were not
rewritten.

### H2 — Persist the actual results

After `ALL_SCORES_COMPLETE.json` and analysis succeed, the runner writes:

1. `EDITOR006E_PREDICTIVE_RESULTS.json`
2. `EDITOR006E_MECHANISM_RESULTS.json` (H3)
3. `EDITOR006E_RUN_MANIFEST.json`
4. `EXECUTION_COMPLETE.json` last

`EXECUTION_COMPLETE.json` binds SHA-256 of
`EXECUTION_STARTED.json`, `ALL_SCORES_COMPLETE.json`,
`EDITOR006E_PREDICTIVE_RESULTS.json`, `EDITOR006E_MECHANISM_RESULTS.json`, and
`EDITOR006E_RUN_MANIFEST.json`. It is refused if any of those files is missing.
No per-model PR-AUC/F1 is printed during scoring.

### H3 — Execute the predeclared mechanism analysis

`run_authorised_mechanism_pass` now calls the previously unused
`mechanism_on_deoverlap` after all raw scores. Hash-gated load is limited to
teacher / C2 / original-paper C5 seeds 42/52/62. View is `DEOVERLAP_OFFSET0`
only. Unused-leaf fraction and tree-contribution rho remain disabled. The runner
does not hard-code that C5 improves anything.

### H4 — Truthful failure / partial-execution state

Explicit flags: `bundle_opened`, `execution_started`, `scoring_started`,
`all_scores_complete`, `analysis_complete`, `mechanism_complete`,
`execution_complete`.

- Failure before mmap open → `R62_BUNDLE_OPENED_FOR_INFERENCE = NO`.
- After `EXECUTION_STARTED.json` exists, predictive execution is
  `STARTED_OR_PARTIAL`, never `NO`.
- Unexpected `Exception` and `HarnessProtocolError` both write
  `EXECUTION_ABORTED.json` where the output directory was created by this
  one-pass. Outputs are not deleted. The run is not retried.

### H5 — Probability-metric safety

`probability_extras` computes Brier/log-loss only when every score is finite and
in `[0, 1]`. Otherwise it returns `probability_metric_status =
NOT_PROBABILITY_SCALE` with null Brier and log-loss. No sigmoid and no clip-into-
probability. Epsilon clip is used only for numerical log-loss safety on already
valid probabilities.

### H6 — Bind the reviewed runner commit

Future authorisation must include `editor006d_runner_release_commit`. The
reviewed 006D base `1926b333f473654d543afc78eb9ddaf849b9320b` must be an ancestor
of the claimed value, and the claimed value must be an ancestor of `HEAD`. After
this 006D1 commit, a future 006E authorisation may name the new 006D1 commit.
Load-bearing controls remain external-runner SHA, harness SHA, and final bundle
manifest SHA.

### H7 — Incident/scenario dependence summary

Descriptive `DEOVERLAP_OFFSET0` occupancy for r6.2-1 … r6.2-5 at frozen
thresholds for C2 and C5. Not a hypothesis test. Effective malicious cluster
count remains 5. Contextual users are not additional incidents.

## Tests

Combined pytest: **69 passed** (27 existing `tests/test_editor006b_*.py` + 19
existing 006D + 23 new 006D1).

D1–D12 all covered with synthetic / r5.2 VALIDATION-safe fixtures. No r5.2 TEST
tensor. No r6.2 predictive inference.

## Qualifications

- Builder execution identity from EDITOR-006C1 remains
  `REVIEWED_POSTRUN_COPY_NOT_PROVEN_EXECUTED`.
- Unused-leaf fraction and tree-contribution rho remain
  `DISABLED_NOT_REPRODUCIBLE`.
- Checkpoint identity is still not a claim of complete from-source training
  reproducibility.
- CLI scoring still requires `--execute-external` and a true authorisation.
- H6 uses ancestor binding so the reviewed 006D commit remains valid after this
  hardening commit; 006E should bind the new runner SHA and may name the 006D1
  commit.
- Component-byte tests use copied fixtures; the authorised 006E run must hash
  the actual derived-bundle files.

## NEXT_ACTION

One short independent review of the NEW runner SHA and these six corrections.
If PASS, create the true EDITOR-006E authorisation and execute exactly once.

HARD STOP: do not score CERT r6.2 and do not create a true authorisation in this
task.
