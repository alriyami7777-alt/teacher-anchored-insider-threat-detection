"""EDITOR-021 result-blind protocol freeze."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from editor012_rescue.constants import EXPECTED_TRAIN_SHA256, EXPECTED_USER_MAPPING_SHA256, EXPECTED_VAL_SHA256
from editor012_rescue.producing import pin_producing_sources
from editor012_rescue.safety import TRAIN_NPZ, VAL_NPZ
from editor017_robustness.perturbations import perturbation_module_hashes, protocol_lock
from editor020_robustness.protocol import assert_perturbation_hashes as editor020_assert_hashes
from editor020_robustness.sampler import sampler_lock

from .constants import (
    ALLOWED_TERMS,
    BUDGET_EQUATION,
    CANDIDATES,
    CLEAN_MEAN_MARGIN,
    CLEAN_ODST_PREDICTIVE_SUPERIORITY,
    CLEAN_SEED_MARGIN,
    COSINE_EPS,
    CURRENT_PAPER_MODEL_AT_START,
    EDITOR017_RESULTS_COMMIT,
    EDITOR018_RESULTS_COMMIT,
    EDITOR019_RESULTS_COMMIT,
    EDITOR020C_PARENT_COMMIT,
    EDITOR020_TA2_R0_INNER,
    EPS_GRAD,
    EXPECTED_GAUSSIAN_SHA256,
    EXPECTED_SCALER_JSON_SHA256,
    EXPECTED_SOURCE_ABLATION_SHA256,
    FAMILY_P_NOISE,
    FAMILY_P_SOURCE,
    FORBIDDEN_THREAT_TERMS,
    FROZEN_CLEAN_VAL_PR_AUC,
    FROZEN_TA2_MEAN_PR_AUC,
    GLOBAL_TOPK_PR_AUC_FAITHFULNESS,
    LAMBDA_FP,
    LAMBDA_ROUTE,
    LAMBDA_TEACHER,
    NOISE_LEVELS,
    ODST046,
    PRIMARY_SEEDS,
    PROJECTION_EQUATION,
    ROBUSTNESS_CANDIDATES,
    ROBUSTNESS_GAIN,
    SAMPLER_SEED,
    SCALER_JSON,
    SOURCE_CHANNELS,
    TA2_CHECKPOINTS,
    TASK_ID,
    TASK_NAME,
)
from .io_util import write_json
from .safety import REPO_ROOT, REVIEW_ROOT, Editor021Blocked, Editor021ProtocolError, refuse_r52_test, sha256_file, utc_now


def _review(*parts: str) -> Path:
    path = REVIEW_ROOT.joinpath(*parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def assert_perturbation_hashes() -> dict[str, str]:
    hashes = perturbation_module_hashes(REPO_ROOT)
    if hashes["objective3_missing_source_robustness.py"] != EXPECTED_SOURCE_ABLATION_SHA256:
        raise Editor021Blocked("EDITOR021_PERTURBATION_HASH_GATE = FAIL")
    if hashes["objective3_perturbations.py"] != EXPECTED_GAUSSIAN_SHA256:
        raise Editor021Blocked("EDITOR021_PERTURBATION_HASH_GATE = FAIL")
    if hashes["EDITOR006A_SCALER.json"] != EXPECTED_SCALER_JSON_SHA256:
        raise Editor021Blocked("r5.2 TRAIN scaler hash mismatch")
    inherited = editor020_assert_hashes()
    if inherited != hashes:
        raise Editor021Blocked("EDITOR-021 perturbation hashes diverged from EDITOR-020")
    return hashes


def write_protocol_packet() -> dict[str, Any]:
    try:
        refuse_r52_test(
            r"C:\PhD\07_Projects\cert-r42-feasibility\data\processed\r5.2\tensors\r52_T20_s1_test.npz"
        )
        raise Editor021Blocked("r5.2 TEST deny-list failed to fire")
    except Exception as exc:
        if "TEST" not in str(exc):
            raise
    if abs(float(LAMBDA_TEACHER) - 0.5) > 1e-15 or abs(float(LAMBDA_ROUTE) - 0.5) > 1e-15:
        raise Editor021ProtocolError("lambdas must remain 0.5")
    if abs(float(LAMBDA_FP) - 1.0) > 1e-15:
        raise Editor021ProtocolError("lambda_fp must remain 1.0")
    if ODST046["n_trees"] != 4 or ODST046["depth"] != 4:
        raise Editor021Blocked("ODST-046 lock mismatch")
    hashes = assert_perturbation_hashes()
    pins = pin_producing_sources()
    lock = protocol_lock()
    sampler = sampler_lock()
    checkpoints = {
        str(seed): {
            "checkpoint": str(spec["checkpoint"]),
            "sha256": spec["sha256"],
            "validation_PR_AUC": spec["validation_PR_AUC"],
        }
        for seed, spec in TA2_CHECKPOINTS.items()
    }
    protocol = {
        "task": TASK_ID,
        "title": TASK_NAME,
        "utc": utc_now(),
        "parent_commit": EDITOR020C_PARENT_COMMIT,
        "EDITOR017_RESULTS_COMMIT": EDITOR017_RESULTS_COMMIT,
        "EDITOR018_RESULTS_COMMIT": EDITOR018_RESULTS_COMMIT,
        "EDITOR019_RESULTS_COMMIT": EDITOR019_RESULTS_COMMIT,
        "EDITOR020C_PARENT_COMMIT": EDITOR020C_PARENT_COMMIT,
        "data_boundary": {
            "train": "CERT r5.2 TRAIN",
            "validation": "CERT r5.2 VALIDATION confirmation only",
            "model_selection": "INNER_TRAIN / INNER_SELECT",
            "R52_TEST": "HARD_DENY",
            "r51": "NO",
            "r62": "NO",
            "new_architecture_search": False,
            "TARGET_SCALER_FIT": "NO",
            "TARGET_CALIBRATION_FIT": "NO",
            "TARGET_THRESHOLD_SEARCH": "NO",
        },
        "architecture": {
            "identity": "TA2 = Bi-LSTM + attention + ODST-046",
            "start_checkpoints": checkpoints,
            "no_new_features": True,
            "no_adapters": True,
            "no_residual_branches": True,
        },
        "candidates": CANDIDATES,
        "robustness_candidates": list(ROBUSTNESS_CANDIDATES),
        "rho_values": {k: v["rho"] for k, v in CANDIDATES.items()},
        "lambda_fp": LAMBDA_FP,
        "lambda_teacher": LAMBDA_TEACHER,
        "lambda_route": LAMBDA_ROUTE,
        "gradient_projection_equation": PROJECTION_EQUATION,
        "gradient_budget_equation": BUDGET_EQUATION,
        "eps_grad": EPS_GRAD,
        "cosine_eps": COSINE_EPS,
        "seeds": list(PRIMARY_SEEDS),
        "split_hashes": {
            "train_sha256": EXPECTED_TRAIN_SHA256,
            "val_sha256": EXPECTED_VAL_SHA256,
            "user_mapping_sha256": EXPECTED_USER_MAPPING_SHA256,
        },
        "train_npz": str(TRAIN_NPZ),
        "val_npz": str(VAL_NPZ),
        "scaler_json": str(SCALER_JSON),
        "clean_gates": {
            "mean_margin": CLEAN_MEAN_MARGIN,
            "seed_margin": CLEAN_SEED_MARGIN,
            "cfp0_scaffold_reference": "starting TA2 (F11) INNER_SELECT; EDITOR-020 TA2-R0 not rerun",
        },
        "robustness_gates": {
            "composite_gain": ROBUSTNESS_GAIN,
            "S_source": "mean_c (PR_source,c - PR_clean)",
            "S_noise": "mean_sigma (PR_noise,sigma - PR_clean)",
            "S_composite": "0.5 S_source + 0.5 S_noise",
        },
        "selection_rules": "G1-G5 then greatest S_composite; tie <=0.001 chooses smaller rho",
        "official_validation_rules": "O1-O6 on CFP0 vs one selected CFPR only",
        "deny_list": ["r5.2 TEST", "r5.1", "r6.2", "adversarial training"],
        "terminology_allowed": list(ALLOWED_TERMS),
        "terminology_forbidden": list(FORBIDDEN_THREAT_TERMS),
        "producing_pins": pins,
        "perturbation_hashes": hashes,
        "sampler": sampler,
        "perturbation_lock": lock,
        "frozen_clean_val_PR_AUC_TA2": FROZEN_CLEAN_VAL_PR_AUC,
        "frozen_ta2_mean": FROZEN_TA2_MEAN_PR_AUC,
        "editor020_ta2_r0_inner": EDITOR020_TA2_R0_INNER,
        "CURRENT_PAPER_MODEL_AT_START": CURRENT_PAPER_MODEL_AT_START,
        "CLEAN_ODST_PREDICTIVE_SUPERIORITY": CLEAN_ODST_PREDICTIVE_SUPERIORITY,
        "GLOBAL_TOPK_PR_AUC_FAITHFULNESS": GLOBAL_TOPK_PR_AUC_FAITHFULNESS,
        "SOURCE_CHANNELS": list(SOURCE_CHANNELS),
        "NOISE_LEVELS": list(NOISE_LEVELS),
        "SAMPLER_SEED": SAMPLER_SEED,
        "P_source": FAMILY_P_SOURCE,
        "P_noise": FAMILY_P_NOISE,
        "RESULT_STATUS_AT_START": "UNSEEN",
    }
    write_json(_review("EDITOR021_PROTOCOL.json"), protocol)
    write_json(_review("EDITOR021_CANDIDATE_REGISTRY.json"), {"candidates": CANDIDATES, "start_checkpoints": checkpoints})
    md = _protocol_markdown(protocol, hashes, pins)
    _review("EDITOR021_PROTOCOL.md").write_text(md, encoding="utf-8")
    return {"protocol": protocol, "hashes": hashes, "pins": pins, "sampler": sampler}


def _protocol_markdown(protocol: dict[str, Any], hashes: dict[str, str], pins: dict[str, str]) -> str:
    ckpt_lines = []
    for seed, spec in protocol["architecture"]["start_checkpoints"].items():
        ckpt_lines.append(f"- seed {seed}: `{spec['sha256']}`")
    return "\n".join(
        [
            "# EDITOR-021 protocol freeze",
            "",
            "Result-blind freeze. No EDITOR-021 predictive result has been observed.",
            "",
            f"Parent commit: `{protocol['parent_commit']}`",
            "",
            "## Architecture",
            "",
            "TA2: 20-day × 13-feature → Bi-LSTM → temporal attention → attention-pooled `h(x)` → ODST-046 → logit.",
            "",
            "Starting hash-gated F11/TA2 checkpoints:",
            *ckpt_lines,
            "",
            "## Objectives",
            "",
            f"- `L_TA2 = L_task + {LAMBDA_TEACHER} L_teacher + {LAMBDA_ROUTE} L_route`",
            f"- `L_FP = MSE(z_S(x), stopgrad(z_Fref(x)))` with `LAMBDA_FP = {LAMBDA_FP}`",
            "- `L_clean = L_TA2 + L_FP`",
            "- `L_repr = 1 - cos(h_S(x_tilde), stopgrad(h_Fref(x)))`",
            "",
            "`L_repr` is not applied to ODST/head parameters. CFP0 has `rho = 0` and no representation gradient.",
            "",
            "## Gradient geometry",
            "",
            f"- projection: `{PROJECTION_EQUATION}`",
            f"- budget: `{BUDGET_EQUATION}`",
            "- rho search: 0.10 / 0.25 / 0.50 only",
            "",
            "## Gates",
            "",
            "- CFP0 scaffold vs starting TA2 INNER_SELECT: mean delta >= -0.001 and no seed < -0.003",
            "- INNER G1–G5 versus matched CFP0",
            "- Official O1–O6 only for the one automatically selected CFPR",
            "",
            "## Perturbations",
            "",
            f"- source: `{hashes['objective3_missing_source_robustness.py']}`",
            f"- gaussian: `{hashes['objective3_perturbations.py']}`",
            f"- scaler: `{hashes['EDITOR006A_SCALER.json']}`",
            "",
            "## Deny-list",
            "",
            "r5.2 TEST, CERT r5.1, CERT r6.2, adversarial/evasion/poisoning claims.",
            "",
            "## Producing pins",
            "",
            f"- architecture `{pins['architecture']}`",
            f"- odst `{pins['odst']}`",
            f"- sequence_ensemble `{pins['sequence_ensemble']}`",
            "",
        ]
    )
