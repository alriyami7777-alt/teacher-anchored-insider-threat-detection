# EDITOR-006D — Freeze the CERT r6.2 one-pass external runner

Verdict: **EDITOR006D_EXTERNAL_RUNNER_READY_WITH_QUALIFICATIONS**

This task froze `scripts/run_editor006e_r62_one_pass.py` as the only authorised
future CERT r6.2 execution entrypoint. It reuses the frozen EDITOR-006B1 harness
modules and does not copy their implementations.

It did **not** score CERT r6.2 and did **not** create a true predictive
authorisation (`predictive_external_run_authorised` remains false in the only
committed auth file).

## Identities

| Item | Value |
| --- | --- |
| EXTERNAL_RUNNER_SHA256 | `f9c33800a5340701c908e7d37fcd0c9fc810c6e550005df2440bb0c1dd4d8061` |
| FINAL_RELEASE_MANIFEST_SHA256 | `56d3aae461835009471ccb22b1511530bb40e41a294c8bb1640943eaf14354ba` |
| HARNESS_CODE_SHA256 | `d287a85e03e8c666be5cf06c2329e6d81fbed3ea08cb1563225ac2d92badc451` |
| HARNESS_RUNNER_SHA256 | `3965f47a08fa79f17bc2d4c1cbf54fbdcd3ce1d6add6d7f864c123a501f8d17d` |
| CONTRACT_BUNDLE_SHA256 | `d9f3daf89da4b1d06d22081245a63eac50a0768aece1f1e566187593783e734a` |
| MODEL_ALLOWLIST_SHA256 | `699c983d1ad98a5dcce7768447dcac4a44f5a5e8fed740b4c8378876efa52e5a` |
| SEQUENCE_ORDER_SHA256 | `21c4dd51f8aefb26fa1987764b0c129fac599fc52653349732a4fd8e39c32b4c` |
| Starting HEAD | `b4b19d44b31c4b9d054fa0d782f80e65a18dac4b` |
| Harness vs `2a73123` | empty |

## Gate order

1. parse CLI
2. compute runner self-hash
3. read authorisation JSON
4. validate frozen harness auth fields (`task_id=EDITOR-006E`, dataset, hashes, `predictive_external_run_authorised=true`)
5. validate additional release bindings (runner SHA, harness-runner SHA, 006C commit, sequence-order SHA, scaler SHA)
6–9. verify final-release manifest, harness-code, harness-runner, contract/allow-list/scaler identities
10. producing-source hash preflight
11. hash-preflight all 18 allow-listed checkpoints (no deserialisation)
12. require empty score output directory
13. only then open bundle components
14. validate shapes/order
15. write `EXECUTION_STARTED.json`
16. only then load/score via `DenseDailyWindowProvider` + `write_scores_phase_streaming`

CLI default is `identity-preflight`. Scoring additionally requires `--execute-external` **and** a true authorisation. EDITOR-006D created neither a true authorisation nor a score directory.

## Tests

Combined pytest: **46 passed** (existing `tests/test_editor006b_*.py` + `tests/test_editor006d_external_runner.py`).

FALSE template abort:

```text
EDITOR006E_EXTERNAL_RUN_ABORTED
EXTERNAL GATE: predictive_external_run_authorised is not true
R62_BUNDLE_OPENED_FOR_INFERENCE = NO
R62_PREDICTIVE_INFERENCE_EXECUTED = NO
```

## Qualifications

- Builder execution identity from EDITOR-006C1 remains `REVIEWED_POSTRUN_COPY_NOT_PROVEN_EXECUTED`; this does not change the independently verified scientific bundle.
- Unused-leaf fraction and tree-contribution rho remain `DISABLED_NOT_REPRODUCIBLE`.
- Checkpoint identity is still not a claim of complete from-source training reproducibility.
- The future one-pass run is not authorised by EDITOR-006D.

## NEXT_ACTION

Short independent review of the actual external runner and its SHA.
If approved, create the true EDITOR-006E authorisation bound to the runner SHA
and execute the one-pass run. Do not score CERT r6.2 until that authorisation exists.
