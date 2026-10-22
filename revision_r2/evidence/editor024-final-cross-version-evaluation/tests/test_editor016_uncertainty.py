"""EDITOR-016 identity, gate, residual, and freeze tests. Do not open r5.2 TEST."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import torch

from editor012_rescue.bootstrap import paired_user_cluster_mean_across_seeds
from editor012_rescue.producing import build_odst046_model
from editor012_rescue.safety import refuse_r51, refuse_r52_test, refuse_r62
from editor015_residual.explain import directional_table, train_references
from editor016_uncertainty.constants import (
    DIRECTIONAL_KS,
    EDITOR015_RESULTS_FULL_COMMIT,
    HISTORICAL_SINGLE_TEACHER_STATIC_LOGIT_ANCHOR,
    LAMBDA_ROUTE,
    LAMBDA_TEACHER,
    N_TREES_TOTAL,
    PROMOTION_MARGIN,
    Q_VALUES,
    SPECIALIST_CONDITIONS,
    TEACHER_GUIDANCE_VS_INITIALISATION,
)
from editor016_uncertainty.freeze import function_preserving_proof
from editor016_uncertainty.gate import (
    apply_cascade,
    freeze_thresholds,
    gate_indicator,
    l1_margin,
    tau_from_train,
)
from editor016_uncertainty.models import (
    editor016_forward,
    make_modules,
    reference_grad_l1,
    specialist_param_grad_norm,
)
from editor016_uncertainty.promotion import decide_promotions
from editor016_uncertainty.safety import (
    Editor016Blocked,
    Editor016ProtocolError,
    assert_q_allowed,
    enter_inner_phase,
    exit_inner_phase,
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
    with pytest.raises(Editor016ProtocolError, match="historical"):
        refuse_historical_write(
            r"C:\PhD\07_Projects\teacher-anchored-insider-threat-detection-editor015\review\editor015_residual_complementarity\x.json"
        )
    with pytest.raises(Editor016ProtocolError, match="historical"):
        refuse_historical_write(
            r"C:\PhD\07_Projects\teacher-anchored-insider-threat-detection-editor014\review\editor014_temporal_odst_value\x.json"
        )
    with pytest.raises(Editor016ProtocolError, match="historical"):
        refuse_historical_write(
            r"C:\PhD\07_Projects\teacher-anchored-insider-threat-detection-editor013\review\editor013_odst_value_proof\x.json"
        )


def test_editor015_results_commit_recovered():
    assert EDITOR015_RESULTS_FULL_COMMIT == "d8e1d04b8c199f56cab9956f62c16cd4301f0bac"
    assert TEACHER_GUIDANCE_VS_INITIALISATION == "SUPPORTED_STRONG"


def test_gate_uses_only_abs_l1_logit():
    src = Path("src/editor016_uncertainty/gate.py").read_text(encoding="utf-8")
    assert "abs(L1_logit" in src or "np.abs" in src
    logits = np.array([-2.0, -0.1, 0.0, 0.4, 3.0])
    assert np.allclose(l1_margin(logits), np.abs(logits))


def test_gate_thresholds_from_train_only_and_q_restricted():
    assert Q_VALUES == (0.10, 0.20, 0.30, 0.40, 0.50)
    with pytest.raises(Editor016Blocked):
        assert_q_allowed(0.15)
    with pytest.raises(Editor016Blocked):
        freeze_thresholds(np.array([0.1, 0.2, 0.3]), seed=42, source="validation")
    train = np.linspace(-4, 4, 101)
    taus = freeze_thresholds(train, seed=42, source="INNER_TRAIN")
    assert set(taus) == set(Q_VALUES)
    tau = tau_from_train(train, 0.20)
    g = gate_indicator(train, tau)
    assert g.dtype == np.int8
    val = np.array([0.0, 10.0])
    g_val = gate_indicator(val, tau)
    assert g_val[0] == 1
    assert g_val[1] == 0


def test_validation_never_determines_tau():
    src = Path("src/editor016_uncertainty/gate.py").read_text(encoding="utf-8")
    assert "validation never determines tau" in src
    src_c = Path("src/editor016_uncertainty/campaign.py").read_text(encoding="utf-8")
    assert 'source="TRAIN"' in src_c or 'source="INNER_TRAIN"' in src_c
    assert "freeze_thresholds(cache_va" not in src_c


def test_linear_residual_starts_zero_with_nonzero_gradient():
    proof = function_preserving_proof()
    assert proof["LINEAR_RESIDUAL_INITIAL_OUTPUT"] == "ZERO"
    assert proof["LINEAR_RESIDUAL_INITIAL_GRADIENT"] == "NONZERO"
    assert proof["linear_grad_l2"] > 0


def test_odst_residual_starts_zero_with_nonzero_gradient():
    proof = function_preserving_proof()
    assert proof["ODST_RESIDUAL_INITIAL_OUTPUT"] == "ZERO"
    assert proof["ODST_RESIDUAL_INITIAL_EQUALS_L1"] is True
    assert proof["ODST_RESIDUAL_INITIAL_GRADIENT"] == "NONZERO"
    assert proof["odst_grad_l2"] > 0
    assert proof["reference_odst_grad_l1"] == 0.0


def test_frozen_residual_reference_receives_no_gradient():
    student = build_odst046_model()
    modules = make_modules("odst")
    modules.attach_reference(student.node_head)
    x = torch.randn(4, 20, 13)
    y = torch.tensor([0.0, 1.0, 0.0, 1.0])
    gate = torch.ones(4)
    out = editor016_forward(student, x, modules, gate=gate)
    out["logit"].sum().backward()
    assert reference_grad_l1(modules) == 0.0
    for p in modules.reference_odst.parameters():
        assert p.grad is None
        assert p.requires_grad is False
    assert specialist_param_grad_norm(student, modules) > 0


def test_factorial_differs_only_by_declared_factor():
    assert SPECIALIST_CONDITIONS["S0"]["head"] == "linear"
    assert SPECIALIST_CONDITIONS["S2"]["head"] == "odst"
    assert SPECIALIST_CONDITIONS["S0"]["teacher_residual"] is False
    assert SPECIALIST_CONDITIONS["S2"]["teacher_residual"] is False
    assert SPECIALIST_CONDITIONS["S1"]["head"] == "linear"
    assert SPECIALIST_CONDITIONS["S3"]["head"] == "odst"
    assert SPECIALIST_CONDITIONS["S1"]["teacher_residual"] is True
    assert SPECIALIST_CONDITIONS["S3"]["teacher_residual"] is True
    assert SPECIALIST_CONDITIONS["S2"]["teacher_residual"] is False
    assert SPECIALIST_CONDITIONS["S3"]["teacher_residual"] is True
    assert SPECIALIST_CONDITIONS["S3"]["route"] is False
    assert SPECIALIST_CONDITIONS["S4"]["route"] is True
    assert SPECIALIST_CONDITIONS["S3"]["head"] == SPECIALIST_CONDITIONS["S4"]["head"]
    assert SPECIALIST_CONDITIONS["S3"]["teacher_residual"] is True


def test_teacher_residual_target_and_lambdas():
    src = Path("src/editor016_uncertainty/train.py").read_text(encoding="utf-8")
    assert "ens.detach() - frozen_l1.detach()" in src
    assert "LAMBDA_TEACHER" in src
    assert LAMBDA_TEACHER == 0.5
    assert LAMBDA_ROUTE == 0.5
    assert HISTORICAL_SINGLE_TEACHER_STATIC_LOGIT_ANCHOR == "RETIRED"
    assert "historical_c5_logit_consistency" not in src
    assert "LAMBDA_HISTORICAL_SINGLE_TEACHER_LOGIT != 0.0" in src


def test_whole_system_equals_l1_when_gate_zero_and_l1_plus_delta_when_gate_one():
    l1 = np.array([1.0, -2.0, 0.5, 3.0])
    delta = np.array([10.0, 20.0, 30.0, 40.0])
    gate = np.array([0, 1, 0, 1])
    final = apply_cascade(l1, delta, gate)
    assert np.allclose(final[gate == 0], l1[gate == 0])
    assert np.allclose(final[gate == 1], l1[gate == 1] + delta[gate == 1])


def test_inner_selection_cannot_read_official_validation():
    enter_inner_phase()
    try:
        with pytest.raises(Editor016Blocked, match="inner"):
            refuse_official_validation_during_inner(
                r"C:\PhD\07_Projects\cert-r42-feasibility\data\processed\r5.2\tensors\r52_T20_s1_validation.npz"
            )
    finally:
        exit_inner_phase()


def test_promotion_commit_precedes_validation_training():
    with pytest.raises(Editor016Blocked, match="promotion"):
        refuse_validation_before_promotion(
            "review/editor016_uncertainty_routed_odst/03_validation_confirmation/x.csv"
        )


def test_bootstrap_resamples_users():
    src = Path("src/editor012_rescue/bootstrap.py").read_text(encoding="utf-8")
    assert "sampling_unit" in src
    assert "validation user" in src
    users = np.array(["u1", "u1", "u2", "u2", "u3", "u3"])
    y = np.array([0, 1, 0, 1, 0, 1])
    a = np.array([0.1, 0.9, 0.2, 0.8, 0.3, 0.7])
    b = a + 0.05
    out = paired_user_cluster_mean_across_seeds(
        users, y, [a], [b], frozen_thresholds_a=[0.5], frozen_thresholds_b=[0.5], n_valid=20, seed=42
    )
    assert out["cluster"] == "user"
    assert out["windows_not_independent"] is True


def test_directional_intervention_train_references_and_same_sign_controls():
    src = Path("src/editor015_residual/explain.py").read_text(encoding="utf-8")
    assert "TRAIN only" in src
    assert "same-sign" in src or "same_sign" in src
    assert DIRECTIONAL_KS == (1, 2, 3)
    rng = np.random.default_rng(1)
    trees = rng.normal(size=(12, N_TREES_TOTAL))
    refs = train_references(trees)
    y = np.array([1, 1, 1, 1, 0, 0, 0, 0, 1, 0, 1, 0])
    users = np.array([f"u{i//2}" for i in range(12)])
    lin = rng.normal(size=12)
    faith = directional_table(
        y=y,
        tree_outputs=trees,
        references=refs,
        linear_logit=lin,
        reference_tree_outputs=None,
        users=users,
    )
    assert faith["HISTORICAL_GLOBAL_TOPK_FAITHFULNESS"] == "NOT_SUPPORTED"
    assert all(row["random_control"] == "same-sign eligible trees only" for row in faith["rows"])
    assert all(row["references_from"] == "r5.2 TRAIN only" for row in faith["rows"])


def test_promotion_requires_odst_specific_value():
    rows = [
        {"condition": "L1", "select_PR_AUC": 0.90, "select_F1": 0.8, "executed": True},
        {"condition": "S0@q0.20", "select_PR_AUC": 0.901, "select_F1": 0.8, "executed": True, "gate_coverage": 0.2},
        {"condition": "S1@q0.20", "select_PR_AUC": 0.902, "select_F1": 0.8, "executed": True, "gate_coverage": 0.2},
        {"condition": "S2@q0.20", "select_PR_AUC": 0.900, "select_F1": 0.8, "executed": True, "gate_coverage": 0.2},
        {"condition": "S3@q0.20", "select_PR_AUC": 0.910, "select_F1": 0.8, "executed": True, "gate_coverage": 0.2},
        {"condition": "S4@q0.20", "select_PR_AUC": 0.911, "select_F1": 0.8, "executed": True, "gate_coverage": 0.2},
        {"condition": "S0@q0.10", "select_PR_AUC": 0.900, "select_F1": 0.8, "executed": True, "gate_coverage": 0.1},
        {"condition": "S1@q0.10", "select_PR_AUC": 0.900, "select_F1": 0.8, "executed": True, "gate_coverage": 0.1},
        {"condition": "S2@q0.10", "select_PR_AUC": 0.900, "select_F1": 0.8, "executed": True, "gate_coverage": 0.1},
        {"condition": "S3@q0.10", "select_PR_AUC": 0.9005, "select_F1": 0.8, "executed": True, "gate_coverage": 0.1},
        {"condition": "S4@q0.10", "select_PR_AUC": 0.9004, "select_F1": 0.8, "executed": True, "gate_coverage": 0.1},
    ]
    for q in (0.30, 0.40, 0.50):
        for name in ("S0", "S1", "S2", "S3", "S4"):
            rows.append(
                {
                    "condition": f"{name}@q{q:.2f}",
                    "select_PR_AUC": 0.899,
                    "select_F1": 0.7,
                    "executed": True,
                    "gate_coverage": q,
                }
            )
    dec = decide_promotions(rows)
    assert dec["n_promoted"] <= 2
    assert dec["official_r52_validation_not_used_for_selection"] is True
    assert all(p["delta_vs_L1"] >= PROMOTION_MARGIN for p in dec["promoted"])
    assert all(p["odst_minus_matched_linear"] >= PROMOTION_MARGIN for p in dec["promoted"])
    families = {p["inner_condition"] for p in dec["promoted"]}
    assert families <= {"S3", "S4"}
