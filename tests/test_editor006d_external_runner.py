"""EDITOR-006D tests for the CERT r6.2 one-pass external runner.

Never opens the derived r6.2 bundle for inference. Never writes a true
committed authorisation. Synthetic fixtures and hash-only preflight only.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from editor006b_harness.contracts import load_freeze_bundle, validate_contracts
from editor006b_harness.hash_gate import gate_one, preflight_all_eighteen
from editor006b_harness.input_bundle import DenseDailyWindowProvider, build_synthetic_bundle
from editor006b_harness.mechanism import STATUS_DISABLED, mechanism_registry
from editor006b_harness.safety import (
    C2_SEED62_THRESHOLD,
    HarnessProtocolError,
    N_FEATURES,
    T_WINDOW,
    hash_harness_sources,
)
from editor006b_harness.scoring import stream_scores_from_provider, write_scores_phase

RUNNER_PATH = ROOT / "scripts" / "run_editor006e_r62_one_pass.py"


def _load_runner():
    spec = importlib.util.spec_from_file_location("run_editor006e_r62_one_pass", RUNNER_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


R = _load_runner()


def _true_auth_payload(**overrides):
    payload = {
        "task_id": R.TASK_ID_FUTURE,
        "dataset_id": R.DATASET_ID,
        "input_bundle_manifest_sha256": R.FINAL_RELEASE_MANIFEST_SHA256,
        "contract_bundle_sha256": R.CONTRACT_BUNDLE_SHA256,
        "harness_code_sha256": R.HARNESS_CODE_SHA256,
        "model_allowlist_sha256": R.MODEL_ALLOWLIST_SHA256,
        "authorised_timestamp": "2026-08-13T00:00:00Z",
        "predictive_external_run_authorised": True,
        "external_runner_sha256": R.compute_external_runner_sha256(),
        "harness_runner_sha256": R.HARNESS_RUNNER_SHA256,
        "editor006c_release_commit": R.EDITOR006C_RELEASE_COMMIT,
        "sequence_order_sha256": R.SEQUENCE_ORDER_SHA256,
        "scaler_sha256": R.SCALER_SHA256,
    }
    payload.update(overrides)
    return payload


def _write_auth(tmp_path: Path, **overrides) -> Path:
    path = tmp_path / "auth.json"
    path.write_text(json.dumps(_true_auth_payload(**overrides)), encoding="utf-8")
    return path


def test_wrong_manifest_hash_aborts_before_bundle_open(tmp_path: Path):
    spy = MagicMock()
    auth = _write_auth(tmp_path, input_bundle_manifest_sha256="ab" * 32)
    with pytest.raises(HarnessProtocolError, match="wrong input_bundle_manifest"):
        R.execute_external_one_pass(
            auth_path=auth,
            output_dir=tmp_path / "out",
            bundle_dir=tmp_path / "bundle",
            final_manifest_path=R.FINAL_MANIFEST_DEFAULT,
            open_bundle_fn=spy,
        )
    spy.assert_not_called()


def test_wrong_external_runner_hash_aborts(tmp_path: Path):
    spy = MagicMock()
    auth = _write_auth(tmp_path, external_runner_sha256="cd" * 32)
    with pytest.raises(HarnessProtocolError, match="wrong external_runner"):
        R.execute_external_one_pass(
            auth_path=auth,
            output_dir=tmp_path / "out",
            bundle_dir=tmp_path / "bundle",
            final_manifest_path=R.FINAL_MANIFEST_DEFAULT,
            open_bundle_fn=spy,
        )
    spy.assert_not_called()


def test_wrong_harness_hash_aborts(tmp_path: Path):
    spy = MagicMock()
    auth = _write_auth(tmp_path, harness_code_sha256="ef" * 32)
    with pytest.raises(HarnessProtocolError, match="wrong harness"):
        R.execute_external_one_pass(
            auth_path=auth,
            output_dir=tmp_path / "out",
            bundle_dir=tmp_path / "bundle",
            final_manifest_path=R.FINAL_MANIFEST_DEFAULT,
            open_bundle_fn=spy,
        )
    spy.assert_not_called()


def test_wrong_sequence_order_hash_aborts(tmp_path: Path):
    spy = MagicMock()
    auth = _write_auth(tmp_path, sequence_order_sha256="11" * 32)
    with pytest.raises(HarnessProtocolError, match="wrong sequence_order"):
        R.execute_external_one_pass(
            auth_path=auth,
            output_dir=tmp_path / "out",
            bundle_dir=tmp_path / "bundle",
            final_manifest_path=R.FINAL_MANIFEST_DEFAULT,
            open_bundle_fn=spy,
        )
    spy.assert_not_called()


def test_wrong_scaler_hash_aborts(tmp_path: Path):
    spy = MagicMock()
    auth = _write_auth(tmp_path, scaler_sha256="22" * 32)
    with pytest.raises(HarnessProtocolError, match="wrong scaler"):
        R.execute_external_one_pass(
            auth_path=auth,
            output_dir=tmp_path / "out",
            bundle_dir=tmp_path / "bundle",
            final_manifest_path=R.FINAL_MANIFEST_DEFAULT,
            open_bundle_fn=spy,
        )
    spy.assert_not_called()


def test_false_authorisation_aborts(tmp_path: Path):
    spy = MagicMock()
    auth = _write_auth(tmp_path, predictive_external_run_authorised=False)
    with pytest.raises(HarnessProtocolError, match="not true"):
        R.execute_external_one_pass(
            auth_path=auth,
            output_dir=tmp_path / "out",
            bundle_dir=tmp_path / "bundle",
            final_manifest_path=R.FINAL_MANIFEST_DEFAULT,
            open_bundle_fn=spy,
        )
    spy.assert_not_called()


def test_wrong_task_or_dataset_aborts(tmp_path: Path):
    spy = MagicMock()
    with pytest.raises(HarnessProtocolError, match="wrong task_id"):
        R.execute_external_one_pass(
            auth_path=_write_auth(tmp_path, task_id="EDITOR-006D"),
            output_dir=tmp_path / "out",
            bundle_dir=tmp_path / "bundle",
            final_manifest_path=R.FINAL_MANIFEST_DEFAULT,
            open_bundle_fn=spy,
        )
    spy.assert_not_called()
    with pytest.raises(HarnessProtocolError, match="wrong dataset"):
        R.execute_external_one_pass(
            auth_path=_write_auth(tmp_path, dataset_id="CERT r5.2"),
            output_dir=tmp_path / "out",
            bundle_dir=tmp_path / "bundle",
            final_manifest_path=R.FINAL_MANIFEST_DEFAULT,
            open_bundle_fn=spy,
        )
    spy.assert_not_called()


def test_output_directory_nonempty_aborts(tmp_path: Path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "stale.txt").write_text("nope", encoding="utf-8")
    spy = MagicMock()
    with pytest.raises(HarnessProtocolError, match="not empty"):
        R.execute_external_one_pass(
            auth_path=_write_auth(tmp_path),
            output_dir=out,
            bundle_dir=tmp_path / "bundle",
            final_manifest_path=R.FINAL_MANIFEST_DEFAULT,
            open_bundle_fn=spy,
        )
    spy.assert_not_called()


def test_execution_started_already_present_aborts(tmp_path: Path):
    out = tmp_path / "empty"
    out.mkdir()
    R.assert_output_dir_ready(out)
    started = R.write_execution_started(
        out,
        authorisation_sha256="aa" * 32,
        external_runner_sha256=R.compute_external_runner_sha256(),
        final_release_manifest_sha256=R.FINAL_RELEASE_MANIFEST_SHA256,
    )
    assert started.is_file()
    with pytest.raises(HarnessProtocolError, match="already exists"):
        R.write_execution_started(
            out,
            authorisation_sha256="aa" * 32,
            external_runner_sha256=R.compute_external_runner_sha256(),
            final_release_manifest_sha256=R.FINAL_RELEASE_MANIFEST_SHA256,
        )


def test_dev_array_external_scoring_rejected():
    with pytest.raises(HarnessProtocolError, match="development-array"):
        R.refuse_dev_array_scorer_for_external()
    src = RUNNER_PATH.read_text(encoding="utf-8")
    assert "write_scores_phase_streaming" in src
    assert "write_scores_phase_streaming" in src
    # The development-array function name must not be invoked.
    stripped = src.replace("write_scores_phase_streaming", "STREAMING")
    assert "write_scores_phase(" not in stripped


def test_streaming_path_selected_on_synthetic():
    syn = build_synthetic_bundle(n_users=6, n_days=50)
    dense = syn["bundle"].scaled_dense_daily
    n = syn["n_sequences"]
    provider = DenseDailyWindowProvider(
        dense, syn["user_index"], syn["start_index"], batch_size=8
    )
    scores = stream_scores_from_provider(
        provider=provider,
        score_fn=lambda b: 1.0 / (1.0 + np.exp(-b[:, 0, 0].astype(np.float64))),
        expected_n=n,
    )
    assert scores.shape == (n,)
    provider.assert_never_full_sequence_tensor()
    assert all(shape[0] <= 8 for shape in provider.batch_shapes)
    assert all(shape != (n, T_WINDOW, N_FEATURES) for shape in provider.batch_shapes)


def test_metrics_blocked_before_all_scores_complete(tmp_path: Path):
    with pytest.raises(HarnessProtocolError, match="ALL_SCORES_COMPLETE"):
        R.require_all_scores_complete(tmp_path)


def test_c5_denylist_and_frozen_thresholds_preserved():
    bundle = load_freeze_bundle()
    validated = validate_contracts(bundle)
    deny = set(validated["deny_hashes"])
    allow = {str(a["expected_sha256"]) for a in validated["artefacts"]}
    deny_art = bundle["EDITOR006A_C5_DENYLIST.json"]["artefacts"][0]
    with pytest.raises(HarnessProtocolError, match="deny-listed"):
        gate_one(
            family="C5_original_paper",
            seed=42,
            path=deny_art["path"],
            expected_sha256=validated["artefacts"][6]["expected_sha256"],
            deny_hashes=deny,
            allow_hashes=allow,
        )
    rows = preflight_all_eighteen(validated["artefacts"], deny)
    assert len(rows) == 18
    c2_62 = next(t for t in validated["thresholds"] if t["family"] == "C2" and int(t["seed"]) == 62)
    assert float(c2_62["threshold"]) == C2_SEED62_THRESHOLD
    families = {a["family"] for a in validated["artefacts"]}
    assert "C5_original_paper" in families
    assert len(validated["artefacts"]) == 18


def test_mechanism_disabled_metrics_remain_disabled():
    reg = mechanism_registry()
    unused = next(m for m in reg["metrics"] if m["metric_name"] == "unused_leaf_fraction")
    rho = next(m for m in reg["metrics"] if m["metric_name"] == "tree_contribution_rho")
    assert unused["status"] == STATUS_DISABLED
    assert rho["status"] == STATUS_DISABLED
    assert unused["paper_facing"] is False
    assert rho["paper_facing"] is False


def test_identity_preflight_false_auth_does_not_open_r62(tmp_path: Path):
    auth = _write_auth(tmp_path, predictive_external_run_authorised=False)
    rc = R.main(
        [
            "--mode",
            "identity-preflight",
            "--authorization",
            str(auth),
            "--output-dir",
            str(tmp_path / "out"),
        ]
    )
    assert rc == 2
    default_scores = R.OUTPUT_DIR_DEFAULT
    assert not default_scores.exists()


def test_cli_external_without_execute_flag_refuses_scoring(tmp_path: Path):
    auth = _write_auth(tmp_path)
    rc = R.main(
        [
            "--mode",
            "external",
            "--authorization",
            str(auth),
            "--output-dir",
            str(tmp_path / "out"),
        ]
    )
    assert rc == 2


def test_open_bundle_refused_without_authorisation(tmp_path: Path):
    with pytest.raises(HarnessProtocolError, match="without authorisation"):
        R.open_external_bundle(tmp_path / "bundle", authorised=False)


def test_harness_code_sha_matches_frozen():
    assert hash_harness_sources() == R.HARNESS_CODE_SHA256


def test_write_scores_phase_still_exists_for_fixtures_only():
    assert callable(write_scores_phase)
    with pytest.raises(HarnessProtocolError, match="development-array"):
        R.refuse_dev_array_scorer_for_external()
