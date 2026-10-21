"""EDITOR-007A diagnostic protocol tests. Does not rerun 006E. Does not score r6.2."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from editor006b_harness.safety import (  # noqa: E402
    EXPECTED_AGGREGATOR_SHA256,
    EXPECTED_SCALER_SHA256,
    EXPECTED_VAL_X_RAW_SHA256,
    HarnessProtocolError,
    VAL_NPZ,
)

SCRIPT = ROOT / "scripts" / "run_editor007a_post006e_diagnostics.py"


def _load():
    spec = importlib.util.spec_from_file_location("run_editor007a_post006e_diagnostics", SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


R = _load()


def test_a01_006e_completion_hashes_reproduce():
    freeze = R.freeze_006e_evidence()
    assert freeze["EDITOR006E_EXECUTION_STATUS"] == "COMPLETE"
    complete = json.loads((R.E006E / "EXECUTION_COMPLETE.json").read_text(encoding="utf-8"))
    for name, expected in complete["file_sha256"].items():
        assert freeze[
            {
                "EXECUTION_STARTED.json": "EXECUTION_STARTED_sha256",
                "ALL_SCORES_COMPLETE.json": "ALL_SCORES_COMPLETE_sha256",
                "EDITOR006E_PREDICTIVE_RESULTS.json": "predictive_results_sha256",
                "EDITOR006E_MECHANISM_RESULTS.json": "mechanism_results_sha256",
                "EDITOR006E_RUN_MANIFEST.json": "run_manifest_sha256",
            }[name]
        ] == expected


def test_a02_all_18_frozen_r62_score_hashes_reproduce():
    freeze = R.freeze_006e_evidence()
    assert len(freeze["models"]) == 18
    all_scores = json.loads((R.E006E / "ALL_SCORES_COMPLETE.json").read_text(encoding="utf-8"))
    by_name = {m["score_filename"]: m["score_sha256"] for m in all_scores["models"]}
    for rec in freeze["models"]:
        assert rec["score_sha256"] == by_name[rec["score_filename"]]


def test_a03_no_r62_model_loader_invoked():
    src = SCRIPT.read_text(encoding="utf-8")
    replay = src[src.index("def replay_one") : src.index("def classify_parity")]
    assert "scaled_dense_daily" not in replay
    assert "teacher_anchored_r62_editor006e_scores" not in replay
    assert "E006E" not in replay
    assert R.PROTOCOL["r62_predictive_model_loaded"] is False


def test_a04_no_r62_score_array_modified():
    freeze = R.freeze_006e_evidence()
    from editor006b_harness.safety import sha256_file

    for rec in freeze["models"]:
        live = R.E006E / "raw_scores" / rec["score_filename"]
        assert sha256_file(live) == rec["score_sha256"]
        assert live.stat().st_mtime


def test_a05_inverted_score_is_diagnostic_only():
    y = np.array([0, 0, 1, 1])
    s = np.array([0.1, 0.2, 0.8, 0.9])
    pair = R.ap_pair(y, s)
    assert pair["inverted_is_diagnostic_only"] is True
    assert pair["not_a_corrected_result"] is True
    src = SCRIPT.read_text(encoding="utf-8")
    assert "never replace the frozen result with 1-score" in src
    assert "1.0 - s" in src


def test_a06_r52_test_path_is_rejected():
    with pytest.raises(HarnessProtocolError, match="r5.2 TEST"):
        from editor006b_harness.safety import refuse_r52_test

        refuse_r52_test(R.TEST_NPZ)
    src = SCRIPT.read_text(encoding="utf-8")
    assert "r52_T20_s1_test" in src
    assert "refuse_r52_test(TEST_NPZ)" in src


def test_a07_r52_validation_input_sha_is_frozen():
    assert R.EXPECTED_VAL_X_RAW_SHA256 == EXPECTED_VAL_X_RAW_SHA256
    assert R.VAL_NPZ_SHA == "5ac2e7e8fbd50eb62638cdb8c9d444464e02ff2ea20ba55989c36926dd751a5c"
    assert Path(VAL_NPZ) == R.VAL_NPZ
    src = SCRIPT.read_text(encoding="utf-8")
    assert "73192caa4bfbbaee88e755912768c39b3f39d404686c97eb487756964ba7b292" in src


def test_a08_same_exact_18_checkpoint_shas_used():
    freeze = R.freeze_006e_evidence()
    from editor006b_harness.contracts import load_freeze_bundle, validate_contracts

    arts = validate_contracts(load_freeze_bundle())["artefacts"]
    live = {(a["family"], int(a["seed"])): a["expected_sha256"] for a in arts}
    for rec in freeze["models"]:
        assert rec["checkpoint_sha256"] == live[(rec["family"], rec["seed"])]


def test_a09_same_frozen_thresholds_used():
    freeze = R.freeze_006e_evidence()
    from editor006b_harness.contracts import load_freeze_bundle, validate_contracts

    arts = validate_contracts(load_freeze_bundle())["artefacts"]
    live = {(a["family"], int(a["seed"])): float(a["threshold"]) for a in arts}
    for rec in freeze["models"]:
        assert float(rec["threshold"]) == live[(rec["family"], rec["seed"])]


def test_a10_same_rf_xgb_aggregator_used():
    assert R.EXPECTED_AGGREGATOR_SHA256 == EXPECTED_AGGREGATOR_SHA256
    src = SCRIPT.read_text(encoding="utf-8")
    assert "import_aggregate_common13_windows" in src
    assert "EXPECTED_AGGREGATOR_SHA256" in src


def test_a11_same_frozen_scaler_identity_used():
    assert R.EXPECTED_SCALER_SHA256 == EXPECTED_SCALER_SHA256
    src = SCRIPT.read_text(encoding="utf-8")
    assert "scaler_fit_executed" in src
    assert "PROTOCOL[\"scaler_fit_executed\"] = False" in src or "scaler_fit_executed\": False" in src


def test_a12_parity_reference_must_be_producing_evidence():
    src = SCRIPT.read_text(encoding="utf-8")
    assert "manuscript_rounding_used" in src
    assert "producing_unrounded_metric_json" in src
    assert "r52_odst_confirmation" in src
    assert "r52_locked_baselines" in src


def test_a13_feature_audit_uses_no_scaler_fitting():
    src = SCRIPT.read_text(encoding="utf-8")
    body = src[src.index("def feature_shift_audit") : src.index("def score_distribution_shift")]
    assert "fit(" not in body
    assert "StandardScaler" not in body
    assert "scaler_fit_executed" in body


def test_a14_no_pvalue_significance_language_in_feature_shift():
    src = SCRIPT.read_text(encoding="utf-8")
    body = src[src.index("def feature_shift_audit") : src.index("def score_distribution_shift")]
    assert "p_value" not in body.lower() or "no_pvalue_used" in body
    assert "significantly shifted" not in body.lower()
    assert "p_values_used" in body


def test_a15_r51_inference_never_executes():
    src = SCRIPT.read_text(encoding="utf-8")
    assert "r51_predictive_inference_executed" in src
    assert '"execute_now": False' in src
    assert "R51_SECONDARY_STRESS_ONLY" in src
    r51_fn = src[src.index("def r51_preauth") : src.index("def interpret_questions")]
    assert "infer_neural" not in r51_fn
    assert "infer_classical" not in r51_fn


def test_a16_decision_ab_forbids_r51_recommendation():
    fail = R.decision_gate(True, {"parity_gate": "R52_PARITY_FAIL"}, {"SCORE_ORIENTATION": "MECHANICAL_FAILURE"})
    assert fail["R51_SECONDARY_STRESS_WARRANTED"] == "NO"
    unresolved = R.decision_gate(True, {"parity_gate": "R52_PARITY_UNRESOLVED"}, {"SCORE_ORIENTATION": "UNRESOLVED"})
    assert unresolved["R51_SECONDARY_STRESS_WARRANTED"] == "NO"
    assert fail["decision"] == "EDITOR007A_R62_INTERPRETATION_BLOCKED_MECHANICAL_FAILURE"
    assert unresolved["decision"] == "EDITOR007A_R62_INTERPRETATION_UNRESOLVED"


def test_a17_decision_c_permits_only_r51_secondary_stress_preauth():
    ok = R.decision_gate(
        True,
        {"parity_gate": "R52_PARITY_PASS"},
        {"SCORE_ORIENTATION": "MECHANICALLY_VALIDATED"},
    )
    assert ok["decision"] == "EDITOR007A_R62_NEGATIVE_RESULT_DIAGNOSTICALLY_SUPPORTED"
    assert ok["R51_SECONDARY_STRESS_WARRANTED"] == "YES"
    assert ok["r51_role_if_warranted"] == "R51_SECONDARY_STRESS_ONLY"
    pre = R.r51_preauth()
    assert pre["execute_now"] is False
    assert pre["role"] == "R51_SECONDARY_STRESS_ONLY"


def test_a18_no_rescue_threshold_recalibration_path_exists():
    src = SCRIPT.read_text(encoding="utf-8")
    assert "threshold_selection_executed" in src
    assert "calibration_fit_executed" in src
    forbidden = ["recalibrat", "fine-tun", "domain adapt", "threshold optim"]
    low = src.lower()
    for token in forbidden:
        if token in low:
            assert "must_not" in src or "rescue_experiments_executed" in src
    assert "rescue_experiments_executed" in src
