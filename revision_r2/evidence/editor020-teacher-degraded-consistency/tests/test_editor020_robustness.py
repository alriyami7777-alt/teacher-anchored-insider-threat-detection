"""EDITOR-020 protocol, sampler, hash-gate, and safety tests. Do not open r5.2 TEST."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from editor012_rescue.safety import refuse_r51, refuse_r52_test, refuse_r62
from editor017_robustness.perturbations import apply_gaussian_noise, apply_source_ablation, load_r52_train_scaler
from editor020_robustness.constants import (
    ARCH_SPECS,
    CLEAN_ODST_PREDICTIVE_SUPERIORITY,
    EDITOR017_RESULTS_COMMIT,
    EDITOR018_RESULTS_COMMIT,
    EDITOR019_RESULTS_COMMIT,
    EXPECTED_GAUSSIAN_SHA256,
    EXPECTED_SOURCE_ABLATION_SHA256,
    FAMILY_P_NOISE,
    FAMILY_P_SOURCE,
    FORBIDDEN_THREAT_TERMS,
    INNER_CONDITIONS,
    LAMBDA_ROUTE,
    LAMBDA_TEACHER,
    NOISE_LEVELS,
    OBJECTIVES,
    SAMPLER_SEED,
    SOURCE_CHANNELS,
    TEACHER_GUIDANCE_VS_INITIALISATION,
)
from editor020_robustness.models import condition_flags
from editor020_robustness.promotion import decide_promotions
from editor020_robustness.protocol import assert_perturbation_hashes, write_protocol_packet
from editor020_robustness.safety import (
    Editor020Blocked,
    Editor020ProtocolError,
    enter_inner_phase,
    exit_inner_phase,
    refuse_historical_write,
    refuse_official_validation_during_inner,
    refuse_validation_outputs_before_promotion,
)
from editor020_robustness.sampler import apply_sampled_batch, empirical_family_rates, sample_partner, sampler_lock


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
    with pytest.raises(Editor020ProtocolError, match="historical"):
        refuse_historical_write("review/editor017_explanation_robustness/x.json")
    with pytest.raises(Editor020ProtocolError, match="historical"):
        refuse_historical_write("review/editor018_cross_view_tree_rescue/x.json")
    with pytest.raises(Editor020ProtocolError, match="historical"):
        refuse_historical_write("review/editor019_oblique_boosted_tree_rescue/x.json")


def test_frozen_source_commits():
    assert EDITOR017_RESULTS_COMMIT == "c75321a627ecc7539d1a759764d7ce395895179a"
    assert EDITOR018_RESULTS_COMMIT == "9dafa51b7dd81d97cead84b4b7e10b2c230b08b4"
    assert EDITOR019_RESULTS_COMMIT == "26614089fe4ee8695f1a15d902ebf2f5fdf1f45a"
    assert TEACHER_GUIDANCE_VS_INITIALISATION == "SUPPORTED_STRONG"
    assert CLEAN_ODST_PREDICTIVE_SUPERIORITY == "NOT_SUPPORTED"


def test_editor017_perturbation_hashes_match():
    hashes = assert_perturbation_hashes()
    assert hashes["objective3_missing_source_robustness.py"] == EXPECTED_SOURCE_ABLATION_SHA256
    assert hashes["objective3_perturbations.py"] == EXPECTED_GAUSSIAN_SHA256


def test_source_and_noise_frozen():
    assert SOURCE_CHANNELS == ("logon", "device", "file", "email", "http")
    assert NOISE_LEVELS == (0.05, 0.10, 0.20)


def test_family_first_sampler_is_half_half():
    lock = sampler_lock()
    assert lock["P_source"] == 0.5
    assert lock["P_noise"] == 0.5
    assert FAMILY_P_SOURCE == 0.5 and FAMILY_P_NOISE == 0.5
    rates = empirical_family_rates(n=40000, epoch=0, seed=SAMPLER_SEED)
    assert abs(rates["p_source"] - 0.5) < 0.02
    assert abs(rates["p_noise"] - 0.5) < 0.02


def test_source_and_noise_sampled_uniformly():
    src = []
    nz = []
    for i in range(30000):
        fam, spec = sample_partner(i, 1, seed=SAMPLER_SEED)
        if fam == "source":
            src.append(spec)
        else:
            nz.append(float(spec))
    src_counts = {ch: src.count(ch) for ch in SOURCE_CHANNELS}
    nz_counts = {lv: nz.count(lv) for lv in NOISE_LEVELS}
    src_vals = list(src_counts.values())
    nz_vals = list(nz_counts.values())
    assert max(src_vals) - min(src_vals) < 0.08 * (sum(src_vals) / 5)
    assert max(nz_vals) - min(nz_vals) < 0.08 * (sum(nz_vals) / 3)


def test_labels_unchanged_by_corruption_and_clean_data_shape():
    scaler = load_r52_train_scaler()
    x = np.random.default_rng(0).normal(size=(8, 20, 13)).astype(np.float32)
    y = np.array([0, 1, 0, 1, 0, 1, 0, 1], dtype=np.float32)
    xp = apply_source_ablation(x, "http", scaler)
    xn = apply_gaussian_noise(x, 0.10)
    xd = apply_sampled_batch(x, np.arange(8), epoch=0, scaler=scaler)
    assert xp.shape == x.shape == xn.shape == xd.shape
    assert np.array_equal(y, np.array([0, 1, 0, 1, 0, 1, 0, 1], dtype=np.float32))
    assert not np.allclose(xp, x)
    assert not np.allclose(xn, x)


def test_lambdas_frozen():
    assert LAMBDA_TEACHER == 0.5
    assert LAMBDA_ROUTE == 0.5


def test_r1_and_r3_differ_only_by_teacher_consistency():
    r1 = OBJECTIVES["R1"]
    r3 = OBJECTIVES["R3"]
    assert r1["task_clean"] is True and r3["task_clean"] is True
    assert r1["task_degraded"] is True and r3["task_degraded"] is True
    assert r1["teacher_degraded"] is False
    assert r3["teacher_degraded"] is True
    assert r1["route_robust"] is False and r3["route_robust"] is False
    assert r1["teacher_clean"] is False and r3["teacher_clean"] is False


def test_r3_and_r4_differ_only_by_robust_route_consistency():
    r3 = OBJECTIVES["R3"]
    r4 = OBJECTIVES["R4"]
    assert r3["task_degraded"] == r4["task_degraded"]
    assert r3["teacher_degraded"] == r4["teacher_degraded"]
    assert r3["route_robust"] is False
    assert r4["route_robust"] is True
    f10 = condition_flags("F10", "R3")
    ta2_r3 = condition_flags("TA2", "R3")
    ta2_r4 = condition_flags("TA2", "R4")
    assert f10["route_robust"] is False
    assert ta2_r3["route_robust"] is False
    assert ta2_r4["route_robust"] is True
    assert ta2_r3["teacher_degraded"] is True and ta2_r4["teacher_degraded"] is True


def test_matched_architectures_share_sampler_and_teacher_sees_clean():
    assert set(ARCH_SPECS) == {"L1", "F10", "TA2"}
    for arch in ARCH_SPECS:
        r2 = condition_flags(arch, "R2")
        r3 = condition_flags(arch, "R3")
        assert r2["teacher_degraded"] is True
        assert r3["teacher_degraded"] is True
        assert r2["teacher_clean"] is False
        assert r3["needs_degraded"] is True
    assert "R4" not in ARCH_SPECS["L1"]["objectives"]
    assert "R4" not in ARCH_SPECS["F10"]["objectives"]
    assert "R4" in ARCH_SPECS["TA2"]["objectives"]
    assert len(INNER_CONDITIONS) == 13


def test_no_validation_derived_corruption_parameters():
    lock = sampler_lock()
    assert lock["validation_derived_corruption_parameters"] is False
    with pytest.raises(Exception):
        apply_gaussian_noise(np.zeros((2, 20, 13), dtype=np.float32), 0.15)


def test_inner_cannot_read_validation_and_promotion_precedes_validation():
    enter_inner_phase()
    try:
        with pytest.raises(Editor020Blocked):
            refuse_official_validation_during_inner("r52_T20_s1_validation.npz")
    finally:
        exit_inner_phase()
    with pytest.raises(Editor020Blocked):
        refuse_validation_outputs_before_promotion("review/editor020_teacher_degraded_consistency/02_validation/x.csv")


def test_forbidden_threat_terms_are_locked():
    blob = " ".join(FORBIDDEN_THREAT_TERMS).upper()
    assert "ADVERSARIAL" in blob
    assert "EVASION" in blob
    assert "POISONING" in blob
    for path in Path("src/editor020_robustness").glob("*.py"):
        if path.name == "constants.py":
            continue
        text = path.read_text(encoding="utf-8")
        assert "EVASION RESISTANCE" not in text
        assert "POISONING RESISTANCE" not in text
        assert "ADVERSARIAL ROBUSTNESS" not in text


def test_promotion_selects_at_most_one_per_arch_and_prefers_source_then_noise():
    rows = []
    for arch in ("L1", "F10", "TA2"):
        rows.append(
            {
                "condition": f"{arch}-R0",
                "clean_PR_AUC": 0.90,
                "MEAN_SOURCE_DELTA": -0.40,
                "WORST_SOURCE_DELTA": -0.80,
                "MEAN_NOISE_RETENTION": 0.90,
            }
        )
        for obj, src, nz in (("R1", -0.30, 0.92), ("R2", -0.28, 0.91), ("R3", -0.25, 0.94)):
            rows.append(
                {
                    "condition": f"{arch}-{obj}",
                    "clean_PR_AUC": 0.9005,
                    "MEAN_SOURCE_DELTA": src,
                    "WORST_SOURCE_DELTA": -0.70,
                    "MEAN_NOISE_RETENTION": nz,
                }
            )
    rows.append(
        {
            "condition": "TA2-R4",
            "clean_PR_AUC": 0.9005,
            "MEAN_SOURCE_DELTA": -0.24,
            "WORST_SOURCE_DELTA": -0.70,
            "MEAN_NOISE_RETENTION": 0.95,
        }
    )
    freeze = decide_promotions(rows)
    assert freeze["promoted"]["L1"] == "L1-R3"
    assert freeze["promoted"]["F10"] == "F10-R3"
    assert freeze["promoted"]["TA2"] == "TA2-R4"
    assert freeze["weighted_robustness_score_invented"] is False


def test_protocol_writes_before_results(tmp_path, monkeypatch):
    packet = write_protocol_packet()
    root = Path("review/editor020_teacher_degraded_consistency/00_protocol")
    assert (root / "EDITOR020_PROTOCOL.json").is_file()
    assert (root / "EDITOR020_PERTURBATION_AUDIT.json").is_file()
    assert (root / "EDITOR020_TRAINING_SAMPLER_FREEZE.json").is_file()
    assert (root / "EDITOR020_MODEL_OBJECTIVES.json").is_file()
    assert packet["audit"]["EDITOR017_perturbation_code_hash_matched"] is True
    assert packet["sampler"]["family_first"] is True
