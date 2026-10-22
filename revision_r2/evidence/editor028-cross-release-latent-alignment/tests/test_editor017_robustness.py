"""EDITOR-017 protocol, hash-gate, and safety tests. Do not open r5.2 TEST."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from editor012_rescue.safety import refuse_r51, refuse_r52_test, refuse_r62
from editor015_residual.explain import directional_table, train_references
from editor017_robustness.constants import (
    DIRECTIONAL_KS,
    EDITOR012_RESULTS_COMMIT,
    EDITOR013_RESULTS_COMMIT,
    EDITOR014_RESULTS_COMMIT,
    EDITOR015_RESULTS_COMMIT,
    EDITOR016_RESULTS_COMMIT,
    EXPECTED_SCALER_JSON_SHA256,
    FORBIDDEN_THREAT_TERMS,
    GLOBAL_TOPK_PR_AUC_FAITHFULNESS,
    NOISE_LEVELS,
    NOISE_PERTURBATION_SEED,
    NOISE_SLOPE_DEFINITION,
    PRIMARY_SEEDS,
    SOURCE_CHANNELS,
    TEACHER_GUIDANCE_VS_INITIALISATION,
)
from editor017_robustness.perturbations import apply_gaussian_noise, apply_source_ablation, load_r52_train_scaler
from editor017_robustness.protocol import build_perturbation_audit
from editor017_robustness.safety import Editor017Blocked, Editor017ProtocolError, refuse_historical_write
from editor017_robustness.score import ols_slope
from editor017_robustness.stability import contribution_stability


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
    with pytest.raises(Editor017ProtocolError, match="historical"):
        refuse_historical_write(
            r"C:\PhD\07_Projects\teacher-anchored-insider-threat-detection-editor016\review\editor016_uncertainty_routed_odst\x.json"
        )
    with pytest.raises(Editor017ProtocolError, match="historical"):
        refuse_historical_write("review/editor015_residual_complementarity/x.json")
    with pytest.raises(Editor017ProtocolError, match="historical"):
        refuse_historical_write("review/editor012_teacher_anchor_rescue/x.json")


def test_frozen_commits_recovered():
    assert EDITOR012_RESULTS_COMMIT == "4bcf522a502ed98e5dd393a80bd9da7fffd51964"
    assert EDITOR013_RESULTS_COMMIT == "09c4bb97b143810147feef08f31a8d8d042a6726"
    assert EDITOR014_RESULTS_COMMIT == "c3343462dc3b35d20907da6ad017f5f853852f84"
    assert EDITOR015_RESULTS_COMMIT == "d8e1d04b8c199f56cab9956f62c16cd4301f0bac"
    assert EDITOR016_RESULTS_COMMIT == "07b90867dc83ac42a4f3dce538ee7eca0cedb230"
    assert TEACHER_GUIDANCE_VS_INITIALISATION == "SUPPORTED_STRONG"
    assert GLOBAL_TOPK_PR_AUC_FAITHFULNESS == "NOT_SUPPORTED"


def test_source_list_fixed_at_five_channels():
    assert SOURCE_CHANNELS == ("logon", "device", "file", "email", "http")
    assert len(SOURCE_CHANNELS) == 5


def test_noise_severities_frozen_before_results():
    assert NOISE_LEVELS == (0.05, 0.10, 0.20)
    assert NOISE_PERTURBATION_SEED == 101
    assert "0.00_0.05_0.10_0.20" in NOISE_SLOPE_DEFINITION
    assert ols_slope(np.array([0.0, 0.05, 0.10, 0.20]), np.array([1.0, 0.9, 0.8, 0.6])) < 0


def test_perturbation_protocol_recovers_exactly_one_implementation_each():
    audit = build_perturbation_audit()
    assert audit["ROBUSTNESS_BRANCH"] == "AUTHORISED"
    assert audit["PERTURBATION_PROTOCOL_RECOVERED"] is True
    selected = [c for c in audit["candidates"] if c.get("selected_for_editor017")]
    assert len(selected) == 2
    assert audit["selected_source_ablation"].startswith("editor017_library_inverse_scale")
    assert "gaussian" in audit["selected_gaussian"]
    assert audit["scaler_sha256"] == EXPECTED_SCALER_JSON_SHA256


def test_no_validation_derived_perturbation_or_source_choice():
    src = Path("src/editor017_robustness/perturbations.py").read_text(encoding="utf-8")
    assert "SOURCE_CHANNELS" in src
    assert "NOISE_LEVELS" in src
    with pytest.raises(Editor017Blocked):
        apply_gaussian_noise(np.zeros((2, 20, 13), dtype=np.float32), 0.15)
    with pytest.raises(Editor017Blocked):
        apply_source_ablation(np.zeros((2, 20, 13), dtype=np.float32), "usb", {"mean": np.zeros(13), "scale": np.ones(13)})


def test_source_ablation_uses_train_scaler_and_does_not_change_labels():
    scaler = load_r52_train_scaler()
    assert scaler["sha256"] == EXPECTED_SCALER_JSON_SHA256
    x = np.random.default_rng(0).normal(size=(4, 20, 13)).astype(np.float32)
    y = np.array([0, 1, 0, 1])
    xp = apply_source_ablation(x, "http", scaler)
    assert xp.shape == x.shape
    assert not np.allclose(xp, x)
    assert np.array_equal(y, np.array([0, 1, 0, 1]))


def test_gaussian_is_paired_and_leaves_binaries():
    x = np.random.default_rng(1).random((3, 20, 13)).astype(np.float32)
    x[:, :, 7:] = (x[:, :, 7:] > 0.5).astype(np.float32)
    a = apply_gaussian_noise(x, 0.10)
    b = apply_gaussian_noise(x, 0.10)
    assert np.allclose(a, b)
    assert np.allclose(a[:, :, 7:], x[:, :, 7:])
    assert not np.allclose(a[:, :, :7], x[:, :, :7])


def test_same_sign_random_control_and_train_references():
    rng = np.random.default_rng(42)
    train_trees = rng.normal(size=(200, 8))
    refs = train_references(train_trees)
    assert refs.shape == (8,)
    y = np.array([1, 1, 0, 0])
    trees = np.array(
        [
            [2.0, 1.5, 0.1, -0.2, 0.0, 0.3, -0.1, 0.2],
            [1.8, 1.2, 0.2, -0.1, 0.1, 0.2, 0.0, 0.1],
            [-1.5, -1.2, 0.1, 0.2, -0.3, 0.0, 0.1, -0.2],
            [-1.1, -0.8, 0.0, 0.1, -0.2, 0.1, 0.0, -0.1],
        ],
        dtype=np.float64,
    )
    users = np.array(["u1", "u2", "u3", "u4"])
    tab = directional_table(
        y=y,
        tree_outputs=trees,
        references=refs,
        linear_logit=np.zeros(4),
        reference_tree_outputs=None,
        users=users,
        rng_seed=42,
    )
    assert DIRECTIONAL_KS == (1, 2, 3)
    assert tab["HISTORICAL_GLOBAL_TOPK_FAITHFULNESS"] == "NOT_SUPPORTED"
    assert all(r["random_control"] == "same-sign eligible trees only" for r in tab["rows"])
    assert all(r["references_from"] == "r5.2 TRAIN only" for r in tab["rows"])


def test_tree_identities_not_compared_across_seeds():
    src = Path("src/editor017_robustness/stability.py").read_text(encoding="utf-8")
    assert "same model and seed" in src or "same model/seed" in src.lower() or "within the same model" in src
    a = np.array([[1.0, -0.5, 0.2, 0.1, 0.0, 0.0, 0.0, 0.0]])
    b = np.array([[0.9, -0.4, 0.1, 0.2, 0.0, 0.0, 0.0, 0.0]])
    rec = contribution_stability(a, b)
    assert rec["tree_identities_compared_across_seeds"] is False
    assert rec["n_trees"] == 8


def test_forbidden_threat_terms_not_authorised():
    assert "ADVERSARIAL_ROBUSTNESS" in FORBIDDEN_THREAT_TERMS
    for path in Path("src/editor017_robustness").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        if path.name in {"constants.py", "protocol.py", "campaign.py"}:
            continue
        assert "ADVERSARIAL_ROBUSTNESS" not in text


def test_no_training_paths_in_campaign():
    src = Path("src/editor017_robustness/campaign.py").read_text(encoding="utf-8")
    assert "optimizer" not in src.lower()
    assert "loss.backward" not in src
    assert "train_student" not in src
    assert "requires_grad = False" in Path("src/editor017_robustness/models.py").read_text(encoding="utf-8")


def test_global_topk_negative_result_preserved():
    assert GLOBAL_TOPK_PR_AUC_FAITHFULNESS == "NOT_SUPPORTED"
    src = Path("src/editor017_robustness/constants.py").read_text(encoding="utf-8")
    assert 'TA2_GLOBAL_TOPK_PR_AUC_FAITHFULNESS = "NOT_SUPPORTED"' in src
