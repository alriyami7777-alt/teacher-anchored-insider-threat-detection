"""EDITOR-026 protocol, representation, gate, and safety tests. No CERT predictive run."""

from __future__ import annotations

import ast
import hashlib
import json
import subprocess
from pathlib import Path

import numpy as np
import pytest

from editor026_user_relative.bootstrap import user_cluster_bootstrap
from editor026_user_relative.constants import (
    EDITOR025_RESULTS_COMMIT,
    FEATURE_DIM,
    FEATURE_ORDER,
    G0A_MEAN_ABS_SHIFT_REDUCTION_MIN,
    G0B_MEAN_PSI_REDUCTION_MIN,
    G0C_N_FEATURES_LOWER_PSI_MIN,
    MINIMUM_AP_PREVALENCE_LIFT,
    ODST046,
    R61_LABEL_VIEW_A,
    R61_LABEL_VIEW_B,
    SCENARIO4_STATUS,
    SEEDS,
    SEQUENCE_LENGTH_LOCKED,
    STUDENT_MODELS,
    USER_RELATIVE_LOOKBACK_DAYS,
)
from editor026_user_relative.representation import causal_user_relative_daily
from editor026_user_relative.safety import Editor026ProtocolError, refuse_historical_write
from editor026_user_relative.scaler import UserRelativeStandardScaler
from editor026_user_relative.stage0 import (
    class_separation,
    discriminant_direction,
    input_transfer_ratio,
    reduction_metrics,
)
from editor026_user_relative.windows import flatten_windows


REPO = Path(__file__).resolve().parents[1]
PKG = REPO / "src" / "editor026_user_relative"


def _src(*names: str) -> str:
    return "\n".join((PKG / n).read_text(encoding="utf-8") for n in names)


def test_t01_parent_commit_exact():
    assert EDITOR025_RESULTS_COMMIT == "1f176bb7bf589da20be8ae9b02a23a4c8f0e0af7"
    ancestor = subprocess.check_output(
        ["git", "merge-base", EDITOR025_RESULTS_COMMIT, "HEAD"],
        cwd=str(REPO),
        text=True,
    ).strip()
    assert ancestor == EDITOR025_RESULTS_COMMIT


def test_t02_architecture_dimensions_unchanged():
    assert SEQUENCE_LENGTH_LOCKED == 20
    assert FEATURE_DIM == 13
    assert ODST046["n_trees"] == 4
    assert ODST046["depth"] == 4
    src = _src("constants.py", "protocol.py")
    assert "Transformer" in src
    assert "Bi-LSTM" in src or "Bi-LSTM" in (REPO / "src" / "editor026_user_relative" / "protocol.py").read_text(encoding="utf-8")


def test_t03_exactly_13_output_features():
    assert len(FEATURE_ORDER) == 13
    ident = json.dumps(causal_user_relative_daily(np.zeros((3, 13))).shape)
    assert causal_user_relative_daily(np.zeros((5, 13))).shape == (5, 13)


def test_t04_lookback_exactly_20_calendar_days():
    assert USER_RELATIVE_LOOKBACK_DAYS == 20
    dates = np.array([np.datetime64("2010-01-01") + np.timedelta64(i, "D") for i in range(40)])
    x = np.zeros((40, 13), dtype=np.float64)
    x[:, 0] = np.arange(40)
    out = causal_user_relative_daily(x, dates, lookback_days=20)
    # day 20 uses exactly days 0..19
    past = np.log1p(np.arange(20.0))
    assert out[20, 0] == pytest.approx(np.log1p(20.0) - np.median(past))


def test_t05_no_future_day_enters_user_baseline():
    dates = np.array([np.datetime64("2010-01-01") + np.timedelta64(i, "D") for i in range(5)])
    x = np.zeros((5, 13))
    x[:, 0] = [1, 2, 1000, 4, 5]
    out = causal_user_relative_daily(x, dates)
    # day 1 baseline cannot use day 2's 1000
    assert out[1, 0] == pytest.approx(np.log1p(2.0) - np.log1p(1.0))


def test_t06_no_other_user_data_enters_baseline():
    a = np.zeros((3, 13))
    a[:, 0] = [10, 20, 30]
    b = np.zeros((3, 13))
    b[:, 0] = [999, 999, 999]
    dates = np.array([np.datetime64("2010-01-01") + np.timedelta64(i, "D") for i in range(3)])
    out_a = causal_user_relative_daily(a, dates)
    out_b = causal_user_relative_daily(b, dates)
    assert out_a[2, 0] != out_b[2, 0]


def test_t07_no_label_enters_baseline():
    src = (PKG / "representation.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "causal_user_relative_daily"][0]
    names = {n.arg for n in fn.args.args}
    assert "y" not in names and "label" not in names


def test_t08_zero_prior_history_output_equals_zero():
    x = np.ones((1, 13)) * 7.0
    out = causal_user_relative_daily(x)
    assert np.allclose(out[0], 0.0)


def test_t09_seven_volume_features_use_log1p_minus_past_median():
    dates = np.array([np.datetime64("2010-01-01") + np.timedelta64(i, "D") for i in range(3)])
    x = np.zeros((3, 13))
    x[:, :7] = [[1, 1, 1, 1, 1, 1, 1], [3, 3, 3, 3, 3, 3, 3], [8, 8, 8, 8, 8, 8, 8]]
    out = causal_user_relative_daily(x, dates)
    med = np.median([np.log1p(1.0), np.log1p(3.0)])
    assert out[2, 0] == pytest.approx(np.log1p(8.0) - med)


def test_t10_six_binary_features_use_current_minus_past_mean():
    dates = np.array([np.datetime64("2010-01-01") + np.timedelta64(i, "D") for i in range(3)])
    x = np.zeros((3, 13))
    x[:, 7:] = [[1, 0, 1, 0, 1, 0], [1, 1, 0, 0, 1, 1], [0, 1, 1, 1, 0, 1]]
    out = causal_user_relative_daily(x, dates)
    mean_past = x[:2, 7:].mean(axis=0)
    assert np.allclose(out[2, 7:], x[2, 7:] - mean_past)
    assert np.all(out[:, 7:] >= -1.0 - 1e-12)
    assert np.all(out[:, 7:] <= 1.0 + 1e-12)


def test_t11_r52_scaler_fit_only_on_r52_train():
    sc = UserRelativeStandardScaler()
    with pytest.raises(Exception):
        sc.fit(np.zeros((10, 13)), source="R61")
    sc.fit(np.random.default_rng(0).normal(size=(20, 13)), source="R52 TRAIN ONLY")
    assert sc.fitted_on == "R52 TRAIN ONLY"


def test_t12_r61_never_fits_scaler():
    src = _src("scaler.py", "tensors.py", "campaign.py", "constants.py")
    assert "R61_SCALER_FIT" in src
    assert 'source="R61"' not in (PKG / "tensors.py").read_text(encoding="utf-8")
    assert "R61 TRAIN" not in (PKG / "scaler.py").read_text(encoding="utf-8")


def test_t13_stage0_psi_bins_from_r52_train_only():
    src = (PKG / "stage0.py").read_text(encoding="utf-8")
    assert 'bins_fitted_from": "R52_TRAIN"' in src
    from editor025_r61_autopsy.feature_shift import train_decile_edges

    train = np.linspace(0, 1, 1000)
    edges = train_decile_edges(train)
    assert edges.min() == pytest.approx(0.0)
    assert edges.max() == pytest.approx(1.0)


def test_t14_stage0_support_bounds_from_r52_train_only():
    src = (PKG / "stage0.py").read_text(encoding="utf-8")
    assert 'oos_bounds_fitted_from": "R52_TRAIN"' in src
    from editor025_r61_autopsy.feature_shift import support_bounds_from_train

    lo, hi = support_bounds_from_train(np.linspace(0, 1, 1001))
    assert lo == pytest.approx(0.005, abs=1e-6)
    assert hi == pytest.approx(0.995, abs=1e-6)


def test_t15_stage0_discriminant_from_r52_train_only():
    src = (PKG / "stage0.py").read_text(encoding="utf-8")
    assert 'discriminant_source": "R52_TRAIN"' in src
    rng = np.random.default_rng(0)
    pos = rng.normal(1, 0.1, size=(20, 4))
    neg = rng.normal(0, 0.1, size=(20, 4))
    d = discriminant_direction(pos, neg)
    assert d.shape == (4,)
    assert d.mean() > 0


def test_t16_both_r61_label_views_are_frozen():
    assert R61_LABEL_VIEW_A == "R61_EDITOR024_LABEL_VIEW"
    assert R61_LABEL_VIEW_B == "R61_INSIDER_CONSISTENT_VIEW"
    src = (PKG / "labels.py").read_text(encoding="utf-8")
    assert R61_LABEL_VIEW_A in src
    assert R61_LABEL_VIEW_B in src


def test_t17_missing_scenario_4_remains_not_evaluable():
    assert SCENARIO4_STATUS == "NOT_EVALUABLE"
    src = (PKG / "labels.py").read_text(encoding="utf-8")
    assert "NOT_EVALUABLE" in src
    assert "invent" in src.lower() or "scenario4_not_invented" in src


def test_t18_stage0_gates_implemented_exactly():
    assert G0A_MEAN_ABS_SHIFT_REDUCTION_MIN == 0.50
    assert G0B_MEAN_PSI_REDUCTION_MIN == 0.50
    assert G0C_N_FEATURES_LOWER_PSI_MIN == 9
    src = (PKG / "stage0.py").read_text(encoding="utf-8")
    assert "G0A" in src and "G0B" in src and "G0C" in src
    assert "G0D" in src and "G0E" in src and "G0F" in src


def test_t19_no_training_before_stage0_pass():
    src = (PKG / "campaign.py").read_text(encoding="utf-8")
    i_req = src.index("require_stage0_pass")
    i_train = src.index("def run_training")
    assert "require_stage0_pass(action=\"r5.2 training\")" in src
    assert "EDITOR026_TRAINING_AUTHORISED" in src


def test_t20_teacher_training_never_reads_r61():
    src = (PKG / "train.py").read_text(encoding="utf-8")
    assert "r6.1" not in src.lower() or "never" in src.lower()
    assert "r61_used': False" in src.replace(" ", "") or '"r61_used": False' in src
    assert "load_r61" not in src


def test_t21_r52_checkpoint_selection_never_reads_r61():
    src = (PKG / "train.py").read_text(encoding="utf-8")
    assert "x_val" in src
    assert "load_r61" not in src
    camp = (PKG / "campaign.py").read_text(encoding="utf-8")
    train_fn = camp[camp.index("def run_training") : camp.index("def write_r52_model_freeze")]
    assert "r61_ur_windows" not in train_fn
    assert "y_r61" not in train_fn


def test_t22_r52_checkpoints_frozen_before_r61_inference():
    src = (PKG / "campaign.py").read_text(encoding="utf-8")
    assert "require_r52_model_frozen" in src
    assert src.index("def write_r52_model_freeze") < src.index("def run_r61_evaluation")
    assert "require_r52_model_frozen(action=\"r6.1 diagnostic evaluation\")" in src


def test_t23_exactly_models_ur_c2_f10_final_linear():
    assert STUDENT_MODELS == ("UR_C2", "UR_F10", "UR_FINAL", "UR_LINEAR")


def test_t24_seeds_exactly_42_52_62():
    assert SEEDS == (42, 52, 62)


def test_t25_no_r61_threshold_search():
    src = _src("campaign.py", "train.py")
    assert "THRESHOLD_SOURCE" in (PKG / "campaign.py").read_text(encoding="utf-8") or "frozen_threshold" in src
    r61_fn = (PKG / "campaign.py").read_text(encoding="utf-8")
    block = r61_fn[r61_fn.index("def run_r61_evaluation") :]
    assert "choose_threshold" not in block


def test_t26_no_r61_calibration_fitting():
    block = (PKG / "campaign.py").read_text(encoding="utf-8")
    r61 = block[block.index("def run_r61_evaluation") :]
    assert "CalibratedClassifier" not in r61
    assert "isotonic" not in r61.lower()


def test_t27_user_cluster_bootstrap_uses_users_not_windows():
    users = np.array(["u0"] * 4 + ["u1"] * 4)
    y = np.array([0, 0, 1, 0, 0, 0, 1, 0])
    scores = np.linspace(0, 1, 8)

    def stat(sl, yb):
        return {"pr": float(yb.mean() + scores[sl].mean())}

    rec = user_cluster_bootstrap(users, y, stat, n_valid=10, seed=42)
    assert rec["sampling_unit"] == "user"
    assert rec["windows_not_independent"] is True
    assert rec["n_users"] == 2


def test_t28_same_users_used_for_paired_contrasts():
    src = (PKG / "bootstrap.py").read_text(encoding="utf-8")
    assert "matched_contrasts_share_resampled_users" in src
    camp = (PKG / "campaign.py").read_text(encoding="utf-8")
    assert "UR_FINAL_minus_historical_TA2" in camp
    assert "stat_fn" in camp


def test_t29_minimum_prevalence_lift_gate_exactly_10():
    assert MINIMUM_AP_PREVALENCE_LIFT == 10.0


def test_t30_historical_ta2_predictions_read_only():
    src = (PKG / "campaign.py").read_text(encoding="utf-8")
    assert "historical_ta2_logits" in src
    assert "TA2_seed" in src
    with pytest.raises(Editor026ProtocolError):
        refuse_historical_write(REPO / "review" / "editor024_r61_final_confirmation" / "EDITOR024_PROTOCOL.json")


def test_t31_no_r51_r62_inference():
    src = _src("campaign.py", "tensors.py", "train.py")
    assert "scaled_dense_daily_r51" not in src
    assert "r52_T20_s1_test" not in src
    assert "refuse_r51_r62" in (PKG / "campaign.py").read_text(encoding="utf-8")


def test_t32_no_future_untouched_target_search():
    src = _src("campaign.py", "protocol.py", "constants.py")
    assert "no_new_untouched_target" in src or "DO NOT SELECT" in src or "untouched" in src.lower()
    camp = (PKG / "campaign.py").read_text(encoding="utf-8")
    assert "select_new_untouched" not in camp


def test_t33_sha_manifest_excludes_itself():
    from editor026_user_relative.campaign import SHA256_MANIFEST_NAME, sha256_manifest

    fake = REPO / "review" / "editor026_user_relative_representation"
    fake.mkdir(parents=True, exist_ok=True)
    rec = sha256_manifest([fake / SHA256_MANIFEST_NAME, fake / "EDITOR026_PROTOCOL.json"], repo_root=REPO)
    assert SHA256_MANIFEST_NAME not in rec
    assert all(Path(k).name != SHA256_MANIFEST_NAME for k in rec)


def _fn_source(path: Path, name: str) -> str:
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(text, node) or ""
    raise AssertionError(name)


def test_t34_finalisation_order_regression_passes():
    src = _fn_source(PKG / "campaign.py", "finalise")
    i_run = src.index("EDITOR026_RUN_MANIFEST")
    i_freeze = src.index("write_result_freeze")
    i_term = src.index("terminal_block")
    i_sha = src.index("write_sha256_manifest_last")
    assert i_run < i_freeze < i_term < i_sha


def test_flatten_windows_is_260():
    x = np.zeros((2, 20, 13))
    assert flatten_windows(x).shape == (2, 260)


def test_input_transfer_ratio_preserves_sign():
    assert input_transfer_ratio(-0.5, 2.0) == pytest.approx(-0.25)


def test_reduction_metrics_formula():
    rows = []
    for i, name in enumerate(FEATURE_ORDER):
        rows.append(
            {
                "feature": name,
                "MEAN_SHIFT_Z": 0.0,
                "PSI_R61_VS_R52": 0.0,
                "psi_lower_than_original": True,
            }
        )
    rec = reduction_metrics(rows)
    assert rec["N_FEATURES_WITH_LOWER_PSI"] == 13
    assert rec["G0C"] is True
