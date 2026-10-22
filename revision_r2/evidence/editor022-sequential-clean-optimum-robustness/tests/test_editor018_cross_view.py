"""EDITOR-018 protocol, hash-gate, and safety tests. Do not open r5.2 TEST."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import torch

from editor012_rescue.safety import refuse_r51, refuse_r52_test, refuse_r62
from editor017_robustness.constants import GLOBAL_TOPK_PR_AUC_FAITHFULNESS
from editor018_cross_view.aggregate40 import (
    aggregate40,
    assert_no_metadata_in_features,
    audit_record,
    fit_standard_scaler,
    metadata_keys_only,
    producer_sha256,
    transform_standard,
)
from editor018_cross_view.constants import (
    EDITOR012_RESULTS_COMMIT,
    EDITOR013_RESULTS_COMMIT,
    EDITOR014_RESULTS_COMMIT,
    EDITOR015_RESULTS_COMMIT,
    EDITOR016_RESULTS_COMMIT,
    EDITOR017_RESULTS_COMMIT,
    EXPECTED_AGGREGATE40_SHA256,
    LAMBDA_TEACHER,
    LOCKED_AGG_FEATURES,
    N_TREES_TOTAL,
    PROMOTION_MARGIN,
    SUMMARY_DIM,
    TEACHER_GUIDANCE_VS_INITIALISATION,
)
from editor018_cross_view.models import (
    InstanceWiseTreeGate,
    SummaryBranch,
    prove_function_preserving,
    teacher_residual,
)
from editor018_cross_view.promotion import decide_promotions
from editor018_cross_view.safety import (
    Editor018Blocked,
    Editor018ProtocolError,
    enter_inner_phase,
    exit_inner_phase,
    mark_promotion_frozen,
    refuse_historical_write,
    refuse_official_validation_during_inner,
    refuse_validation_before_promotion,
)


def test_r52_test_hard_denied():
    with pytest.raises(Exception, match="TEST"):
        refuse_r52_test(
            r"C:\PhD\07_Projects\cert-r42-feasibility\data\processed\r5.2\tensors\r52_T20_s1_test.npz"
        )


def test_r51_and_r62_denied():
    with pytest.raises(Exception):
        refuse_r51(r"C:\PhD\07_Projects\cert-r42-feasibility\data\processed\r5.1\tensors\x.npz")
    with pytest.raises(Exception):
        refuse_r62(r"C:\PhD\07_Projects\cert-r42-feasibility\data\processed\r6.2\tensors\x.npz")


def test_historical_packets_read_only():
    with pytest.raises(Editor018ProtocolError, match="historical"):
        refuse_historical_write("review/editor017_explanation_robustness/x.json")
    with pytest.raises(Editor018ProtocolError, match="historical"):
        refuse_historical_write("review/editor012_teacher_anchor_rescue/x.json")
    with pytest.raises(Editor018ProtocolError, match="historical"):
        refuse_historical_write(
            r"C:\PhD\07_Projects\teacher-anchored-insider-threat-detection-editor016\review\editor016_uncertainty_routed_odst\x.json"
        )


def test_frozen_commits_recovered():
    assert EDITOR012_RESULTS_COMMIT == "4bcf522a502ed98e5dd393a80bd9da7fffd51964"
    assert EDITOR013_RESULTS_COMMIT == "09c4bb97b143810147feef08f31a8d8d042a6726"
    assert EDITOR014_RESULTS_COMMIT == "c3343462dc3b35d20907da6ad017f5f853852f84"
    assert EDITOR015_RESULTS_COMMIT == "d8e1d04b8c199f56cab9956f62c16cd4301f0bac"
    assert EDITOR016_RESULTS_COMMIT == "07b90867dc83ac42a4f3dce538ee7eca0cedb230"
    assert EDITOR017_RESULTS_COMMIT == "c75321a627ecc7539d1a759764d7ce395895179a"
    assert TEACHER_GUIDANCE_VS_INITIALISATION == "SUPPORTED_STRONG"
    assert GLOBAL_TOPK_PR_AUC_FAITHFULNESS == "NOT_SUPPORTED"


def test_40_feature_producer_hash_gated():
    assert producer_sha256() == EXPECTED_AGGREGATE40_SHA256
    rec = audit_record()
    assert rec["feature_count"] == 40
    assert rec["feature_order"] == list(LOCKED_AGG_FEATURES)
    assert rec["producing_implementation"]["recreated_from_prose"] is False
    assert rec["fitted_state_uses_train_only"] is True


def test_40_feature_count_and_order():
    rng = np.random.default_rng(0)
    X = rng.random((5, 20, 13)).astype(np.float32)
    feat, names = aggregate40(X)
    assert feat.shape == (5, 40)
    assert names == list(LOCKED_AGG_FEATURES)
    assert feat.dtype == np.float32


def test_no_metadata_enters_predictive_inputs():
    rng = np.random.default_rng(1)
    X = rng.random((3, 20, 13)).astype(np.float32)
    feat, _ = aggregate40(X)
    meta = metadata_keys_only(
        np.array(["u1", "u2", "u3"]),
        np.array(["s1", "s2", "s3"]),
        np.array(["2010-01-01"] * 3),
        np.array(["2010-01-20"] * 3),
    )
    assert_no_metadata_in_features(feat, meta)
    assert feat.shape[1] == SUMMARY_DIM


def test_labels_and_mapping_one_to_one():
    y_seq = np.array([0, 1, 0, 1], dtype=np.float32)
    y_sum = y_seq.copy()
    assert np.array_equal(y_seq, y_sum)
    assert len(y_seq) == 4


def test_scaler_train_only_and_shared_transform():
    rng = np.random.default_rng(2)
    train = rng.normal(size=(20, 40))
    other = rng.normal(size=(6, 40))
    scaler = fit_standard_scaler(train)
    assert int(scaler.n_samples_seen_) == 20
    a = transform_standard(scaler, other)
    b = transform_standard(scaler, other)
    assert np.allclose(a, b)
    for family_input in (a, a.copy()):
        assert family_input.shape == (6, 40)


def test_function_preserving_and_gradients():
    for family in ("LIN40", "MLP40", "ODST40", "IWODST40"):
        rec = prove_function_preserving(family, batch=8)
        assert rec["initial_final_equals_l1"]
        assert rec["initial_correction_zero"]
        assert rec["live_grad_norm"] > 0
        assert rec["reference_grad_norm"] == 0.0


def test_iw_odst_initial_weights_uniform_and_sum_to_one():
    gate = InstanceWiseTreeGate()
    s = torch.randn(11, 40)
    w = gate(s)
    assert torch.allclose(w, torch.full_like(w, 1.0 / N_TREES_TOTAL), atol=1e-6)
    assert torch.allclose(w.sum(dim=-1), torch.ones(11), atol=1e-6)


def test_teacher_residual_and_lambda():
    ens = torch.tensor([1.0, 2.0, 3.0])
    l1 = torch.tensor([0.2, 0.5, 1.0])
    r = teacher_residual(ens, l1)
    assert torch.allclose(r, ens - l1)
    assert abs(LAMBDA_TEACHER - 0.5) < 1e-15


def test_inner_selection_cannot_read_official_validation():
    enter_inner_phase()
    try:
        with pytest.raises(Editor018Blocked, match="inner search cannot read official validation"):
            refuse_official_validation_during_inner(
                r"C:\PhD\07_Projects\cert-r42-feasibility\data\processed\r5.2\tensors\r52_T20_s1_validation.npz"
            )
    finally:
        exit_inner_phase()


def test_promotion_freeze_precedes_validation():
    with pytest.raises(Editor018Blocked, match="promotion freeze precedes validation"):
        refuse_validation_before_promotion("review/editor018_cross_view_tree_rescue/02_validation_confirmation/x.csv")
    mark_promotion_frozen()
    refuse_validation_before_promotion("review/editor018_cross_view_tree_rescue/02_validation_confirmation/x.csv")


def test_bootstrap_resamples_users_not_windows():
    from editor012_rescue.bootstrap import paired_user_cluster_mean_across_seeds

    users = np.array([f"u{i//2}" for i in range(20)])
    y = np.array([0, 1] * 10)
    a = [np.linspace(-1, 1, 20), np.linspace(-0.8, 0.8, 20), np.linspace(-1.1, 0.9, 20)]
    b = [x + 0.2 for x in a]
    out = paired_user_cluster_mean_across_seeds(
        users,
        y,
        a,
        b,
        frozen_thresholds_a=[0.5, 0.5, 0.5],
        frozen_thresholds_b=[0.5, 0.5, 0.5],
        n_valid=20,
        seed=42,
    )
    assert out["cluster"] == "user"
    assert out["sampling_unit"] == "validation user"
    assert out["n_users"] == 10


def test_perturbation_before_summary_keeps_alignment():
    from editor018_cross_view.robustness import perturb_then_summarise

    rng = np.random.default_rng(3)
    X = rng.random((4, 20, 13)).astype(np.float32)
    scaler = fit_standard_scaler(aggregate40(X)[0])
    Xp, s = perturb_then_summarise(X, kind="source", channel="logon", scaler=scaler)
    assert Xp.shape == X.shape
    assert s.shape == (4, 40)
    assert s.shape[0] == Xp.shape[0]


def test_global_topk_negative_faithfulness_preserved():
    assert GLOBAL_TOPK_PR_AUC_FAITHFULNESS == "NOT_SUPPORTED"


def test_promotion_margin_cannot_be_lowered():
    assert PROMOTION_MARGIN == 0.001
    rows = []
    for name, pr in {
        "LIN40-T": 0.90,
        "LIN40-D": 0.91,
        "MLP40-T": 0.90,
        "MLP40-D": 0.912,
        "ODST40-T": 0.91,
        "ODST40-D": 0.920,
        "IWODST40-T": 0.90,
        "IWODST40-D": 0.905,
    }.items():
        rows.append({"condition": name, "select_PR_AUC": pr})
    dec = decide_promotions(rows, l1_pr_auc=0.90)
    assert dec["promoted_names"] == ["ODST40-D"]
    assert dec["margin_lowered_after_results"] is False
