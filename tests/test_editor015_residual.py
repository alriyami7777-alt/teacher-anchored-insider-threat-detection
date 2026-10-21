"""EDITOR-015 identity, residual-gradient, and freeze tests. Do not open r5.2 TEST."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import torch

from editor012_rescue.bootstrap import paired_user_cluster_mean_across_seeds
from editor012_rescue.producing import build_odst046_model
from editor012_rescue.safety import refuse_r51, refuse_r52_test, refuse_r62
from editor013_odst_value.models import HybridAlpha
from editor014_temporal_odst.models import ResidualBeta
from editor015_residual.complementarity import fixed_combinations, percentile_rank
from editor015_residual.constants import (
    DIRECTIONAL_KS,
    EDITOR012_RESULTS_COMMIT,
    EDITOR013_RESULTS_COMMIT,
    EDITOR014_RESULTS_COMMIT,
    LAMBDA_DISTILL,
    LAMBDA_RESIDUAL_TEACHER,
    LAMBDA_ROUTE,
    N_TREES_TOTAL,
    PROMOTION_MARGIN,
    TEACHER_GUIDANCE_VS_INITIALISATION,
)
from editor015_residual.explain import centred_contributions, directional_table, train_references
from editor015_residual.freeze import function_preserving_residual_proof, previous_residual_gradient_audit
from editor015_residual.models import editor015_forward, make_modules, r3_equivalent_to_r1_if_l1_frozen
from editor015_residual.promotion import decide_promotions
from editor015_residual.safety import (
    Editor015Blocked,
    Editor015ProtocolError,
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
    with pytest.raises(Editor015ProtocolError, match="historical"):
        refuse_historical_write(
            r"C:\PhD\07_Projects\teacher-anchored-insider-threat-detection-editor014\review\editor014_temporal_odst_value\x.json"
        )
    with pytest.raises(Editor015ProtocolError, match="historical"):
        refuse_historical_write(
            r"C:\PhD\07_Projects\teacher-anchored-insider-threat-detection-editor013\review\editor013_odst_value_proof\x.json"
        )
    with pytest.raises(Editor015ProtocolError, match="historical"):
        refuse_historical_write(
            r"C:\PhD\07_Projects\teacher-anchored-insider-threat-detection-editor012\review\editor012_teacher_anchor_rescue\x.json"
        )


def test_frozen_source_commits():
    assert EDITOR012_RESULTS_COMMIT == "4bcf522a502ed98e5dd393a80bd9da7fffd51964"
    assert EDITOR013_RESULTS_COMMIT == "09c4bb97b143810147feef08f31a8d8d042a6726"
    assert EDITOR014_RESULTS_COMMIT == "c3343462dc3b35d20907da6ad017f5f853852f84"
    assert TEACHER_GUIDANCE_VS_INITIALISATION == "SUPPORTED_STRONG"


def test_lambdas_frozen():
    assert LAMBDA_DISTILL == 0.5
    assert LAMBDA_RESIDUAL_TEACHER == 0.5
    assert LAMBDA_ROUTE == 0.5
    assert PROMOTION_MARGIN == 0.001


def test_previous_residual_initial_odst_gradient_is_zero():
    audit = previous_residual_gradient_audit()
    assert audit["PREVIOUS_RESIDUAL_ODST_INITIAL_GRADIENT"] == "ZERO"
    assert float(HybridAlpha().alpha.item()) == 0.0
    assert float(ResidualBeta().beta.item()) == 0.0


def test_function_preserving_residual_initial_output_zero_and_odst_grad_nonzero():
    proof = function_preserving_residual_proof()
    assert proof["FUNCTION_PRESERVING_RESIDUAL_INITIAL_OUTPUT"] == "ZERO"
    assert proof["FUNCTION_PRESERVING_RESIDUAL_INITIAL_EQUALS_L1"] is True
    assert proof["FUNCTION_PRESERVING_RESIDUAL_INITIAL_ODST_GRADIENT"] == "NONZERO"
    assert proof["odst_grad_l2"] > 0
    assert proof["reference_odst_grad_l1"] == 0.0


def test_frozen_reference_odst_receives_no_gradient():
    student = build_odst046_model()
    modules = make_modules()
    modules.attach_reference(student.node_head)
    x = torch.randn(4, 20, 13)
    y = torch.tensor([0.0, 1.0, 0.0, 1.0])
    out = editor015_forward(student, x, modules)
    out["logit"].sum().backward()
    for p in modules.reference_odst.parameters():
        assert p.grad is None
        assert p.requires_grad is False


def test_teacher_residual_target_is_ensemble_minus_l1():
    src = Path("src/editor015_residual/train.py").read_text(encoding="utf-8")
    assert "ens.detach() - frozen_l1.detach()" in src
    assert "LAMBDA_RESIDUAL_TEACHER" in src
    assert "historical_c5" not in src.lower() or "must remain retired" in src


def test_historical_c5_single_teacher_logit_anchor_absent():
    src = Path("src/editor015_residual/train.py").read_text(encoding="utf-8")
    assert "LAMBDA_HISTORICAL_SINGLE_TEACHER_LOGIT != 0.0" in src
    assert "historical_c5_logit_consistency" not in src
    camp = Path("src/editor015_residual/constants.py").read_text(encoding="utf-8")
    assert "LAMBDA_DISTILL = 0.5" in camp
    assert "LAMBDA_RESIDUAL_TEACHER = 0.5" in camp


def test_lambda_route_only_where_declared():
    src = Path("src/editor015_residual/train.py").read_text(encoding="utf-8")
    assert 'if spec.get("route")' in src
    assert "LAMBDA_ROUTE" in src
    assert RESIDUAL_ROUTE_OFF_IN_R0_R1()


def RESIDUAL_ROUTE_OFF_IN_R0_R1() -> bool:
    from editor015_residual.constants import RESIDUAL_CONDITIONS

    assert RESIDUAL_CONDITIONS["R0"]["route"] is False
    assert RESIDUAL_CONDITIONS["R1"]["route"] is False
    assert RESIDUAL_CONDITIONS["R2"]["route"] is True
    return True


def test_c0_c1_weights_exactly_half():
    rng = np.random.default_rng(0)
    y = np.array([0, 1, 0, 1, 0, 0, 1, 0])
    l1 = rng.normal(size=8)
    ta2 = rng.normal(size=8)
    combos = fixed_combinations(y, l1, ta2)
    assert combos["C0"]["weights"] == [0.5, 0.5]
    assert combos["C1"]["weights"] == [0.5, 0.5]
    assert np.allclose(combos["C0"]["logits"], 0.5 * l1 + 0.5 * ta2)


def test_rank_average_implementation_deterministic():
    x = np.array([3.0, 1.0, 2.0, 2.0])
    a = percentile_rank(x)
    b = percentile_rank(x)
    assert np.allclose(a, b)
    assert a[1] == 0.0
    assert a[0] == 1.0


def test_r3_equivalent_to_r1_under_frozen_l1():
    l1 = torch.randn(16)
    r = torch.randn(16)
    ens = torch.randn(16)
    assert r3_equivalent_to_r1_if_l1_frozen(l1, r, ens) is True


def test_inner_selection_cannot_use_official_validation():
    enter_inner_phase()
    try:
        with pytest.raises(Editor015Blocked, match="inner"):
            refuse_official_validation_during_inner(
                r"C:\PhD\07_Projects\cert-r42-feasibility\data\processed\r5.2\tensors\r52_T20_s1_validation.npz"
            )
    finally:
        exit_inner_phase()


def test_promotion_commit_precedes_validation_evaluation():
    with pytest.raises(Editor015Blocked, match="promotion"):
        refuse_validation_before_promotion("review/editor015_residual_complementarity/03_validation_confirmation/x.csv")


def test_bootstrap_resamples_users_not_windows():
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


def test_directional_references_train_only_and_same_sign_controls():
    src = Path("src/editor015_residual/explain.py").read_text(encoding="utf-8")
    assert "r5.2 TRAIN only" in src or "TRAIN only" in src
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


def test_promotion_limit_and_margin():
    rows = [
        {"condition": "L1", "select_PR_AUC": 0.90, "select_F1": 0.8, "executed": True},
        {"condition": "TA2", "select_PR_AUC": 0.91, "select_F1": 0.8, "executed": True},
        {"condition": "R0", "select_PR_AUC": 0.902, "select_F1": 0.81, "executed": True, "final_distill": True, "residual_teacher": False, "route": False},
        {"condition": "R1", "select_PR_AUC": 0.905, "select_F1": 0.82, "executed": True, "final_distill": False, "residual_teacher": True, "route": False},
        {"condition": "R2", "select_PR_AUC": 0.899, "select_F1": 0.7, "executed": True, "final_distill": False, "residual_teacher": True, "route": True},
    ]
    dec = decide_promotions(rows)
    assert dec["n_promoted"] <= 2
    assert dec["official_r52_validation_not_used_for_selection"] is True
    assert all(p["delta_vs_L1"] >= PROMOTION_MARGIN for p in dec["promoted"])
    assert "R2" not in dec["eligible_before_cap"]
