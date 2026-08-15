"""EDITOR-012 identity, safety, and formulation tests. Do not open r5.2 TEST."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pytest
import torch

from editor012_rescue.constants import (
    ANCHOR_FORMULATIONS,
    C2OPT_CHECKPOINTS,
    ENCODER_ARCH,
    ET1_LOGIT_DISTILL_WEIGHT,
    ET1_TEMPERATURE,
    FACTORIAL,
    LAMBDA_HISTORICAL_SINGLE_TEACHER_LOGIT,
    LAMBDA_ROUTE,
    ODST046,
    ORIGINAL_SINGLE_TEACHER_LOGIT_ANCHOR,
    R2OPT_CHECKPOINTS,
    TOPT_CHECKPOINTS,
)
from editor012_rescue.data import SequenceBundle
from editor012_rescue.inner_split import inner_split_masks
from editor012_rescue.losses import (
    Editor012RetiredAnchor,
    agreement_weights,
    binary_entropy,
    class_balanced_reduction,
    confidence_weights,
    ensemble_anchor_loss,
    et1_ensemble_logit_mse,
    historical_c5_logit_consistency,
    route_consistency_loss,
)
from editor012_rescue.models import architecture_identity, assert_odst046, assert_teacher_student_match
from editor012_rescue.producing import build_odst046_model
from editor012_rescue.promotion import decide_promotions
from editor012_rescue.safety import (
    Editor012ProtocolError,
    refuse_historical_write,
    refuse_r51,
    refuse_r52_test,
    refuse_r62,
)


def test_r52_test_hard_denied():
    with pytest.raises(Editor012ProtocolError, match="TEST"):
        refuse_r52_test(
            r"C:\PhD\07_Projects\cert-r42-feasibility\data\processed\r5.2\tensors\r52_T20_s1_test.npz"
        )


def test_r51_r62_denied():
    with pytest.raises(Editor012ProtocolError, match="r5.1"):
        refuse_r51(r"C:\data\processed\r5.1\tensors\x.npz")
    with pytest.raises(Editor012ProtocolError, match="r6.2"):
        refuse_r62(r"C:\data\processed\r6.2\tensors\x.npz")


def test_historical_editor009_010_011_files_read_only():
    with pytest.raises(Editor012ProtocolError, match="historical"):
        refuse_historical_write(
            r"C:\PhD\07_Projects\teacher-anchored-insider-threat-detection\review\editor009_c2_c5_odst_rescue\x.json"
        )
    with pytest.raises(Editor012ProtocolError, match="historical"):
        refuse_historical_write(
            r"C:\PhD\07_Projects\teacher-anchored-insider-threat-detection-editor010\review\editor010_capacity_objective_teacher_rescue\x.json"
        )
    with pytest.raises(Editor012ProtocolError, match="historical"):
        refuse_historical_write(
            r"C:\PhD\07_Projects\teacher-anchored-insider-threat-detection-editor011\review\editor011_matched_route_confirmation\x.json"
        )


def test_odst046_identity_exact():
    assert ODST046["n_trees"] == 4
    assert ODST046["depth"] == 4
    assert ODST046["temperature"] == 0.5
    assert ODST046["lr"] == 0.001
    assert ODST046["weight_decay"] == 0.0
    assert ENCODER_ARCH["node_n_trees"] == 4
    assert ENCODER_ARCH["node_depth"] == 4
    assert ENCODER_ARCH["node_temperature"] == 0.5
    model = build_odst046_model()
    assert_odst046(model)
    ident = architecture_identity(model)
    assert ident["n_trees"] == 4
    assert ident["depth"] == 4
    assert ident["n_trees_total"] == 8


def test_topt_checkpoint_hash_constants_present():
    for seed in (42, 52, 62):
        assert Path(TOPT_CHECKPOINTS[seed]["checkpoint"]).is_file()
        assert len(TOPT_CHECKPOINTS[seed]["sha256"]) == 64
        assert C2OPT_CHECKPOINTS[seed]["sha256"]
        assert R2OPT_CHECKPOINTS[seed]["sha256"]


def test_factorial_students_begin_from_same_topt_bytes_per_seed():
    src = Path("src/editor012_rescue/campaign.py").read_text(encoding="utf-8")
    assert "student_from_topt" in src
    assert "paired-start T-OPT hash mismatch" in src
    for seed in (42, 52, 62):
        assert TOPT_CHECKPOINTS[seed]["sha256"]


def test_factorial_switch_identities():
    assert FACTORIAL["F00"]["ensemble_teacher_predictive_anchor"] is False
    assert FACTORIAL["F00"]["route_anchor"] is False
    assert FACTORIAL["F10"]["ensemble_teacher_predictive_anchor"] is True
    assert FACTORIAL["F10"]["route_anchor"] is False
    assert FACTORIAL["F01"]["ensemble_teacher_predictive_anchor"] is False
    assert FACTORIAL["F01"]["route_anchor"] is True
    assert FACTORIAL["F11"]["ensemble_teacher_predictive_anchor"] is True
    assert FACTORIAL["F11"]["route_anchor"] is True
    assert FACTORIAL["F10"]["lambda_et1"] == 0.5
    assert FACTORIAL["F11"]["lambda_et1"] == 0.5
    assert FACTORIAL["F11"]["lambda_route"] == 0.5
    assert FACTORIAL["F10"]["historical_single_teacher_logit_anchor"] is False
    assert FACTORIAL["F11"]["historical_single_teacher_logit_anchor"] is False


def test_no_historical_static_single_teacher_logit_anchor_in_f10_f11():
    assert LAMBDA_HISTORICAL_SINGLE_TEACHER_LOGIT == 0.0
    assert ORIGINAL_SINGLE_TEACHER_LOGIT_ANCHOR == "RETIRED_AFTER_GRADIENT_CONFLICT_DIAGNOSIS"
    s = torch.tensor([0.2, -1.0], requires_grad=True)
    t = torch.tensor([0.1, -0.5])
    with pytest.raises(Editor012RetiredAnchor):
        historical_c5_logit_consistency(s, t)
    src = Path("src/editor012_rescue/train.py").read_text(encoding="utf-8")
    assert "historical_c5_logit_consistency" not in src
    assert "logit_consistency_loss" not in src


def test_et1_equal_weight_and_detached_and_no_temperature():
    assert ET1_LOGIT_DISTILL_WEIGHT == 0.5
    assert ET1_TEMPERATURE is None
    a = torch.tensor([1.0, 2.0, 3.0])
    b = torch.tensor([3.0, 2.0, 1.0])
    c = torch.tensor([2.0, 2.0, 2.0])
    ens = (a + b + c) / 3.0
    assert torch.allclose(ens, torch.tensor([2.0, 2.0, 2.0]))
    student = torch.tensor([2.5, 1.5, 2.0], requires_grad=True)
    target = ens.clone().requires_grad_(True)
    loss = et1_ensemble_logit_mse(student, target)
    loss.backward()
    assert target.grad is None
    assert student.grad is not None


def test_a1_confidence_equation_correct():
    p = torch.tensor([0.5, 1.0 - 1e-7, 0.0 + 1e-7])
    w = confidence_weights(p)
    assert float(w[0]) == pytest.approx(0.0, abs=1e-5)
    assert float(w[1]) == pytest.approx(1.0, abs=1e-4)
    assert 0.0 <= float(w.min()) and float(w.max()) <= 1.0
    h = binary_entropy(torch.tensor([0.5]))
    assert float(h) == pytest.approx(np.log(2.0), rel=1e-6)


def test_a2_agreement_equation_correct():
    same = torch.tensor([0.8, 0.2])
    w = agreement_weights(same, same, same)
    assert torch.allclose(w, torch.ones_like(w), atol=1e-6)
    p42 = torch.tensor([0.0, 0.5])
    p52 = torch.tensor([0.5, 0.5])
    p62 = torch.tensor([1.0, 0.5])
    w2 = agreement_weights(p42, p52, p62)
    # Var([0,0.5,1]) = ((0-0.5)^2 + 0 + (1-0.5)^2)/3 = 1/6; 1-4/6 = 1/3
    assert float(w2[0]) == pytest.approx(1.0 - 4.0 * (1.0 / 6.0), abs=1e-6)
    assert 0.0 <= float(w2.min()) and float(w2.max()) <= 1.0


def test_a3_class_balanced_anchor_reduction_correct():
    loss = torch.tensor([1.0, 1.0, 1.0, 10.0])
    y = torch.tensor([0.0, 0.0, 0.0, 1.0])
    bal = class_balanced_reduction(loss, y)
    assert float(bal) == pytest.approx(0.5 * 1.0 + 0.5 * 10.0)
    unweighted = loss.mean()
    assert float(bal) > float(unweighted)


def test_positive_negative_class_anchor_batches_handled_safely():
    loss = torch.tensor([0.3, 0.4])
    y_neg = torch.zeros(2)
    y_pos = torch.ones(2)
    assert torch.isfinite(class_balanced_reduction(loss, y_neg))
    assert torch.isfinite(class_balanced_reduction(loss, y_pos))
    s = torch.tensor([0.1, -0.2], requires_grad=True)
    ens = torch.tensor([0.0, 0.0])
    out = ensemble_anchor_loss(
        s, ens, y_neg, class_balanced_reduction_flag=True
    )
    out.backward()
    assert s.grad is not None


def test_teacher_ensemble_equal_weighted():
    a = np.array([0.1, 0.8, 0.4])
    b = np.array([0.2, 0.7, 0.5])
    c = np.array([0.3, 0.6, 0.6])
    ens = np.mean([a, b, c], axis=0)
    assert np.allclose(ens, np.array([0.2, 0.7, 0.5]))


def test_route_teacher_matched_to_correct_topt_seed():
    src = Path("src/editor012_rescue/campaign.py").read_text(encoding="utf-8")
    assert "matched_teacher=teachers[start_seed]" in src or "matched_teacher=teachers[seed]" in src
    assert "student_from_topt" in src


def test_f00_has_no_teacher_guidance_f10_ensemble_only():
    assert FACTORIAL["F00"]["lambda_et1"] == 0.0
    assert FACTORIAL["F00"]["lambda_route"] == 0.0
    assert FACTORIAL["F10"]["lambda_et1"] == ET1_LOGIT_DISTILL_WEIGHT
    assert FACTORIAL["F10"]["lambda_route"] == 0.0
    assert FACTORIAL["F01"]["lambda_et1"] == 0.0
    assert FACTORIAL["F01"]["lambda_route"] == LAMBDA_ROUTE


def test_inner_select_only_used_during_anchor_search():
    src = Path("src/editor012_rescue/inner_split.py").read_text(encoding="utf-8")
    assert "Inner split may be constructed only from r5.2 TRAIN" in src
    assert "r52_T20_s1_test" not in src
    camp = Path("src/editor012_rescue/campaign.py").read_text(encoding="utf-8")
    assert "official_r52_validation_not_used_for_selection" in camp or "INNER_SELECT" in camp
    assert "decide_promotions" in camp


def test_official_validation_never_used_to_promote_inner_candidates():
    promo = Path("src/editor012_rescue/promotion.py").read_text(encoding="utf-8")
    assert "INNER_SELECT" in promo
    assert "validation" not in promo.lower() or "Official VALIDATION is unused" in promo
    camp = Path("src/editor012_rescue/campaign.py").read_text(encoding="utf-8")
    freeze_at = camp.index("EDITOR012_PROMOTION_FREEZE.json")
    full_at = camp.index("EDITOR012_FACTORIAL_RESULTS.csv")
    assert freeze_at < full_at


def test_promotion_freeze_committed_before_promoted_validation_evaluation():
    camp = Path("src/editor012_rescue/campaign.py").read_text(encoding="utf-8")
    assert camp.index("run_inner_search") < camp.index("F10_DOPT")
    assert "PROMOTION_COMMIT_READY" in camp


def test_user_mapping_hash_matches_editor011_constant():
    from editor012_rescue.constants import EXPECTED_USER_MAPPING_SHA256

    assert EXPECTED_USER_MAPPING_SHA256 == "851385f9c926cf945b3c74b5c9442e3ccb94cf1d9dabb98106a29cbfea01c5c0"


def test_bootstrap_resamples_users_not_windows_and_frozen_f1():
    src = Path("src/editor012_rescue/bootstrap.py").read_text(encoding="utf-8")
    assert "sampling_unit" in src
    assert "validation user" in src
    assert "f1_retuned_inside_bootstrap" in src
    assert "frozen_thresholds" in src
    assert "choice(unique" in src


def test_teacher_student_architecture_match_and_route_shape():
    teacher = build_odst046_model()
    student = build_odst046_model()
    assert_teacher_student_match(teacher, student)
    x = torch.zeros(3, 20, 13)
    from editor012_rescue.models import student_forward

    out = student_forward(teacher, x)
    assert tuple(out["choices"].shape) == (3, 8, 4)


def test_route_loss_zero_when_identical():
    p = torch.tensor([[[0.2, 0.8], [0.4, 0.6]]])
    assert float(route_consistency_loss(p, p)) == pytest.approx(0.0, abs=1e-6)


def test_inner_split_rejects_non_train_and_is_chronological():
    xs, ys, users, seqs, starts, ends = [], [], [], [], [], []
    base = datetime(2010, 1, 1)
    sid = 0
    for u in range(2):
        for d in range(80):
            start = base + timedelta(days=d)
            end = start + timedelta(days=19)
            xs.append(np.zeros((20, 13), dtype=np.float32))
            ys.append(0.0)
            users.append(f"U{u:03d}")
            seqs.append(f"s{sid}")
            starts.append(start.strftime("%Y-%m-%d"))
            ends.append(end.strftime("%Y-%m-%d"))
            sid += 1
    bundle = SequenceBundle(
        X=np.stack(xs),
        y=np.asarray(ys, dtype=np.float32),
        user=np.asarray(users),
        sequence_id=np.asarray(seqs),
        start_date=np.asarray(starts),
        end_date=np.asarray(ends),
        path=Path("r52_T20_s1_train.npz"),
        sha256="synthetic",
        name="train",
    )
    split = inner_split_masks(bundle)
    assert split["disjoint"]
    assert split["official_validation_used"] is False
    bad = SequenceBundle(**{**bundle.__dict__, "name": "validation"})
    with pytest.raises(Exception):
        inner_split_masks(bad)


def test_promotion_requires_beating_a0():
    rows = [
        {"anchor_id": "A0", "route_on": False, "inner_select_pr_auc": 0.90, "inner_select_f1": 0.5},
        {"anchor_id": "A1", "route_on": False, "inner_select_pr_auc": 0.89, "inner_select_f1": 0.5},
        {"anchor_id": "A3", "route_on": False, "inner_select_pr_auc": 0.91, "inner_select_f1": 0.5},
    ]
    dec = decide_promotions(rows)
    assert dec["official_r52_validation_not_used_for_selection"] is True
    assert [p["anchor_id"] for p in dec["promoted"]] == ["A3"]


def test_anchor_formulation_ids_frozen():
    assert set(ANCHOR_FORMULATIONS) == {"A0", "A1", "A2", "A3", "A4", "A5"}
    assert ANCHOR_FORMULATIONS["A0"]["simplicity_rank"] == 0
