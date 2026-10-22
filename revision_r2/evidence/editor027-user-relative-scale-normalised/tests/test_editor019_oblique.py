"""EDITOR-019 protocol, geometry, capacity, and safety tests. Do not open r5.2 TEST."""

from __future__ import annotations

import numpy as np
import pytest
import torch

from editor012_rescue.safety import refuse_r51, refuse_r52_test, refuse_r62
from editor017_robustness.constants import GLOBAL_TOPK_PR_AUC_FAITHFULNESS
from editor018_cross_view.aggregate40 import aggregate40, producer_sha256
from editor018_cross_view.constants import EXPECTED_AGGREGATE40_SHA256, LOCKED_AGG_FEATURES
from editor019_oblique.boost import prove_stagewise_freeze
from editor019_oblique.campaign import family_from_condition
from editor019_oblique.capacity import mlp40_branch_parameter_count, select_tree_count, so_dte_params_per_tree
from editor019_oblique.constants import (
    EDITOR017_RESULTS_COMMIT,
    EDITOR018_RESULTS_COMMIT,
    LAMBDA_TEACHER,
    PROMOTION_MARGIN,
    SIGNED_DIM,
    SUMMARY_DIM,
    XGB_TRIGGER_MLP_BAND,
    XGB_TRIGGER_ODST_MARGIN,
)
from editor019_oblique.geometry import audit_current_odst_geometry
from editor019_oblique.models import (
    SparseObliqueForest,
    SparseObliqueTree,
    SummaryBranch,
    build_odst40,
    build_so_odst40,
    prove_function_preserving,
    signed_channels,
    signed_coefficients_from_probs,
)
from editor019_oblique.promotion import decide_promotions
from editor019_oblique.safety import (
    Editor019Blocked,
    Editor019ProtocolError,
    enter_inner_phase,
    exit_inner_phase,
    mark_promotion_frozen,
    refuse_historical_write,
    refuse_official_validation_during_inner,
    refuse_validation_before_promotion,
)
from editor019_oblique.xgb_teacher import xgb_logit_from_prob, xgb_residual


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
    with pytest.raises(Editor019ProtocolError, match="historical"):
        refuse_historical_write("review/editor018_cross_view_tree_rescue/x.json")
    with pytest.raises(Editor019ProtocolError, match="historical"):
        refuse_historical_write("review/editor017_explanation_robustness/x.json")


def test_source_commits():
    assert EDITOR017_RESULTS_COMMIT == "c75321a627ecc7539d1a759764d7ce395895179a"
    assert EDITOR018_RESULTS_COMMIT == "9dafa51b7dd81d97cead84b4b7e10b2c230b08b4"
    assert GLOBAL_TOPK_PR_AUC_FAITHFULNESS == "NOT_SUPPORTED"


def test_40_summary_provenance_hash_match():
    assert producer_sha256() == EXPECTED_AGGREGATE40_SHA256
    rng = np.random.default_rng(0)
    feat, names = aggregate40(rng.random((4, 20, 13)).astype(np.float32))
    assert feat.shape == (4, 40)
    assert names == list(LOCKED_AGG_FEATURES)


def test_same_input_supplied_to_mlp_and_trees():
    s = torch.randn(5, SUMMARY_DIM)
    mlp = SummaryBranch("MLP40")
    tree = SummaryBranch("SO-DTE40", n_trees=2)
    assert mlp.live.net[0].in_features == SUMMARY_DIM
    out_t, _ = tree.live.trees[0](s)
    assert out_t.shape == (5,)


def test_odst_geometry_audit_not_from_names():
    rec = audit_current_odst_geometry()
    assert rec["CURRENT_SPLIT_SIGNED"] == "NO"
    assert rec["CURRENT_SPLIT_OBLIVIOUS"] == "YES"
    assert rec["CURRENT_SPLIT_NODE_SPECIFIC"] == "NO"
    assert rec["weights_constrained_non_negative"] is True
    assert rec["weights_sum_to_one"] is True
    assert rec["negative_feature_coefficients_impossible"] is True
    assert rec["signed_oblique_branch_redundant"] is False


def test_signed_projection_allows_positive_and_negative_coefficients():
    tree = SparseObliqueTree()
    with torch.no_grad():
        tree.feature_logits.zero_()
        tree.feature_logits[0, 0] = 5.0
        tree.feature_logits[0, SUMMARY_DIM + 1] = 5.0
        coeff = tree.signed_feature_coefficients()[0]
    assert float(coeff[0]) > 0
    assert float(coeff[1]) < 0
    probs = tree.feature_selection_probs()
    recon = signed_coefficients_from_probs(probs)[0]
    assert torch.allclose(coeff, recon)
    x = signed_channels(torch.ones(1, SUMMARY_DIM))
    assert x.shape[-1] == SIGNED_DIM
    assert torch.allclose(x[0, :SUMMARY_DIM], -x[0, SUMMARY_DIM:])


def test_so_odst_differs_from_odst_only_in_split_geometry():
    od = build_odst40()
    so = build_so_odst40()
    assert od.num_layers == so.num_layers == 2
    assert od.n_trees == so.n_trees == 4
    assert od.depth == so.depth == 4
    assert od.choice_function == so.choice_function == "sparsemax_sigmoid"
    assert od.readout == so.readout == "canonical_tree_average"
    assert od.in_dim == 40
    assert so.in_dim == 80


def test_so_dte_uses_node_specific_splits():
    tree = SparseObliqueTree()
    assert tree.n_internal == 15
    assert tree.n_leaves == 16
    assert tuple(tree.feature_logits.shape) == (15, 80)
    forest = SparseObliqueForest(3, combine="mean")
    s = torch.randn(4, 40)
    out = forest(s)
    assert out["tree_outputs"].shape == (4, 3)
    assert out["choices"].shape == (4, 3, 15)


def test_capacity_match_frozen_before_results():
    cap = select_tree_count()
    mlp_n = mlp40_branch_parameter_count()
    per = so_dte_params_per_tree()
    n = cap["CAPACITY_MATCHED_TREE_COUNT"]
    assert cap["MLP40_branch_parameter_count"] == mlp_n
    assert 2 <= n <= 32
    assert n * per <= 1.05 * mlp_n
    assert (n + 1) * per > 1.05 * mlp_n or n == 32
    assert cap["frozen_before_results"] is True


def test_function_preserving_and_nonzero_first_step_gradient():
    n = int(select_tree_count()["CAPACITY_MATCHED_TREE_COUNT"])
    for family in ("MLP40", "ODST40", "SO-ODST40", "SO-DTE40", "BSO-DTE40"):
        rec = prove_function_preserving(family, batch=8, n_trees=n if family in {"SO-DTE40", "BSO-DTE40"} else None)
        assert rec["initial_final_equals_l1"]
        assert rec["initial_correction_zero"]
        assert rec["live_grad_norm"] > 0
        assert rec["reference_grad_norm"] == 0.0


def test_teacher_lambda_exactly_half():
    assert LAMBDA_TEACHER == 0.5
    assert abs(LAMBDA_TEACHER - 0.5) <= 1e-15


def test_stagewise_boosting_freezes_earlier_stages():
    rec = prove_stagewise_freeze(n_trees=3)
    assert rec["initial_correction_zero"]
    assert rec["earlier_stage_frozen"]
    assert rec["new_stage_trainable"]
    assert rec["joint_finetune_predeclared"]


def test_xgb_target_from_probability_and_never_needs_retrain():
    p = np.array([0.1, 0.5, 0.9], dtype=np.float64)
    z = xgb_logit_from_prob(p)
    assert np.allclose(z, np.log(np.clip(p, 1e-7, 1 - 1e-7) / (1 - np.clip(p, 1e-7, 1 - 1e-7))))
    l1 = np.array([0.0, 0.0, 0.0], dtype=np.float32)
    assert np.allclose(xgb_residual(z, l1), z)


def test_family_from_condition_keeps_bso_prefix():
    assert family_from_condition("BSO-DTE40-D") == "BSO-DTE40"
    assert family_from_condition("BSO-DTE40-XD") == "BSO-DTE40"
    assert family_from_condition("SO-DTE40-T") == "SO-DTE40"
    assert family_from_condition("MLP40-D") == "MLP40"


def test_xgb_trigger_implemented_exactly():
    def rows(so_dte, bso, mlp=0.940112, odst=0.938224, l1=0.938179):
        out = [
            {"condition": "L1", "select_PR_AUC": l1},
            {"condition": "MLP40-D", "select_PR_AUC": mlp},
            {"condition": "ODST40-D", "select_PR_AUC": odst},
        ]
        for fam, val in (("SO-ODST40", odst), ("SO-DTE40", so_dte), ("BSO-DTE40", bso)):
            out.append({"condition": f"{fam}-T", "select_PR_AUC": val - 0.01})
            out.append({"condition": f"{fam}-D", "select_PR_AUC": val})
        return out

    promoted = decide_promotions(rows(0.942, 0.941), l1_pr_auc=0.938179)
    assert promoted["promoted_names"]
    assert promoted["XGB_TEACHER_BRANCH"] == "NOT_TRIGGERED"

    near = decide_promotions(rows(0.9393, 0.9385), l1_pr_auc=0.938179)
    assert near["promoted_names"] == []
    assert near["XGB_TEACHER_BRANCH"] == "TRIGGERED"
    assert near["xgb_trigger_detail"]["delta_vs_ODST40_D"] >= XGB_TRIGGER_ODST_MARGIN
    assert near["xgb_trigger_detail"]["abs_delta_vs_MLP40_D"] <= XGB_TRIGGER_MLP_BAND

    far = decide_promotions(rows(0.9383, 0.9382), l1_pr_auc=0.938179)
    assert far["XGB_TEACHER_BRANCH"] == "NOT_TRIGGERED"


def test_promotion_requires_l1_and_mlp_and_teacher():
    rows = [
        {"condition": "L1", "select_PR_AUC": 0.90},
        {"condition": "MLP40-D", "select_PR_AUC": 0.91},
        {"condition": "ODST40-D", "select_PR_AUC": 0.90},
        {"condition": "SO-ODST40-T", "select_PR_AUC": 0.92},
        {"condition": "SO-ODST40-D", "select_PR_AUC": 0.91},
        {"condition": "SO-DTE40-T", "select_PR_AUC": 0.916},
        {"condition": "SO-DTE40-D", "select_PR_AUC": 0.915},
        {"condition": "BSO-DTE40-T", "select_PR_AUC": 0.90},
        {"condition": "BSO-DTE40-D", "select_PR_AUC": 0.9105},
    ]
    dec = decide_promotions(rows, l1_pr_auc=0.90)
    assert dec["promoted_names"] == []
    assert PROMOTION_MARGIN == 0.001


def test_inner_cannot_open_validation_and_promotion_precedes_validation():
    enter_inner_phase()
    try:
        with pytest.raises(Editor019Blocked):
            refuse_official_validation_during_inner("r52_T20_s1_validation.npz")
    finally:
        exit_inner_phase()
    with pytest.raises(Editor019Blocked):
        refuse_validation_before_promotion("review/editor019_oblique_boosted_tree_rescue/03_validation/x.csv")
    mark_promotion_frozen()
    refuse_validation_before_promotion("review/editor019_oblique_boosted_tree_rescue/03_validation/x.csv")
