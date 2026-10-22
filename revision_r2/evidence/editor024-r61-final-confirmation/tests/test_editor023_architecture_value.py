"""EDITOR-023 protocol, safety, curve, and training-gate tests. Do not open r5.2 TEST."""

from __future__ import annotations

import ast
import json
import subprocess
from pathlib import Path

import numpy as np
import pytest

from editor012_rescue.safety import refuse_r51, refuse_r52_test, refuse_r62
from editor017_robustness.perturbations import apply_gaussian_noise as editor017_noise
from editor023_architecture_value.constants import (
    DEGRADED_PARITY_TOLERANCE,
    EDITOR022_RESULTS_COMMIT,
    HYPOTHESES,
    NOISE_LEVELS,
    NOISE_LEVELS_HISTORICAL,
    NOISE_LEVELS_NEW,
    PARITY_TOLERANCE,
    PRIMARY_MODELS,
    SOURCE_CHANNELS,
    SOURCE_DEGRADATION_LEVELS,
)
from editor023_architecture_value.curves import failure_profile, first_crossing, noise_aurc, source_channel_aurc
from editor023_architecture_value.perturbations import apply_gaussian_noise, apply_graded_source, apply_source_ablation, load_r52_train_scaler
from editor023_architecture_value.ruling import (
    odst_degraded_over_linear,
    overall_architecture_value,
    route_anchor_structural_value,
    teacher_guidance_clean_value,
    teacher_guidance_degraded_value,
)
from editor023_architecture_value.safety import Editor023Blocked, Editor023ProtocolError, refuse_historical_write, refuse_training
from editor023_architecture_value.training_gate import assert_no_training, scan_training_apis


def test_parent_commit_is_exactly_editor022_results():
    assert EDITOR022_RESULTS_COMMIT == "ac50596ed8c3b480c887640911092e46b4631670"
    assert len(EDITOR022_RESULTS_COMMIT) == 40
    ancestor = subprocess.check_output(
        ["git", "merge-base", EDITOR022_RESULTS_COMMIT, "HEAD"],
        text=True,
    ).strip()
    assert ancestor == EDITOR022_RESULTS_COMMIT


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
    with pytest.raises(Editor023ProtocolError, match="historical"):
        refuse_historical_write("review/editor017_explanation_robustness/x.json")
    with pytest.raises(Editor023ProtocolError, match="historical"):
        refuse_historical_write("review/editor022_sequential_clean_optimum_robustness/x.json")
    with pytest.raises(Editor023ProtocolError, match="historical"):
        refuse_historical_write("review/editor012_teacher_anchor_rescue/x.json")


def test_training_is_refused():
    with pytest.raises(Editor023Blocked, match="TRAINING_GATE"):
        refuse_training()


def test_no_training_apis_in_editor023_package():
    assert_no_training()
    hits = scan_training_apis()
    assert hits == {}
    campaign = Path("src/editor023_architecture_value/campaign.py").read_text(encoding="utf-8")
    assert "optimizer" not in campaign.lower()
    assert "train_student" not in campaign
    assert "train_stage2" not in campaign


def test_hypotheses_and_grids_frozen_before_results():
    assert SOURCE_CHANNELS == ("logon", "device", "file", "email", "http")
    assert SOURCE_DEGRADATION_LEVELS == (0.00, 0.25, 0.50, 0.75, 1.00)
    assert NOISE_LEVELS == (0.00, 0.025, 0.05, 0.075, 0.10, 0.15, 0.20)
    assert NOISE_LEVELS_HISTORICAL == (0.05, 0.10, 0.20)
    assert NOISE_LEVELS_NEW == (0.025, 0.075, 0.15)
    assert PARITY_TOLERANCE == 5e-4
    assert DEGRADED_PARITY_TOLERANCE == 5e-3
    assert set(HYPOTHESES) == {"H1", "H2", "H3", "H4", "H5", "H6"}
    with pytest.raises(Editor023Blocked):
        apply_gaussian_noise(np.zeros((2, 20, 13), dtype=np.float32), 0.30)
    with pytest.raises(Editor023Blocked):
        apply_graded_source(np.zeros((2, 20, 13), dtype=np.float32), np.ones((2, 20, 13), dtype=np.float32), 0.33)


def test_graded_source_endpoints_and_labels_unchanged():
    scaler = load_r52_train_scaler()
    rng = np.random.default_rng(0)
    x = rng.normal(size=(4, 20, 13)).astype(np.float32)
    y = np.array([0, 1, 0, 1])
    abl = apply_source_ablation(x, "http", scaler)
    assert not np.allclose(abl, x)
    d0 = apply_graded_source(x, abl, 0.0)
    d1 = apply_graded_source(x, abl, 1.0)
    d50 = apply_graded_source(x, abl, 0.50)
    assert np.array_equal(d0, x)
    assert np.array_equal(d1, abl)
    expected = (1.0 - np.float32(0.50)) * x + np.float32(0.50) * abl
    assert np.allclose(d50, expected)
    assert np.array_equal(y, np.array([0, 1, 0, 1]))


def test_historical_gaussian_matches_editor017_and_leaves_binaries():
    x = np.random.default_rng(1).random((3, 20, 13)).astype(np.float32)
    x[:, :, 7:] = (x[:, :, 7:] > 0.5).astype(np.float32)
    for lvl in NOISE_LEVELS_HISTORICAL:
        a = editor017_noise(x, lvl)
        b = apply_gaussian_noise(x, lvl)
        assert np.allclose(a, b)
        assert np.allclose(b[:, :, 7:], x[:, :, 7:])
    c = apply_gaussian_noise(x, 0.15)
    d = apply_gaussian_noise(x, 0.15)
    assert np.allclose(c, d)
    assert not np.allclose(c[:, :, :7], x[:, :, :7])


def test_aurc_perfect_retention_is_one_and_definition_frozen():
    src = {float(d): 1.0 for d in SOURCE_DEGRADATION_LEVELS}
    assert abs(source_channel_aurc(src) - 1.0) < 1e-12
    noise = {float(s): 1.0 for s in NOISE_LEVELS}
    assert abs(noise_aurc(noise) - 1.0) < 1e-12
    declining = {0.0: 1.0, 0.25: 0.75, 0.50: 0.50, 0.75: 0.25, 1.00: 0.0}
    assert abs(source_channel_aurc(declining) - 0.5) < 1e-12


def test_failure_profile_does_not_invent_uncrossed_thresholds():
    src = {ch: {0.0: 1.0, 0.25: 0.96, 0.50: 0.88, 0.75: 0.86, 1.00: 0.85} for ch in SOURCE_CHANNELS}
    src["file"] = {0.0: 1.0, 0.25: 0.70, 0.50: 0.50, 0.75: 0.45, 1.00: 0.40}
    noise = {float(s): 0.99 for s in NOISE_LEVELS}
    rec = failure_profile(src, noise)
    assert rec["worst_source"] == "file"
    assert rec["source_retention_first_below_0.90"] is not None
    assert rec["source_retention_first_below_0.75"] is None
    assert rec["noise_retention_first_below_0.90"] is None
    assert first_crossing((0.0, 0.5, 1.0), [1.0, 0.92, 0.91], 0.90) is None


def test_ruling_functions_are_result_independent():
    assert teacher_guidance_clean_value(0.007, 3) == "SUPPORTED_STRONG"
    assert teacher_guidance_clean_value(0.001, 2) == "PRESERVED"
    assert teacher_guidance_clean_value(-0.001, 1) == "CONTRADICTED"
    assert teacher_guidance_degraded_value(0.01, 0.01, [0.001, 0.02], [-0.001, 0.02]) == "SUPPORTED_STRONG"
    assert teacher_guidance_degraded_value(0.01, 0.01, [-0.01, 0.02], [-0.01, 0.02]) == "CONSISTENT"
    assert teacher_guidance_degraded_value(-0.01, -0.01, [-0.02, 0.0], [-0.02, 0.0]) == "NOT_SUPPORTED"
    assert route_anchor_structural_value(0.002, 0.007, 0.005, 0.010) == "SUPPORTED"
    assert route_anchor_structural_value(0.008, 0.007, 0.005, 0.010) == "NOT_SUPPORTED"
    assert odst_degraded_over_linear(0.01, 0.01, [0.001, 0.02], [-0.01, 0.02]) == "SUPPORTED"
    assert odst_degraded_over_linear(0.01, 0.01, [-0.01, 0.02], [-0.01, 0.02]) == "CONSISTENT"
    assert overall_architecture_value("SUPPORTED_STRONG", "SUPPORTED_STRONG", "SUPPORTED", "SUPPORTED") == "SUPPORTED"
    assert overall_architecture_value("CONTRADICTED", "SUPPORTED", "SUPPORTED", "SUPPORTED") == "NOT_SUPPORTED"


def test_sha_manifest_does_not_hash_itself():
    src = Path("src/editor023_architecture_value/campaign.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    assert "EDITOR023_SHA256_MANIFEST.json" in src
    assert "p.name != SHA256_MANIFEST_NAME" in src


def test_forbidden_threat_terms_not_used_as_claims():
    for path in Path("src/editor023_architecture_value").glob("*.py"):
        if path.name in {"constants.py", "protocol.py", "campaign.py", "ruling.py"}:
            continue
        text = path.read_text(encoding="utf-8")
        assert "ADVERSARIAL_ROBUSTNESS" not in text
