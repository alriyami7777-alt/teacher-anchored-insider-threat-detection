"""Phase A protocol freeze: source register, gate freeze, function-preserving proofs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import torch

from editor012_rescue.losses import make_task_criterion
from editor012_rescue.producing import build_odst046_model, pin_producing_sources
from editor012_rescue.safety import (
    EXPECTED_ARCHITECTURE_SHA256,
    EXPECTED_ODST_SHA256,
    EXPECTED_SCALER_SHA256,
    TRAIN_NPZ,
    VAL_NPZ,
)

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
    EDITOR015_PROMOTION_COMMIT,
    EDITOR015_PROTOCOL_COMMIT,
    EDITOR015_RESULTS_FULL_COMMIT,
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
    FIXED_LINEAR_ODST_COMPLEMENTARITY,
    FROZEN_L1_MEAN_PR_AUC,
    FROZEN_TA2_L1_CI,
    FROZEN_TA2_MEAN_PR_AUC,
    HISTORICAL_GLOBAL_TOPK_FAITHFULNESS,
    HISTORICAL_SINGLE_TEACHER_STATIC_LOGIT_ANCHOR,
    L1_CHECKPOINTS,
    LAMBDA_ROUTE,
    LAMBDA_TEACHER,
    LOCAL_DIRECTIONAL_TREE_FAITHFULNESS,
    N_TREES_PER_LAYER,
    N_TREES_TOTAL,
    ODST046,
    POST_ATTENTION_ODST_INCREMENTAL_VALUE,
    PRIMARY_SEEDS,
    PROMOTION_MARGIN,
    Q_VALUES,
    RESIDUAL_ODST_VALUE,
    SEQUENCE_LENGTH,
    SPECIALIST_CONDITIONS,
    TEACHER_GUIDANCE_VS_INITIALISATION,
    TEMPORAL_ODST_INCREMENTAL_VALUE,
    TOPT_CHECKPOINTS,
)
from .io_util import write_json
from .models import (
    editor016_forward,
    make_modules,
    reference_grad_l1,
    specialist_param_grad_norm,
)
from .safety import (
    REVIEW_ROOT,
    Editor016Blocked,
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
        raise Editor016Blocked(f"hash mismatch role={role} expected={expected} observed={observed} path={path}")
    return {
        "path": str(path),
        "commit": commit,
        "SHA256": observed,
        "role": role,
        "exists": path.is_file(),
    }


def source_register() -> dict[str, Any]:
    pins = pin_producing_sources()
    artefacts = []
    for seed, spec in TOPT_CHECKPOINTS.items():
        artefacts.append(
            _artefact(spec["checkpoint"], "65214bdeb51f9a04925be41d3b4c778de75cf088", f"T-OPT/{seed}", spec["sha256"])
        )
    for seed, spec in C2OPT_CHECKPOINTS.items():
        artefacts.append(
            _artefact(spec["checkpoint"], "65214bdeb51f9a04925be41d3b4c778de75cf088", f"C2-OPT/{seed}", spec["sha256"])
        )
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
        raise Editor016Blocked(f"missing source artefacts: {missing}")
    return {
        "task_id": "EDITOR-016",
        "EDITOR015_PROTOCOL_COMMIT": EDITOR015_PROTOCOL_COMMIT,
        "EDITOR015_PROMOTION_COMMIT": EDITOR015_PROMOTION_COMMIT,
        "EDITOR015_RESULTS_FULL_COMMIT": EDITOR015_RESULTS_FULL_COMMIT,
        "EDITOR012_PROTOCOL_COMMIT": EDITOR012_PROTOCOL_COMMIT,
        "EDITOR012_IMPLEMENTATION_COMMIT": EDITOR012_IMPLEMENTATION_COMMIT,
        "EDITOR012_PROMOTION_COMMIT": EDITOR012_PROMOTION_COMMIT,
        "EDITOR012_RESULTS_COMMIT": EDITOR012_RESULTS_COMMIT,
        "EDITOR013_RESULTS_COMMIT": EDITOR013_RESULTS_COMMIT,
        "EDITOR014_RESULTS_COMMIT": EDITOR014_RESULTS_COMMIT,
        "historical_packets_readonly": True,
        "TEACHER_GUIDANCE_VS_INITIALISATION": TEACHER_GUIDANCE_VS_INITIALISATION,
        "BEST_CURRENT_PAPER_MODEL": BEST_CURRENT_PAPER_MODEL,
        "POST_ATTENTION_ODST_INCREMENTAL_VALUE": POST_ATTENTION_ODST_INCREMENTAL_VALUE,
        "TEMPORAL_ODST_INCREMENTAL_VALUE": TEMPORAL_ODST_INCREMENTAL_VALUE,
        "RESIDUAL_ODST_VALUE": RESIDUAL_ODST_VALUE,
        "FIXED_LINEAR_ODST_COMPLEMENTARITY": FIXED_LINEAR_ODST_COMPLEMENTARITY,
        "LOCAL_DIRECTIONAL_TREE_FAITHFULNESS": LOCAL_DIRECTIONAL_TREE_FAITHFULNESS,
        "HISTORICAL_GLOBAL_TOPK_FAITHFULNESS": HISTORICAL_GLOBAL_TOPK_FAITHFULNESS,
        "producing_pins": pins,
        "artefacts": artefacts,
        "r52_test_opened": False,
        "r51_rerun": False,
        "r62_rerun": False,
    }


def function_preserving_proof() -> dict[str, Any]:
    """HARD gate: both specialists start at delta=0 with non-zero initial gradients."""
    torch.manual_seed(7)
    x = torch.randn(16, SEQUENCE_LENGTH, FEATURE_DIM)
    y = torch.zeros(16)
    y[:4] = 1.0
    gate = torch.ones(16)
    criterion = make_task_criterion(1.0, x.device)

    lin_student = build_odst046_model()
    lin_mods = make_modules("linear")
    lin_out = editor016_forward(lin_student, x, lin_mods, gate=gate, use_source_l1=False)
    lin_zero = bool(torch.allclose(lin_out["delta"], torch.zeros_like(lin_out["delta"]), atol=1e-6))
    lin_eq = bool(torch.allclose(lin_out["logit"], lin_out["linear_logit"], atol=1e-6))
    if not lin_zero or not lin_eq:
        raise Editor016Blocked("linear residual initial output is not exactly zero")
    criterion(lin_out["logit"], y).backward()
    lin_grad = specialist_param_grad_norm(lin_student, lin_mods)
    if lin_grad <= 0:
        raise Editor016Blocked("linear residual initial gradient is zero")

    od_student = build_odst046_model()
    od_mods = make_modules("odst")
    od_mods.attach_reference(od_student.node_head)
    od_out = editor016_forward(od_student, x, od_mods, gate=gate, use_source_l1=False)
    od_zero = bool(torch.allclose(od_out["delta"], torch.zeros_like(od_out["delta"]), atol=1e-6))
    od_eq = bool(torch.allclose(od_out["logit"], od_out["linear_logit"], atol=1e-6))
    if not od_zero or not od_eq:
        raise Editor016Blocked("ODST residual initial output is not exactly zero")
    criterion(od_out["logit"], y).backward()
    od_grad = specialist_param_grad_norm(od_student, od_mods)
    ref_grad = reference_grad_l1(od_mods)
    if od_grad <= 0:
        raise Editor016Blocked("ODST residual initial gradient is zero")
    if ref_grad != 0.0:
        raise Editor016Blocked("frozen residual reference received a gradient")
    return {
        "task_id": "EDITOR-016",
        "LINEAR_RESIDUAL_INITIAL_OUTPUT": "ZERO",
        "LINEAR_RESIDUAL_INITIAL_GRADIENT": "NONZERO",
        "linear_grad_l2": lin_grad,
        "ODST_RESIDUAL_INITIAL_OUTPUT": "ZERO",
        "ODST_RESIDUAL_INITIAL_EQUALS_L1": od_eq,
        "ODST_RESIDUAL_INITIAL_GRADIENT": "NONZERO",
        "odst_grad_l2": od_grad,
        "reference_odst_grad_l1": ref_grad,
        "reference_requires_grad": False,
        "formula_linear": "delta_linear = w_r^T z + b_r with w_r=0, b_r=0",
        "formula_odst": "delta_ODST = g_theta(z) - stop_gradient(g_theta0(z))",
        "final_logit": "L1_logit + gate_q * delta",
    }


def gate_freeze() -> dict[str, Any]:
    return {
        "task_id": "EDITOR-016",
        "margin": "abs(L1_logit)",
        "labels_used": False,
        "q_values": list(Q_VALUES),
        "no_other_thresholds": True,
        "tau_source_inner": "INNER_TRAIN L1 margins only",
        "tau_source_official": "full TRAIN L1 margins of that seed only",
        "validation_never_determines_tau": True,
        "gate": "1 if abs(L1_logit) <= tau_q else 0",
        "source_frozen": True,
    }


def specialist_factorial() -> dict[str, Any]:
    return {
        "task_id": "EDITOR-016",
        "conditions": SPECIALIST_CONDITIONS,
        "matching": {
            "S0_vs_S2": "ODST versus linear specialist under task-only training",
            "S1_vs_S3": "ODST versus linear specialist under identical teacher guidance",
            "S3_vs_S2": "teacher guidance effect inside the ODST specialist",
            "S4_vs_S3": "route regularisation effect inside teacher-guided ODST specialist",
        },
        "lambda_teacher": LAMBDA_TEACHER,
        "lambda_route": LAMBDA_ROUTE,
        "teacher_residual_target": "ensemble_teacher_logit - L1_logit",
        "historical_C5_single_teacher_anchor": HISTORICAL_SINGLE_TEACHER_STATIC_LOGIT_ANCHOR,
        "route_teacher": "matched T-OPT(seed)",
        "no_architecture_search": True,
    }


def protocol_document() -> dict[str, Any]:
    return {
        "task_id": "EDITOR-016",
        "title": "Uncertainty-routed teacher-anchored ODST specialist",
        "hard_boundary": {
            "train": "CERT r5.2 TRAIN",
            "selection": "INNER_TRAIN / INNER_SELECT",
            "confirmation": "CERT r5.2 VALIDATION",
            "forbidden": [
                "r5.2 TEST",
                "r5.1",
                "r6.2",
                "T change",
                "F change",
                "tree/depth/temperature search",
                "focal/pairwise/GroupDRO/CORAL",
                "global ODST fusion search",
            ],
        },
        "architecture": {
            "L1": "teacher-guided attention-linear base",
            "ODST": "ODST-046",
            "n_trees_per_layer": N_TREES_PER_LAYER,
            "layers": 2,
            "depth": 4,
            "temperature": 0.5,
            "lambda_teacher": LAMBDA_TEACHER,
            "lambda_route": LAMBDA_ROUTE,
            "historical_single_teacher_static_logit_anchor": HISTORICAL_SINGLE_TEACHER_STATIC_LOGIT_ANCHOR,
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
        "promotion_margin": PROMOTION_MARGIN,
        "bootstrap": "user-cluster, 2000 resamples, seed 42; windows are not independent",
        "directional_k": list(DIRECTIONAL_KS),
        "encoder": ENCODER_ARCH,
        "odst046": ODST046,
        "frozen_L1_mean_PR_AUC": FROZEN_L1_MEAN_PR_AUC,
        "frozen_TA2_mean_PR_AUC": FROZEN_TA2_MEAN_PR_AUC,
        "frozen_TA2_L1_CI": FROZEN_TA2_L1_CI,
        "T": SEQUENCE_LENGTH,
        "F": FEATURE_DIM,
        "n_trees_total": N_TREES_TOTAL,
        "created_utc": utc_now(),
    }


def input_checksums() -> dict[str, Any]:
    return {
        "task_id": "EDITOR-016",
        "train_npz": EXPECTED_TRAIN_SHA256,
        "val_npz": EXPECTED_VAL_SHA256,
        "architecture": EXPECTED_ARCHITECTURE_SHA256,
        "odst": EXPECTED_ODST_SHA256,
        "scaler": EXPECTED_SCALER_SHA256,
        "user_mapping": EXPECTED_USER_MAPPING_SHA256,
        "TOPT": {str(s): TOPT_CHECKPOINTS[s]["sha256"] for s in PRIMARY_SEEDS},
        "L1": {str(s): L1_CHECKPOINTS[s]["sha256"] for s in PRIMARY_SEEDS},
        "TA2": {str(s): F11_CHECKPOINTS[s]["sha256"] for s in PRIMARY_SEEDS},
        "EDITOR015_RESULTS_FULL_COMMIT": EDITOR015_RESULTS_FULL_COMMIT,
    }


def write_protocol_packet() -> dict[str, Any]:
    for name in (
        "00_protocol",
        "01_uncertainty_audit",
        "02_inner_specialist",
        "03_validation_confirmation",
        "04_statistics",
        "05_mechanism",
        "06_explainability",
        "07_efficiency",
        "08_editor_response",
        "09_paper_handover",
    ):
        (_review(name)).mkdir(parents=True, exist_ok=True)
    try:
        refuse_r52_test(
            r"C:\PhD\07_Projects\cert-r42-feasibility\data\processed\r5.2\tensors\r52_T20_s1_test.npz"
        )
        raise Editor016Blocked("r5.2 TEST deny-list failed to fire")
    except Exception as exc:
        if "TEST" not in str(exc):
            raise
    register = source_register()
    proof = function_preserving_proof()
    gate = gate_freeze()
    factorial = specialist_factorial()
    proto = protocol_document()
    checks = input_checksums()
    write_json(_review("00_protocol", "EDITOR016_SOURCE_REGISTER.json"), register)
    write_json(_review("00_protocol", "EDITOR016_FUNCTION_PRESERVING_PROOF.json"), proof)
    write_json(_review("00_protocol", "EDITOR016_GATE_FREEZE.json"), gate)
    write_json(_review("00_protocol", "EDITOR016_SPECIALIST_FACTORIAL.json"), factorial)
    write_json(_review("00_protocol", "EDITOR016_PROTOCOL.json"), proto)
    write_json(_review("00_protocol", "EDITOR016_INPUT_CHECKSUMS.json"), checks)
    return {
        "source_register": register,
        "function_preserving": proof,
        "gate": gate,
        "factorial": factorial,
        "protocol": proto,
        "checksums": checks,
    }
