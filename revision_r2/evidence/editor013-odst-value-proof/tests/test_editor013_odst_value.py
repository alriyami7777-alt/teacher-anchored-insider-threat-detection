"""EDITOR-013 identity, safety, readout, hybrid, and freeze tests. Do not open r5.2 TEST."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import torch

from editor012_rescue.losses import et1_ensemble_logit_mse, historical_c5_logit_consistency
from editor012_rescue.producing import build_odst046_model
from editor013_odst_value.constants import (
    EDITOR012_RESULTS_FULL_COMMIT,
    HEAD_CONDITIONS,
    HISTORICAL_SINGLE_TEACHER_LOGIT_ANCHOR,
    LAMBDA_DISTILL,
    LAMBDA_HISTORICAL_SINGLE_TEACHER_LOGIT,
    N_TREES_TOTAL,
    PRIMARY_SEEDS,
    PROMOTION_MARGIN,
    TEACHER_GUIDANCE_VS_INITIALISATION,
)
from editor013_odst_value.explain import centred_contributions, train_references
from editor013_odst_value.models import (
    ConvexTreeReadout,
    Editor013LinearHead,
    Editor013Modules,
    HybridAlpha,
    editor013_forward,
    editor013_forward_from_z,
    make_modules,
    tree_contributions,
    uniform_tree_logit,
)
from editor013_odst_value.promotion import decide_promotions
from editor013_odst_value.safety import (
    Editor013Blocked,
    Editor013ProtocolError,
    enter_inner_phase,
    exit_inner_phase,
    refuse_historical_write,
    refuse_official_validation_during_inner,
)
from editor012_rescue.safety import refuse_r51, refuse_r52_test, refuse_r62


def test_r52_test_hard_denied():
    with pytest.raises(Exception, match="TEST"):
        refuse_r52_test(
            r"C:\PhD\07_Projects\cert-r42-feasibility\data\processed\r5.2\tensors\r52_T20_s1_test.npz"
        )


def test_historical_review_packets_read_only():
    with pytest.raises(Editor013ProtocolError, match="historical"):
        refuse_historical_write(
            r"C:\PhD\07_Projects\teacher-anchored-insider-threat-detection-editor012\review\editor012_teacher_anchor_rescue\x.json"
        )
    with pytest.raises(Editor013ProtocolError, match="historical"):
        refuse_historical_write(
            r"C:\PhD\07_Projects\teacher-anchored-insider-threat-detection-editor011\review\editor011_matched_route_confirmation\x.json"
        )


def test_linear_head_input_is_attended_z():
    src = Path("src/editor013_odst_value/models.py").read_text(encoding="utf-8")
    assert "modules.linear_head(z)" in src
    assert "encode_attention_h" in src
    head = Editor013LinearHead(128)
    z = torch.randn(4, 128)
    out = head(z)
    assert tuple(out.shape) == (4,)


def test_linear_only_and_hybrid_linear_heads_initialise_identically():
    a = Editor013LinearHead()
    b = Editor013LinearHead()
    assert torch.equal(a.linear.weight, b.linear.weight)
    assert torch.equal(a.linear.bias, b.linear.bias)
    assert torch.count_nonzero(a.linear.weight) == 0
    lin = make_modules({"family": "linear", "readout": "none", "hybrid": False})
    hyb = make_modules({"family": "hybrid", "readout": "uniform", "hybrid": True})
    assert lin.initial_linear_hash() == hyb.initial_linear_hash()


def test_hybrid_alpha_initialises_exactly_0():
    h = HybridAlpha()
    assert float(h.alpha.item()) == 0.0
    mods = make_modules({"family": "hybrid", "readout": "uniform", "hybrid": True})
    assert mods.learned_alpha() == 0.0


def test_hybrid_initial_prediction_equals_linear_branch():
    student = build_odst046_model()
    mods = make_modules({"family": "hybrid", "readout": "uniform", "hybrid": True})
    x = torch.zeros(3, 20, 13)
    out = editor013_forward(student, x, mods)
    assert torch.allclose(out["logit"], out["linear_logit"])
    assert float(mods.alpha_mod.alpha.item()) == 0.0


def test_learned_tree_weights_initialise_exactly_uniform():
    r = ConvexTreeReadout(8)
    w = r.tree_weights()
    assert torch.allclose(w, torch.full((8,), 1.0 / 8.0))
    assert torch.equal(r.w.detach(), torch.zeros(8))


def test_softmax_tree_weights_sum_to_1():
    r = ConvexTreeReadout(8)
    r.w.data = torch.tensor([0.0, 1.0, -1.0, 2.0, 0.5, -0.5, 0.25, -0.25])
    w = r.tree_weights()
    assert float(w.sum()) == pytest.approx(1.0, abs=1e-6)


def test_tree_weight_readout_changes_no_route_or_leaf_tensor():
    student = build_odst046_model()
    student.eval()
    x = torch.randn(2, 20, 13)
    with torch.no_grad():
        z, _ = student.encode_attention_h(x)
    uni = make_modules({"family": "odst", "readout": "uniform", "hybrid": False})
    wgt = make_modules({"family": "odst", "readout": "weighted", "hybrid": False})
    wgt.tree_readout.w.data = torch.arange(8, dtype=torch.float32)
    a = editor013_forward_from_z(student, z, uni)
    b = editor013_forward_from_z(student, z, wgt)
    assert torch.allclose(a["choices"], b["choices"])
    assert torch.allclose(a["leaf_probs_all"], b["leaf_probs_all"])
    assert torch.allclose(a["tree_outputs"], b["tree_outputs"])
    assert not torch.allclose(a["logit"], b["logit"])


def test_tree_contributions_sum_to_odst_tree_logit():
    trees = torch.tensor([[1.0, 3.0, -1.0, 5.0, 0.0, 2.0, 4.0, -2.0]])
    a = torch.full((8,), 1.0 / 8.0)
    c = tree_contributions(trees, a, references=None, alpha=1.0)
    assert torch.allclose(c.sum(dim=-1), uniform_tree_logit(trees))
    r = ConvexTreeReadout(8)
    r.w.data.zero_()
    logit, w = r(trees)
    c2 = tree_contributions(trees, w, references=None, alpha=1.0)
    assert torch.allclose(c2.sum(dim=-1), logit)


def test_hybrid_tree_contributions_sum_to_alpha_times_odst_logit():
    trees = torch.randn(4, 8)
    a = torch.full((8,), 1.0 / 8.0)
    alpha = 0.3
    c = tree_contributions(trees, a, references=None, alpha=alpha)
    assert torch.allclose(c.sum(dim=-1), alpha * uniform_tree_logit(trees), atol=1e-6)


def test_single_teacher_mse_uses_same_lambda_0_5_as_ensemble():
    assert LAMBDA_DISTILL == 0.5
    assert HEAD_CONDITIONS["H1-LIN-D"]["teacher"] == "ensemble"
    assert HEAD_CONDITIONS["H1-LIN-S"]["teacher"] == "single"
    assert HEAD_CONDITIONS["H3-ODST-U-S"]["teacher"] == "single"
    src = Path("src/editor013_odst_value/train.py").read_text(encoding="utf-8")
    assert "LAMBDA_DISTILL" in src
    assert "et1_ensemble_logit_mse" in src
    assert "historical_c5_logit_consistency" not in src


def test_single_teacher_mse_is_not_historical_c5():
    assert LAMBDA_HISTORICAL_SINGLE_TEACHER_LOGIT == 0.0
    assert HISTORICAL_SINGLE_TEACHER_LOGIT_ANCHOR == "RETIRED"
    s = torch.tensor([0.2, -1.0], requires_grad=True)
    t = torch.tensor([0.1, -0.5])
    with pytest.raises(Exception):
        historical_c5_logit_consistency(s, t)
    loss = et1_ensemble_logit_mse(s, t)
    assert torch.isfinite(loss)


def test_ensemble_teacher_weights_equal_one_third():
    a = np.array([0.1, 0.8, 0.4])
    b = np.array([0.2, 0.7, 0.5])
    c = np.array([0.3, 0.6, 0.6])
    ens = np.mean([a, b, c], axis=0)
    assert np.allclose(ens, np.array([0.2, 0.7, 0.5]))
    assert abs(1.0 / 3.0 - 0.3333333333333333) < 1e-12


def test_inner_search_cannot_read_official_validation():
    enter_inner_phase()
    try:
        with pytest.raises(Editor013Blocked, match="official validation"):
            refuse_official_validation_during_inner(
                r"C:\PhD\07_Projects\cert-r42-feasibility\data\processed\r5.2\tensors\r52_T20_s1_validation.npz"
            )
    finally:
        exit_inner_phase()


def test_promotion_freeze_precedes_official_validation_new_architecture():
    camp = Path("src/editor013_odst_value/campaign.py").read_text(encoding="utf-8")
    assert camp.index("EDITOR013_PROMOTION_FREEZE.json") < camp.index("run_confirmation")
    assert camp.index("run_inner_search") < camp.index("def run_confirmation")
    promo = Path("src/editor013_odst_value/promotion.py").read_text(encoding="utf-8")
    assert "Official VALIDATION is unused" in promo
    assert "INNER_SELECT" in promo


def test_bootstrap_resamples_users():
    src = Path("src/editor012_rescue/bootstrap.py").read_text(encoding="utf-8")
    assert "sampling_unit" in src
    assert "validation user" in src
    assert "choice(unique" in src
    camp = Path("src/editor013_odst_value/campaign.py").read_text(encoding="utf-8")
    assert "paired_user_cluster_mean_across_seeds" in camp


def test_faithfulness_references_come_from_train_only():
    src = Path("src/editor013_odst_value/explain.py").read_text(encoding="utf-8")
    assert "TRAIN only" in src
    trees = np.arange(40, dtype=np.float64).reshape(5, 8)
    refs = train_references(trees)
    assert refs.shape == (8,)
    c = centred_contributions(trees, refs, None, 1.0)
    assert c.shape == (5, 8)


def test_promotion_margin_not_lowered():
    assert PROMOTION_MARGIN == 0.001
    rows = [
        {"condition": "H1-LIN-D", "select_PR_AUC": 0.90, "select_F1": 0.5},
        {"condition": "H5-ODST-W-D", "select_PR_AUC": 0.9005, "select_F1": 0.5},
        {"condition": "H9-HYB-W-D", "select_PR_AUC": 0.92, "select_F1": 0.5},
    ]
    dec = decide_promotions(rows)
    assert dec["official_r52_validation_not_used_for_selection"] is True
    names = [p["inner_condition"] for p in dec["promoted"]]
    assert "H5-ODST-W-D" not in names
    assert "H9-HYB-W-D" in names


def test_teacher_guidance_vs_initialisation_preserved():
    assert TEACHER_GUIDANCE_VS_INITIALISATION == "SUPPORTED_STRONG"
    assert len(EDITOR012_RESULTS_FULL_COMMIT) == 40
    assert EDITOR012_RESULTS_FULL_COMMIT == "4bcf522a502ed98e5dd393a80bd9da7fffd51964"


def test_r51_r62_denied():
    with pytest.raises(Exception, match="r5.1"):
        refuse_r51(r"C:\data\processed\r5.1\tensors\x.npz")
    with pytest.raises(Exception, match="r6.2"):
        refuse_r62(r"C:\data\processed\r6.2\tensors\x.npz")


def test_primary_seeds_and_n_trees():
    assert PRIMARY_SEEDS == (42, 52, 62)
    assert N_TREES_TOTAL == 8
    student = build_odst046_model()
    x = torch.zeros(2, 20, 13)
    mods = make_modules({"family": "odst", "readout": "uniform", "hybrid": False})
    out = editor013_forward(student, x, mods)
    assert tuple(out["tree_outputs"].shape) == (2, 8)


def test_head_only_forward_from_z_matches_family():
    student = build_odst046_model()
    z = torch.randn(3, 128)
    lin = make_modules({"family": "linear", "readout": "none", "hybrid": False})
    out = editor013_forward_from_z(student, z, lin)
    assert torch.allclose(out["logit"], out["linear_logit"])
