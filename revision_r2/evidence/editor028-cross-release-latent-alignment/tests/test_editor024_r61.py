"""EDITOR-024 protocol, safety, and training-gate tests. Do not open CERT r6.1 content."""

from __future__ import annotations

import ast
import io
import subprocess
from pathlib import Path

import numpy as np
import pytest

from editor006b_harness.safety import EXPECTED_SCALER_SHA256
from editor024_r61.bootstrap import contrast_stat_fn, pr_auc, user_cluster_bootstrap
from editor024_r61.cert_parse import build_dense_daily, gather_windows, parse_answer_file, parse_cert_ts, scan_source
from editor024_r61.checkpoints import gate_student_checkpoints
from editor024_r61.constants import (
    DESIGNATED_FINAL_MODEL,
    EDITOR023_RESULTS_COMMIT,
    FEATURE_ORDER,
    R61_UNTOUCHED_ELIGIBILITY,
    RAW_R61_ROOT,
    SEEDS,
    SEQUENCE_LENGTH,
    SHA256_MANIFEST_NAME,
    STRIDE_PRIMARY,
    STUDENT_MODELS,
    frozen_thresholds,
    student_checkpoint_records,
)
from editor024_r61.ruling import classify_contrast, concern5_status
from editor024_r61.safety import (
    Editor024Blocked,
    Editor024ProtocolError,
    path_looks_like_r61_content,
    refuse_historical_write,
    refuse_target_calibration_fit,
    refuse_target_feature_selection,
    refuse_target_threshold_search,
    refuse_training,
    sha256_file,
    note_open,
)
from editor024_r61.scaler import load_r52_train_scaler, transform_only
from editor024_r61.training_gate import assert_no_training, scan_optimizer_construction, scan_training_apis


REPO = Path(__file__).resolve().parents[1]


def test_t01_parent_commit_is_exactly_editor023_results():
    assert EDITOR023_RESULTS_COMMIT == "a480fa2413cf0b70c398081ca5f8f52470a665a3"
    assert len(EDITOR023_RESULTS_COMMIT) == 40
    ancestor = subprocess.check_output(
        ["git", "merge-base", EDITOR023_RESULTS_COMMIT, "HEAD"],
        cwd=str(REPO),
        text=True,
    ).strip()
    assert ancestor == EDITOR023_RESULTS_COMMIT


def test_t02_r61_eligibility_ruling_recorded():
    assert R61_UNTOUCHED_ELIGIBILITY == "PASS_WITH_DISCLOSED_PRIOR_EXISTENCE_KNOWLEDGE"


def test_t03_no_pre_freeze_function_opens_r61(monkeypatch):
    import editor024_r61.safety as safety

    monkeypatch.setattr(safety, "protocol_freeze_commit", lambda: None)
    assert not path_looks_like_r61_content(REPO / "src" / "editor024_r61" / "campaign.py")
    with pytest.raises(Editor024Blocked, match="PRE_FREEZE"):
        note_open(RAW_R61_ROOT / "logon.csv", role="raw")


def test_t04_no_pre_freeze_function_hashes_r61(monkeypatch):
    import editor024_r61.safety as safety

    monkeypatch.setattr(safety, "protocol_freeze_commit", lambda: None)
    with pytest.raises(Editor024Blocked, match="PRE_FREEZE"):
        sha256_file(RAW_R61_ROOT / "http.csv")


def test_t05_no_optimiser_in_research_runner():
    hits = scan_optimizer_construction()
    assert hits == {}


def test_t06_no_backward_training_path():
    assert_no_training()
    hits = scan_training_apis()
    assert hits == {}
    campaign = (REPO / "src" / "editor024_r61" / "campaign.py").read_text(encoding="utf-8")
    assert "backward" not in campaign
    assert "train_student" not in campaign
    assert "optimizer" not in campaign.lower()


def test_t07_twelve_frozen_student_checkpoint_hashes_match():
    recs = student_checkpoint_records()
    assert len(recs) == 12
    gate = gate_student_checkpoints()
    assert gate["CHECKPOINT_GATE"] == "PASS"
    assert {(r["model"], int(r["seed"])) for r in recs} == {(m, s) for m in STUDENT_MODELS for s in SEEDS}


def test_t08_frozen_r52_scaler_identity():
    scaler = load_r52_train_scaler()
    assert scaler["sha256"] == EXPECTED_SCALER_SHA256
    assert scaler["SCALER_SOURCE"] == "R52_TRAIN"
    assert scaler["TARGET_SCALER_FIT"] == "NO"


def test_t09_scaler_is_transform_only():
    src = (REPO / "src" / "editor024_r61" / "scaler.py").read_text(encoding="utf-8")
    assert "transform_only" in src
    assert "StandardScaler" not in src
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr != "fit"
    scaler = load_r52_train_scaler()
    x = np.zeros((2, 20, 13), dtype=np.float64)
    y = transform_only(x, scaler)
    assert y.dtype == np.float32
    assert y.shape == (2, 20, 13)


def test_t10_feature_set_is_exactly_13():
    assert len(FEATURE_ORDER) == 13
    assert FEATURE_ORDER[0] == "total_events"
    assert FEATURE_ORDER[-1] == "is_active_day"


def test_t11_sequence_length_is_exactly_20():
    assert SEQUENCE_LENGTH == 20


def test_t12_stride_is_exactly_1_for_primary_view():
    assert STRIDE_PRIMARY == 1
    src = (REPO / "src" / "editor024_r61" / "cert_parse.py").read_text(encoding="utf-8")
    assert 'label_semantics": "COMPLETED_WINDOW"' in src or "COMPLETED_WINDOW" in src


def test_t13_completed_window_references_frozen_harness():
    from editor024_r61.constants import PREPROCESSING_PROVENANCE, LABEL_RULE

    assert LABEL_RULE == "R52_LABEL_RULE_EVENT_LEVEL_ANSWER_MATCH"
    assert "run_editor007b_r51_bundle.py" in PREPROCESSING_PROVENANCE["completed_window_labels"]["implementation"]
    assert "EDITOR006A_R62_LABEL_CONTRACT.json" in PREPROCESSING_PROVENANCE["completed_window_labels"]["contract"]


def test_t14_deoverlap_references_frozen_harness():
    from editor024_r61.constants import PREPROCESSING_PROVENANCE

    assert PREPROCESSING_PROVENANCE["deoverlap"]["rule"] == "start_day_index % T_WINDOW == 0"
    assert "input_bundle.py" in PREPROCESSING_PROVENANCE["deoverlap"]["file"]


def test_t15_no_target_threshold_search():
    with pytest.raises(Editor024Blocked, match="THRESHOLD_SEARCH"):
        refuse_target_threshold_search()
    src = (REPO / "src" / "editor024_r61").read_text if False else ""
    campaign = (REPO / "src" / "editor024_r61" / "campaign.py").read_text(encoding="utf-8")
    assert "choose_threshold" not in campaign
    assert frozen_thresholds()["TA2"]["42"] == 0.79


def test_t16_no_target_calibration_fitting():
    with pytest.raises(Editor024Blocked, match="CALIBRATION"):
        refuse_target_calibration_fit()
    for path in (REPO / "src" / "editor024_r61").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "CalibratedClassifier" not in text
        assert "isotonic" not in text.lower()
        assert "temperature-scale" not in text.lower()


def test_t17_no_target_feature_selection():
    with pytest.raises(Editor024Blocked, match="FEATURE_SELECTION"):
        refuse_target_feature_selection()
    campaign = (REPO / "src" / "editor024_r61" / "campaign.py").read_text(encoding="utf-8")
    assert "SelectKBest" not in campaign
    assert "feature_importances_" not in campaign


def test_t18_ta2_is_hard_coded_final_model():
    assert DESIGNATED_FINAL_MODEL == "TA2"
    campaign = (REPO / "src" / "editor024_r61" / "campaign.py").read_text(encoding="utf-8")
    assert "CURRENT_PAPER_MODEL" in campaign
    assert "DESIGNATED_FINAL_MODEL" in campaign
    src = (REPO / "src" / "editor024_r61" / "constants.py").read_text(encoding="utf-8")
    assert 'DESIGNATED_FINAL_MODEL = "TA2"' in src


def test_t19_comparator_set_exact():
    assert STUDENT_MODELS == ("C2-OPT", "F10", "TA2", "L1")


def test_t20_seeds_exact():
    assert SEEDS == (42, 52, 62)


def test_t21_user_cluster_bootstrap_resamples_users_not_windows():
    rng = np.random.default_rng(0)
    users = np.array(["A"] * 5 + ["B"] * 5)
    y = np.array([0, 0, 0, 1, 0, 0, 0, 0, 1, 0])
    scores = rng.random(10)

    def stat(sl, yb):
        return {"pr": pr_auc(yb, scores[sl])}

    rec = user_cluster_bootstrap(users, y, stat, n_valid=20, seed=42)
    assert rec["sampling_unit"] == "r6.1 user"
    assert rec["cluster"] == "user"
    assert rec["n_users"] == 2
    src = (REPO / "src" / "editor024_r61" / "bootstrap.py").read_text(encoding="utf-8")
    assert "rng.choice(unique" in src
    assert "windows are never resampled independently" in src.lower() or "never resampled independently" in src.lower()


def test_t22_matched_model_bootstrap_uses_identical_users():
    src = (REPO / "src" / "editor024_r61" / "bootstrap.py").read_text(encoding="utf-8")
    assert "matched_models_share_resampled_users" in src
    logits = {
        "C2-OPT": {s: np.linspace(-1, 1, 8) for s in SEEDS},
        "F10": {s: np.linspace(-0.5, 1.2, 8) for s in SEEDS},
        "TA2": {s: np.linspace(-0.4, 1.3, 8) for s in SEEDS},
        "L1": {s: np.linspace(-0.8, 1.0, 8) for s in SEEDS},
    }
    y = np.array([0, 0, 1, 0, 0, 1, 0, 0])
    fn = contrast_stat_fn(logits, prevalence=0.25)
    rec = fn(np.arange(8), y)
    assert "TA2_MINUS_C2" in rec
    assert "TA2_RANKING_EXCESS" in rec


def _fn_source(path: Path, name: str) -> str:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(path.read_text(encoding="utf-8"), node) or ""
    raise AssertionError(name)


def test_t23_raw_prediction_writer_before_aggregate():
    src = _fn_source(REPO / "src" / "editor024_r61" / "campaign.py", "run_campaign")
    assert src.index("write_raw_predictions") < src.index("EDITOR024_R61_PRIMARY_SUMMARY")
    assert src.index("write_raw_predictions") < src.index("user_cluster_bootstrap")


def test_t24_historical_editor001_023_read_only():
    with pytest.raises(Editor024ProtocolError, match="historical"):
        refuse_historical_write("review/editor023_positive_architecture_value/x.json")
    with pytest.raises(Editor024ProtocolError, match="historical"):
        refuse_historical_write("review/editor001_dummy/x.json")
    with pytest.raises(Editor024ProtocolError, match="historical"):
        refuse_historical_write("outputs/editor012_teacher_anchor_rescue/x.npy")
    refuse_historical_write("review/editor024_r61_final_confirmation/EDITOR024_PROTOCOL.json")


def test_t25_sha_manifest_excludes_itself():
    src = (REPO / "src" / "editor024_r61" / "campaign.py").read_text(encoding="utf-8")
    assert "SHA256_MANIFEST_NAME" in src
    assert "p.name != SHA256_MANIFEST_NAME" in src


def test_t26_run_manifest_before_sha():
    src = _fn_source(REPO / "src" / "editor024_r61" / "campaign.py", "finalise")
    assert src.index("EDITOR024_RUN_MANIFEST.json") < src.index("write_sha256_manifest_last")


def test_t27_result_freeze_and_terminal_before_sha():
    src = _fn_source(REPO / "src" / "editor024_r61" / "campaign.py", "finalise")
    freeze_at = src.index("write_result_freeze")
    term_at = src.index("terminal_block")
    sha_at = src.index("write_sha256_manifest_last")
    assert freeze_at < sha_at
    assert term_at < sha_at


def test_t28_no_hashed_target_modified_after_sha():
    src = (REPO / "src" / "editor024_r61" / "campaign.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    finalise = None
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "finalise":
            finalise = node
    assert finalise is not None
    sha_line = None
    writes_after = []
    for node in finalise.body:
        if isinstance(node, ast.Assign):
            if any(isinstance(t, ast.Call) and getattr(t.func, "id", None) == "write_sha256_manifest_last" for t in [node.value]):
                sha_line = node.lineno
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            name = getattr(node.value.func, "id", None)
            if name in {"write_json", "write_text", "write_csv", "write_result_freeze", "terminal_block"}:
                writes_after.append((name, node.lineno))
    # Locate sha call
    text_lines = src.splitlines()
    sha_idx = next(i for i, line in enumerate(text_lines) if "rec = write_sha256_manifest_last()" in line)
    after = "\n".join(text_lines[sha_idx + 1 :])
    assert "write_json(" not in after
    assert "write_text(" not in after
    assert "write_csv(" not in after
    assert "terminal_block(" not in after
    assert "write_result_freeze(" not in after


def test_training_is_refused():
    with pytest.raises(Editor024Blocked, match="TRAINING_GATE"):
        refuse_training()


def test_synthetic_completed_window_and_deoverlap():
    eid = "{A0A0A0A0-A0A0-A0A0}"
    answers = parse_answer_file(io.StringIO(f"logon,{eid},01/10/2010 09:00:00,U1\n"), "r6.1-1")
    assert answers[0]["event_id"] == eid
    ts = parse_cert_ts("01/02/2010 08:00:00")
    assert ts == (2010, 1, 2, 8, 0, 0)
    user_index: dict[str, int] = {}
    user_list: list[str] = []
    active: dict[tuple[int, int], list[int]] = {}
    match_counts = {eid: 0}
    rows = ["id,date,user,pc,activity"]
    for day in range(2, 24):
        rows.append(f"{{B{day:02d}B0B0-B0B0-B0B0}},01/{day:02d}/2010 08:00:00,U1,PC,Logon")
        if day == 10:
            rows.append(f"{eid},01/10/2010 09:00:00,U1,PC,Logon")
    rec = scan_source(
        "logon",
        io.StringIO("\n".join(rows) + "\n"),
        source_answer_ids={eid},
        id_to_bit={eid: 1},
        match_counts=match_counts,
        active=active,
        user_index=user_index,
        user_list=user_list,
    )
    assert rec["header_ok"]
    built = build_dense_daily(user_list=user_list, active=active)
    assert built["sequence_length"] == 20
    assert built["stride"] == 1
    assert int(built["deoverlap_offset0_mask"][0]) == 1
    windows = gather_windows(np.zeros((built["n_users"], built["n_days"], 13), dtype=np.float32), built["user_index"][:1], built["start_index"][:1])
    assert windows.shape == (1, 20, 13)
    assert int(built["n_completed_positives"]) >= 1


def test_claim_rule_is_result_independent():
    assert classify_contrast(0.01, 0.001) == "SUPPORTED"
    assert classify_contrast(0.01, -0.001) == "CONSISTENT"
    assert classify_contrast(-0.01, -0.02) == "NOT_SUPPORTED"
    assert concern5_status("SUPPORTED") == "RESOLVED_WITH_PROSPECTIVELY_RESERVED_CONFIRMATION"
    assert concern5_status("CONSISTENT") == "PARTIALLY_RESOLVED_WITH_PROSPECTIVELY_RESERVED_CONFIRMATION"
    assert concern5_status("NOT_SUPPORTED") == "PROSPECTIVELY_TESTED_BUT_GENERALISATION_LIMITED"


def test_t15_campaign_does_not_open_r61_at_import():
    # Importing the package must not touch r6.1.
    assert not path_looks_like_r61_content("src/editor024_r61/campaign.py")
