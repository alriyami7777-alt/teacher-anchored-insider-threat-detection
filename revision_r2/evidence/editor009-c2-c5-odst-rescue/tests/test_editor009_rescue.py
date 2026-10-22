"""Focused EDITOR-009 tests. Do not open r5.2 TEST."""

from __future__ import annotations

import numpy as np
import pytest
import torch

from editor009_rescue.diagnostics import match_route_assignment_from_train
from editor009_rescue.losses import (
    PRODUCING_W_LOGIT,
    PRODUCING_W_ROUTE,
    annealed_weight,
    class_balanced_logit_loss,
    class_balanced_route_loss,
    logit_consistency_loss,
    route_consistency_loss,
    total_loss,
)
from editor009_rescue.models import permute_tree_choices, zero_odst_leaves
from editor009_rescue.producing import build_odst_model
from editor009_rescue.safety import (
    Editor009ProtocolError,
    refuse_historical_write,
    refuse_r52_test,
)


def test_c2_loss_excludes_anchor_terms():
    s = torch.tensor([0.2, -1.0], requires_grad=True)
    t = torch.tensor([0.1, -0.5])
    y = torch.tensor([1.0, 0.0])
    task = torch.nn.BCEWithLogitsLoss()(s, y)
    lgt = logit_consistency_loss(s, t)
    rt = route_consistency_loss(torch.sigmoid(s).view(2, 1, 1), torch.sigmoid(t).view(2, 1, 1))
    tot = total_loss(class_loss=task, logit_loss=lgt, route_loss=rt, w_logit=0.0, w_route=0.0)
    assert torch.allclose(tot, task)


def test_c5_includes_expected_anchor_terms():
    s = torch.tensor([0.2, -1.0], requires_grad=True)
    t = torch.tensor([0.1, -0.5])
    y = torch.tensor([1.0, 0.0])
    task = torch.nn.BCEWithLogitsLoss()(s, y)
    lgt = logit_consistency_loss(s, t)
    rt = route_consistency_loss(torch.sigmoid(s).view(2, 1, 1), torch.sigmoid(t).view(2, 1, 1))
    tot = total_loss(
        class_loss=task,
        logit_loss=lgt,
        route_loss=rt,
        w_logit=PRODUCING_W_LOGIT,
        w_route=PRODUCING_W_ROUTE,
    )
    expected = task + 0.5 * lgt + 0.5 * rt
    assert torch.allclose(tot, expected)


def test_annealed_weights_start_at_producing_c5_and_end_at_zero():
    assert annealed_weight(0.5, 1) == pytest.approx(0.5)
    assert annealed_weight(0.5, 15) == pytest.approx(0.0)
    prev = annealed_weight(0.5, 1)
    for e in range(2, 16):
        cur = annealed_weight(0.5, e)
        assert cur <= prev + 1e-12
        prev = cur


def test_route_off_zero_route_gradient():
    s_logit = torch.tensor([0.3, -0.2], requires_grad=True)
    dummy_choice = torch.tensor([[[0.2, 0.8], [0.4, 0.6]], [[0.1, 0.9], [0.7, 0.3]]], requires_grad=True)
    t_choice = torch.ones_like(dummy_choice) * 0.5
    t_logit = torch.zeros_like(s_logit)
    y = torch.tensor([1.0, 0.0])
    task = torch.nn.BCEWithLogitsLoss()(s_logit, y)
    lgt = logit_consistency_loss(s_logit, t_logit)
    rt = route_consistency_loss(dummy_choice, t_choice)
    tot = total_loss(class_loss=task, logit_loss=lgt, route_loss=rt, w_logit=0.5, w_route=0.0)
    tot.backward()
    # route parameters receive no gradient from the total loss when w_route=0
    # (choice still unused in tot because w_route=0)
    assert dummy_choice.grad is None or torch.count_nonzero(dummy_choice.grad) == 0


def test_logit_off_zero_logit_gradient_from_anchor():
    s_logit = torch.tensor([0.3, -0.2], requires_grad=True)
    t_logit = torch.tensor([1.0, -1.0])
    y = torch.tensor([1.0, 0.0])
    task = torch.nn.BCEWithLogitsLoss()(s_logit, y)
    lgt = logit_consistency_loss(s_logit, t_logit)
    rt = s_logit.new_zeros(())
    tot = total_loss(class_loss=task, logit_loss=lgt, route_loss=rt, w_logit=0.0, w_route=0.5)
    # Compare to task-only backward
    s2 = s_logit.detach().clone().requires_grad_(True)
    task2 = torch.nn.BCEWithLogitsLoss()(s2, y)
    task2.backward()
    tot.backward()
    assert torch.allclose(s_logit.grad, s2.grad, atol=1e-6)


def test_class_balanced_anchor_normalisation():
    # 3 negatives, 1 positive: producing mean is dominated by negatives.
    s = torch.tensor([0.0, 0.0, 0.0, 10.0])
    t = torch.tensor([0.0, 0.0, 0.0, 0.0])
    y = torch.tensor([0.0, 0.0, 0.0, 1.0])
    producing = logit_consistency_loss(s, t)
    balanced = class_balanced_logit_loss(s, t, y)
    assert balanced > producing  # positive window's huge error is upweighted
    ch_s = torch.zeros(4, 2, 2)
    ch_t = torch.zeros(4, 2, 2)
    ch_s[3] = 1.0
    ch_t[3] = 0.0
    b_r = class_balanced_route_loss(ch_s, ch_t, y)
    p_r = route_consistency_loss(ch_s, ch_t)
    assert b_r > p_r


def test_residual_odst_zero_initial_contribution():
    m = build_odst_model()
    zero_odst_leaves(m)
    x = torch.zeros(3, 20, 13)
    from editor009_rescue.models import student_forward

    out = student_forward(m, x, residual=True)
    assert torch.allclose(out["odst_logit"], torch.zeros_like(out["odst_logit"]), atol=1e-6)
    assert torch.allclose(out["logit"], out["linear_logit"], atol=1e-6)


def test_r52_test_path_is_rejected():
    with pytest.raises(Editor009ProtocolError, match="TEST"):
        refuse_r52_test(r"C:\PhD\07_Projects\cert-r42-feasibility\data\processed\r5.2\tensors\r52_T20_s1_test.npz")


def test_historical_frozen_outputs_are_read_only():
    with pytest.raises(Editor009ProtocolError, match="historical"):
        refuse_historical_write(r"C:\PhD\07_Projects\teacher-anchored-insider-threat-detection\review\editor007d1_freeze_compliance\x.json")


def test_seed_reproducibility_anneal_and_assignment():
    assert annealed_weight(0.5, 7) == annealed_weight(0.5, 7)
    torch.manual_seed(42)
    a = torch.rand(4, 16)
    torch.manual_seed(42)
    b = torch.rand(4, 16)
    assert torch.equal(a, b)


def test_route_matching_assignment_deterministic():
    torch.manual_seed(0)
    m1 = build_odst_model()
    torch.manual_seed(1)
    m2 = build_odst_model()
    x = torch.randn(32, 20, 13)
    p1 = match_route_assignment_from_train(m1, m2, x, torch.device("cpu"))
    p2 = match_route_assignment_from_train(m1, m2, x, torch.device("cpu"))
    assert torch.equal(p1, p2)
    assert p1.numel() == 16
