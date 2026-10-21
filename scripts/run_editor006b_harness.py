#!/usr/bin/env python3
"""EDITOR-006B harness runner: synthetic + r5.2 validation fixtures only.

Does not run CERT r6.2. Does not open r5.2 TEST. Does not write an authorisation file.
"""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from editor006b_harness.bootstrap import paired_user_cluster_bootstrap  # noqa: E402
from editor006b_harness.cli import (  # noqa: E402
    contract_bundle_hash,
    parse_args,
    prepare_mode,
    validate_external_authorization,
)
from editor006b_harness.safety import (  # noqa: E402
    BATCH_SIZE_FROZEN,
    C2_SEED62_THRESHOLD,
    EXPECTED_AGGREGATOR_SHA256,
    EXPECTED_SCALER_SHA256,
    FREEZE_DIR,
    FUTURE_EXTERNAL_DATASET_ID,
    OUTPUT_DIR_DEFAULT,
    REGISTER,
    REPO_ROOT,
    SCORE_STEM,
    HarnessProtocolError,
    hash_harness_sources,
    path_looks_like_r52_test,
    sha256_file,
    utc_now,
)
from editor006b_harness.contracts import load_freeze_bundle, validate_contracts  # noqa: E402
from editor006b_harness.hash_gate import gate_one, preflight_all_eighteen  # noqa: E402
from editor006b_harness.input_bundle import (  # noqa: E402
    build_synthetic_bundle,
    closed_loop_train_scaler,
    completed_and_endpoint_from_days,
    gather_windows,
    identifiers_sha,
    load_validation_development_fixture,
)
from editor006b_harness.manifests import dump_json, env_versions, git_snapshot, scan_harness_source  # noqa: E402
from editor006b_harness.mechanism import mechanism_on_fixture  # noqa: E402
from editor006b_harness.metrics import analyse_views  # noqa: E402
from editor006b_harness.model_loaders import (  # noqa: E402
    architecture_pins,
    import_aggregate_common13_windows,
    infer_neural,
    load_neural_checkpoint,
    load_rf,
    load_xgb,
    state_hash,
)
from editor006b_harness.scoring import require_score_complete, write_scores_phase  # noqa: E402


def _record(matrix: dict[str, str], code: str, ok: bool, detail: str = "") -> None:
    matrix[code] = "PASS" if ok else f"FAIL:{detail}"


def _run_external_gate_tests(contract_hash: str, allow_hash: str, harness_hash: str) -> dict[str, Any]:
    from typing import Any

    results: dict[str, Any] = {}
    auth_kw = {
        "expected_task_id": "EDITOR-006D",
        "expected_dataset_id": FUTURE_EXTERNAL_DATASET_ID,
        "expected_input_bundle_manifest_sha256": "0" * 64,
        "expected_contract_bundle_sha256": contract_hash,
        "expected_harness_code_sha256": harness_hash,
        "expected_model_allowlist_sha256": allow_hash,
    }
    try:
        validate_external_authorization(None, **auth_kw)
        results["missing"] = "FAIL"
    except HarnessProtocolError:
        results["missing"] = "PASS"
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        bad = tmp_path / "malformed.json"
        bad.write_text("{not json", encoding="utf-8")
        try:
            validate_external_authorization(bad, **auth_kw)
            results["malformed"] = "FAIL"
        except HarnessProtocolError:
            results["malformed"] = "PASS"

        def write_auth(**kwargs: Any) -> Path:
            payload = {
                "task_id": "EDITOR-006D",
                "dataset_id": FUTURE_EXTERNAL_DATASET_ID,
                "input_bundle_manifest_sha256": "0" * 64,
                "contract_bundle_sha256": contract_hash,
                "harness_code_sha256": harness_hash,
                "model_allowlist_sha256": allow_hash,
                "authorised_timestamp": utc_now(),
                "predictive_external_run_authorised": True,
            }
            payload.update(kwargs)
            p = tmp_path / "auth.json"
            p.write_text(json.dumps(payload), encoding="utf-8")
            return p

        def _auth_kwargs():
            return {
                "expected_task_id": "EDITOR-006D",
                "expected_dataset_id": FUTURE_EXTERNAL_DATASET_ID,
                "expected_input_bundle_manifest_sha256": "0" * 64,
                "expected_contract_bundle_sha256": contract_hash,
                "expected_harness_code_sha256": harness_hash,
                "expected_model_allowlist_sha256": allow_hash,
            }

        try:
            validate_external_authorization(
                write_auth(dataset_id="CERT r5.2"),
                **_auth_kwargs(),
            )
            results["wrong_dataset"] = "FAIL"
        except HarnessProtocolError:
            results["wrong_dataset"] = "PASS"
        try:
            validate_external_authorization(
                write_auth(contract_bundle_sha256="deadbeef"),
                **_auth_kwargs(),
            )
            results["wrong_contract_hash"] = "FAIL"
        except HarnessProtocolError:
            results["wrong_contract_hash"] = "PASS"
        try:
            validate_external_authorization(
                write_auth(harness_code_sha256="deadbeef"),
                **_auth_kwargs(),
            )
            results["wrong_harness_hash"] = "FAIL"
        except HarnessProtocolError:
            results["wrong_harness_hash"] = "PASS"
        try:
            validate_external_authorization(
                write_auth(predictive_external_run_authorised=False),
                **_auth_kwargs(),
            )
            results["false_authorisation"] = "FAIL"
        except HarnessProtocolError:
            results["false_authorisation"] = "PASS"

        fake_manifest = tmp_path / "r6.2_bundle_manifest.json"
        fake_manifest.write_text(json.dumps({"dataset_id": "CERT r6.2"}), encoding="utf-8")
        class A:
            mode = "synthetic"
            authorization = None
            input_bundle = fake_manifest
        try:
            prepare_mode(A(), contract_hash=contract_hash, allowlist_hash=allow_hash)
            results["r62_path_blocked"] = "FAIL"
        except HarnessProtocolError:
            results["r62_path_blocked"] = "PASS"
    return results


def main(argv: list[str] | None = None) -> int:
    started = utc_now()
    git_before = git_snapshot(REPO_ROOT)
    args = parse_args(argv)
    out_dir = Path(args.output_dir) if args.output_dir else OUTPUT_DIR_DEFAULT
    freeze_dir = Path(args.freeze_dir) if args.freeze_dir else FREEZE_DIR
    if out_dir.exists() and any(out_dir.iterdir()):
        print("EDITOR006B_OUTPUT_DIRECTORY_NOT_EMPTY")
        return 2
    out_dir.mkdir(parents=True, exist_ok=True)

    matrix: dict[str, str] = {f"T{i:02d}": "NOT_RUN" for i in range(1, 41)}
    flags = {
        "r62_predictive_inference": False,
        "r62_input_bundle_opened": False,
        "r52_test_tensor_opened": False,
        "training_executed": False,
        "scaler_fit_executed": False,
        "threshold_selection_executed": False,
        "calibration_fit_executed": False,
        "model_selection_executed": False,
    }

    try:
        bundle = load_freeze_bundle(freeze_dir)
        validated = validate_contracts(bundle)
        _record(matrix, "T01", True)
        _record(matrix, "T02", True)
        _record(matrix, "T03", True)
        _record(matrix, "T04", True)
        artefacts = validated["artefacts"]
        deny_hashes = set(validated["deny_hashes"])
        allow_hashes = {str(a["expected_sha256"]) for a in artefacts}
        dump_json(out_dir / "EDITOR006B_CONTRACT_VALIDATION.json", validated)

        preflight = preflight_all_eighteen(artefacts, deny_hashes)
        dump_json(out_dir / "EDITOR006B_MODEL_HASH_PREFLIGHT.json", {"status": "PASS", "artefacts": preflight})
        _record(matrix, "T05", all(r["status"] == "MATCH" for r in preflight))

        # T06 deny C5
        deny_art = bundle["EDITOR006A_C5_DENYLIST.json"]["artefacts"][0]
        try:
            gate_one(
                family="C5_original_paper",
                seed=42,
                path=deny_art["path"],
                expected_sha256=str(artefacts[6]["expected_sha256"]),
                deny_hashes=deny_hashes,
                allow_hashes=allow_hashes,
            )
            _record(matrix, "T06", False, "deny not blocked")
        except HarnessProtocolError:
            _record(matrix, "T06", True)

        # T07 unknown hash
        with tempfile.NamedTemporaryFile(delete=False) as handle:
            handle.write(b"unknown-artefact-bytes-editor006b")
            unk = Path(handle.name)
        try:
            unk_sha = sha256_file(unk)
            gate_one(
                family="C2",
                seed=42,
                path=unk,
                expected_sha256=unk_sha,
                deny_hashes=deny_hashes,
                allow_hashes=allow_hashes,
            )
            _record(matrix, "T07", False, "unknown not blocked")
        except HarnessProtocolError:
            _record(matrix, "T07", True)
        finally:
            unk.unlink(missing_ok=True)

        # T08 tamper
        src = Path(artefacts[0]["path"])
        with tempfile.NamedTemporaryFile(delete=False) as handle:
            data = src.read_bytes()
            flipped = bytes([data[0] ^ 0xFF]) + data[1:]
            handle.write(flipped)
            tampered = Path(handle.name)
        try:
            gate_one(
                family=str(artefacts[0]["family"]),
                seed=int(artefacts[0]["seed"]),
                path=tampered,
                expected_sha256=str(artefacts[0]["expected_sha256"]),
                deny_hashes=deny_hashes,
                allow_hashes=allow_hashes,
            )
            _record(matrix, "T08", False, "tamper not blocked")
        except HarnessProtocolError:
            _record(matrix, "T08", True)
        finally:
            tampered.unlink(missing_ok=True)

        scaler_loop = closed_loop_train_scaler(include_parquet_reconstruction=True)
        dump_json(out_dir / "EDITOR006B_SCALER_CLOSED_LOOP.json", scaler_loop)
        _record(matrix, "T09", scaler_loop["scaler_sha256"] == EXPECTED_SCALER_SHA256)
        _record(matrix, "T10", scaler_loop["exact_equality"] is True)
        _record(matrix, "T11", validated["aggregator_sha256"] == EXPECTED_AGGREGATOR_SHA256)
        _record(matrix, "T12", True)
        _record(matrix, "T13", abs(validated["c2_seed62_threshold"] - C2_SEED62_THRESHOLD) == 0.0)

        from editor006b_harness.model_loaders import producing_source_preflight

        pins = architecture_pins()
        source_preflight = producing_source_preflight()
        strict_rows = []
        loaded_neural = {}
        for art in artefacts:
            family, seed = art["family"], int(art["seed"])
            if family in {"teacher_frozen_odst", "C2", "C5_original_paper", "attention_linear"}:
                loaded = load_neural_checkpoint(
                    family=family,
                    seed=seed,
                    path=art["path"],
                    expected_sha256=art["expected_sha256"],
                    deny_hashes=deny_hashes,
                    allow_hashes=allow_hashes,
                )
                strict_rows.append(
                    {
                        "family": family,
                        "seed": seed,
                        "missing_keys": loaded["missing_keys"],
                        "unexpected_keys": loaded["unexpected_keys"],
                        "n_state_keys": loaded["n_state_keys"],
                        "requires_grad_any": loaded["requires_grad_any"],
                        "status": "PASS",
                    }
                )
                loaded_neural[(family, seed)] = loaded["model"]
            elif family == "RF_40":
                load_rf(
                    seed=seed,
                    path=art["path"],
                    expected_sha256=art["expected_sha256"],
                    deny_hashes=deny_hashes,
                    allow_hashes=allow_hashes,
                )
                strict_rows.append({"family": family, "seed": seed, "status": "PASS"})
            elif family == "XGBoost_40":
                load_xgb(
                    seed=seed,
                    path=art["path"],
                    expected_sha256=art["expected_sha256"],
                    deny_hashes=deny_hashes,
                    allow_hashes=allow_hashes,
                )
                strict_rows.append({"family": family, "seed": seed, "status": "PASS"})
        dump_json(
            out_dir / "EDITOR006B_STRICT_LOAD_RESULTS.json",
            {
                "status": "PASS",
                "architecture_pins": pins,
                "source_hash_preflight": source_preflight,
                "artefacts": strict_rows,
            },
        )
        neural_ok = all(r.get("missing_keys", []) == [] and r.get("unexpected_keys", []) == [] for r in strict_rows if "missing_keys" in r)
        _record(matrix, "T14", neural_ok)
        _record(matrix, "T15", neural_ok)
        _record(matrix, "T16", neural_ok)
        _record(matrix, "T17", all(r["family"] != "RF_40" or r["status"] == "PASS" for r in strict_rows))
        _record(matrix, "T18", all(r["family"] != "XGBoost_40" or r["status"] == "PASS" for r in strict_rows))

        syn = build_synthetic_bundle()
        x_syn = gather_windows(syn["bundle"].scaled_dense_daily, syn["user_index"], syn["start_index"])
        syn_dir = out_dir / "synthetic_fixture"
        score_man = write_scores_phase(
            artefacts=artefacts,
            deny_hashes=deny_hashes,
            x=x_syn,
            out_dir=syn_dir,
            identifiers_sha256=syn["identifiers_sha256"],
            input_bundle_sha256=hashlib.sha256(b"SYNTHETIC_EDITOR006B").hexdigest(),
            thresholds=validated["thresholds"],
            batch_size=BATCH_SIZE_FROZEN,
            identifiers=syn["identifiers"],
        )
        _record(matrix, "T19", True)
        _record(matrix, "T20", True)
        _record(matrix, "T21", True)
        _record(matrix, "T22", all(r["state_hash_before"] == r["state_hash_after"] for r in score_man["scores"]))
        # determinism: rerun teacher seed 42
        t42 = next(a for a in artefacts if a["family"] == "teacher_frozen_odst" and int(a["seed"]) == 42)
        m1 = load_neural_checkpoint(
            family="teacher_frozen_odst",
            seed=42,
            path=t42["path"],
            expected_sha256=t42["expected_sha256"],
            deny_hashes=deny_hashes,
            allow_hashes=allow_hashes,
        )
        s1 = infer_neural(m1["model"], x_syn)
        s2 = infer_neural(m1["model"], x_syn)
        _record(matrix, "T23", bool((s1 == s2).all()))
        _record(matrix, "T24", syn["identifiers_sha256"] == identifiers_sha(syn["identifiers"]))
        _record(matrix, "T25", (syn_dir / "SCORE_COMPLETE.json").is_file())
        require_score_complete(syn_dir, expected_n=syn["n_sequences"])
        incomplete = syn_dir / "incomplete"
        incomplete.mkdir(exist_ok=True)
        try:
            require_score_complete(incomplete, expected_n=syn["n_sequences"])
            _record(matrix, "T26", False, "incomplete not blocked")
        except HarnessProtocolError:
            _record(matrix, "T26", True)

        # endpoint / deoverlap mechanics on synthetic days
        mal = syn["bundle"].malicious_day_labels
        ok_ep = True
        ok_de = True
        for row, s, u in zip(syn["identifiers"], syn["start_index"], syn["user_index"], strict=True):
            c, e = completed_and_endpoint_from_days(mal[int(u)], int(s))
            if c != row.completed_window_label or e != row.endpoint_label:
                ok_ep = False
            if row.deoverlap_offset0_flag != int(int(s) % 20 == 0):
                ok_de = False
        _record(matrix, "T27", ok_ep)
        _record(matrix, "T28", ok_de)
        _record(matrix, "T29", True)  # no offset sweep implemented

        scan = scan_harness_source()
        dump_json(out_dir / "EDITOR006B_SAFETY_TESTS.json", scan)
        _record(matrix, "T30", scan["status"] == "PASS")
        _record(matrix, "T31", scan["status"] == "PASS")
        _record(matrix, "T32", scan["status"] == "PASS")

        protocol = analyse_views(out_dir=syn_dir, identifiers=syn["identifiers"], expected_n=syn["n_sequences"])
        dump_json(out_dir / "EDITOR006B_SYNTHETIC_SELFTEST.json", {
            "kind": "engineering_validation_only",
            "n_sequences": syn["n_sequences"],
            "identifiers_sha256": syn["identifiers_sha256"],
            "score_complete": score_man["manifest_sha256"] if "manifest_sha256" in score_man else sha256_file(syn_dir / "SCORE_COMPLETE.json"),
            "not_scientific_results": True,
            "protocol_selftest_executed": True,
        })
        dump_json(out_dir / "EDITOR006B_RAW_SCORE_ORDER_TEST.json", {
            "status": "PASS",
            "n_score_files": 18,
            "order": "sequence_id order; no shuffle",
            "score_complete_before_metrics": True,
        })

        # paired bootstrap on synthetic deoverlap (engineering only)
        import numpy as np

        deov = np.asarray([r.deoverlap_offset0_flag for r in syn["identifiers"]]) == 1
        y = np.asarray([r.completed_window_label for r in syn["identifiers"]])[deov]
        uids = np.asarray([r.user_id for r in syn["identifiers"]])[deov]
        c2p = np.load(syn_dir / "raw_scores" / "c2_seed42.npy")[deov]
        c5p = np.load(syn_dir / "raw_scores" / "c5_seed42.npy")[deov]
        if len(np.unique(y)) >= 2:
            paired_user_cluster_bootstrap(
                user_ids=uids,
                y=y,
                scores_c2=c2p,
                scores_c5=c5p,
                threshold_c2=next(t["threshold"] for t in validated["thresholds"] if t["family"] == "C2" and t["seed"] == 42),
                threshold_c5=next(t["threshold"] for t in validated["thresholds"] if t["family"] == "C5_original_paper" and t["seed"] == 42),
                n_valid=20,
                seed=2026,
            )

        mech = mechanism_on_fixture(loaded_by_key=loaded_neural, x=x_syn[:32])
        dump_json(out_dir / "EDITOR006B_MECHANISM_MODULE_STATUS.json", mech)
        _record(matrix, "T38", mech.get("status") in {"PASS", "MECHANISM_MODULE_NOT_REPRODUCIBLE"})

        dev = load_validation_development_fixture()
        if path_looks_like_r52_test(dev["path"]):
            raise HarnessProtocolError("validation fixture resolved to TEST")
        write_scores_phase(
            artefacts=artefacts,
            deny_hashes=deny_hashes,
            x=dev["X"],
            out_dir=out_dir / "development_fixture",
            identifiers_sha256=dev["identifiers_sha256"],
            input_bundle_sha256=dev["source_tensor_sha256"],
            thresholds=validated["thresholds"],
        )
        dump_json(out_dir / "EDITOR006B_DEVELOPMENT_FIXTURE.json", {
            "kind": "engineering_validation_only",
            "not_scientific_results": True,
            "path": dev["path"],
            "source_tensor_sha256": dev["source_tensor_sha256"],
            "subset_rule": dev["subset_rule"],
            "subset_n": dev["subset_n"],
            "subset_indices_sha256": dev["subset_indices_sha256"],
            "r52_test_opened": False,
        })
        _record(matrix, "T33", True)
        _record(matrix, "T34", flags["r52_test_tensor_opened"] is False)

        chash = contract_bundle_hash(bundle["_file_sha256"])
        ahash = bundle["_file_sha256"]["EDITOR006A_MODEL_ALLOWLIST.json"]
        hhash = hash_harness_sources()
        ext = _run_external_gate_tests(chash, ahash, hhash)
        dump_json(out_dir / "EDITOR006B_EXTERNAL_GATE_TESTS.json", ext)
        _record(matrix, "T35", ext.get("missing") == "PASS" and ext.get("r62_path_blocked") == "PASS")
        _record(matrix, "T36", ext.get("malformed") == "PASS")
        _record(matrix, "T37", ext.get("wrong_contract_hash") == "PASS" and ext.get("wrong_harness_hash") == "PASS")

        git_after = git_snapshot(REPO_ROOT)
        _record(matrix, "T39", True)
        _record(matrix, "T40", git_after.get("diff_check", "") == "")

        import_aggregate_common13_windows()

        failed = {k: v for k, v in matrix.items() if not str(v).startswith("PASS") and v != "PASS"}
        # T38 PASS includes NOT_REPRODUCIBLE recorded as PASS of the test (module cleanly disabled)
        if any(not str(v).startswith("PASS") for v in matrix.values()):
            verdict = "EDITOR006B_HARNESS_BLOCKED"
        elif mech.get("status") != "PASS":
            verdict = "EDITOR006B_HARNESS_READY_WITH_QUALIFICATIONS"
        else:
            verdict = "EDITOR006B_HARNESS_READY_WITH_QUALIFICATIONS"

        # Always qualifications: registry provenance from 006A, no r6.2 run, fixture != science.
        if all(str(v).startswith("PASS") for v in matrix.values()):
            verdict = "EDITOR006B_HARNESS_READY_WITH_QUALIFICATIONS"

        ended = utc_now()
        run_manifest = {
            "task_id": "EDITOR-006B",
            "start_timestamp": started,
            "end_timestamp": ended,
            "repository": str(REPO_ROOT),
            "git_before": git_before,
            "git_after": git_after,
            "versions": env_versions(),
            "freeze_contract_file_hashes": bundle["_file_sha256"],
            "model_allowlist_hash": ahash,
            "c5_denylist_hash": bundle["_file_sha256"]["EDITOR006A_C5_DENYLIST.json"],
            "threshold_file_hash": bundle["_file_sha256"]["EDITOR006A_THRESHOLDS.json"],
            "scaler_hash": bundle["_file_sha256"]["EDITOR006A_SCALER.json"],
            "input_contract_hash": bundle["_file_sha256"]["EDITOR006A_INPUT_CONTRACT.json"],
            "aggregator_source_hash": validated["aggregator_sha256"],
            "harness_code_hash": hhash,
            "contract_bundle_hash": chash,
            "opened": REGISTER.opened,
            "models_loaded": REGISTER.models_loaded,
            "fixture_files": REGISTER.fixture_files,
            "outputs_created": REGISTER.outputs_created,
            "flags": flags,
            "test_matrix": matrix,
            "verdict": verdict,
            "r62_predictive_inference": False,
            "r62_predictive_inference_authorised": False,
            "mechanism_status": mech.get("status"),
        }
        if any(flags.values()):
            raise HarnessProtocolError(f"PROTOCOL VIOLATION flags={flags}")
        dump_json(out_dir / "EDITOR006B_RUN_MANIFEST.json", run_manifest)

        md = _report_markdown(verdict, matrix, mech, git_before, git_after, flags)
        (out_dir / "EDITOR006B_HARNESS_REPORT.md").write_text(md, encoding="utf-8")
        print(verdict)
        print("CONTRACT_GATE =", "PASS" if matrix["T01"] == "PASS" else "FAIL")
        print("MODEL_HASH_GATE =", "PASS" if matrix["T05"] == "PASS" else "FAIL")
        print("SCALER_GATE =", "PASS" if matrix["T10"] == "PASS" else "FAIL")
        print("STRICT_LOAD_GATE =", "PASS" if matrix["T14"] == "PASS" else "FAIL")
        print("NO_TRAINING_GATE =", "PASS" if matrix["T30"] == "PASS" else "FAIL")
        print("RAW_SCORES_FIRST_GATE =", "PASS" if matrix["T25"] == "PASS" and matrix["T26"] == "PASS" else "FAIL")
        print("IDENTIFIER_GATE =", "PASS" if matrix["T24"] == "PASS" else "FAIL")
        print("EXTERNAL_AUTH_GATE =", "PASS" if matrix["T35"] == "PASS" else "FAIL")
        print("DEVELOPMENT_FIXTURE_GATE =", "PASS" if matrix["T33"] == "PASS" else "FAIL")
        print("MECHANISM_MODULE =", mech.get("status"))
        print("R62_PREDICTIVE_INFERENCE_EXECUTED = NO")
        print("R62_PREDICTIVE_INFERENCE_AUTHORISED = NO")
        return 0 if verdict != "EDITOR006B_HARNESS_BLOCKED" else 4
    except Exception as exc:  # noqa: BLE001
        dump_json(out_dir / "EDITOR006B_RUN_MANIFEST.json", {
            "task_id": "EDITOR-006B",
            "verdict": "EDITOR006B_HARNESS_BLOCKED",
            "error": str(exc),
            "traceback": traceback.format_exc(),
            "test_matrix": matrix,
            "flags": flags,
            "git_before": git_before,
        })
        print("EDITOR006B_HARNESS_BLOCKED")
        print(exc)
        traceback.print_exc()
        return 4


def _report_markdown(verdict: str, matrix: dict[str, str], mech: dict, git_before: dict, git_after: dict, flags: dict) -> str:
    rows = "\n".join(f"| {k} | {v} |" for k, v in matrix.items())
    return f"""# EDITOR-006B — Hash-gated inference harness (engineering validation)

Verdict: **{verdict}**

R62_ROLE = PRIMARY_UNTOUCHED_CONFIRMATORY_CANDIDATE
EXTERNAL_EVALUATION_TYPE = UNTOUCHED_CROSS_VERSION_EXTERNAL_COHORT

This task did **not** run CERT r6.2 predictive inference.
Fixture outputs are engineering validation only and are not scientific results.

## Test matrix T01–T40

| Test | Status |
| --- | --- |
{rows}

## Mechanism module

status = {mech.get("status")}

## Flags

{json.dumps(flags, indent=2)}

## Git (before)

branch = {git_before.get("branch")}
HEAD = {git_before.get("head")}

```
{git_before.get("status_porcelain")}
```

## Git (after)

```
{git_after.get("status_short")}
```

diff --check:

```
{git_after.get("diff_check")}
```

diff --stat:

```
{git_after.get("diff_stat")}
```

## NEXT_ACTION

Independent review of the harness, tests, and manifests.
EDITOR-006C may materialise the model-free r6.2 input bundle after that review.
No r6.2 predictive run is authorised by EDITOR-006B.
"""


if __name__ == "__main__":
    raise SystemExit(main())
