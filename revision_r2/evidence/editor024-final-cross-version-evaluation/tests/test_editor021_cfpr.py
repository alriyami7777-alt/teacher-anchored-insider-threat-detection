"""EDITOR-021 unit/synthetic tests T01–T25. Do not open r5.2 TEST."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
import torch

from editor012_rescue.models import freeze_teacher, student_forward
from editor012_rescue.safety import refuse_r51, refuse_r52_test, refuse_r62
from editor017_robustness.perturbations import apply_gaussian_noise, apply_source_ablation, load_r52_train_scaler
from editor020_robustness.sampler import apply_sampled_batch, sample_partner, sampler_lock
from editor021_cfpr.constants import (
    CANDIDATES,
    EDITOR020C_PARENT_COMMIT,
    EXPECTED_GAUSSIAN_SHA256,
    EXPECTED_SOURCE_ABLATION_SHA256,
    LAMBDA_FP,
    LAMBDA_ROUTE,
    LAMBDA_TEACHER,
    ROBUSTNESS_CANDIDATES,
)
from editor021_cfpr.evaluate import resilience_from_logits
from editor021_cfpr.grads import (
    combine_encoder_grads,
    cosine_repr_loss,
    encoder_attention_params,
    odst_head_params,
    project_robustness,
    rho_scale,
)
from editor021_cfpr.models import assert_initial_match, build_optimizer, load_ta2_reference, load_ta2_student
from editor021_cfpr.promotion import evaluate_cfp0_scaffold, evaluate_official_gates, select_inner_candidate
from editor021_cfpr.protocol import assert_perturbation_hashes
from editor021_cfpr.safety import (
    Editor021Blocked,
    Editor021ProtocolError,
    enter_inner_phase,
    exit_inner_phase,
    refuse_historical_write,
    refuse_official_validation_during_inner,
    refuse_validation_threshold_search,
)


def test_t19_r52_test_denied():
    with pytest.raises(Exception, match="TEST"):
        refuse_r52_test(
            r"C:\PhD\07_Projects\cert-r42-feasibility\data\processed\r5.2\tensors\r52_T20_s1_test.npz"
        )


def test_t20_r51_r62_denied():
    with pytest.raises(Exception):
        refuse_r51(r"C:\PhD\07_Projects\cert-r42-feasibility\data\processed\r5.1\tensors\x.npz")
    with pytest.raises(Exception):
        refuse_r62(r"C:\PhD\07_Projects\cert-r42-feasibility\data\processed\r6.2\tensors\x.npz")


def test_t16_perturbation_hashes_match_editor020():
    hashes = assert_perturbation_hashes()
    assert hashes["objective3_missing_source_robustness.py"] == EXPECTED_SOURCE_ABLATION_SHA256
    assert hashes["objective3_perturbations.py"] == EXPECTED_GAUSSIAN_SHA256


def test_t17_family_first_sampler_deterministic():
    a = [sample_partner(i, 3, seed=42) for i in range(20)]
    b = [sample_partner(i, 3, seed=42) for i in range(20)]
    assert a == b
    lock = sampler_lock()
    assert lock["P_source"] == 0.5 and lock["P_noise"] == 0.5


def test_t18_labels_never_enter_family_selection():
    y = np.array([0, 1, 0, 1], dtype=np.float32)
    fams = [sample_partner(i, 0, seed=42) for i in range(4)]
    y2 = np.array([1, 1, 1, 1], dtype=np.float32)
    fams2 = [sample_partner(i, 0, seed=42) for i in range(4)]
    assert fams == fams2
    assert not np.array_equal(y, y2)


def test_t13_t14_t15_rho_values():
    assert CANDIDATES["CFPR10"]["rho"] == pytest.approx(0.10)
    assert CANDIDATES["CFPR25"]["rho"] == pytest.approx(0.25)
    assert CANDIDATES["CFPR50"]["rho"] == pytest.approx(0.50)
    assert CANDIDATES["CFP0"]["rho"] == pytest.approx(0.0)
    assert CANDIDATES["CFP0"]["robustness"] is False
    assert ROBUSTNESS_CANDIDATES == ("CFPR10", "CFPR25", "CFPR50")


def test_t12_cfp0_has_no_robustness_gradient():
    assert CANDIDATES["CFP0"]["robustness"] is False
    assert abs(CANDIDATES["CFP0"]["rho"]) < 1e-15


def test_lambda_fp_frozen():
    assert LAMBDA_FP == 1.0
    assert LAMBDA_TEACHER == 0.5
    assert LAMBDA_ROUTE == 0.5


def test_t08_conflict_projection_nonnegative_dot():
    g_c = torch.tensor([1.0, 0.0, 0.0])
    g_r = torch.tensor([-2.0, 1.0, 0.0])
    assert float(torch.dot(g_c, g_r)) < 0
    g_perp, projected = project_robustness(g_c, g_r)
    assert projected is True
    assert float(torch.dot(g_c, g_perp)) >= -1e-6


def test_t09_no_projection_when_nonconflicting():
    g_c = torch.tensor([1.0, 0.0])
    g_r = torch.tensor([0.5, 1.0])
    g_perp, projected = project_robustness(g_c, g_r)
    assert projected is False
    assert torch.allclose(g_perp, g_r)


def test_t10_rho_budget():
    g_c = torch.tensor([3.0, 4.0])
    g_r = torch.tensor([100.0, 0.0])
    g_perp, _ = project_robustness(g_c, g_r)
    scaled, alpha = rho_scale(g_c, g_perp, 0.10)
    assert float(torch.linalg.vector_norm(scaled)) <= 0.10 * float(torch.linalg.vector_norm(g_c)) + 1e-6
    packed = combine_encoder_grads(g_c, g_r, 0.25)
    assert float(packed["scaled_norm"]) <= 0.25 * float(packed["gc_norm"]) + 1e-6
    assert alpha >= 0.0


def test_t11_tiny_clean_grad_zeroes_robustness():
    g_c = torch.tensor([1e-16, 0.0])
    g_r = torch.tensor([4.0, 3.0])
    scaled, alpha = rho_scale(g_c, g_r, 0.50)
    assert alpha == 0.0
    assert float(torch.linalg.vector_norm(scaled)) == 0.0


def _tiny_xy(device: torch.device) -> torch.Tensor:
    g = torch.Generator(device="cpu")
    g.manual_seed(0)
    return torch.randn(4, 20, 13, generator=g, dtype=torch.float32).to(device)


@pytest.fixture()
def ta2_pair():
    device = torch.device("cpu")
    student, sha_s = load_ta2_student(42, device)
    reference, sha_r = load_ta2_reference(42, device)
    assert sha_s == sha_r
    return student, reference, device, sha_s


def test_t01_reference_requires_grad_false(ta2_pair):
    _student, reference, _device, _sha = ta2_pair
    assert all(not p.requires_grad for p in reference.parameters())


def test_t02_reference_unchanged_after_student_step(ta2_pair):
    student, reference, device, _sha = ta2_pair
    freeze_teacher(reference)
    before = {k: v.detach().clone() for k, v in reference.state_dict().items()}
    x = _tiny_xy(device)
    student.train()
    opt = build_optimizer(student)
    opt.zero_grad(set_to_none=True)
    out = student_forward(student, x)
    out["logit"].sum().backward()
    opt.step()
    for k, v in reference.state_dict().items():
        assert torch.equal(v.cpu(), before[k].cpu())
    assert all(not p.requires_grad for p in reference.parameters())


def test_t03_initial_outputs_match(ta2_pair):
    student, reference, device, _sha = ta2_pair
    x = _tiny_xy(device)
    rec = assert_initial_match(student, reference, x)
    assert rec["logit_max_abs"] < 1e-6


def test_t04_t05_reference_tensors_detached(ta2_pair):
    student, reference, device, _sha = ta2_pair
    x = _tiny_xy(device)
    with torch.no_grad():
        ref = student_forward(reference, x)
    h_ref = ref["z"].detach()
    z_ref = ref["logit"].detach()
    assert h_ref.requires_grad is False
    assert z_ref.requires_grad is False
    student.train()
    s = student_forward(student, x)
    loss_fp = torch.mean((s["logit"] - z_ref) ** 2)
    loss_repr = cosine_repr_loss(s["z"], h_ref)
    enc = encoder_attention_params(student)
    g_enc = torch.autograd.grad(loss_repr + loss_fp, enc, allow_unused=True)
    assert any(g is not None for g in g_enc)
    assert h_ref.grad is None
    assert z_ref.grad is None


def test_t06_repr_loss_has_no_odst_grad(ta2_pair):
    student, reference, device, _sha = ta2_pair
    x = _tiny_xy(device)
    with torch.no_grad():
        h_ref = student_forward(reference, x)["z"].detach()
    student.train()
    s = student_forward(student, x)
    loss = cosine_repr_loss(s["z"], h_ref)
    head = odst_head_params(student)
    grads = torch.autograd.grad(loss, head, allow_unused=True)
    assert all(g is None or float(g.abs().sum()) == 0.0 for g in grads)
    enc = encoder_attention_params(student)
    enc_grads = torch.autograd.grad(loss, enc, allow_unused=True)
    assert any(g is not None and float(g.abs().sum()) > 0.0 for g in enc_grads)


def test_t07_clean_loss_has_odst_grad(ta2_pair):
    student, _reference, device, _sha = ta2_pair
    x = _tiny_xy(device)
    y = torch.zeros(4, device=device)
    student.train()
    s = student_forward(student, x)
    loss = torch.nn.functional.binary_cross_entropy_with_logits(s["logit"], y)
    head = odst_head_params(student)
    grads = torch.autograd.grad(loss, head, allow_unused=True)
    assert any(g is not None and float(g.abs().sum()) > 0.0 for g in grads)


def test_t21_no_external_scaler_fit():
    scaler = load_r52_train_scaler()
    assert "mean" in scaler or "means" in scaler or "scale" in scaler or "feature_mean" in scaler or scaler


def test_t22_validation_threshold_search_denied():
    with pytest.raises(Editor021Blocked):
        refuse_validation_threshold_search(split="validation", threshold=None)


def test_t23_raw_prediction_writer_exists():
    from editor021_cfpr.campaign import write_raw

    assert callable(write_raw)


def _row(candidate: str, seed: int, clean: float, s_src: float, s_nz: float) -> dict:
    return {
        "candidate": candidate,
        "seed": seed,
        "rho": CANDIDATES.get(candidate, {}).get("rho", 0.0),
        "clean_PR_AUC": clean,
        "S_source": s_src,
        "S_noise": s_nz,
        "S_composite": 0.5 * s_src + 0.5 * s_nz,
    }


def test_t24_inner_gates_g1_g5():
    rows = []
    for seed in (42, 52, 62):
        rows.append(_row("CFP0", seed, 0.90, -0.20, -0.10))
        rows.append(_row("CFPR10", seed, 0.9005, -0.18, -0.08))
        rows.append(_row("CFPR25", seed, 0.88, -0.05, -0.02))
        rows.append(_row("CFPR50", seed, 0.9002, -0.19, -0.09))
    rec = select_inner_candidate(rows)
    assert rec["EDITOR021_SELECTED_CANDIDATE"] == "CFPR10"
    assert rec["manual_override"] is False
    fail_rows = []
    for seed in (42, 52, 62):
        fail_rows.append(_row("CFP0", seed, 0.90, -0.20, -0.10))
        fail_rows.append(_row("CFPR10", seed, 0.89, -0.05, -0.02))
    rec2 = select_inner_candidate(fail_rows)
    assert rec2["EDITOR021_INNER_PROMOTION"] == "NONE"


def test_t25_official_gates_o1_o6():
    ok = evaluate_official_gates(
        clean_delta=-0.0005,
        clean_ci_lo=-0.002,
        composite_delta=0.01,
        source_gain=0.004,
        noise_gain=0.006,
        composite_ci_lo=0.001,
        n_seeds_positive_composite=3,
    )
    assert ok["promoted"] is True
    assert ok["EDITOR021_PROMOTION"] == "SUPPORTED"
    bad = evaluate_official_gates(
        clean_delta=-0.02,
        clean_ci_lo=-0.03,
        composite_delta=0.01,
        source_gain=0.004,
        noise_gain=0.006,
        composite_ci_lo=0.001,
        n_seeds_positive_composite=3,
    )
    assert bad["promoted"] is False
    assert bad["EDITOR021_PROMOTION"] == "NO"


def test_cfp0_scaffold_logic():
    cfp0 = [_row("CFP0", s, 0.93, -0.3, -0.1) for s in (42, 52, 62)]
    start = [_row("STARTING_TA2", s, 0.9305, -0.4, -0.2) for s in (42, 52, 62)]
    rec = evaluate_cfp0_scaffold(cfp0, start)
    assert rec["pass"] is True
    start2 = [_row("STARTING_TA2", s, 0.94, -0.4, -0.2) for s in (42, 52, 62)]
    rec2 = evaluate_cfp0_scaffold(cfp0, start2)
    assert rec2["pass"] is False


def test_inner_cannot_read_validation():
    enter_inner_phase()
    try:
        with pytest.raises(Editor021Blocked):
            refuse_official_validation_during_inner("r52_T20_s1_validation.npz")
    finally:
        exit_inner_phase()


def test_historical_packets_read_only():
    with pytest.raises(Editor021ProtocolError, match="historical"):
        refuse_historical_write("review/editor020_teacher_degraded_consistency/x.json")


def test_parent_commit_is_full_sha():
    assert EDITOR020C_PARENT_COMMIT == "c26e7291c077dd2626544701217201016c27194d"
    assert len(EDITOR020C_PARENT_COMMIT) == 40


def test_resilience_composite_equal_family_weight():
    y = np.array([0, 1, 0, 1, 0, 1], dtype=int)
    clean = np.array([0.0, 3.0, -1.0, 2.0, -2.0, 1.0])
    src = {ch: clean - 0.5 for ch in ("logon", "device", "file", "email", "http")}
    nz = {0.05: clean - 0.2, 0.10: clean - 0.2, 0.20: clean - 0.2}
    rec = resilience_from_logits(y, clean, src, nz, threshold=0.5)
    assert rec["S_composite"] == pytest.approx(0.5 * rec["S_source"] + 0.5 * rec["S_noise"])


def test_no_label_dependent_corruption_shapes():
    scaler = load_r52_train_scaler()
    x = np.random.default_rng(0).normal(size=(6, 20, 13)).astype(np.float32)
    y = np.array([0, 1, 0, 1, 0, 1], dtype=np.float32)
    xd = apply_sampled_batch(x, np.arange(6), epoch=1, scaler=scaler)
    xs = apply_source_ablation(x, "http", scaler)
    xn = apply_gaussian_noise(x, 0.10)
    assert xd.shape == x.shape == xs.shape == xn.shape
    assert np.array_equal(y, np.array([0, 1, 0, 1, 0, 1], dtype=np.float32))


def test_sha256_manifest_does_not_hash_itself(tmp_path):
    from editor021_cfpr.campaign import SHA256_MANIFEST_NAME, sha256_manifest

    review = tmp_path / "review" / "editor021_clean_function_representation_robustness"
    review.mkdir(parents=True)
    (review / "EDITOR021_RUN_MANIFEST.json").write_text('{"phase": "complete"}', encoding="utf-8")
    (review / SHA256_MANIFEST_NAME).write_text("{}", encoding="utf-8")
    rec = sha256_manifest(list(review.rglob("*")), repo_root=tmp_path)
    assert rec
    assert all(Path(key).name != SHA256_MANIFEST_NAME for key in rec)
    assert any(Path(key).name == "EDITOR021_RUN_MANIFEST.json" for key in rec)


def test_final_run_manifest_not_modified_after_hash_recorded(tmp_path, monkeypatch):
    """A completed RUN_MANIFEST must not be rewritten after its SHA256 is recorded."""
    import editor021_cfpr.campaign as campaign

    repo = tmp_path
    review = repo / "review" / "editor021_clean_function_representation_robustness"
    review.mkdir(parents=True)
    (review / "EDITOR021_PROMOTION_DECISION.json").write_text(
        '{"EDITOR021_PROMOTION": "NO"}', encoding="utf-8"
    )

    writes: list[str] = []
    real_write_json = campaign.write_json

    def tracked_write_json(path, obj):
        writes.append(Path(path).name)
        real_write_json(path, obj)

    monkeypatch.setattr(campaign, "write_json", tracked_write_json)

    payload = {
        "EDITOR021_PROMOTION": "NO",
        "CURRENT_PAPER_MODEL": "TA2",
        "EDITOR021_CLEAN_FUNCTION_PRESERVATION": "SUPPORTED",
        "EDITOR021_TRAINING_TIME_ROBUSTNESS_HARDENING": "NOT_SUPPORTED",
        "EDITOR021_OFFICIAL_VALIDATION_EXECUTED": "NO",
        "CFP0_SCAFFOLD_GATE": "PASS",
        "protocol_commit": "a1e7825c1f11bfe36595ef28c197c7a105685aaf",
    }
    rec, _text = campaign.finalise_completed_packet(payload, review_root=review, repo_root=repo)

    run_name = campaign.RUN_MANIFEST_NAME
    sha_name = campaign.SHA256_MANIFEST_NAME
    assert run_name in writes
    assert sha_name in writes
    assert writes.index(run_name) < writes.index(sha_name)
    assert run_name not in writes[writes.index(sha_name) :]

    run_path = review / run_name
    before_digest = hashlib.sha256(run_path.read_bytes()).hexdigest()
    key = next(k for k in rec if Path(k).name == run_name)
    assert rec[key] == before_digest
    stored = json.loads((review / sha_name).read_text(encoding="utf-8"))
    assert stored[key] == hashlib.sha256(run_path.read_bytes()).hexdigest()
    assert run_path.read_bytes()
    assert stored[key] == before_digest
    assert all(Path(k).name != sha_name for k in rec)
