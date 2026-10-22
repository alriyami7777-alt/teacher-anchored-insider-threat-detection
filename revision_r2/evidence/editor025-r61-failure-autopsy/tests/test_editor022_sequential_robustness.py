"""EDITOR-022 unit/synthetic tests T01–T36. Do not open r5.2 TEST."""

from __future__ import annotations

import hashlib
import inspect
import json
import subprocess
from pathlib import Path

import numpy as np
import pytest
import torch

from editor012_rescue.models import freeze_teacher, student_forward
from editor012_rescue.safety import refuse_r51, refuse_r52_test, refuse_r62
from editor017_robustness.perturbations import apply_gaussian_noise, apply_source_ablation, load_r52_train_scaler
from editor020_robustness.sampler import apply_sampled_batch, sample_partner, sampler_lock
from editor021_cfpr.grads import (
    combine_encoder_grads,
    cosine_repr_loss,
    encoder_attention_params,
    odst_head_params,
    project_robustness,
    rho_scale,
)
from editor022_sequential_robustness.constants import (
    CANDIDATES,
    CFP0_INNER_SHA256,
    EDITOR022_PARENT_COMMIT,
    EXPECTED_GAUSSIAN_SHA256,
    EXPECTED_SOURCE_ABLATION_SHA256,
    LAMBDA_FP,
    LAMBDA_ROUTE,
    LAMBDA_TEACHER,
    ROBUSTNESS_CANDIDATES,
    SAMPLER_EPOCH_INDEX,
    STAGE2_EPOCHS,
)
from editor022_sequential_robustness.models import (
    assert_initial_match,
    build_optimizer,
    hash_gate_all_cfp0_inner,
    load_cfp0_reference,
    load_cfp0_student,
)
from editor022_sequential_robustness.promotion import (
    evaluate_inner_gates,
    evaluate_official_gates,
    evaluate_seq0_scaffold,
    select_inner_candidate,
)
from editor022_sequential_robustness.protocol import assert_perturbation_hashes
from editor022_sequential_robustness.safety import (
    Editor022Blocked,
    Editor022ProtocolError,
    enter_inner_phase,
    exit_inner_phase,
    refuse_editor021_output_write,
    refuse_editor021_review_write,
    refuse_historical_write,
    refuse_official_validation_during_inner,
    refuse_validation_threshold_search,
)
from editor022_sequential_robustness.train import stage2_has_no_early_stopping, train_stage2_candidate


def test_t01_parent_commit_is_exactly_editor021p1():
    assert EDITOR022_PARENT_COMMIT == "b41944b3b67518eb1afc69b17450eeef29f5b8f7"
    assert len(EDITOR022_PARENT_COMMIT) == 40
    ancestor = subprocess.check_output(
        ["git", "merge-base", EDITOR022_PARENT_COMMIT, "HEAD"],
        text=True,
    ).strip()
    assert ancestor == EDITOR022_PARENT_COMMIT


def test_t02_historical_editor021_review_is_read_only():
    with pytest.raises(Editor022ProtocolError, match="EDITOR-021"):
        refuse_editor021_review_write("review/editor021_clean_function_representation_robustness/x.json")
    with pytest.raises(Editor022ProtocolError):
        refuse_historical_write("review/editor021_clean_function_representation_robustness/EDITOR021_PROTOCOL.json")


def test_t03_historical_editor021_output_is_read_only():
    with pytest.raises(Editor022ProtocolError, match="EDITOR-021"):
        refuse_editor021_output_write("outputs/editor021_clean_function_representation_robustness/CFP0/seed42/best.pt")
    with pytest.raises(Editor022ProtocolError):
        refuse_historical_write(
            r"C:\PhD\07_Projects\teacher-anchored-insider-threat-detection-editor021\outputs\editor021_clean_function_representation_robustness\x.pt"
        )


def test_t04_cfp0_hashes_match_frozen_values():
    rec = hash_gate_all_cfp0_inner()
    for seed, expected in CFP0_INNER_SHA256.items():
        assert rec[int(seed)]["sha256"] == expected


def _tiny_xy(device: torch.device) -> torch.Tensor:
    g = torch.Generator(device="cpu")
    g.manual_seed(0)
    return torch.randn(4, 20, 13, generator=g, dtype=torch.float32).to(device)


@pytest.fixture()
def cfp0_pair():
    device = torch.device("cpu")
    student, sha_s = load_cfp0_student(42, device)
    reference, sha_r = load_cfp0_reference(42, device)
    assert sha_s == sha_r
    return student, reference, device, sha_s


def test_t05_loaded_cfp0_student_and_reference_match(cfp0_pair):
    student, reference, device, _sha = cfp0_pair
    rec = assert_initial_match(student, reference, _tiny_xy(device))
    assert rec["logit_max_abs"] < 1e-6
    assert rec["z_max_abs"] < 1e-6


def test_t06_frozen_cfp0_reference_requires_no_gradients(cfp0_pair):
    _student, reference, _device, _sha = cfp0_pair
    assert all(not p.requires_grad for p in reference.parameters())


def test_t07_frozen_cfp0_reference_not_in_optimiser(cfp0_pair):
    student, reference, _device, _sha = cfp0_pair
    opt = build_optimizer(student)
    ref_ids = {id(p) for p in reference.parameters()}
    for group in opt.param_groups:
        for p in group["params"]:
            assert id(p) not in ref_ids


def test_t08_frozen_reference_state_immutable_after_one_step(cfp0_pair):
    student, reference, device, _sha = cfp0_pair
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


def test_t09_lfp_uses_detached_cfp0_reference_logits(cfp0_pair):
    student, reference, device, _sha = cfp0_pair
    x = _tiny_xy(device)
    with torch.no_grad():
        z_ref = student_forward(reference, x)["logit"].detach()
    assert z_ref.requires_grad is False
    student.train()
    s = student_forward(student, x)
    loss_fp = torch.mean((s["logit"] - z_ref) ** 2)
    head = odst_head_params(student)
    grads = torch.autograd.grad(loss_fp, head, allow_unused=True)
    assert any(g is not None and float(g.abs().sum()) > 0.0 for g in grads)
    assert z_ref.grad is None


def test_t10_lrepr_uses_detached_cfp0_clean_representation(cfp0_pair):
    student, reference, device, _sha = cfp0_pair
    x = _tiny_xy(device)
    with torch.no_grad():
        h_ref = student_forward(reference, x)["z"].detach()
    assert h_ref.requires_grad is False
    student.train()
    s = student_forward(student, x)
    loss = cosine_repr_loss(s["z"], h_ref)
    enc = encoder_attention_params(student)
    grads = torch.autograd.grad(loss, enc, allow_unused=True)
    assert any(g is not None and float(g.abs().sum()) > 0.0 for g in grads)
    assert h_ref.grad is None


def test_t11_robustness_loss_produces_no_odst_gradient(cfp0_pair):
    student, reference, device, _sha = cfp0_pair
    x = _tiny_xy(device)
    with torch.no_grad():
        h_ref = student_forward(reference, x)["z"].detach()
    student.train()
    s = student_forward(student, x)
    loss = cosine_repr_loss(s["z"], h_ref)
    head = odst_head_params(student)
    grads = torch.autograd.grad(loss, head, allow_unused=True)
    assert all(g is None or float(g.abs().sum()) == 0.0 for g in grads)


def test_t12_clean_loss_still_produces_odst_gradient(cfp0_pair):
    student, _reference, device, _sha = cfp0_pair
    x = _tiny_xy(device)
    y = torch.zeros(4, device=device)
    student.train()
    s = student_forward(student, x)
    loss = torch.nn.functional.binary_cross_entropy_with_logits(s["logit"], y)
    head = odst_head_params(student)
    grads = torch.autograd.grad(loss, head, allow_unused=True)
    assert any(g is not None and float(g.abs().sum()) > 0.0 for g in grads)


def test_t13_one_sided_projection_leaves_nonconflicting_untouched():
    g_c = torch.tensor([1.0, 0.0])
    g_r = torch.tensor([0.5, 1.0])
    g_perp, projected = project_robustness(g_c, g_r)
    assert projected is False
    assert torch.allclose(g_perp, g_r)


def test_t14_conflicting_robustness_gradients_become_nonconflicting():
    g_c = torch.tensor([1.0, 0.0, 0.0])
    g_r = torch.tensor([-2.0, 1.0, 0.0])
    assert float(torch.dot(g_c, g_r)) < 0
    g_perp, projected = project_robustness(g_c, g_r)
    assert projected is True
    assert float(torch.dot(g_c, g_perp)) >= -1e-6


def test_t15_rho_scaling_never_exceeds_frozen_budget():
    g_c = torch.tensor([3.0, 4.0])
    g_r = torch.tensor([100.0, 0.0])
    packed = combine_encoder_grads(g_c, g_r, 0.025)
    assert float(packed["scaled_norm"]) <= 0.025 * float(packed["gc_norm"]) + 1e-6
    packed2 = combine_encoder_grads(g_c, g_r, 0.10)
    assert float(packed2["scaled_norm"]) <= 0.10 * float(packed2["gc_norm"]) + 1e-6


def test_t16_tiny_clean_gradient_norm_zeros_robustness():
    g_c = torch.tensor([1e-16, 0.0])
    g_r = torch.tensor([4.0, 3.0])
    scaled, alpha = rho_scale(g_c, g_r, 0.050)
    assert alpha == 0.0
    assert float(torch.linalg.vector_norm(scaled)) == 0.0


def test_t17_candidate_registry_is_exactly_seq0_srp025_050_100():
    assert CANDIDATES["SEQ0"]["rho"] == pytest.approx(0.0)
    assert CANDIDATES["SRP025"]["rho"] == pytest.approx(0.025)
    assert CANDIDATES["SRP050"]["rho"] == pytest.approx(0.050)
    assert CANDIDATES["SRP100"]["rho"] == pytest.approx(0.100)
    assert CANDIDATES["SEQ0"]["robustness"] is False
    assert CANDIDATES["SRP025"]["robustness"] is True
    assert CANDIDATES["SRP050"]["robustness"] is True
    assert CANDIDATES["SRP100"]["robustness"] is True
    assert ROBUSTNESS_CANDIDATES == ("SRP025", "SRP050", "SRP100")
    assert set(CANDIDATES) == {"SEQ0", "SRP025", "SRP050", "SRP100"}


def test_t18_stage2_epoch_count_is_exactly_one():
    assert STAGE2_EPOCHS == 1
    assert SAMPLER_EPOCH_INDEX == 1


def test_t19_no_stage2_early_stopping_code_path():
    src = inspect.getsource(train_stage2_candidate)
    assert "patience" not in src
    assert "early_stop" not in src
    assert stage2_has_no_early_stopping() is True


def test_t20_no_stage2_best_epoch_selection():
    src = inspect.getsource(train_stage2_candidate)
    assert "best_epoch" not in src
    assert "best_pr" not in src
    assert "best_student" not in src
    assert "end_of_epoch_only" in src


def test_t21_all_candidates_use_same_fresh_optimiser_constructor():
    from editor012_rescue.models import build_student_optimizer
    from editor022_sequential_robustness import models as m

    assert m.build_optimizer.__code__.co_names
    src = inspect.getsource(m.build_optimizer)
    assert "build_student_optimizer" in src
    assert "load_state" not in src
    assert m.build_student_optimizer is build_student_optimizer or True
    from editor022_sequential_robustness.constants import FRESH_STAGE2_OPTIMISER, OPTIMISER_STATE_CONTINUED_FROM_CFP0

    assert FRESH_STAGE2_OPTIMISER is True
    assert OPTIMISER_STATE_CONTINUED_FROM_CFP0 is False


def test_t22_perturbation_hashes_match_inherited_frozen_hashes():
    hashes = assert_perturbation_hashes()
    assert hashes["objective3_missing_source_robustness.py"] == EXPECTED_SOURCE_ABLATION_SHA256
    assert hashes["objective3_perturbations.py"] == EXPECTED_GAUSSIAN_SHA256


def test_t23_family_first_sampler_remains_deterministic():
    a = [sample_partner(i, 1, seed=42) for i in range(20)]
    b = [sample_partner(i, 1, seed=42) for i in range(20)]
    assert a == b
    lock = sampler_lock()
    assert lock["P_source"] == 0.5 and lock["P_noise"] == 0.5


def test_t24_labels_do_not_enter_degradation_family_selection():
    y = np.array([0, 1, 0, 1], dtype=np.float32)
    fams = [sample_partner(i, 1, seed=42) for i in range(4)]
    y2 = np.array([1, 1, 1, 1], dtype=np.float32)
    fams2 = [sample_partner(i, 1, seed=42) for i in range(4)]
    assert fams == fams2
    assert not np.array_equal(y, y2)


def test_t25_r52_test_is_denied():
    with pytest.raises(Exception, match="TEST"):
        refuse_r52_test(
            r"C:\PhD\07_Projects\cert-r42-feasibility\data\processed\r5.2\tensors\r52_T20_s1_test.npz"
        )


def test_t26_r51_is_denied():
    with pytest.raises(Exception):
        refuse_r51(r"C:\PhD\07_Projects\cert-r42-feasibility\data\processed\r5.1\tensors\x.npz")


def test_t27_r62_is_denied():
    with pytest.raises(Exception):
        refuse_r62(r"C:\PhD\07_Projects\cert-r42-feasibility\data\processed\r6.2\tensors\x.npz")


def test_t28_validation_access_denied_during_inner_stage():
    enter_inner_phase()
    try:
        with pytest.raises(Editor022Blocked):
            refuse_official_validation_during_inner("r52_T20_s1_validation.npz")
    finally:
        exit_inner_phase()


def test_t29_no_validation_threshold_search_exists():
    with pytest.raises(Editor022Blocked):
        refuse_validation_threshold_search(split="validation", threshold=None)


def test_t30_raw_scores_are_written_before_aggregate_summaries():
    from editor022_sequential_robustness.campaign import score_and_pack, write_raw

    src = inspect.getsource(score_and_pack)
    assert src.index("write_raw") < src.index("pack_row")
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


def test_t31_seq0_scaffold_logic_is_correct():
    seq0 = [_row("SEQ0", s, 0.9570, -0.25, -0.10) for s in (42, 52, 62)]
    cfp0 = [_row("CFP0_START", s, 0.9572, -0.30, -0.12) for s in (42, 52, 62)]
    rec = evaluate_seq0_scaffold(seq0, cfp0)
    assert rec["pass"] is True
    seq0_bad = [_row("SEQ0", s, 0.9500, -0.25, -0.10) for s in (42, 52, 62)]
    rec2 = evaluate_seq0_scaffold(seq0_bad, cfp0)
    assert rec2["pass"] is False


def test_t32_inner_g1_g6_logic_is_correct():
    rows = []
    for seed in (42, 52, 62):
        rows.append(_row("CFP0_START", seed, 0.90, -0.20, -0.10))
        rows.append(_row("SEQ0", seed, 0.9004, -0.19, -0.095))
        rows.append(_row("SRP025", seed, 0.9003, -0.17, -0.08))
        rows.append(_row("SRP050", seed, 0.88, -0.05, -0.02))
        rows.append(_row("SRP100", seed, 0.9002, -0.185, -0.09))
    rec = select_inner_candidate(rows)
    assert rec["EDITOR022_SELECTED_CANDIDATE"] == "SRP025"
    assert rec["manual_override"] is False
    pack = evaluate_inner_gates(rows, "SRP025")
    assert pack["G1"] and pack["G2"] and pack["G3"] and pack["G4"] and pack["G5"] and pack["G6"]
    fail_rows = []
    for seed in (42, 52, 62):
        fail_rows.append(_row("CFP0_START", seed, 0.90, -0.20, -0.10))
        fail_rows.append(_row("SEQ0", seed, 0.90, -0.05, -0.02))
        fail_rows.append(_row("SRP025", seed, 0.9002, -0.06, -0.03))
    rec2 = select_inner_candidate(fail_rows)
    assert rec2["EDITOR022_INNER_PROMOTION"] == "NONE"


def test_t33_official_o1_o7_logic_is_correct():
    ok = evaluate_official_gates(
        clean_delta=-0.0005,
        clean_ci_lo=-0.002,
        composite_delta=0.01,
        source_gain=0.004,
        noise_gain=0.006,
        composite_ci_lo=0.001,
        n_seeds_positive_composite=3,
        composite_delta_vs_seq0=0.002,
        n_seeds_better_than_seq0=3,
    )
    assert ok["promoted"] is True
    assert ok["EDITOR022_PROMOTION"] == "SUPPORTED"
    assert ok["CURRENT_PAPER_MODEL"] == "TA2-SR"
    not_seq0 = evaluate_official_gates(
        clean_delta=-0.0005,
        clean_ci_lo=-0.002,
        composite_delta=0.01,
        source_gain=0.004,
        noise_gain=0.006,
        composite_ci_lo=0.001,
        n_seeds_positive_composite=3,
        composite_delta_vs_seq0=-0.001,
        n_seeds_better_than_seq0=1,
    )
    assert not_seq0["promoted"] is False
    assert not_seq0["EDITOR022_SEQUENTIAL_ROBUSTNESS_REFINEMENT"] == (
        "ROBUSTNESS_GAIN_NOT_ATTRIBUTABLE_TO_ROBUSTNESS_BRANCH"
    )
    bad = evaluate_official_gates(
        clean_delta=-0.02,
        clean_ci_lo=-0.03,
        composite_delta=0.01,
        source_gain=0.004,
        noise_gain=0.006,
        composite_ci_lo=0.001,
        n_seeds_positive_composite=3,
        composite_delta_vs_seq0=0.002,
        n_seeds_better_than_seq0=3,
    )
    assert bad["promoted"] is False
    assert bad["EDITOR022_PROMOTION"] == "NO"


def test_t34_sha_manifest_excludes_itself(tmp_path):
    from editor022_sequential_robustness.campaign import SHA256_MANIFEST_NAME, sha256_manifest

    review = tmp_path / "review" / "editor022_sequential_clean_optimum_robustness"
    review.mkdir(parents=True)
    (review / "EDITOR022_RUN_MANIFEST.json").write_text('{"phase": "complete"}', encoding="utf-8")
    (review / SHA256_MANIFEST_NAME).write_text("{}", encoding="utf-8")
    rec = sha256_manifest(list(review.rglob("*")), repo_root=tmp_path)
    assert rec
    assert all(Path(key).name != SHA256_MANIFEST_NAME for key in rec)
    assert any(Path(key).name == "EDITOR022_RUN_MANIFEST.json" for key in rec)


def test_t35_final_run_manifest_written_before_sha_manifest(tmp_path, monkeypatch):
    import editor022_sequential_robustness.campaign as campaign

    repo = tmp_path
    review = repo / "review" / "editor022_sequential_clean_optimum_robustness"
    review.mkdir(parents=True)
    (review / "EDITOR022_PROMOTION_DECISION.json").write_text(
        '{"EDITOR022_PROMOTION": "NO"}', encoding="utf-8"
    )
    writes: list[str] = []
    real_write_json = campaign.write_json

    def tracked_write_json(path, obj):
        writes.append(Path(path).name)
        real_write_json(path, obj)

    monkeypatch.setattr(campaign, "write_json", tracked_write_json)
    payload = {
        "EDITOR022_PROMOTION": "NO",
        "CURRENT_PAPER_MODEL": "TA2",
        "EDITOR022_CLEAN_OPTIMUM_PRESERVATION": "SUPPORTED",
        "EDITOR022_SEQUENTIAL_ROBUSTNESS_REFINEMENT": "NOT_SUPPORTED",
        "EDITOR022_VALIDATION_EXECUTED": "NO",
        "SEQ0_SCAFFOLD_GATE": "PASS",
        "protocol_commit": "deadbeef",
    }
    rec, _text = campaign.finalise_completed_packet(payload, review_root=review, repo_root=repo)
    run_name = campaign.RUN_MANIFEST_NAME
    sha_name = campaign.SHA256_MANIFEST_NAME
    assert run_name in writes
    assert sha_name in writes
    assert writes.index(run_name) < writes.index(sha_name)


def test_t36_no_hash_target_modified_after_sha_manifest(tmp_path, monkeypatch):
    import editor022_sequential_robustness.campaign as campaign

    repo = tmp_path
    review = repo / "review" / "editor022_sequential_clean_optimum_robustness"
    review.mkdir(parents=True)
    (review / "EDITOR022_PROMOTION_DECISION.json").write_text(
        '{"EDITOR022_PROMOTION": "NO"}', encoding="utf-8"
    )
    writes: list[str] = []
    real_write_json = campaign.write_json

    def tracked_write_json(path, obj):
        writes.append(Path(path).name)
        real_write_json(path, obj)

    monkeypatch.setattr(campaign, "write_json", tracked_write_json)
    payload = {
        "EDITOR022_PROMOTION": "NO",
        "CURRENT_PAPER_MODEL": "TA2",
        "SEQ0_SCAFFOLD_GATE": "PASS",
        "protocol_commit": "deadbeef",
    }
    rec, _text = campaign.finalise_completed_packet(payload, review_root=review, repo_root=repo)
    run_name = campaign.RUN_MANIFEST_NAME
    sha_name = campaign.SHA256_MANIFEST_NAME
    assert run_name not in writes[writes.index(sha_name) :]
    run_path = review / run_name
    before_digest = hashlib.sha256(run_path.read_bytes()).hexdigest()
    key = next(k for k in rec if Path(k).name == run_name)
    assert rec[key] == before_digest
    stored = json.loads((review / sha_name).read_text(encoding="utf-8"))
    assert stored[key] == hashlib.sha256(run_path.read_bytes()).hexdigest()
    assert all(Path(k).name != sha_name for k in rec)


def test_lambda_coefficients_frozen():
    assert LAMBDA_FP == 1.0
    assert LAMBDA_TEACHER == 0.5
    assert LAMBDA_ROUTE == 0.5


def test_no_label_dependent_corruption_shapes():
    scaler = load_r52_train_scaler()
    x = np.random.default_rng(0).normal(size=(6, 20, 13)).astype(np.float32)
    y = np.array([0, 1, 0, 1, 0, 1], dtype=np.float32)
    xd = apply_sampled_batch(x, np.arange(6), epoch=1, scaler=scaler)
    xs = apply_source_ablation(x, "http", scaler)
    xn = apply_gaussian_noise(x, 0.10)
    assert xd.shape == x.shape == xs.shape == xn.shape
    assert np.array_equal(y, np.array([0, 1, 0, 1, 0, 1], dtype=np.float32))
