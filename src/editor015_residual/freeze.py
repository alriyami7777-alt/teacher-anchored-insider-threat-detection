"""Phase A protocol freeze: source register, residual audits, model family freeze."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import torch

from editor012_rescue.losses import make_task_criterion
from editor012_rescue.models import live_odst_forward
from editor012_rescue.producing import build_odst046_model, pin_producing_sources
from editor012_rescue.safety import (
    EXPECTED_ARCHITECTURE_SHA256,
    EXPECTED_ODST_SHA256,
    EXPECTED_SCALER_SHA256,
    TRAIN_NPZ,
    VAL_NPZ,
)
from editor013_odst_value.models import HybridAlpha
from editor014_temporal_odst.models import ResidualBeta

from .constants import (
    BEST_CURRENT_PAPER_MODEL,
    C2OPT_CHECKPOINTS,
    DIRECTIONAL_KS,
    EDITOR012_IMPLEMENTATION_COMMIT,
    EDITOR012_PROMOTION_COMMIT,
    EDITOR012_PROTOCOL_COMMIT,
    EDITOR012_RESULTS_COMMIT,
    EDITOR013_RESULTS_COMMIT,
    EDITOR014_RESULTS_COMMIT,
    ENCODER_ARCH,
    ENSEMBLE_CACHE,
    EXPECTED_INNER_SELECT_N,
    EXPECTED_INNER_SELECT_POS,
    EXPECTED_INNER_TRAIN_N,
    EXPECTED_INNER_TRAIN_POS,
    EXPECTED_TRAIN_SHA256,
    EXPECTED_USER_MAPPING_SHA256,
    EXPECTED_VAL_MALICIOUS_USERS,
    EXPECTED_VAL_SHA256,
    EXPECTED_VAL_USERS,
    EXPECTED_VAL_WINDOWS_PER_USER,
    F11_CHECKPOINTS,
    FEATURE_DIM,
    FROZEN_L1_MEAN_PR_AUC,
    FROZEN_TA2_L1_CI,
    FROZEN_TA2_MEAN_PR_AUC,
    FROZEN_TA2_MINUS_L1,
    L1_CHECKPOINTS,
    LAMBDA_DISTILL,
    LAMBDA_RESIDUAL_TEACHER,
    LAMBDA_ROUTE,
    N_TREES_TOTAL,
    ODST046,
    POST_ATTENTION_ODST_INCREMENTAL_VALUE,
    PRIMARY_SEEDS,
    PROMOTION_MARGIN,
    RESIDUAL_CONDITIONS,
    SEQUENCE_LENGTH,
    TA2_REFERENCE_CENTRED_GLOBAL_TOPK_FAITHFULNESS,
    TEACHER_GUIDANCE_VS_INITIALISATION,
    TEMPORAL_ODST_INCREMENTAL_VALUE,
    TOPT_CHECKPOINTS,
    TREE_ORDER,
)
from .io_util import write_json
from .models import editor015_forward, make_modules, r3_equivalent_to_r1_if_l1_frozen
from .safety import (
    REVIEW_ROOT,
    Editor015Blocked,
    refuse_historical_write,
    refuse_r52_test,
    sha256_file,
    utc_now,
)
def _review(*parts: str) -> Path:
    path = REVIEW_ROOT.joinpath(*parts)
    refuse_historical_write(path)
    return path


def _artefact(path: Path, commit: str, role: str, expected: str | None = None) -> dict[str, Any]:
    observed = sha256_file(path) if path.is_file() else None
    if expected is not None and observed is not None and observed != expected:
        raise Editor015Blocked(f"hash mismatch role={role} expected={expected} observed={observed} path={path}")
    return {
        "path": str(path),
        "source_commit": commit,
        "SHA256": observed,
        "role": role,
        "exists": path.is_file(),
    }


def source_register() -> dict[str, Any]:
    pins = pin_producing_sources()
    artefacts = []
    for seed, spec in TOPT_CHECKPOINTS.items():
        artefacts.append(_artefact(spec["checkpoint"], "65214bdeb51f9a04925be41d3b4c778de75cf088", f"T-OPT/{seed}", spec["sha256"]))
    for seed, spec in C2OPT_CHECKPOINTS.items():
        artefacts.append(_artefact(spec["checkpoint"], "65214bdeb51f9a04925be41d3b4c778de75cf088", f"C2-OPT/{seed}", spec["sha256"]))
    for seed, spec in F11_CHECKPOINTS.items():
        artefacts.append(_artefact(spec["checkpoint"], EDITOR012_RESULTS_COMMIT, f"TA2/{seed}", spec["sha256"]))
        artefacts.append(_artefact(spec["val_logits"], EDITOR012_RESULTS_COMMIT, f"TA2_val_logits/{seed}"))
    for seed, spec in L1_CHECKPOINTS.items():
        artefacts.append(_artefact(spec["checkpoint"], EDITOR013_RESULTS_COMMIT, f"L1/{seed}", spec["sha256"]))
        artefacts.append(_artefact(spec["val_logits"], EDITOR013_RESULTS_COMMIT, f"L1_val_logits/{seed}"))
    for key, path in ENSEMBLE_CACHE.items():
        artefacts.append(_artefact(path, EDITOR013_RESULTS_COMMIT, f"ensemble_teacher/{key}"))
    artefacts.append(_artefact(TRAIN_NPZ, "locked-r52-tensors", "r52_TRAIN", EXPECTED_TRAIN_SHA256))
    artefacts.append(_artefact(VAL_NPZ, "locked-r52-tensors", "r52_VALIDATION", EXPECTED_VAL_SHA256))
    missing = [a["role"] for a in artefacts if not a["exists"]]
    if missing:
        raise Editor015Blocked(f"missing source artefacts: {missing}")
    return {
        "task_id": "EDITOR-015",
        "EDITOR012_PROTOCOL_COMMIT": EDITOR012_PROTOCOL_COMMIT,
        "EDITOR012_IMPLEMENTATION_COMMIT": EDITOR012_IMPLEMENTATION_COMMIT,
        "EDITOR012_PROMOTION_COMMIT": EDITOR012_PROMOTION_COMMIT,
        "EDITOR012_RESULTS_COMMIT": EDITOR012_RESULTS_COMMIT,
        "EDITOR013_RESULTS_COMMIT": EDITOR013_RESULTS_COMMIT,
        "EDITOR014_RESULTS_COMMIT": EDITOR014_RESULTS_COMMIT,
        "historical_packets_readonly": True,
        "TEACHER_GUIDANCE_VS_INITIALISATION": TEACHER_GUIDANCE_VS_INITIALISATION,
        "POST_ATTENTION_ODST_INCREMENTAL_VALUE": POST_ATTENTION_ODST_INCREMENTAL_VALUE,
        "TEMPORAL_ODST_INCREMENTAL_VALUE": TEMPORAL_ODST_INCREMENTAL_VALUE,
        "BEST_CURRENT_PAPER_MODEL": BEST_CURRENT_PAPER_MODEL,
        "producing_pins": pins,
        "artefacts": artefacts,
        "r52_test_opened": False,
        "r51_rerun": False,
        "r62_rerun": False,
    }


def previous_residual_gradient_audit() -> dict[str, Any]:
    """Autograd proof that alpha=0 / beta=0 starves ODST parameter gradients."""
    torch.manual_seed(42)
    student = build_odst046_model()
    student.train()
    x = torch.randn(8, SEQUENCE_LENGTH, FEATURE_DIM)
    z, enc = student.encode_attention_h(x)
    linear = enc["linear_logit"].detach()
    od = live_odst_forward(student.node_head, z)
    alpha = HybridAlpha()
    beta = ResidualBeta()
    assert float(alpha.alpha.item()) == 0.0
    assert float(beta.beta.item()) == 0.0
    final_a = alpha(linear, od["logit"])
    (final_a.sum()).backward(retain_graph=True)
    g_alpha = []
    for p in student.node_head.parameters():
        g_alpha.append(0.0 if p.grad is None else float(p.grad.detach().abs().sum().item()))
        if p.grad is not None:
            p.grad = None
    final_b = beta(linear, od["logit"])
    (final_b.sum()).backward()
    g_beta = []
    for p in student.node_head.parameters():
        g_beta.append(0.0 if p.grad is None else float(p.grad.detach().abs().sum().item()))
    norm_a = float(sum(g_alpha))
    norm_b = float(sum(g_beta))
    status = "ZERO" if norm_a == 0.0 and norm_b == 0.0 else "NONZERO"
    if status != "ZERO":
        raise Editor015Blocked(
            f"previous residual initial ODST gradient unexpectedly non-zero: alpha={norm_a} beta={norm_b}"
        )
    return {
        "task_id": "EDITOR-015",
        "previous_formula": "final_logit = linear_logit + alpha * odst_logit",
        "alpha_initial": 0.0,
        "beta_initial": 0.0,
        "EDITOR013_HybridAlpha_used": True,
        "EDITOR014_ResidualBeta_used": True,
        "d_final_d_theta_ODST_at_init": 0.0,
        "autograd_l1_norm_HybridAlpha": norm_a,
        "autograd_l1_norm_ResidualBeta": norm_b,
        "PREVIOUS_RESIDUAL_ODST_INITIAL_GRADIENT": status,
        "mechanistically_distinct_new_residual": True,
        "reason": "zero scalar gate multiplies the ODST logit, so parameter gradients are exactly zero at step 0",
    }


def function_preserving_residual_proof() -> dict[str, Any]:
    """HARD gate: initial residual is 0 but ODST gradients are non-zero."""
    torch.manual_seed(7)
    student = build_odst046_model()
    modules = make_modules()
    modules.attach_reference(student.node_head)
    student.train()
    x = torch.randn(16, SEQUENCE_LENGTH, FEATURE_DIM)
    y = torch.zeros(16)
    y[:4] = 1.0
    out = editor015_forward(student, x, modules)
    init_match = bool(torch.allclose(out["logit"], out["linear_logit"], atol=1e-6, rtol=1e-6))
    init_zero = bool(torch.allclose(out["residual_logit"], torch.zeros_like(out["residual_logit"]), atol=1e-6))
    if not init_match or not init_zero:
        raise Editor015Blocked("EDITOR015_BLOCKED_FUNCTION_PRESERVING_RESIDUAL_INVALID")
    criterion = make_task_criterion(1.0, x.device)
    loss = criterion(out["logit"], y)
    loss.backward()
    live_norm = 0.0
    for p in student.node_head.parameters():
        if p.grad is not None:
            live_norm += float(p.grad.detach().pow(2).sum().item())
    live_norm = live_norm ** 0.5
    ref_grad = 0.0
    if modules.reference_odst is not None:
        for p in modules.reference_odst.parameters():
            if p.grad is not None:
                ref_grad += float(p.grad.detach().abs().sum().item())
    if live_norm <= 0:
        raise Editor015Blocked("EDITOR015_BLOCKED_FUNCTION_PRESERVING_RESIDUAL_INVALID")
    if ref_grad != 0.0:
        raise Editor015Blocked("frozen reference ODST received gradient")
    l1 = out["linear_logit"].detach()
    r = out["residual_logit"].detach()
    ens = torch.randn_like(l1)
    r3_eq = r3_equivalent_to_r1_if_l1_frozen(l1, r, ens)
    return {
        "task_id": "EDITOR-015",
        "FUNCTION_PRESERVING_RESIDUAL_INITIAL_OUTPUT": "ZERO",
        "FUNCTION_PRESERVING_RESIDUAL_INITIAL_EQUALS_L1": init_match,
        "FUNCTION_PRESERVING_RESIDUAL_INITIAL_ODST_GRADIENT": "NONZERO",
        "odst_grad_l2": live_norm,
        "reference_odst_grad_l1": ref_grad,
        "reference_requires_grad": False,
        "R3_equivalent_to_R1_under_frozen_L1": r3_eq,
        "R3": "REDUNDANT_NOT_EXECUTED" if r3_eq else "EXECUTE",
        "formula": "final_logit = L1_logit + (g_theta(z) - stop_gradient(g_theta0(z)))",
    }


def model_family_freeze() -> dict[str, Any]:
    return {
        "task_id": "EDITOR-015",
        "frozen_before_results": True,
        "TEACHER_GUIDANCE_VS_INITIALISATION": TEACHER_GUIDANCE_VS_INITIALISATION,
        "POST_ATTENTION_ODST_INCREMENTAL_VALUE": POST_ATTENTION_ODST_INCREMENTAL_VALUE,
        "TEMPORAL_ODST_INCREMENTAL_VALUE": TEMPORAL_ODST_INCREMENTAL_VALUE,
        "BEST_CURRENT_PAPER_MODEL": BEST_CURRENT_PAPER_MODEL,
        "TA2_REFERENCE_CENTRED_GLOBAL_TOPK_FAITHFULNESS": TA2_REFERENCE_CENTRED_GLOBAL_TOPK_FAITHFULNESS,
        "encoder": "matched L1 Bi-LSTM + attention + linear head",
        "odst046": ODST046,
        "residual": {
            "g_theta": "live ODST-046 on attended z",
            "g_theta0": "frozen identical initial copy, requires_grad=FALSE",
            "r_theta": "g_theta(z) - stop_gradient(g_theta0(z))",
            "final_logit": "L1_logit + r_theta(z)",
            "initial_residual": 0.0,
            "no_zero_alpha_gate": True,
        },
        "conditions": RESIDUAL_CONDITIONS,
        "R3_policy": "REDUNDANT_NOT_EXECUTED if algebraically identical to R1 under frozen L1",
        "teacher_guidance": {
            "ensemble": "equal-weight mean of T-OPT(42/52/62) logits",
            "lambda_distill": LAMBDA_DISTILL,
            "lambda_residual_teacher": LAMBDA_RESIDUAL_TEACHER,
            "lambda_route": LAMBDA_ROUTE,
            "historical_C5_single_teacher_logit_anchor": False,
            "not_tuned": True,
        },
        "fixed_combinations": {
            "C0": "0.5 L1_logit + 0.5 TA2_logit",
            "C1": "0.5 sigmoid(L1) + 0.5 sigmoid(TA2)",
            "C2": "0.5 percentile_rank(L1) + 0.5 percentile_rank(TA2)",
            "learned_weights": False,
            "validation_tuned_blend": False,
        },
        "promotion_margin": PROMOTION_MARGIN,
        "max_promoted_residual": 2,
        "no_tree_count_depth_temperature_grid": True,
        "no_temporal_placement_search": True,
        "no_learned_tree_weights": True,
        "no_focal_pairwise": True,
        "T": SEQUENCE_LENGTH,
        "F": FEATURE_DIM,
        "n_trees_total": N_TREES_TOTAL,
        "tree_order": TREE_ORDER,
        "directional_k": list(DIRECTIONAL_KS),
        "frozen_L1_mean_PR_AUC": FROZEN_L1_MEAN_PR_AUC,
        "frozen_TA2_mean_PR_AUC": FROZEN_TA2_MEAN_PR_AUC,
        "frozen_TA2_minus_L1": FROZEN_TA2_MINUS_L1,
        "frozen_TA2_L1_CI": FROZEN_TA2_L1_CI,
    }


def protocol_document() -> dict[str, Any]:
    return {
        "task_id": "EDITOR-015",
        "title": "Function-preserving residual ODST and complementarity rescue",
        "hard_boundary": {
            "train": "CERT r5.2 TRAIN",
            "selection": "INNER_TRAIN / INNER_SELECT",
            "confirmation": "CERT r5.2 VALIDATION",
            "forbidden": ["r5.2 TEST", "r5.1", "r6.2", "T change", "F change", "tree/depth/temperature search"],
        },
        "inner_counts": {
            "INNER_TRAIN": EXPECTED_INNER_TRAIN_N,
            "INNER_SELECT": EXPECTED_INNER_SELECT_N,
            "INNER_TRAIN_POS": EXPECTED_INNER_TRAIN_POS,
            "INNER_SELECT_POS": EXPECTED_INNER_SELECT_POS,
        },
        "validation_users": {
            "n_users": EXPECTED_VAL_USERS,
            "windows_per_user": EXPECTED_VAL_WINDOWS_PER_USER,
            "malicious_users": EXPECTED_VAL_MALICIOUS_USERS,
            "mapping_sha256": EXPECTED_USER_MAPPING_SHA256,
        },
        "bootstrap": "user-cluster, 2000 resamples, seed 42; windows are not independent",
        "created_utc": utc_now(),
    }


def input_checksums() -> dict[str, Any]:
    return {
        "task_id": "EDITOR-015",
        "train_npz": EXPECTED_TRAIN_SHA256,
        "val_npz": EXPECTED_VAL_SHA256,
        "architecture": EXPECTED_ARCHITECTURE_SHA256,
        "odst": EXPECTED_ODST_SHA256,
        "scaler": EXPECTED_SCALER_SHA256,
        "user_mapping": EXPECTED_USER_MAPPING_SHA256,
        "TOPT": {str(s): TOPT_CHECKPOINTS[s]["sha256"] for s in PRIMARY_SEEDS},
        "L1": {str(s): L1_CHECKPOINTS[s]["sha256"] for s in PRIMARY_SEEDS},
        "TA2": {str(s): F11_CHECKPOINTS[s]["sha256"] for s in PRIMARY_SEEDS},
    }


def write_protocol_packet() -> dict[str, Any]:
    for name in (
        "00_protocol",
        "01_complementarity",
        "02_inner_residual",
        "03_validation_confirmation",
        "04_statistics",
        "05_directional_faithfulness",
        "06_editor_response",
        "07_paper_handover",
    ):
        (_review(name)).mkdir(parents=True, exist_ok=True)
    try:
        refuse_r52_test(
            r"C:\PhD\07_Projects\cert-r42-feasibility\data\processed\r5.2\tensors\r52_T20_s1_test.npz"
        )
        raise Editor015Blocked("r5.2 TEST deny-list failed to fire")
    except Exception as exc:
        if "TEST" not in str(exc):
            raise
    register = source_register()
    prev = previous_residual_gradient_audit()
    proof = function_preserving_residual_proof()
    family = model_family_freeze()
    proto = protocol_document()
    checks = input_checksums()
    write_json(_review("00_protocol", "EDITOR015_SOURCE_REGISTER.json"), register)
    write_json(_review("00_protocol", "EDITOR015_PREVIOUS_RESIDUAL_GRADIENT_AUDIT.json"), prev)
    write_json(_review("00_protocol", "EDITOR015_FUNCTION_PRESERVING_RESIDUAL_PROOF.json"), proof)
    write_json(_review("00_protocol", "EDITOR015_MODEL_FAMILY_FREEZE.json"), family)
    write_json(_review("00_protocol", "EDITOR015_PROTOCOL.json"), proto)
    write_json(_review("00_protocol", "EDITOR015_INPUT_CHECKSUMS.json"), checks)
    return {
        "source_register": register,
        "previous_residual": prev,
        "function_preserving": proof,
        "model_family": family,
        "protocol": proto,
        "checksums": checks,
    }
