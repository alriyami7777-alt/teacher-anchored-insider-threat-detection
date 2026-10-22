"""EDITOR-022 result-blind protocol freeze."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from editor012_rescue.constants import EXPECTED_TRAIN_SHA256, EXPECTED_USER_MAPPING_SHA256, EXPECTED_VAL_SHA256
from editor012_rescue.producing import pin_producing_sources
from editor012_rescue.safety import TRAIN_NPZ, VAL_NPZ
from editor017_robustness.perturbations import perturbation_module_hashes, protocol_lock
from editor020_robustness.protocol import assert_perturbation_hashes as editor020_assert_hashes
from editor020_robustness.sampler import sampler_lock
from editor021_cfpr.protocol import assert_perturbation_hashes as editor021_assert_hashes

from .constants import (
    ALLOWED_TERMS,
    BUDGET_EQUATION,
    CANDIDATES,
    CFP0_INNER_LOGICAL,
    CFP0_INNER_SHA256,
    CFP0_START_MEAN_CLEAN_PR_AUC,
    CFP0_START_MEAN_S_COMPOSITE,
    CFP0_START_MEAN_S_NOISE,
    CFP0_START_MEAN_S_SOURCE,
    CFP0_START_METRICS,
    CLEAN_MEAN_MARGIN,
    CLEAN_SEED_MARGIN,
    COSINE_EPS,
    CURRENT_PAPER_MODEL_AT_START,
    EDITOR021_PROTOCOL_COMMIT,
    EDITOR021P1_CORRECTION_COMMIT,
    EDITOR021_RESULTS_COMMIT,
    EDITOR022_PARENT_COMMIT,
    EPS_GRAD,
    EXPECTED_GAUSSIAN_SHA256,
    EXPECTED_SCALER_JSON_SHA256,
    EXPECTED_SOURCE_ABLATION_SHA256,
    FAMILY_P_NOISE,
    FAMILY_P_SOURCE,
    FORBIDDEN_THREAT_TERMS,
    FROZEN_INNER_CFP0_THRESHOLDS,
    LAMBDA_FP,
    LAMBDA_ROUTE,
    LAMBDA_TEACHER,
    NOISE_LEVELS,
    ODST046,
    PARITY_TOLERANCE,
    PRIMARY_SEEDS,
    PROJECTION_EQUATION,
    ROBUSTNESS_CANDIDATES,
    ROBUSTNESS_GAIN,
    SAMPLER_EPOCH_INDEX,
    SAMPLER_SEED,
    SCALER_JSON,
    SOURCE_CHANNELS,
    STAGE2_EPOCHS,
    TA2_CHECKPOINTS,
    TASK_ID,
    TASK_NAME,
)
from .io_util import write_json
from .models import hash_gate_all_cfp0_inner
from .safety import REPO_ROOT, REVIEW_ROOT, Editor022Blocked, Editor022ProtocolError, refuse_r52_test, utc_now


def _review(*parts: str) -> Path:
    path = REVIEW_ROOT.joinpath(*parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def assert_perturbation_hashes() -> dict[str, str]:
    hashes = perturbation_module_hashes(REPO_ROOT)
    if hashes["objective3_missing_source_robustness.py"] != EXPECTED_SOURCE_ABLATION_SHA256:
        raise Editor022Blocked("EDITOR022_PERTURBATION_HASH_GATE = FAIL")
    if hashes["objective3_perturbations.py"] != EXPECTED_GAUSSIAN_SHA256:
        raise Editor022Blocked("EDITOR022_PERTURBATION_HASH_GATE = FAIL")
    if hashes["EDITOR006A_SCALER.json"] != EXPECTED_SCALER_JSON_SHA256:
        raise Editor022Blocked("r5.2 TRAIN scaler hash mismatch")
    inherited20 = editor020_assert_hashes()
    inherited21 = editor021_assert_hashes()
    if inherited20 != hashes or inherited21 != hashes:
        raise Editor022Blocked("EDITOR-022 perturbation hashes diverged from EDITOR-020/021")
    return hashes


def write_protocol_packet() -> dict[str, Any]:
    try:
        refuse_r52_test(
            r"C:\PhD\07_Projects\cert-r42-feasibility\data\processed\r5.2\tensors\r52_T20_s1_test.npz"
        )
        raise Editor022Blocked("r5.2 TEST deny-list failed to fire")
    except Exception as exc:
        if "TEST" not in str(exc):
            raise
    if abs(float(LAMBDA_TEACHER) - 0.5) > 1e-15 or abs(float(LAMBDA_ROUTE) - 0.5) > 1e-15:
        raise Editor022ProtocolError("lambdas must remain 0.5")
    if abs(float(LAMBDA_FP) - 1.0) > 1e-15:
        raise Editor022ProtocolError("lambda_fp must remain 1.0")
    if int(STAGE2_EPOCHS) != 1:
        raise Editor022Blocked("STAGE2_EPOCHS must remain 1")
    if ODST046["n_trees"] != 4 or ODST046["depth"] != 4:
        raise Editor022Blocked("ODST-046 lock mismatch")
    hashes = assert_perturbation_hashes()
    cfp0_live = hash_gate_all_cfp0_inner()
    pins = pin_producing_sources()
    lock = protocol_lock()
    sampler = sampler_lock()
    cfp0_ckpts = {
        str(seed): {
            "logical_path": str(CFP0_INNER_LOGICAL[seed]).replace("\\", "/"),
            "sha256": CFP0_INNER_SHA256[seed],
        }
        for seed in PRIMARY_SEEDS
    }
    ta2_ckpts = {
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
        "parent_commit": EDITOR022_PARENT_COMMIT,
        "EDITOR021_RESULTS_COMMIT": EDITOR021_RESULTS_COMMIT,
        "EDITOR021P1_CORRECTION_COMMIT": EDITOR021P1_CORRECTION_COMMIT,
        "EDITOR021_PROTOCOL_COMMIT": EDITOR021_PROTOCOL_COMMIT,
        "RESULT_STATUS_AT_START": "UNSEEN",
        "PROTOCOL_STATUS_AT_START": "NOT_YET_FROZEN",
        "EDITOR022_IS_FINAL_BOUNDED_ROBUSTNESS_RESCUE": True,
        "data_boundary": {
            "train": "CERT r5.2 TRAIN",
            "validation": "CERT r5.2 VALIDATION confirmation only after inner selection",
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
            "identity": "TA2 = 20x13 -> Bi-LSTM -> temporal attention -> attention-pooled h -> ODST-046 -> binary logit",
            "no_new_layer": True,
            "no_adapters": True,
            "no_residual_pathway": True,
            "no_second_classifier": True,
        },
        "cfp0_inner_checkpoints": cfp0_ckpts,
        "cfp0_inner_hash_gate": {str(k): v for k, v in cfp0_live.items()},
        "cfp0_start_metrics": {str(k): v for k, v in CFP0_START_METRICS.items()},
        "cfp0_start_means": {
            "clean_PR_AUC": CFP0_START_MEAN_CLEAN_PR_AUC,
            "S_source": CFP0_START_MEAN_S_SOURCE,
            "S_noise": CFP0_START_MEAN_S_NOISE,
            "S_composite": CFP0_START_MEAN_S_COMPOSITE,
        },
        "parity_tolerance": PARITY_TOLERANCE,
        "ta2_checkpoints_for_cfp0_full": ta2_ckpts,
        "candidates": CANDIDATES,
        "robustness_candidates": list(ROBUSTNESS_CANDIDATES),
        "rho_values": {k: v["rho"] for k, v in CANDIDATES.items()},
        "STAGE2_EPOCHS": STAGE2_EPOCHS,
        "SAMPLER_EPOCH_INDEX": SAMPLER_EPOCH_INDEX,
        "FRESH_STAGE2_OPTIMISER": True,
        "OPTIMISER_STATE_CONTINUED_FROM_CFP0": False,
        "lambda_fp": LAMBDA_FP,
        "lambda_teacher": LAMBDA_TEACHER,
        "lambda_route": LAMBDA_ROUTE,
        "clean_objective": "L_clean = L_task + 0.5 L_teacher + 0.5 L_route + 1.0 L_FP",
        "L_FP": "MSE(z_S(x), stopgrad[z_F_CFP0(x)])",
        "L_repr": "1 - cos(h_S(x_tilde), stopgrad[h_F_CFP0(x)])",
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
            "seq0_scaffold_reference": "CFP0_START",
            "g1_g2_reference": "CFP0_START not SEQ0",
        },
        "robustness_gates": {
            "composite_gain": ROBUSTNESS_GAIN,
            "S_source": "mean_c (PR_source,c - PR_clean)",
            "S_noise": "mean_sigma (PR_noise,sigma - PR_clean)",
            "S_composite": "0.5 S_source + 0.5 S_noise",
        },
        "selection_rules": "G1-G6 then greatest S_composite; tie <=0.001 chooses smaller rho",
        "official_validation_rules": "O1-O7 on selected SRP vs CFP0_FULL_START and SEQ0_FULL",
        "deny_list": [
            "r5.2 TEST",
            "r5.1",
            "r6.2",
            "new perturbation families",
            "new architecture",
            "validation threshold search",
            "EDITOR022B",
            "EDITOR023 robustness rescue",
        ],
        "result_freeze_procedure": [
            "write all scientific result artefacts",
            "write completed EDITOR022_RUN_MANIFEST.json",
            "write EDITOR022_RESULT_FREEZE.md",
            "write EDITOR022_TERMINAL_BLOCK.txt",
            "compute hashes of all final stable hash-target artefacts",
            "write EDITOR022_SHA256_MANIFEST.json LAST",
        ],
        "frozen_inner_cfp0_thresholds": {str(k): v for k, v in FROZEN_INNER_CFP0_THRESHOLDS.items()},
        "terminology_allowed": list(ALLOWED_TERMS),
        "terminology_forbidden": list(FORBIDDEN_THREAT_TERMS),
        "producing_pins": pins,
        "perturbation_hashes": hashes,
        "sampler": sampler,
        "perturbation_lock": lock,
        "CURRENT_PAPER_MODEL_AT_START": CURRENT_PAPER_MODEL_AT_START,
        "SOURCE_CHANNELS": list(SOURCE_CHANNELS),
        "NOISE_LEVELS": list(NOISE_LEVELS),
        "SAMPLER_SEED": SAMPLER_SEED,
        "P_source": FAMILY_P_SOURCE,
        "P_noise": FAMILY_P_NOISE,
        "historical_editor021_read_only": True,
    }
    write_json(_review("EDITOR022_PROTOCOL.json"), protocol)
    write_json(
        _review("EDITOR022_CANDIDATE_REGISTRY.json"),
        {
            "candidates": CANDIDATES,
            "cfp0_inner_checkpoints": cfp0_ckpts,
            "STAGE2_EPOCHS": STAGE2_EPOCHS,
            "FRESH_STAGE2_OPTIMISER": True,
            "OPTIMISER_STATE_CONTINUED_FROM_CFP0": False,
        },
    )
    md = _protocol_markdown(protocol, hashes, pins)
    _review("EDITOR022_PROTOCOL.md").write_text(md, encoding="utf-8")
    return {"protocol": protocol, "hashes": hashes, "pins": pins, "sampler": sampler}


def _protocol_markdown(protocol: dict[str, Any], hashes: dict[str, str], pins: dict[str, str]) -> str:
    ckpt_lines = []
    for seed, spec in protocol["cfp0_inner_checkpoints"].items():
        ckpt_lines.append(f"- seed {seed}: `{spec['logical_path']}` sha256=`{spec['sha256']}`")
    return "\n".join(
        [
            "# EDITOR-022 protocol freeze",
            "",
            "Result-blind freeze. No EDITOR-022 predictive result has been observed.",
            "",
            f"Parent commit: `{protocol['parent_commit']}`",
            f"EDITOR021_RESULTS_COMMIT: `{protocol['EDITOR021_RESULTS_COMMIT']}`",
            f"EDITOR021P1_CORRECTION_COMMIT: `{protocol['EDITOR021P1_CORRECTION_COMMIT']}`",
            f"EDITOR021_PROTOCOL_COMMIT: `{protocol['EDITOR021_PROTOCOL_COMMIT']}`",
            "",
            "This is one unified experiment. It is not EDITOR-022A/B/C.",
            "",
            "## Frozen CFP0 Stage-1 starting checkpoints",
            "",
            *ckpt_lines,
            "",
            "Do not recreate these INNER_SELECT checkpoints.",
            "",
            "## Frozen CFP0_START metrics",
            "",
            f"- mean clean PR-AUC `{protocol['cfp0_start_means']['clean_PR_AUC']}`",
            f"- mean S_source `{protocol['cfp0_start_means']['S_source']}`",
            f"- mean S_noise `{protocol['cfp0_start_means']['S_noise']}`",
            f"- mean S_composite `{protocol['cfp0_start_means']['S_composite']}`",
            f"- parity tolerance `{protocol['parity_tolerance']}`",
            "",
            "## Architecture",
            "",
            protocol["architecture"]["identity"],
            "",
            "## Stage-2 candidates",
            "",
            "- SEQ0 rho=0.000 robustness=OFF",
            "- SRP025 rho=0.025 robustness=ON",
            "- SRP050 rho=0.050 robustness=ON",
            "- SRP100 rho=0.100 robustness=ON",
            "",
            f"STAGE2_EPOCHS = {STAGE2_EPOCHS}. End-of-epoch checkpoint only. No early stopping. No best-epoch selection.",
            "",
            "FRESH_STAGE2_OPTIMISER = YES. OPTIMISER_STATE_CONTINUED_FROM_CFP0 = NO.",
            "",
            f"SAMPLER_EPOCH_INDEX = {SAMPLER_EPOCH_INDEX}.",
            "",
            "## Objectives",
            "",
            f"- `{protocol['clean_objective']}`",
            f"- `{protocol['L_FP']}`",
            f"- `{protocol['L_repr']}`",
            "",
            "The frozen CFP0 reference is F_CFP0. It does not replace T-OPT.",
            "",
            "## Gradient geometry",
            "",
            f"- projection: `{PROJECTION_EQUATION}`",
            f"- budget: `{BUDGET_EQUATION}`",
            "- ODST/head receives clean gradient only",
            "",
            "## Gates",
            "",
            "- SEQ0 scaffold vs CFP0_START: mean delta >= -0.001 and no seed < -0.003",
            "- INNER G1–G6 versus CFP0_START, with G6 versus SEQ0",
            "- Official O1–O7 only for the one automatically selected SRP",
            "",
            "## Selection rule",
            "",
            protocol["selection_rules"],
            "",
            "## Official validation rule",
            "",
            protocol["official_validation_rules"],
            "",
            "Validation Stage V1 trains inherited CFP0_FULL from historical TA2 on full r5.2 TRAIN.",
            "Stage V2 then applies one matched SEQ0_FULL / SELECTED_SRP_FULL epoch from frozen CFP0_FULL.",
            "",
            "Frozen INNER CFP0 thresholds: seed 42 = 0.89, seed 52 = 0.85, seed 62 = 0.85.",
            "",
            "## Perturbations",
            "",
            f"- source: `{hashes['objective3_missing_source_robustness.py']}`",
            f"- gaussian: `{hashes['objective3_perturbations.py']}`",
            f"- scaler: `{hashes['EDITOR006A_SCALER.json']}`",
            "",
            "## Split identity",
            "",
            f"- train `{protocol['split_hashes']['train_sha256']}`",
            f"- validation `{protocol['split_hashes']['val_sha256']}`",
            f"- user mapping `{protocol['split_hashes']['user_mapping_sha256']}`",
            f"- seeds `{protocol['seeds']}`",
            "",
            "## Deny-list",
            "",
            "r5.2 TEST, CERT r5.1, CERT r6.2, target-domain fit, new perturbations, new architecture,",
            "EDITOR022B/C, EDITOR-023 robustness rescue, post-result rho/epoch/LR search.",
            "",
            "## Historical artefacts",
            "",
            "EDITOR-021 review and output directories are read-only to EDITOR-022.",
            "",
            "## Result-freeze procedure",
            "",
            *[f"{i+1}. {step}" for i, step in enumerate(protocol["result_freeze_procedure"])],
            "",
            "The SHA manifest must not hash itself. Nothing listed in it may be modified afterwards.",
            "",
            "## Producing pins",
            "",
            f"- architecture `{pins['architecture']}`",
            f"- odst `{pins['odst']}`",
            f"- sequence_ensemble `{pins['sequence_ensemble']}`",
            "",
        ]
    )


def preflight_cfp0_hashes() -> dict[str, Any]:
    return hash_gate_all_cfp0_inner()
