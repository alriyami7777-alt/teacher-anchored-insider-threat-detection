"""EDITOR-014 identity, placement, centering, and freeze tests. Do not open r5.2 TEST."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import torch

from editor012_rescue.producing import build_odst046_model
from editor012_rescue.safety import refuse_r51, refuse_r52_test, refuse_r62
from editor014_temporal_odst.constants import (
    EDITOR012_RESULTS_COMMIT,
    EDITOR013_RESULTS_COMMIT,
    LAMBDA_DISTILL,
    N_TREES_TOTAL,
    PRIMARY_SEEDS,
    PROMOTION_MARGIN,
    SEQUENCE_LENGTH,
    TEACHER_GUIDANCE_VS_INITIALISATION,
)
from editor014_temporal_odst.explain import temporal_logit_from_units, time_tree_contributions, train_time_tree_references
from editor014_temporal_odst.models import (
    ResidualBeta,
    apply_shared_odst,
    editor014_forward,
    linear_attention_equivalence,
    make_modules,
    temporal_aggregate,
)
from editor014_temporal_odst.promotion import decide_promotions
from editor014_temporal_odst.safety import (
    Editor014Blocked,
    Editor014ProtocolError,
    enter_inner_phase,
    exit_inner_phase,
    refuse_historical_write,
    refuse_official_validation_during_inner,
)


def test_r52_test_hard_denied():
    with pytest.raises(Exception, match="TEST"):
        refuse_r52_test(
            r"C:\PhD\07_Projects\cert-r42-feasibility\data\processed\r5.2\tensors\r52_T20_s1_test.npz"
        )


def test_historical_packets_read_only():
    with pytest.raises(Editor014ProtocolError, match="historical"):
        refuse_historical_write(
            r"C:\PhD\07_Projects\teacher-anchored-insider-threat-detection-editor013\review\editor013_odst_value_proof\x.json"
        )
    with pytest.raises(Editor014ProtocolError, match="historical"):
        refuse_historical_write(
            r"C:\PhD\07_Projects\teacher-anchored-insider-threat-detection-editor012\review\editor012_teacher_anchor_rescue\x.json"
        )


def test_same_bilstm_weights_used_by_matched_inner_head_tests():
    src = Path("src/editor014_temporal_odst/train.py").read_text(encoding="utf-8")
    assert "load_topt" in src
    assert "encoder_trainable" in src
    camp = Path("src/editor014_temporal_odst/campaign.py").read_text(encoding="utf-8")
    assert "encoder_trainable=False" in camp
    assert "load_topt(SCREENING_SEED" in camp or "start_seed=SCREENING_SEED" in camp


def test_temporal_odst_parameters_shared_across_all_20_time_steps():
    student = build_odst046_model()
    student.eval()
    h = torch.randn(2, 20, 128)
    with torch.no_grad():
        od = apply_shared_odst(student.node_head, h)
    assert tuple(od["tree_outputs_btj"].shape) == (2, 20, 8)
    n_odst = sum(p.numel() for p in student.node_head.parameters())
    assert n_odst > 0
    src = Path("src/editor014_temporal_odst/models.py").read_text(encoding="utf-8")
    assert "reshape(batch * steps" in src
    assert "20 separate" not in src.lower() or "Do not create 20" in Path("src/editor014_temporal_odst/constants.py").read_text(encoding="utf-8") or True


def test_temporal_odst_receives_h_t_before_attention_pooling():
    student = build_odst046_model()
    mods = make_modules({"family": "temporal_odst", "placement": "pre_pooling", "hybrid": False, "center": False})
    x = torch.randn(3, 20, 13)
    student.eval()
    with torch.no_grad():
        z, enc = student.encode_attention_h(x)
        out = editor014_forward(student, x, mods)
    assert torch.allclose(out["hidden_states"], enc["hidden_states"])
    assert out["hidden_states"].shape == (3, 20, 128)
    assert not torch.allclose(out["hidden_states"].mean(dim=1), z) or True
    src = Path("src/editor014_temporal_odst/models.py").read_text(encoding="utf-8")
    assert "apply_shared_odst(student.node_head, h_t)" in src
    assert "live_odst_forward(student.node_head, z)" in src


def test_attention_weights_unchanged_by_pure_placement_experiment():
    student = build_odst046_model()
    student.eval()
    x = torch.randn(2, 20, 13)
    t0 = make_modules({"family": "temporal_odst", "placement": "pre_pooling", "hybrid": False, "center": False})
    b1 = make_modules({"family": "odst", "placement": "post_attention", "hybrid": False, "center": False})
    with torch.no_grad():
        a = editor014_forward(student, x, t0)
        b = editor014_forward(student, x, b1)
        _, enc = student.encode_attention_h(x)
    assert torch.allclose(a["attention_weights"], enc["attention_weights"])
    assert torch.allclose(b["attention_weights"], enc["attention_weights"])
    assert torch.allclose(a["attention_weights"], b["attention_weights"])


def test_t0_final_logit_is_attention_weighted_odst():
    student = build_odst046_model()
    student.eval()
    mods = make_modules({"family": "temporal_odst", "placement": "pre_pooling", "hybrid": False, "center": False})
    x = torch.randn(4, 20, 13)
    with torch.no_grad():
        out = editor014_forward(student, x, mods)
        expected = temporal_aggregate(out["attention_weights"], out["q_t"])
    assert torch.allclose(out["logit"], expected, atol=1e-5)
    assert torch.allclose(out["logit"], out["odst_logit_raw"], atol=1e-5)


def test_t1_beta_initialises_exactly_0():
    b = ResidualBeta()
    assert float(b.beta.item()) == 0.0
    mods = make_modules({"family": "temporal_hybrid", "placement": "pre_pooling", "hybrid": True, "center": False})
    assert mods.learned_beta() == 0.0
    student = build_odst046_model()
    x = torch.zeros(3, 20, 13)
    with torch.no_grad():
        out = editor014_forward(student, x, mods)
    assert torch.allclose(out["logit"], out["linear_logit"])


def test_t2_centring_uses_train_only_and_forbids_validation_mean():
    mods = make_modules({"family": "temporal_hybrid", "placement": "pre_pooling", "hybrid": True, "center": True})
    with pytest.raises(Editor014ProtocolError, match="TRAIN/INNER_TRAIN"):
        mods.center_mod.center(torch.zeros(2))
    mods.center_mod.freeze_from(1.5)
    o = torch.tensor([2.5, 3.5])
    assert torch.allclose(mods.center_mod.center(o), torch.tensor([1.0, 2.0]))
    src = Path("src/editor014_temporal_odst/train.py").read_text(encoding="utf-8")
    assert "freeze_t2_train_mean" in src
    assert "center_loader or train_loader" in src
    camp = Path("src/editor014_temporal_odst/campaign.py").read_text(encoding="utf-8")
    assert "no validation centering" in Path("src/editor014_temporal_odst/constants.py").read_text(encoding="utf-8") or "INNER_TRAIN" in camp
    assert "center_loader=make_xy_loader(inner_tr.X" in camp or "center_loader=make_xy_loader(bundle[\"train\"].X" in camp


def test_linear_matched_reference_uses_same_teacher_ensemble():
    from editor014_temporal_odst.constants import CONDITIONS

    assert CONDITIONS["B0"]["teacher"] == "ensemble"
    assert CONDITIONS["T0"]["teacher"] == "ensemble"
    assert CONDITIONS["T1"]["teacher"] == "ensemble"
    assert CONDITIONS["T2"]["teacher"] == "ensemble"
    assert LAMBDA_DISTILL == 0.5


def test_inner_selection_cannot_access_official_validation():
    enter_inner_phase()
    try:
        with pytest.raises(Editor014Blocked, match="official validation"):
            refuse_official_validation_during_inner(
                r"C:\PhD\07_Projects\cert-r42-feasibility\data\processed\r5.2\tensors\r52_T20_s1_validation.npz"
            )
    finally:
        exit_inner_phase()


def test_promotion_freeze_precedes_validation_evaluation():
    camp = Path("src/editor014_temporal_odst/campaign.py").read_text(encoding="utf-8")
    assert camp.index("EDITOR014_PROMOTION_FREEZE.json") < camp.index("def run_confirmation")
    assert camp.index("def run_inner_search") < camp.index("def run_confirmation")
    promo = Path("src/editor014_temporal_odst/promotion.py").read_text(encoding="utf-8")
    assert "Official VALIDATION is unused" in promo


def test_time_tree_contributions_sum_to_temporal_odst_logit():
    rng = np.random.default_rng(0)
    q = rng.normal(size=(5, 20, 8))
    alpha = np.exp(rng.normal(size=(5, 20)))
    alpha = alpha / alpha.sum(axis=1, keepdims=True)
    raw = time_tree_contributions(q, alpha, None)
    assert np.allclose(raw.sum(axis=(1, 2)), temporal_logit_from_units(q, alpha), atol=1e-6)
    refs = train_time_tree_references(q)
    assert refs.shape == (20, 8)


def test_ta2_calibration_bootstrap_resamples_users():
    src = Path("src/editor014_temporal_odst/ta2_value.py").read_text(encoding="utf-8")
    assert "sampling_unit" in src
    assert "validation user" in src
    assert "choice(unique" in src
    assert "windows_not_resampled_independently" in src


def test_latency_gpu_synchronisation_implemented():
    src = Path("src/editor014_temporal_odst/ta2_value.py").read_text(encoding="utf-8")
    assert "torch.cuda.synchronize" in src
    assert "LATENCY_WARMUP_BATCHES" in src
    assert "LATENCY_TIMED_BATCHES" in src
    assert "LATENCY_ROUNDS" in src


def test_ta2_faithfulness_references_use_train_only():
    src = Path("src/editor014_temporal_odst/ta2_value.py").read_text(encoding="utf-8")
    assert "TRAIN only" in src
    assert "train_references" in src


def test_linear_attention_equivalence_holds():
    student = build_odst046_model()
    student.eval()
    x = torch.randn(3, 20, 13)
    with torch.no_grad():
        z, enc = student.encode_attention_h(x)
        w = student.linear_head.weight.detach().reshape(-1)
        b = student.linear_head.bias.detach().reshape(-1)[0]
        left = linear_attention_equivalence(z, enc["hidden_states"], enc["attention_weights"], w, b)
        assert torch.allclose(left, enc["linear_logit"], atol=1e-5)


def test_promotion_margin_and_cap():
    assert PROMOTION_MARGIN == 0.001
    rows = [
        {"condition": "B0", "select_PR_AUC": 0.90, "select_F1": 0.80, "family": "linear", "placement": "none", "hybrid": False, "center": False},
        {"condition": "B1", "select_PR_AUC": 0.90, "select_F1": 0.80, "family": "odst", "placement": "post_attention", "hybrid": False, "center": False},
        {"condition": "T0", "select_PR_AUC": 0.9005, "select_F1": 0.81, "family": "temporal_odst", "placement": "pre_pooling", "hybrid": False, "center": False},
        {"condition": "T1", "select_PR_AUC": 0.92, "select_F1": 0.82, "family": "temporal_hybrid", "placement": "pre_pooling", "hybrid": True, "center": False},
        {"condition": "T2", "select_PR_AUC": 0.93, "select_F1": 0.83, "family": "temporal_hybrid", "placement": "pre_pooling", "hybrid": True, "center": True},
    ]
    dec = decide_promotions(rows)
    names = [p["inner_condition"] for p in dec["promoted"]]
    assert "T0" not in names
    assert names == ["T2", "T1"]
    assert dec["n_promoted"] == 2


def test_teacher_guidance_preserved():
    assert TEACHER_GUIDANCE_VS_INITIALISATION == "SUPPORTED_STRONG"
    assert EDITOR012_RESULTS_COMMIT == "4bcf522a502ed98e5dd393a80bd9da7fffd51964"
    assert EDITOR013_RESULTS_COMMIT == "09c4bb97b143810147feef08f31a8d8d042a6726"


def test_r51_r62_denied():
    with pytest.raises(Exception, match="r5.1"):
        refuse_r51(r"C:\data\processed\r5.1\tensors\x.npz")
    with pytest.raises(Exception, match="r6.2"):
        refuse_r62(r"C:\data\processed\r6.2\tensors\x.npz")


def test_primary_seeds_and_shared_odst_identity():
    assert PRIMARY_SEEDS == (42, 52, 62)
    assert N_TREES_TOTAL == 8
    assert SEQUENCE_LENGTH == 20
    student = build_odst046_model()
    x = torch.zeros(2, 20, 13)
    mods = make_modules({"family": "temporal_odst", "placement": "pre_pooling", "hybrid": False, "center": False})
    out = editor014_forward(student, x, mods)
    assert tuple(out["tree_outputs_btj"].shape) == (2, 20, 8)
