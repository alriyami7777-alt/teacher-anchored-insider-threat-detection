"""EDITOR-007B tests. Does not score r5.1. Does not rerun r6.2. No r5.2 TEST."""
from __future__ import annotations

import hashlib
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

from editor006b_harness.cli import validate_external_authorization  # noqa: E402
from editor006b_harness.mechanism import STATUS_DISABLED, mechanism_registry  # noqa: E402
from editor006b_harness.safety import (  # noqa: E402
    COMMON_13_FEATURES,
    EXPECTED_SCALER_SHA256,
    HarnessProtocolError,
    sha256_file,
)

REVIEW = ROOT / "review" / "editor007b_r51_secondary_stress"
BUNDLE = Path(r"C:\PhD\06_Datasets\derived\teacher_anchored_r51_editor007b_bundle")
BUILDER = ROOT / "scripts" / "run_editor007b_r51_bundle.py"
RUNNER = ROOT / "scripts" / "run_editor007c_r51_secondary_stress.py"
RUNNER_006E = ROOT / "scripts" / "run_editor006e_r62_one_pass.py"
ADJ_JSON = REVIEW / "EDITOR007B_007A_ADJUDICATION_FREEZE.json"
ADJ_MD = REVIEW / "EDITOR007B_007A_ADJUDICATION_FREEZE.md"
FALSE_AUTH = REVIEW / "EDITOR007B_R51_AUTH_TEMPLATE_FALSE.json"
COUNT_JSON = REVIEW / "EDITOR007B_R51_COUNT_VALIDATION.json"
META_JSON = REVIEW / "EDITOR007B_R51_METADATA_VALIDATION.json"
MANIFEST = REVIEW / "EDITOR007B_R51_BUNDLE_MANIFEST.json"
COMPONENTS = REVIEW / "EDITOR007B_R51_BUNDLE_COMPONENTS.json"
FEATURE_JSON = REVIEW / "EDITOR007B_R51_FEATURE_PROFILE.json"
FEATURE_CSV = REVIEW / "EDITOR007B_R51_FEATURE_PROFILE.csv"

OFFICIAL = ["JTC1885", "LBE0376", "BGC0686", "JAK0783"]
CONTEXTUAL = [
    "ACB0270", "DKB0259", "EHW0689", "GJB0268", "HCW0681", "HRS0274",
    "KSC0148", "LHO0687", "MAH0683", "RNW0269", "SDP0271", "SKR0266", "UNK0265",
]


def _load_runner():
    spec = importlib.util.spec_from_file_location("run_editor007c_r51_secondary_stress", RUNNER)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_b01_adjudication_preserves_automated_gate_failure_and_independent_override():
    payload = _json(ADJ_JSON)
    text = ADJ_MD.read_text(encoding="utf-8")
    assert payload["automated_protocol_gate"]["status"] == "FAIL_EXACT_NUMERICAL_IDENTITY"
    assert payload["automated_protocol_gate"]["decision"] == (
        "EDITOR007A_R62_INTERPRETATION_BLOCKED_MECHANICAL_FAILURE"
    )
    assert payload["independent_scientific_adjudication"]["status"] == (
        "SCIENTIFIC_PARITY_WITH_NUMERICAL_NONIDENTITY"
    )
    assert payload["frozen_ruling"] == "EDITOR007A_R_SCIENTIFIC_PARITY_WITH_NUMERICAL_NONIDENTITY"
    assert payload["scientific_ruling"]["MECHANICAL_CAUSE_CAPABLE_OF_EXPLAINING_R62_COLLAPSE"] == "NO"
    assert payload["scientific_ruling"]["R62_INTERPRETATION_MAY_REOPEN"] == "YES"
    assert payload["scientific_ruling"]["R51_SECONDARY_STRESS_WARRANTED"] == "YES"
    assert payload["historical_automated_007a_record_preserved"] is True
    assert "FAIL_EXACT_NUMERICAL_IDENTITY" in text
    assert "SCIENTIFIC_PARITY_WITH_NUMERICAL_NONIDENTITY" in text
    assert "never failed" in text.lower() or "does **not** erase" in text


def test_b02_r51_label_rule_frozen():
    builder = BUILDER.read_text(encoding="utf-8")
    runner = RUNNER.read_text(encoding="utf-8")
    assert "R52_LABEL_RULE_EVENT_LEVEL_ANSWER_MATCH" in builder
    assert "R52_LABEL_RULE_EVENT_LEVEL_ANSWER_MATCH" in runner
    assert "official-insider-only" in builder
    man = _json(MANIFEST)
    assert man["label_rule"] == "R52_LABEL_RULE_EVENT_LEVEL_ANSWER_MATCH"
    assert man["dataset_role"] == "R51_SECONDARY_STRESS_ONLY"


def test_b03_351_of_351_answer_ids():
    counts = _json(COUNT_JSON)
    assert counts["assertions"]["answer_ids"]["observed"] == 351
    assert counts["assertions"]["matched_once"]["observed"] == 351
    assert counts["matching"]["MATCHED_ONCE"] == 351
    assert counts["matching"]["UNMATCHED"] == 0
    assert counts["matching"]["MULTIPLE"] == 0
    assert counts["matching"]["rule"] == "declared-source-scoped"


def test_b04_four_official_insiders():
    meta = _json(META_JSON)
    assert meta["official_insiders_true_count"] == 4
    counts = _json(COUNT_JSON)
    assert counts["assertions"]["official_insiders"]["observed"] == 4
    man = _json(MANIFEST)
    assert man["official_mapped_insiders"] == OFFICIAL


def test_b05_four_official_incidents():
    meta = _json(META_JSON)
    assert meta["official_incidents"] == ["r5.1-1", "r5.1-2", "r5.1-3", "r5.1-4"]
    assert meta["effective_malicious_cluster_count"] == 4
    assert meta["not_eight_independent_malicious_units"] is True
    counts = _json(COUNT_JSON)
    assert counts["assertions"]["official_incidents"]["observed"] == 4


def test_b06_seventeen_event_level_labelled_users():
    meta = _json(META_JSON)
    users = meta["event_level_labelled_users"]
    assert len(users) == 17
    assert set(OFFICIAL).issubset(set(users))
    assert meta["contextual_users"] == CONTEXTUAL


def test_b07_completed_positives_461():
    assert _json(COUNT_JSON)["assertions"]["completed_positives"]["observed"] == 461
    y = np.load(BUNDLE / "completed_window_labels.npy", mmap_mode="r")
    assert int(np.asarray(y).sum()) == 461


def test_b08_endpoint_positives_58():
    assert _json(COUNT_JSON)["assertions"]["endpoint_positives"]["observed"] == 58
    y = np.load(BUNDLE / "endpoint_labels.npy", mmap_mode="r")
    assert int(np.asarray(y).sum()) == 58


def test_b09_deoverlap_positives_24():
    assert _json(COUNT_JSON)["assertions"]["deoverlap_positives"]["observed"] == 24
    completed = np.load(BUNDLE / "completed_window_labels.npy", mmap_mode="r")
    deov = np.load(BUNDLE / "deoverlap_offset0_mask.npy", mmap_mode="r")
    assert int((np.asarray(completed) * np.asarray(deov)).sum()) == 24
    assert int(np.asarray(deov).sum()) == 50_000


def test_b10_frozen_scaler_transform_only():
    builder = BUILDER.read_text(encoding="utf-8")
    assert "transform only" in builder.lower() or "TRANSFORM only" in builder
    assert ".fit(" not in builder
    assert "scaler_fit_executed" in builder
    man = _json(MANIFEST)
    assert man["scaler_sha256"] == EXPECTED_SCALER_SHA256
    flags = _json(REVIEW / "EDITOR007B_R51_RUN_MANIFEST.json")["protocol_flags"]
    assert flags["scaler_fit_executed"] is False
    assert list(man["feature_order"]) == list(COMMON_13_FEATURES)


def test_b11_no_r51_model_loading():
    builder = BUILDER.read_text(encoding="utf-8")
    assert "load_neural_checkpoint" not in builder
    assert "joblib.load" not in builder
    assert "torch.load" not in builder
    effect = _json(REVIEW / "EDITOR007B_R51_EFFECT_REGISTER.json")
    assert effect["model_files_opened"] == []
    assert effect["predictive_inference_calls"] == []
    assert effect["model_deserialisation_calls"] == []
    man = _json(MANIFEST)
    assert man["predictive_models_loaded"] is False


def test_b12_no_r62_scoring():
    builder = BUILDER.read_text(encoding="utf-8")
    assert "teacher_anchored_r62_editor006e_scores" not in builder
    assert "write_scores_phase_streaming" not in builder
    effect = _json(REVIEW / "EDITOR007B_R51_EFFECT_REGISTER.json")
    assert effect["r62_score_files_opened"] == []
    assert effect["r62_predictive_inference_executed"] is False
    run = _json(REVIEW / "EDITOR007B_R51_RUN_MANIFEST.json")
    assert run["protocol_flags"]["r62_predictive_inference_executed"] is False


def test_b13_no_r52_test_access():
    builder = BUILDER.read_text(encoding="utf-8")
    assert "r52_t20_s1_test" not in builder
    run = _json(REVIEW / "EDITOR007B_R51_RUN_MANIFEST.json")
    assert run["protocol_flags"]["r52_test_opened"] is False
    effect = _json(REVIEW / "EDITOR007B_R51_EFFECT_REGISTER.json")
    assert effect["r52_test_files_opened"] == []


def test_b14_contextual_incident_ids_remain_null():
    meta = _json(META_JSON)
    assert meta["contextual_users_official_incident_null"] is True
    assert meta["invented_official_incident_ids_for_contextual_users"] is False
    users = np.load(BUNDLE / "user_ids.npy")
    flags = np.load(BUNDLE / "official_insider_flags.npy")
    codes = np.load(BUNDLE / "official_incident_codes.npy")
    for u in CONTEXTUAL:
        idx = int(np.where(users == u)[0][0])
        assert int(flags[idx]) == 0
        assert str(codes[idx]) == ""


def test_b15_scenario_metadata_preserved():
    man = _json(MANIFEST)
    assert man["scenario_bit_legend"] == {"bit_0": "r5.1-1", "bit_1": "r5.1-2", "bit_2": "r5.1-3", "bit_3": "r5.1-4"}
    for name in (
        "answer_scenario_day_bitmask.npy",
        "window_scenario_bitmask.npy",
        "endpoint_scenario_bitmask.npy",
        "official_insider_flags.npy",
        "official_incident_codes.npy",
    ):
        assert (BUNDLE / name).is_file()
    bits = np.load(BUNDLE / "answer_scenario_day_bitmask.npy", mmap_mode="r")
    assert int(bits.max()) <= 15


def test_b16_bundle_component_hashes_reproducible():
    comps = _json(COMPONENTS)["components"]
    assert len(comps) == 13
    for rec in comps:
        path = BUNDLE / rec["filename"]
        assert sha256_file(path) == rec["sha256"]
        assert int(path.stat().st_size) == int(rec["byte_size"])
    man = _json(MANIFEST)
    assert sha256_file(MANIFEST) == _json(REVIEW / "EDITOR007B_R51_RUN_MANIFEST.json")["bundle_manifest_sha256"]
    assert man["component_files"][0]["filename"] == "scaled_dense_daily.npy"


def test_b17_sequence_ordering_deterministic():
    man = _json(MANIFEST)
    users = np.load(BUNDLE / "user_ids.npy")
    calendar = np.load(BUNDLE / "calendar_dates.npy")
    wi = np.load(BUNDLE / "window_index.npy")
    assert wi.shape[0] == 996_000
    assert np.all(np.diff(wi[:, 0]) >= 0)
    n_users = 2000
    n_starts = 498
    expected_ui = np.repeat(np.arange(n_users, dtype=wi.dtype), n_starts)
    expected_si = np.tile(np.arange(n_starts, dtype=wi.dtype), n_users)
    assert np.array_equal(wi[:, 0], expected_ui)
    assert np.array_equal(wi[:, 1], expected_si)
    digest = hashlib.sha256()
    cal_iso = [str(d) for d in calendar]
    for u in range(n_users):
        uid = str(users[u])
        for s in range(n_starts):
            digest.update(f"{uid}|{cal_iso[s]}|{cal_iso[s + 19]}\n".encode("utf-8"))
    assert digest.hexdigest() == man["sequence_order_sha256"]


def test_b18_runner_rejects_false_authorisation(tmp_path: Path):
    auth = _json(FALSE_AUTH)
    assert auth["task_id"] == "EDITOR-007C"
    assert auth["dataset_id"] == "CERT r5.1"
    assert auth["predictive_external_run_authorised"] is False
    assert auth.get("true_authorisation_created") is not True
    R = _load_runner()
    with pytest.raises(HarnessProtocolError, match="predictive_external_run_authorised is not true"):
        validate_external_authorization(
            FALSE_AUTH,
            expected_task_id="EDITOR-007C",
            expected_dataset_id="CERT r5.1",
            expected_input_bundle_manifest_sha256=auth["input_bundle_manifest_sha256"],
            expected_contract_bundle_sha256=auth["contract_bundle_sha256"],
            expected_harness_code_sha256=auth["harness_code_sha256"],
            expected_model_allowlist_sha256=auth["model_allowlist_sha256"],
        )
    rc = R.main(
        [
            "--mode",
            "identity-preflight",
            "--authorization",
            str(FALSE_AUTH),
            "--output-dir",
            str(tmp_path),
        ]
    )
    assert rc == 2


def test_b19_streaming_only_future_path():
    src = RUNNER.read_text(encoding="utf-8")
    assert "write_scores_phase_streaming" in src
    assert "DenseDailyWindowProvider" in src
    assert "refuse_dev_array_scorer_for_external" in src
    assert "assert_never_full_sequence_tensor" in BUILDER.read_text(encoding="utf-8")
    assert "no_full_N_20_13_tensor" in _json(MANIFEST)
    assert _json(MANIFEST)["no_full_N_20_13_tensor"] is True
    R = _load_runner()
    with pytest.raises(HarnessProtocolError, match="development-array scorer"):
        R.refuse_dev_array_scorer_for_external()


def test_b20_all_18_frozen_model_identities_required():
    src = RUNNER.read_text(encoding="utf-8")
    assert "preflight_all_eighteen" in src
    R = _load_runner()
    assert R.N_WINDOWS == 996_000
    assert "n_models" in src
    man = _json(MANIFEST)
    assert man["model_allowlist_sha256"] == "699c983d1ad98a5dcce7768447dcac4a44f5a5e8fed740b4c8378876efa52e5a"
    assert "18 frozen" in man["frozen_checkpoint_contract"]


def test_b21_no_new_threshold_or_calibration_path():
    builder = BUILDER.read_text(encoding="utf-8")
    runner = RUNNER.read_text(encoding="utf-8")
    for src in (builder, runner):
        assert "threshold_selection_executed" in src
        assert "calibration_fit_executed" in src
    assert "CalibratedClassifierCV" not in runner
    assert "precision_recall_curve" not in runner or "frozen threshold" in runner.lower()
    flags = _json(REVIEW / "EDITOR007B_R51_RUN_MANIFEST.json")["protocol_flags"]
    assert flags["threshold_selection_executed"] is False
    assert flags["calibration_fit_executed"] is False
    assert flags["model_selection_executed"] is False
    views = [v["name"] for v in _json(MANIFEST)["predeclared_views"]]
    assert views == ["COMPLETED_WINDOW", "ENDPOINT_PAST_ONLY", "DEOVERLAP_OFFSET0"]


def test_b22_unused_leaf_and_tree_rho_remain_disabled():
    registry = mechanism_registry()
    by_name = {m["metric_name"]: m for m in registry["metrics"]}
    assert by_name["unused_leaf_fraction"]["status"] == STATUS_DISABLED
    assert by_name["tree_contribution_rho"]["status"] == STATUS_DISABLED
    src = RUNNER.read_text(encoding="utf-8")
    assert "UNUSED_LEAF_METRIC_NOT_REPRODUCIBLE" in src
    assert "TREE_CONTRIBUTION_RHO_NOT_REPRODUCIBLE" in src
    disabled = _json(MANIFEST)["predeclared_metrics"]["mechanism_disabled"]
    assert "unused-leaf fraction" in disabled
    assert "tree-contribution rho" in disabled


def test_006e_runner_unmodified_bytes_still_present():
    assert RUNNER_006E.is_file()
    text = RUNNER_006E.read_text(encoding="utf-8")
    assert "EDITOR-006E" in text
    assert "CERT r6.2" in text


def test_false_auth_is_not_true_authorisation():
    auth = _json(FALSE_AUTH)
    assert auth["predictive_external_run_authorised"] is False
    flags = _json(REVIEW / "EDITOR007B_R51_RUN_MANIFEST.json")["protocol_flags"]
    assert flags["true_authorisation_created"] is False
    assert flags["r51_predictive_inference_executed"] is False


def test_feature_profile_complete():
    payload = _json(FEATURE_JSON)
    assert payload["predictive_models_loaded"] is False
    assert payload["predictive_interpretation"] is False
    assert len(payload["features"]) == 13
    names = [r["feature"] for r in payload["features"]]
    assert names == list(COMMON_13_FEATURES)
    csv_text = FEATURE_CSV.read_text(encoding="utf-8")
    header = csv_text.splitlines()[0]
    for col in ("mean", "sd", "q01", "q05", "q25", "q50", "q75", "q95", "q99",
                "fraction_abs_z_gt_3", "fraction_abs_z_gt_5", "fraction_abs_z_gt_10"):
        assert col in header
        assert payload["features"][0][col] is not None or col.startswith("fraction")
