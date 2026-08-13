"""EDITOR-006D1 H4/H5/H6/H7 failure-state, probability, and scenario tests.

Synthetic fixtures only. Does not score CERT r6.2.
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

from editor006b_harness.safety import HarnessProtocolError, N_FEATURES, T_WINDOW

RUNNER_PATH = ROOT / "scripts" / "run_editor006e_r62_one_pass.py"


def _load_runner():
    spec = importlib.util.spec_from_file_location("run_editor006e_r62_one_pass_d1c", RUNNER_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


R = _load_runner()


def _d1_auth(tmp_path: Path, **overrides) -> Path:
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
        "editor006d_runner_release_commit": R.EDITOR006D_REVIEWED_BASE_COMMIT,
    }
    payload.update(overrides)
    path = tmp_path / "auth.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _dummy_bundle():
    n_users, n_days, n_win = 4, 40, 8
    ui = np.repeat(np.arange(n_users, dtype=np.int32), 2)
    si = np.tile(np.array([0, 20], dtype=np.int32), n_users)
    return {
        "dense": np.zeros((n_users, n_days, N_FEATURES), dtype=np.float32),
        "window_index": np.stack([ui, si], axis=1),
        "completed": np.zeros(n_win, dtype=np.uint8),
        "endpoint": np.zeros(n_win, dtype=np.uint8),
        "deov": np.ones(n_win, dtype=np.uint8),
        "user_ids": np.array([f"U{i}" for i in range(n_users)]),
        "calendar": np.array([f"2010-01-{d:02d}" for d in range(1, n_days + 1)]),
        "official_flags": np.array([1, 0, 1, 0], dtype=np.uint8),
        "official_incidents": np.array(["r6.2-1", "", "r6.2-2", ""]),
        "window_bits": np.zeros(n_win, dtype=np.uint8),
        "endpoint_bits": np.zeros(n_win, dtype=np.uint8),
    }


def test_d6_failure_before_bundle_open_reports_no(tmp_path: Path):
    spy = MagicMock()
    state = R.ExecutionAuditState()
    with pytest.raises(HarnessProtocolError, match="wrong external_runner"):
        R.execute_external_one_pass(
            auth_path=_d1_auth(tmp_path, external_runner_sha256="cd" * 32),
            output_dir=tmp_path / "out",
            bundle_dir=tmp_path / "bundle",
            final_manifest_path=R.FINAL_MANIFEST_DEFAULT,
            open_bundle_fn=spy,
            audit=state,
        )
    spy.assert_not_called()
    assert state.bundle_opened_report() == "NO"
    assert state.predictive_execution_report() == "NO"
    flags = state.as_flags()
    assert flags["R62_BUNDLE_OPENED_FOR_INFERENCE"] == "NO"
    assert flags["R62_PREDICTIVE_INFERENCE_EXECUTED"] == "NO"


def test_d6_identity_mismatch_still_reports_bundle_not_opened(tmp_path: Path):
    names = [
        row["filename"]
        for row in json.loads(R.FINAL_MANIFEST_DEFAULT.read_text(encoding="utf-8"))[
            "component_files"
        ]
    ]
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    for name in names:
        (bundle / name).write_bytes(b"not-the-real-bytes")
    spy = MagicMock()
    state = R.ExecutionAuditState()
    with pytest.raises(HarnessProtocolError, match="BUNDLE_COMPONENT_IDENTITY_MISMATCH"):
        R.execute_external_one_pass(
            auth_path=_d1_auth(tmp_path),
            output_dir=tmp_path / "out",
            bundle_dir=bundle,
            final_manifest_path=R.FINAL_MANIFEST_DEFAULT,
            open_bundle_fn=spy,
            audit=state,
        )
    spy.assert_not_called()
    assert state.bundle_opened_report() == "NO"
    assert not (tmp_path / "out" / "EXECUTION_STARTED.json").exists()


def test_d7_failure_after_execution_started_does_not_report_predictive_no(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr(
        R,
        "verify_bundle_component_identity",
        lambda *_a, **_k: {"status": "PASS", "n_components": 13, "components": []},
    )

    def fail_scores(**_kwargs):
        raise RuntimeError("injected after EXECUTION_STARTED")

    monkeypatch.setattr(R, "write_scores_phase_streaming", fail_scores)
    dummy = _dummy_bundle()
    opener = MagicMock(return_value=dummy)
    state = R.ExecutionAuditState()
    out = tmp_path / "out"
    with pytest.raises(RuntimeError, match="injected after EXECUTION_STARTED"):
        R.execute_external_one_pass(
            auth_path=_d1_auth(tmp_path),
            output_dir=out,
            bundle_dir=tmp_path / "bundle",
            final_manifest_path=R.FINAL_MANIFEST_DEFAULT,
            open_bundle_fn=opener,
            audit=state,
            skip_r62_geometry=True,
        )
    opener.assert_called_once()
    assert (out / "EXECUTION_STARTED.json").is_file()
    assert (out / "EXECUTION_ABORTED.json").is_file()
    assert state.execution_started is True
    assert state.predictive_execution_report() == "STARTED_OR_PARTIAL"
    assert state.as_flags()["R62_PREDICTIVE_INFERENCE_EXECUTED"] != "NO"
    abort = json.loads((out / "EXECUTION_ABORTED.json").read_text(encoding="utf-8"))
    assert abort["state_flags"]["R62_PREDICTIVE_INFERENCE_EXECUTED"] != "NO"
    assert abort["automatic_rerun"] is False
    assert abort["outputs_deleted"] is False
    assert "EXECUTION_STARTED.json" in abort["files_already_produced"]


def test_d6_cli_identity_preflight_failure_prints_no(tmp_path: Path, capsys):
    auth = _d1_auth(tmp_path, predictive_external_run_authorised=False)
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
    captured = capsys.readouterr().out
    assert "R62_BUNDLE_OPENED_FOR_INFERENCE = NO" in captured
    assert "R62_PREDICTIVE_INFERENCE_EXECUTED = NO" in captured


def test_h6_missing_runner_commit_aborts_before_open(tmp_path: Path):
    spy = MagicMock()
    auth = _d1_auth(tmp_path)
    payload = json.loads(auth.read_text(encoding="utf-8"))
    del payload["editor006d_runner_release_commit"]
    auth.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(HarnessProtocolError, match="editor006d_runner_release_commit"):
        R.execute_external_one_pass(
            auth_path=auth,
            output_dir=tmp_path / "out",
            bundle_dir=tmp_path / "bundle",
            final_manifest_path=R.FINAL_MANIFEST_DEFAULT,
            open_bundle_fn=spy,
        )
    spy.assert_not_called()


def test_d9_probability_scale_computes_brier_and_log_loss():
    y = np.array([0, 1, 0, 1, 1], dtype=int)
    p = np.array([0.1, 0.9, 0.2, 0.8, 0.7], dtype=np.float64)
    extra = R.probability_extras(y, p)
    assert extra["probability_metric_status"] == "PROBABILITY_SCALE"
    assert extra["Brier"] is not None
    assert extra["log_loss"] is not None
    assert extra["Brier"] >= 0.0
    assert extra["log_loss"] >= 0.0


def test_d9_non_probability_does_not_produce_brier_or_log_loss():
    y = np.array([0, 1, 0, 1], dtype=int)
    logits = np.array([-2.0, 3.5, 0.2, 4.0], dtype=np.float64)
    extra = R.probability_extras(y, logits)
    assert extra["probability_metric_status"] == "NOT_PROBABILITY_SCALE"
    assert extra["Brier"] is None
    assert extra["log_loss"] is None
    src = RUNNER_PATH.read_text(encoding="utf-8")
    body = src[src.index("def probability_extras") : src.index("def assert_output_dir_ready")]
    assert "expit" not in body
    assert "sigmoid" not in body.lower()


def test_d9_non_finite_is_not_probability_scale():
    y = np.array([0, 1], dtype=int)
    scores = np.array([0.2, np.nan], dtype=np.float64)
    extra = R.probability_extras(y, scores)
    assert extra["probability_metric_status"] == "NOT_PROBABILITY_SCALE"
    assert extra["Brier"] is None
    assert extra["log_loss"] is None


def test_d10_scenario_summary_preserves_exactly_five_identities():
    n = 12
    completed = np.array([1, 1, 1, 1, 1, 0, 0, 0, 1, 0, 1, 0], dtype=int)
    deov = np.array([1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 1, 1], dtype=np.uint8)
    window_bits = np.array([1, 2, 4, 8, 16, 1, 0, 3, 1, 0, 16, 0], dtype=np.uint8)
    user_index = np.array([0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 0, 1], dtype=int)
    official_flags = np.array([1, 1, 1, 0, 0], dtype=int)
    scores_by_key = {}
    thresholds = []
    rng = np.random.default_rng(0)
    for family in ("C2", "C5_original_paper"):
        for seed in (42, 52, 62):
            scores_by_key[(family, seed)] = rng.random(n)
            thresholds.append({"family": family, "seed": seed, "threshold": 0.5})
    summary = R.scenario_deoverlap_summary(
        completed=completed,
        deov=deov,
        window_bits=window_bits,
        user_index=user_index,
        official_flags=official_flags,
        scores_by_key=scores_by_key,
        thresholds=thresholds,
    )
    assert summary["kind"] == "descriptive_only"
    assert summary["no_hypothesis_test"] is True
    assert summary["n_scenario_identities"] == 5
    assert summary["scenario_identities"] == ["r6.2-1", "r6.2-2", "r6.2-3", "r6.2-4", "r6.2-5"]
    assert summary["effective_malicious_cluster_count"] == 5
    assert "Five official insider–incident clusters" in summary["frozen_wording"]
    assert summary["contextual_users_are_not_additional_incidents"] is True
    for family in ("C2", "C5_original_paper"):
        for seed in (42, 52, 62):
            scenarios = summary["per_family_seed"][family][seed]
            assert set(scenarios) == {f"r6.2-{i}" for i in range(1, 6)}
            for rec in scenarios.values():
                if rec["n_positive_deoverlap_windows"] == 0:
                    assert rec["recall"] is None
                else:
                    assert 0.0 <= rec["recall"] <= 1.0


def test_d10_scenario_identities_cannot_be_expanded():
    assert tuple(R.SCENARIO_IDS) == (1, 2, 3, 4, 5)
    assert T_WINDOW == 20
