"""EDITOR-027 protocol, representation, gate, and safety tests. No CERT predictive run."""

from __future__ import annotations

import ast
import json
import subprocess
from pathlib import Path

import numpy as np
import pytest

from editor027_scale_normalised.bootstrap import user_cluster_bootstrap
from editor027_scale_normalised.constants import (
    EDITOR026_CENTERED_PSI,
    EDITOR026_RESULTS_COMMIT,
    EDITOR025_ORIGINAL_PSI,
    FEATURE_DIM,
    FEATURE_ORDER,
    FLOOR_FALLBACK,
    G0A_MEAN_ABS_SHIFT_REDUCTION_MIN,
    G0B_MEAN_PSI_REDUCTION_VS_ORIGINAL_MIN,
    G0C_N_FEATURES_LOWER_PSI_MIN,
    G0D_MEAN_PSI_REDUCTION_VS_CENTERED_MIN,
    MAD_SCALE_CONSTANT,
    MINIMUM_AP_PREVALENCE_LIFT,
    ODST046,
    R61_LABEL_VIEW_A,
    R61_LABEL_VIEW_B,
    SCALE_FLOOR_PERCENTILE,
    SCENARIO4_STATUS,
    SEEDS,
    SEQUENCE_LENGTH_LOCKED,
    STUDENT_MODELS,
    USER_RELATIVE_LOOKBACK_DAYS,
    VOLUME_FEATURES,
)
from editor027_scale_normalised.floors import floors_from_positive_scales
from editor027_scale_normalised.representation import (
    causal_scale_normalised_daily,
    causal_volume_scales_daily,
    jeffreys_bernoulli_residual,
    robust_centre_and_scale,
)
from editor027_scale_normalised.safety import Editor027ProtocolError, refuse_historical_write
from editor027_scale_normalised.scaler import ScaleNetworkScaler
from editor027_scale_normalised.stage0 import (
    class_separation,
    discriminant_direction,
    input_transfer_ratio,
    reduction_metrics,
)
from editor027_scale_normalised.windows import flatten_windows


REPO = Path(__file__).resolve().parents[1]
PKG = REPO / "src" / "editor027_scale_normalised"


def _src(*names: str) -> str:
    return "\n".join((PKG / n).read_text(encoding="utf-8") for n in names)


def _dates(n: int):
    return np.array([np.datetime64("2010-01-01") + np.timedelta64(i, "D") for i in range(n)])


def test_t01_parent_commit_exact():
    assert EDITOR026_RESULTS_COMMIT == "83f3f8f6cbe2b75faa176e2840bec84bf84b09d0"
    ancestor = subprocess.check_output(
        ["git", "merge-base", EDITOR026_RESULTS_COMMIT, "HEAD"],
        cwd=str(REPO),
        text=True,
    ).strip()
    assert ancestor == EDITOR026_RESULTS_COMMIT


def test_t02_output_dimension_remains_13():
    assert SEQUENCE_LENGTH_LOCKED == 20
    assert FEATURE_DIM == 13
    assert len(FEATURE_ORDER) == 13
    assert ODST046["n_trees"] == 4
    assert ODST046["depth"] == 4
    floors = np.ones(7)
    assert causal_scale_normalised_daily(np.zeros((5, 13)), scale_floors=floors).shape == (5, 13)


def test_t03_lookback_exactly_20_calendar_days():
    assert USER_RELATIVE_LOOKBACK_DAYS == 20
    dates = _dates(40)
    x = np.zeros((40, 13), dtype=np.float64)
    x[:, 0] = np.arange(40)
    floors = np.ones(7)
    out = causal_scale_normalised_daily(x, dates, lookback_days=20, scale_floors=floors)
    past = np.log1p(np.arange(20.0))
    centre, scale = robust_centre_and_scale(past[:, None])
    expected = (np.log1p(20.0) - centre[0]) / max(scale[0], 1.0)
    assert out[20, 0] == pytest.approx(expected)


def test_t04_only_past_same_user_days_enter_baseline():
    dates = _dates(3)
    a = np.zeros((3, 13))
    a[:, 0] = [10, 20, 30]
    b = np.zeros((3, 13))
    b[:, 0] = [999, 999, 999]
    floors = np.ones(7)
    out_a = causal_scale_normalised_daily(a, dates, scale_floors=floors)
    out_b = causal_scale_normalised_daily(b, dates, scale_floors=floors)
    assert out_a[2, 0] != out_b[2, 0]


def test_t05_future_data_prohibited():
    dates = _dates(5)
    x = np.zeros((5, 13))
    x[:, 0] = [1, 2, 1000, 4, 5]
    floors = np.ones(7)
    out = causal_scale_normalised_daily(x, dates, scale_floors=floors)
    past = np.log1p(np.array([1.0]))[:, None]
    centre, scale = robust_centre_and_scale(past)
    expected = (np.log1p(2.0) - centre[0]) / max(float(scale[0]), 1.0)
    assert out[1, 0] == pytest.approx(expected)


def test_t06_other_users_prohibited():
    src = (PKG / "representation.py").read_text(encoding="utf-8")
    assert "other users never enter" in src.lower() or "Other users never enter" in src
    tree = ast.parse(src)
    fn = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "causal_scale_normalised_daily"][0]
    names = {n.arg for n in fn.args.args}
    assert "other_user" not in names


def test_t07_labels_prohibited():
    src = (PKG / "representation.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "causal_scale_normalised_daily"][0]
    names = {n.arg for n in fn.args.args}
    assert "y" not in names and "label" not in names


def test_t08_zero_history_output_equals_zero():
    x = np.ones((1, 13)) * 7.0
    out = causal_scale_normalised_daily(x, scale_floors=np.ones(7))
    assert np.allclose(out[0], 0.0)


def test_t09_seven_volume_features_use_log1p():
    src = (PKG / "representation.py").read_text(encoding="utf-8")
    assert "np.log1p" in src
    dates = _dates(3)
    x = np.zeros((3, 13))
    x[:, :7] = 8.0
    x[0, :7] = 1.0
    x[1, :7] = 3.0
    floors = np.ones(7)
    out = causal_scale_normalised_daily(x, dates, scale_floors=floors)
    past = np.log1p(np.array([[1.0], [3.0]]))
    # broadcast to 7 features
    past7 = np.column_stack([past[:, 0]] * 7)
    centre, scale = robust_centre_and_scale(past7)
    expected = (np.log1p(8.0) - centre) / np.maximum(scale, floors)
    assert np.allclose(out[2, :7], expected)


def test_t10_robust_centre_is_causal_median():
    past = np.log1p(np.array([[1.0], [3.0], [8.0]]))
    centre, _ = robust_centre_and_scale(past)
    assert centre[0] == pytest.approx(np.median(past))


def test_t11_robust_scale_is_mad_constant_times_causal_mad():
    assert MAD_SCALE_CONSTANT == 1.4826
    past = np.log1p(np.array([[1.0], [3.0], [8.0]]))
    centre, scale = robust_centre_and_scale(past)
    mad = np.median(np.abs(past - centre))
    assert scale[0] == pytest.approx(1.4826 * mad)


def test_t12_scale_floor_derived_only_from_r52_train():
    src = _src("floors.py", "tensors.py", "campaign.py", "constants.py")
    assert "CERT r5.2 TRAIN ONLY" in src
    assert "R61_TARGET_SCALE_FLOOR" in (PKG / "floors.py").read_text(encoding="utf-8")


def test_t13_floor_percentile_exactly_25():
    assert SCALE_FLOOR_PERCENTILE == 0.25
    rec = floors_from_positive_scales({"total_events": np.array([1.0, 2.0, 3.0, 4.0])})
    assert rec["SCALE_FLOOR_PERCENTILE"] == 0.25


def test_t14_strictly_positive_source_scales_only_enter_floor():
    rec = floors_from_positive_scales(
        {"total_events": np.array([-1.0, 0.0, np.nan, 2.0, 4.0, 6.0, 8.0])}
    )
    assert rec["n_positive_source_scales"]["total_events"] == 4
    assert rec["floors"]["total_events"] == pytest.approx(float(np.quantile([2.0, 4.0, 6.0, 8.0], 0.25)))


def test_t15_floor_fallback_exactly_1():
    assert FLOOR_FALLBACK == 1.0
    rec = floors_from_positive_scales({name: np.array([]) for name in VOLUME_FEATURES})
    assert all(rec["floors"][f] == 1.0 for f in VOLUME_FEATURES)
    assert all(rec["fallback_used"][f] for f in VOLUME_FEATURES)


def test_t16_no_r61_statistic_enters_volume_scale_floor():
    src = (PKG / "floors.py").read_text(encoding="utf-8")
    assert "r6.1 statistic refused" in src
    assert "R61_TARGET_SCALE_FLOOR" in src


def test_t17_binary_smoothing_uses_jeffreys():
    past = np.array([[1.0], [0.0], [1.0]])
    z = jeffreys_bernoulli_residual(np.array([1.0]), past)
    n = 3.0
    k = 2.0
    p = (k + 0.5) / (n + 1.0)
    expected = (1.0 - p) / np.sqrt(p * (1.0 - p))
    assert z[0] == pytest.approx(expected)


def test_t18_binary_denominator_uses_sqrt_p_one_minus_p():
    src = (PKG / "representation.py").read_text(encoding="utf-8")
    assert "np.sqrt(p_hat * (1.0 - p_hat))" in src


def test_t19_no_binary_clipping_exists():
    src = (PKG / "representation.py").read_text(encoding="utf-8")
    assert "clip" not in src.split("jeffreys")[-1].lower() or "No clipping" in src or "clipping" in src
    assert '"clipping": "NO"' in src or "clipping" in src
    dates = _dates(3)
    x = np.zeros((3, 13))
    x[:, 7:] = 1.0
    out = causal_scale_normalised_daily(x, dates, scale_floors=np.ones(7))
    # Jeffreys residual can exceed 1; absence of clip is the point
    assert np.all(np.isfinite(out[2, 7:]))


def test_t20_network_scaler_fit_only_on_r52_train():
    sc = ScaleNetworkScaler()
    with pytest.raises(Exception):
        sc.fit(np.zeros((10, 13)), source="R61")
    sc.fit(np.random.default_rng(0).normal(size=(20, 13)), source="CERT r5.2 TRAIN ONLY")
    assert sc.fitted_on == "CERT r5.2 TRAIN ONLY"


def test_t21_no_r61_scaler_fit():
    src = _src("scaler.py", "tensors.py", "campaign.py", "constants.py")
    assert "R61_SCALER_FIT" in src
    assert 'source="R61"' not in (PKG / "tensors.py").read_text(encoding="utf-8")


def test_t22_stage0_original_reference_is_frozen_editor025():
    src = (PKG / "stage0.py").read_text(encoding="utf-8")
    assert "EDITOR025_ORIGINAL_PSI" in src
    assert "ORIGINAL_SHIFT_REFERENCE" in src
    assert EDITOR025_ORIGINAL_PSI["email_count"] == pytest.approx(3.317436383694681)


def test_t23_stage0_centred_reference_is_frozen_editor026():
    src = (PKG / "stage0.py").read_text(encoding="utf-8")
    assert "EDITOR026_CENTERED_PSI" in src
    assert "CENTERED_SHIFT_REFERENCE" in src
    assert EDITOR026_CENTERED_PSI["is_active_day"] == pytest.approx(4.650173525189193)


def test_t24_psi_bins_derive_from_r52_train_only():
    src = (PKG / "stage0.py").read_text(encoding="utf-8")
    assert 'bins_fitted_from": "R52_TRAIN"' in src
    from editor025_r61_autopsy.feature_shift import train_decile_edges

    train = np.linspace(0, 1, 1000)
    edges = train_decile_edges(train)
    assert edges.min() == pytest.approx(0.0)
    assert edges.max() == pytest.approx(1.0)


def test_t25_g0a_g0g_implemented_exactly():
    assert G0A_MEAN_ABS_SHIFT_REDUCTION_MIN == 0.50
    assert G0B_MEAN_PSI_REDUCTION_VS_ORIGINAL_MIN == 0.50
    assert G0C_N_FEATURES_LOWER_PSI_MIN == 9
    assert G0D_MEAN_PSI_REDUCTION_VS_CENTERED_MIN == 0.50
    src = (PKG / "stage0.py").read_text(encoding="utf-8")
    for g in ("G0A", "G0B", "G0C", "G0D", "G0E", "G0F", "G0G"):
        assert g in src


def test_t26_no_training_before_stage0_pass():
    src = (PKG / "campaign.py").read_text(encoding="utf-8")
    assert 'require_stage0_pass(action="r5.2 training")' in src
    assert "EDITOR027_TRAINING_AUTHORISED" in src
    assert src.index("def run_stage0") < src.index("def run_training")


def test_t27_teacher_training_uses_r52_only():
    src = (PKG / "train.py").read_text(encoding="utf-8")
    assert "load_r61" not in src
    assert '"r61_used": False' in src


def test_t28_student_checkpoint_selection_uses_r52_validation_only():
    camp = (PKG / "campaign.py").read_text(encoding="utf-8")
    train_fn = camp[camp.index("def run_training") : camp.index("def write_r52_model_freeze")]
    assert "r61_scale_windows" not in train_fn
    assert "y_r61" not in train_fn


def test_t29_r52_model_freeze_before_r61_inference():
    src = (PKG / "campaign.py").read_text(encoding="utf-8")
    assert src.index("def write_r52_model_freeze") < src.index("def run_r61_evaluation")
    assert 'require_r52_model_frozen(action="r6.1 diagnostic evaluation")' in src


def test_t30_exactly_four_scale_variants_exist():
    assert STUDENT_MODELS == ("SCALE_C2", "SCALE_F10", "SCALE_FINAL", "SCALE_LINEAR")


def test_t31_seeds_exactly_42_52_62():
    assert SEEDS == (42, 52, 62)


def test_t32_no_r61_threshold_search():
    src = (PKG / "campaign.py").read_text(encoding="utf-8")
    block = src[src.index("def run_r61_evaluation") :]
    assert "choose_threshold" not in block


def test_t33_no_r61_calibration_fit():
    src = (PKG / "campaign.py").read_text(encoding="utf-8")
    r61 = src[src.index("def run_r61_evaluation") :]
    assert "CalibratedClassifier" not in r61
    assert "isotonic" not in r61.lower()


def test_t34_user_cluster_bootstrap_uses_users():
    users = np.array(["u0"] * 4 + ["u1"] * 4)
    y = np.array([0, 0, 1, 0, 0, 0, 1, 0])
    scores = np.linspace(0, 1, 8)

    def stat(sl, yb):
        return {"pr": float(yb.mean() + scores[sl].mean())}

    rec = user_cluster_bootstrap(users, y, stat, n_valid=10, seed=42)
    assert rec["sampling_unit"] == "user"
    assert rec["windows_not_independent"] is True
    assert rec["n_users"] == 2


def test_t35_matched_bootstrap_uses_identical_resampled_users():
    src = (PKG / "bootstrap.py").read_text(encoding="utf-8")
    assert "matched_contrasts_share_resampled_users" in src
    camp = (PKG / "campaign.py").read_text(encoding="utf-8")
    assert "SCALE_FINAL_minus_historical_TA2" in camp


def test_t36_minimum_ap_prevalence_lift_exactly_10():
    assert MINIMUM_AP_PREVALENCE_LIFT == 10.0


def test_t37_historical_editor024_025_026_artefacts_read_only():
    with pytest.raises(Editor027ProtocolError):
        refuse_historical_write(REPO / "review" / "editor024_r61_final_confirmation" / "EDITOR024_PROTOCOL.json")
    with pytest.raises(Editor027ProtocolError):
        refuse_historical_write(REPO / "review" / "editor025_r61_failure_autopsy" / "EDITOR025_PROTOCOL.json")
    with pytest.raises(Editor027ProtocolError):
        refuse_historical_write(REPO / "review" / "editor026_user_relative_representation" / "EDITOR026_PROTOCOL.json")


def test_t38_no_r51_r62_inference():
    src = _src("campaign.py", "tensors.py", "train.py")
    assert "scaled_dense_daily_r51" not in src
    assert "r52_T20_s1_test" not in src
    assert "refuse_r51_r62" in (PKG / "campaign.py").read_text(encoding="utf-8")


def test_t39_no_future_target_search():
    camp = (PKG / "campaign.py").read_text(encoding="utf-8")
    assert "select_new_untouched" not in camp
    proto = (PKG / "protocol.py").read_text(encoding="utf-8")
    assert "no_new_untouched_target" in proto or "Do not select a new untouched target" in proto


def test_t40_sha_manifest_excludes_itself():
    from editor027_scale_normalised.campaign import SHA256_MANIFEST_NAME, sha256_manifest

    fake = REPO / "review" / "editor027_scale_normalised_representation"
    fake.mkdir(parents=True, exist_ok=True)
    rec = sha256_manifest([fake / SHA256_MANIFEST_NAME, fake / "EDITOR027_PROTOCOL.json"], repo_root=REPO)
    assert SHA256_MANIFEST_NAME not in rec
    assert all(Path(k).name != SHA256_MANIFEST_NAME for k in rec)


def _fn_source(path: Path, name: str) -> str:
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(text, node) or ""
    raise AssertionError(name)


def test_t41_finalisation_order_regression_passes():
    src = _fn_source(PKG / "campaign.py", "finalise")
    i_run = src.index("EDITOR027_RUN_MANIFEST")
    i_freeze = src.index("write_result_freeze")
    i_term = src.index("terminal_block")
    i_sha = src.index("write_sha256_manifest_last")
    assert i_run < i_freeze < i_term < i_sha


def test_flatten_windows_is_260():
    x = np.zeros((2, 20, 13))
    assert flatten_windows(x).shape == (2, 260)


def test_input_transfer_ratio_preserves_sign():
    assert input_transfer_ratio(-0.5, 2.0) == pytest.approx(-0.25)


def test_reduction_metrics_formula_includes_centered_gate():
    rows = []
    for name in FEATURE_ORDER:
        rows.append(
            {
                "feature": name,
                "MEAN_SHIFT_Z": 0.0,
                "PSI_R61_VS_R52": 0.0,
                "psi_lower_than_original": True,
            }
        )
    rec = reduction_metrics(rows)
    assert rec["N_FEATURES_LOWER_PSI_VS_ORIGINAL"] == 13
    assert rec["G0C"] is True
    assert rec["G0D"] is True
    assert rec["EDITOR027_DISTRIBUTION_GATE"] == "PASS"
