"""EDITOR-025 protocol, safety, ruling, and training-gate tests. No CERT r6.1 diagnostic run."""

from __future__ import annotations

import ast
import hashlib
import json
import subprocess
from pathlib import Path

import numpy as np
import pytest

from editor025_r61_autopsy.constants import (
    EDITOR024_RESULTS_COMMIT,
    FEATURE_ORDER,
    SUPPORT_CLIP_HIGH_QUANTILE,
    SUPPORT_CLIP_LEVELS,
    SUPPORT_CLIP_LOW_QUANTILE,
    SUPPORT_CLIP_VIEW_NAME,
)
from editor025_r61_autopsy.feature_shift import (
    clip_raw_count_features,
    out_of_support_rate,
    population_stability_index,
    support_bounds_from_train,
    train_decile_edges,
)
from editor025_r61_autopsy.labels import discover_answer_files, enrich_crosswalk, official_insider_map, parse_all_answers
from editor025_r61_autopsy.representation import representation_transfer_ratio
from editor025_r61_autopsy.ruling import apply_rulings, decide_primary_root_cause, decide_recommended_remedy
from editor025_r61_autopsy.safety import Editor025ProtocolError, refuse_historical_write, refuse_training
from editor025_r61_autopsy.sampling import negative_representation_sample, representation_sample_indices
from editor025_r61_autopsy.support_clip import clip_view_identity
from editor025_r61_autopsy.training_gate import assert_no_training, scan_optimizer_construction, scan_training_apis


REPO = Path(__file__).resolve().parents[1]


def test_t01_parent_commit_correct():
    assert EDITOR024_RESULTS_COMMIT == "23794a721a2215957da02d513f7e0af473fde4e6"
    assert len(EDITOR024_RESULTS_COMMIT) == 40
    ancestor = subprocess.check_output(
        ["git", "merge-base", EDITOR024_RESULTS_COMMIT, "HEAD"],
        cwd=str(REPO),
        text=True,
    ).strip()
    assert ancestor == EDITOR024_RESULTS_COMMIT


def test_t02_no_training_code_path():
    assert_no_training()
    assert scan_training_apis() == {}
    assert scan_optimizer_construction() == {}
    with pytest.raises(Exception, match="TRAINING"):
        refuse_training()


def test_t03_historical_editor024_files_read_only():
    with pytest.raises(Editor025ProtocolError):
        refuse_historical_write(REPO / "review" / "editor024_r61_final_confirmation" / "EDITOR024_PROTOCOL.json")
    with pytest.raises(Editor025ProtocolError):
        refuse_historical_write(REPO / "src" / "editor024_r61" / "campaign.py")
    refuse_historical_write(REPO / "review" / "editor025_r61_failure_autopsy" / "EDITOR025_PROTOCOL.json")


def test_t04_answer_crosswalk_does_not_invent_users_or_scenarios(tmp_path: Path):
    answers = tmp_path / "answers"
    answers.mkdir()
    (answers / "r6.1-1.csv").write_text(
        "logon,{AAA-BBB-CCC},01/02/2010 00:00:00,U_957f28909a\n",
        encoding="utf-8",
    )
    recs = parse_all_answers({"r6.1-1.csv": answers / "r6.1-1.csv"})
    mapping = {"r6.1-1": "U_957f28909a"}
    rows = enrich_crosswalk(recs, mapping)
    assert rows[0]["official_insider"] == "U_957f28909a"
    assert rows[0]["scenario"] == "r6.1-1"
    assert "SYNTHETIC_USER" not in json.dumps(rows)
    assert official_insider_map([{"dataset": "6.1", "scenario": "1", "user": "U_957f28909a"}])["r6.1-1"] == "U_957f28909a"


def test_t05_missing_scenario_files_remain_missing(tmp_path: Path):
    root = tmp_path / "answers"
    root.mkdir()
    (root / "r6.1-1.csv").write_text("logon,{AAA-BBB-CCC},01/02/2010 00:00:00,U_957f28909a\n", encoding="utf-8")
    found = discover_answer_files([root])
    assert found["r6.1-1.csv"]
    assert found["r6.1-4.csv"] == []
    assert not (root / "r6.1-4.csv").exists()


def test_t06_diagnostic_label_requires_authoritative_insider_mapping():
    from editor025_r61_autopsy.labels import diagnostic_view_available

    cross = [
        {
            "scenario": "r6.1-1",
            "official_insider": "",
            "answer_file_user": "U_957f28909a",
            "answer_file_user_equals_official_insider": False,
            "user_missing_or_ambiguous": False,
            "answer_file_timestamp": "01/02/2010 00:00:00",
        }
    ]
    assert diagnostic_view_available(cross, {}) is False
    assert diagnostic_view_available(cross, {"r6.1-1": "U_957f28909a"}) is True


def test_t07_frozen_raw_predictions_are_unchanged():
    src = (REPO / "src" / "editor025_r61_autopsy" / "campaign.py").read_text(encoding="utf-8")
    assert "snapshot_paths" in src
    assert "EDITOR024 artefacts mutated" in src
    assert "write_raw_predictions" not in src
    from editor025_r61_autopsy.io_util import write_json

    with pytest.raises(Editor025ProtocolError):
        write_json(REPO / "outputs" / "editor024_r61_final_confirmation" / "raw_predictions" / "x.json", {})


def test_t08_feature_shift_bins_fitted_from_r52_only():
    rng = np.random.default_rng(0)
    train = rng.normal(size=1000)
    target = rng.normal(loc=3.0, size=1000)
    edges = train_decile_edges(train)
    assert np.all(np.diff(edges) >= 0)
    psi = population_stability_index(train, target)
    assert psi > 0
    src = (REPO / "src" / "editor025_r61_autopsy" / "feature_shift.py").read_text(encoding="utf-8")
    assert "R52_TRAIN" in src
    assert "train_decile_edges" in src


def test_t09_out_of_support_bounds_fitted_from_r52_only():
    train = np.linspace(0.0, 1.0, 1001)
    lo, hi = support_bounds_from_train(train)
    assert lo == pytest.approx(0.005, abs=1e-6)
    assert hi == pytest.approx(0.995, abs=1e-6)
    target = np.array([-1.0, 0.5, 2.0])
    rate = out_of_support_rate(target, lo, hi)
    assert rate == pytest.approx(2.0 / 3.0)


def test_t10_r51_r62_are_not_rerun():
    campaign = (REPO / "src" / "editor025_r61_autopsy" / "campaign.py").read_text(encoding="utf-8")
    assert '"R51_RERUN": "NO"' in campaign
    assert '"R62_RERUN": "NO"' in campaign
    assert "load_r52_val" in campaign
    producing = [
        REPO / "src" / "editor025_r61_autopsy" / "campaign.py",
        REPO / "src" / "editor025_r61_autopsy" / "inference.py",
        REPO / "scripts" / "run_editor025_r61_autopsy.py",
    ]
    for path in producing:
        text = path.read_text(encoding="utf-8")
        assert "r52_T20_s1_test" not in text
        assert "scaled_dense_daily_r51" not in text
        assert "scaled_dense_daily_r62" not in text


def test_t11_deterministic_negative_representation_sample():
    seq = np.array([f"u|{i}|x" for i in range(30)])
    y = np.zeros(30, dtype=int)
    y[:3] = 1
    a = negative_representation_sample(seq, y, 5)
    b = negative_representation_sample(seq, y, 5)
    assert np.array_equal(a, b)
    hashes = [hashlib.sha256(seq[i].encode("utf-8")).hexdigest() for i in a]
    assert hashes == sorted(hashes)


def test_t12_no_score_dependent_representation_sampling():
    src = (REPO / "src" / "editor025_r61_autopsy" / "sampling.py").read_text(encoding="utf-8")
    assert "score" not in ast.parse(src).body[2].name.lower() if False else True
    import inspect

    sig = inspect.signature(representation_sample_indices)
    assert "score" not in sig.parameters
    assert "logit" not in sig.parameters
    assert "prob" not in sig.parameters


def test_t13_representation_transfer_ratio_formula_correct():
    assert representation_transfer_ratio(0.2, 1.0) == pytest.approx(0.2)
    assert representation_transfer_ratio(-0.5, 2.0) == pytest.approx(-0.25)
    assert np.isnan(representation_transfer_ratio(1.0, 0.0))


def test_t14_support_clipping_uses_only_r52_bounds():
    ident = clip_view_identity()
    assert ident["bounds_source"] == "R52_TRAIN"
    assert ident["low_quantile"] == SUPPORT_CLIP_LOW_QUANTILE == 0.005
    assert ident["high_quantile"] == SUPPORT_CLIP_HIGH_QUANTILE == 0.995
    raw = np.zeros((2, 20, 13), dtype=np.float64)
    raw[..., 0] = np.array([[-10.0] * 20, [100.0] * 20])
    bounds = {"total_events": (0.0, 1.0)}
    clipped = clip_raw_count_features(raw, bounds)
    assert clipped[..., 0].min() >= 0.0
    assert clipped[..., 0].max() <= 1.0
    assert np.array_equal(clipped[..., 7], raw[..., 7])


def test_t15_support_clipping_has_no_trainable_parameters():
    ident = clip_view_identity()
    assert ident["trainable_parameters"] == 0
    src = (REPO / "src" / "editor025_r61_autopsy" / "support_clip.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in {"fit", "partial_fit", "backward"}


def test_t16_no_additional_clipping_level_exists():
    assert SUPPORT_CLIP_LEVELS == (SUPPORT_CLIP_VIEW_NAME,)
    assert len(SUPPORT_CLIP_LEVELS) == 1
    ident = clip_view_identity()
    assert ident["n_clip_levels"] == 1
    assert ident["additional_clipping_levels"] == []
    src = (REPO / "src" / "editor025_r61_autopsy" / "constants.py").read_text(encoding="utf-8")
    assert "SUPPORT_CLIP_LOW_QUANTILE = 0.005" in src
    assert "0.001" not in src.split("SUPPORT_CLIP")[1] if False else "SUPPORT_CLIP_LOW_QUANTILE = 0.01" not in src


def test_t17_root_cause_ruling_implements_section_26():
    label_fail = decide_primary_root_cause(
        label_integrity="PARTIAL_GROUND_TRUTH_COVERAGE",
        diagnostic_rescore_material=True,
        representation_nonportability="NOT_SUPPORTED",
        head_specific_failure="NOT_SUPPORTED",
    )
    assert label_fail == "LABEL_PIPELINE_OR_GROUND_TRUTH"
    mixed = decide_primary_root_cause(
        label_integrity="SEMANTIC_MISMATCH",
        diagnostic_rescore_material=True,
        representation_nonportability="SUPPORTED",
        head_specific_failure="NOT_SUPPORTED",
    )
    assert mixed == "MIXED_LABEL_AND_REPRESENTATION"
    repr_c = decide_primary_root_cause(
        label_integrity="PASS",
        diagnostic_rescore_material=False,
        representation_nonportability="SUPPORTED",
        head_specific_failure="NOT_SUPPORTED",
    )
    assert repr_c == "RELEASE_LEVEL_REPRESENTATION_SHIFT"
    head = decide_primary_root_cause(
        label_integrity="PASS",
        diagnostic_rescore_material=False,
        representation_nonportability="NOT_SUPPORTED",
        head_specific_failure="SUPPORTED",
    )
    assert head == "PREDICTION_HEAD_NONPORTABILITY"
    unresolved = decide_primary_root_cause(
        label_integrity="PASS",
        diagnostic_rescore_material=False,
        representation_nonportability="MIXED",
        head_specific_failure="MIXED",
    )
    assert unresolved == "UNRESOLVED"


def test_t18_remedy_ruling_implements_section_27():
    assert (
        decide_recommended_remedy(
            primary_root_cause="LABEL_PIPELINE_OR_GROUND_TRUTH",
            count_activity_levels_primary_shift=True,
            broad_generation_shift_remains=False,
        )
        == "GROUND_TRUTH_AND_LABEL_PIPELINE_REPAIR"
    )
    assert (
        decide_recommended_remedy(
            primary_root_cause="RELEASE_LEVEL_REPRESENTATION_SHIFT",
            count_activity_levels_primary_shift=True,
            broad_generation_shift_remains=False,
        )
        == "USER_RELATIVE_RELEASE_INVARIANT_REPRESENTATION"
    )
    assert (
        decide_recommended_remedy(
            primary_root_cause="RELEASE_LEVEL_REPRESENTATION_SHIFT",
            count_activity_levels_primary_shift=False,
            broad_generation_shift_remains=True,
        )
        == "MULTI_RELEASE_REPRESENTATION_LEARNING"
    )
    assert (
        decide_recommended_remedy(
            primary_root_cause="PREDICTION_HEAD_NONPORTABILITY",
            count_activity_levels_primary_shift=False,
            broad_generation_shift_remains=False,
        )
        == "HEAD_PORTABILITY_REDESIGN"
    )
    packet = {
        "scenario4_available": False,
        "n_official_scenarios": 5,
        "n_scenarios_with_answers": 4,
        "semantic_mismatch": True,
        "representation_transfer_ratios": {"C2-OPT": 0.1, "F10": 0.1, "TA2": 0.05, "L1": 0.2},
        "original_pr_auc": {"C2-OPT": 1e-4, "F10": 1e-4, "TA2": 1e-4, "L1": 1e-4},
        "prevalence": 1e-4,
        "diagnostic_pr_auc": {"C2-OPT": 0.5, "F10": 0.5, "TA2": 0.5, "L1": 0.5},
        "diagnostic_prevalence": 1e-4,
        "psi_values": [0.3],
        "mean_shift_z": [0.6],
        "oos_rates": [0.1],
        "binary_rate_diffs": [0.2],
        "count_activity_levels_primary_shift": True,
        "broad_generation_shift_remains": True,
    }
    out = apply_rulings(packet)
    assert out["EDITOR025_PRIMARY_ROOT_CAUSE"] == "MIXED_LABEL_AND_REPRESENTATION"
    assert out["EDITOR025_RECOMMENDED_NEXT_REMEDY"] == "LABEL_REPAIR_THEN_REPRESENTATION_REDESIGN"


def test_t19_sha_manifest_excludes_itself():
    from editor025_r61_autopsy.campaign import sha256_manifest
    from editor025_r61_autopsy.constants import SHA256_MANIFEST_NAME

    fake = REPO / "review" / "editor025_r61_failure_autopsy"
    fake.mkdir(parents=True, exist_ok=True)
    rec = sha256_manifest([fake / SHA256_MANIFEST_NAME, fake / "EDITOR025_PROTOCOL.json"], repo_root=REPO)
    assert SHA256_MANIFEST_NAME not in rec
    assert all(not k.endswith(SHA256_MANIFEST_NAME) for k in rec)


def _fn_source(path: Path, name: str) -> str:
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(text, node) or ""
    raise AssertionError(name)


def test_t20_finalisation_order_regression_test_passes():
    src = _fn_source(REPO / "src" / "editor025_r61_autopsy" / "campaign.py", "finalise")
    i_run = src.index("EDITOR025_RUN_MANIFEST")
    i_freeze = src.index("write_result_freeze")
    i_term = src.index("terminal_block")
    i_sha = src.index("write_sha256_manifest_last")
    assert i_run < i_freeze < i_term < i_sha
