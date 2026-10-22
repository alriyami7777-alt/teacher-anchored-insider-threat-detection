"""Focused EDITOR-011 identity and fairness tests. Do not open r5.2 TEST."""

from __future__ import annotations

import torch
import pytest

from editor011_confirmation.constants import (
    ENCODER_ARCH,
    LAMBDA_LOGIT_C2,
    LAMBDA_LOGIT_R2,
    LAMBDA_ROUTE_C2,
    LAMBDA_ROUTE_R2,
    ODST046,
)
from editor011_confirmation.losses import (
    logit_consistency_loss,
    route_consistency_loss,
    total_loss,
)
from editor011_confirmation.models import (
    architecture_identity,
    assert_odst046,
    assert_teacher_student_match,
)
from editor011_confirmation.producing import build_odst046_model
from editor011_confirmation.safety import (
    Editor011ProtocolError,
    refuse_historical_write,
    refuse_r52_test,
)


def test_r52_test_path_is_rejected():
    with pytest.raises(Editor011ProtocolError, match="TEST"):
        refuse_r52_test(
            r"C:\PhD\07_Projects\cert-r42-feasibility\data\processed\r5.2\tensors\r52_T20_s1_test.npz"
        )


def test_historical_editor009_010_packets_are_read_only():
    with pytest.raises(Editor011ProtocolError, match="historical"):
        refuse_historical_write(
            r"C:\PhD\07_Projects\teacher-anchored-insider-threat-detection\review\editor009_c2_c5_odst_rescue\x.json"
        )
    with pytest.raises(Editor011ProtocolError, match="historical"):
        refuse_historical_write(
            r"C:\PhD\07_Projects\teacher-anchored-insider-threat-detection-editor010\review\editor010_capacity_objective_teacher_rescue\x.json"
        )


def test_odst046_lock_matches_frozen_grid():
    assert ODST046["n_trees"] == 4
    assert ODST046["depth"] == 4
    assert ODST046["temperature"] == 0.5
    assert ODST046["lr"] == 0.001
    assert ODST046["weight_decay"] == 0.0
    assert ENCODER_ARCH["node_n_trees"] == 4
    assert ENCODER_ARCH["node_depth"] == 4
    assert ENCODER_ARCH["node_temperature"] == 0.5


def test_c2_and_r2_lambda_identities():
    assert LAMBDA_LOGIT_C2 == 0.0
    assert LAMBDA_ROUTE_C2 == 0.0
    assert LAMBDA_LOGIT_R2 == 0.0
    assert LAMBDA_ROUTE_R2 == 0.5


def test_route_loss_returns_exactly_zero_contribution_when_disabled():
    s = torch.tensor([0.2, -1.0], requires_grad=True)
    t = torch.tensor([0.1, -0.5])
    y = torch.tensor([1.0, 0.0])
    task = torch.nn.BCEWithLogitsLoss()(s, y)
    lgt = logit_consistency_loss(s, t)
    rt = route_consistency_loss(torch.sigmoid(s).view(2, 1, 1), torch.sigmoid(t).view(2, 1, 1))
    tot = total_loss(class_loss=task, logit_loss=lgt, route_loss=rt, w_logit=0.0, w_route=0.0)
    assert torch.allclose(tot, task)


def test_r2_excludes_logit_anchor_from_total_loss():
    s = torch.tensor([0.2, -1.0], requires_grad=True)
    t = torch.tensor([0.1, -0.5])
    y = torch.tensor([1.0, 0.0])
    task = torch.nn.BCEWithLogitsLoss()(s, y)
    lgt = logit_consistency_loss(s, t)
    rt = route_consistency_loss(torch.sigmoid(s).view(2, 1, 1), torch.sigmoid(t).view(2, 1, 1))
    tot = total_loss(class_loss=task, logit_loss=lgt, route_loss=rt, w_logit=0.0, w_route=0.5)
    expected = task + 0.5 * rt
    assert torch.allclose(tot, expected)


def test_disabled_route_contributes_zero_to_total():
    s = torch.tensor([0.3, -0.2], requires_grad=True)
    dummy_choice = torch.tensor([[[0.2, 0.8], [0.4, 0.6]], [[0.1, 0.9], [0.7, 0.3]]], requires_grad=True)
    t_choice = torch.ones_like(dummy_choice) * 0.5
    t_logit = torch.zeros_like(s)
    y = torch.tensor([1.0, 0.0])
    task = torch.nn.BCEWithLogitsLoss()(s, y)
    lgt = logit_consistency_loss(s, t_logit)
    rt = route_consistency_loss(dummy_choice, t_choice)
    tot = total_loss(class_loss=task, logit_loss=lgt, route_loss=rt, w_logit=0.0, w_route=0.0)
    tot.backward()
    assert dummy_choice.grad is None or torch.count_nonzero(dummy_choice.grad) == 0


def test_teacher_student_odst046_architecture_and_route_shape():
    teacher = build_odst046_model()
    student = build_odst046_model()
    assert_odst046(teacher)
    assert_odst046(student)
    assert_teacher_student_match(teacher, student)
    ident = architecture_identity(teacher)
    assert ident["n_trees"] == 4
    assert ident["depth"] == 4
    assert ident["n_trees_total"] == 8
    x = torch.zeros(3, 20, 13)
    from editor011_confirmation.models import student_forward

    out_t = student_forward(teacher, x)
    out_s = student_forward(student, x)
    assert tuple(out_t["choices"].shape) == (3, 8, 4)
    assert tuple(out_s["choices"].shape) == tuple(out_t["choices"].shape)
    assert tuple(out_t["leaf_probs_all"].shape) == (3, 8, 16)


def test_tree_index_correspondence_after_clone():
    teacher = build_odst046_model()
    student = build_odst046_model()
    student.load_state_dict(teacher.state_dict())
    teacher.eval()
    student.eval()
    x = torch.randn(4, 20, 13)
    from editor011_confirmation.models import student_forward

    t = student_forward(teacher, x)
    s = student_forward(student, x)
    assert torch.allclose(t["choices"], s["choices"], atol=1e-6)
    assert torch.allclose(t["logit"], s["logit"], atol=1e-6)
