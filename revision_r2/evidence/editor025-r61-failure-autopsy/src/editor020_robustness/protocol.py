"""EDITOR-020 protocol freeze. Written before any robustness-training result is viewed."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from editor012_rescue.constants import EXPECTED_TRAIN_SHA256, EXPECTED_USER_MAPPING_SHA256, EXPECTED_VAL_SHA256
from editor012_rescue.producing import pin_producing_sources
from editor012_rescue.safety import TRAIN_NPZ, VAL_NPZ
from editor017_robustness.perturbations import perturbation_module_hashes, protocol_lock

from .constants import (
    ALLOWED_TERMS,
    ARCH_SPECS,
    BASE_COMMIT,
    CLEAN_ODST_PREDICTIVE_SUPERIORITY,
    CLEAN_PRESERVATION_MARGIN,
    EDITOR017_RESULTS_COMMIT,
    EDITOR018_RESULTS_COMMIT,
    EDITOR019_RESULTS_COMMIT,
    EXPECTED_GAUSSIAN_SHA256,
    EXPECTED_SCALER_JSON_SHA256,
    EXPECTED_SOURCE_ABLATION_SHA256,
    FAMILY_P_NOISE,
    FAMILY_P_SOURCE,
    FORBIDDEN_THREAT_TERMS,
    FROZEN_CLEAN_VAL_PR_AUC,
    FROZEN_L1_MEAN_PR_AUC,
    FROZEN_TA2_MEAN_PR_AUC,
    GLOBAL_TOPK_PR_AUC_FAITHFULNESS,
    INNER_CONDITIONS,
    LAMBDA_ROUTE,
    LAMBDA_TEACHER,
    NOISE_LEVELS,
    NOISE_PERTURBATION_SEED,
    OBJECTIVES,
    ODST046,
    ODST_DEGRADED_INPUT_ADVANTAGE_OVER_LINEAR,
    PRIMARY_SEEDS,
    REVIEW_REL,
    ROUTE_ANCHOR_STRUCTURAL_ROBUSTNESS,
    SAMPLER_SEED,
    SCALER_JSON,
    SCREENING_SEED,
    SOURCE_CHANNELS,
    TEACHER_GUIDANCE_DEGRADED_INPUT_VALUE,
    TEACHER_GUIDANCE_VS_INITIALISATION,
)
from .io_util import write_json
from .safety import REPO_ROOT, REVIEW_ROOT, Editor020Blocked, Editor020ProtocolError, refuse_r52_test, sha256_file, utc_now
from .sampler import sampler_lock


def _review(*parts: str) -> Path:
    path = REVIEW_ROOT.joinpath(*parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def assert_perturbation_hashes() -> dict[str, str]:
    hashes = perturbation_module_hashes(REPO_ROOT)
    if hashes["objective3_missing_source_robustness.py"] != EXPECTED_SOURCE_ABLATION_SHA256:
        raise Editor020Blocked("EDITOR-017 source-ablation implementation hash mismatch")
    if hashes["objective3_perturbations.py"] != EXPECTED_GAUSSIAN_SHA256:
        raise Editor020Blocked("EDITOR-017 gaussian implementation hash mismatch")
    if hashes["EDITOR006A_SCALER.json"] != EXPECTED_SCALER_JSON_SHA256:
        raise Editor020Blocked("r5.2 TRAIN scaler hash mismatch")
    return hashes


def write_protocol_packet() -> dict[str, Any]:
    try:
        refuse_r52_test(
            r"C:\PhD\07_Projects\cert-r42-feasibility\data\processed\r5.2\tensors\r52_T20_s1_test.npz"
        )
        raise Editor020Blocked("r5.2 TEST deny-list failed to fire")
    except Exception as exc:
        if "TEST" not in str(exc):
            raise

    if abs(float(LAMBDA_TEACHER) - 0.5) > 1e-15 or abs(float(LAMBDA_ROUTE) - 0.5) > 1e-15:
        raise Editor020ProtocolError("lambdas must remain 0.5")
    if ODST046["n_trees"] != 4 or ODST046["depth"] != 4:
        raise Editor020Blocked("ODST-046 lock mismatch")
    hashes = assert_perturbation_hashes()
    pins = pin_producing_sources()
    lock = protocol_lock()
    sampler = sampler_lock()

    protocol = {
        "task": "EDITOR-020",
        "title": "CLEAN-TEACHER-TO-DEGRADED-STUDENT ROBUSTNESS TRAINING",
        "utc": utc_now(),
        "base_commit": BASE_COMMIT,
        "EDITOR017_RESULTS_COMMIT": EDITOR017_RESULTS_COMMIT,
        "EDITOR018_RESULTS_COMMIT": EDITOR018_RESULTS_COMMIT,
        "EDITOR019_RESULTS_COMMIT": EDITOR019_RESULTS_COMMIT,
        "data_boundary": {
            "train": "CERT r5.2 TRAIN",
            "validation": "CERT r5.2 VALIDATION confirmation only",
            "model_selection": "INNER_TRAIN / INNER_SELECT",
            "R52_TEST": "HARD_DENY",
            "r51": "NO",
            "r62": "NO",
            "new_architecture_search": False,
        },
        "controlling_evidence": {
            "TEACHER_GUIDANCE_VS_INITIALISATION": TEACHER_GUIDANCE_VS_INITIALISATION,
            "TEACHER_GUIDANCE_DEGRADED_INPUT_VALUE": TEACHER_GUIDANCE_DEGRADED_INPUT_VALUE,
            "ROUTE_ANCHOR_STRUCTURAL_ROBUSTNESS": ROUTE_ANCHOR_STRUCTURAL_ROBUSTNESS,
            "ODST_DEGRADED_INPUT_ADVANTAGE_OVER_LINEAR": ODST_DEGRADED_INPUT_ADVANTAGE_OVER_LINEAR,
            "CLEAN_ODST_PREDICTIVE_SUPERIORITY": CLEAN_ODST_PREDICTIVE_SUPERIORITY,
            "GLOBAL_TOPK_PR_AUC_FAITHFULNESS": GLOBAL_TOPK_PR_AUC_FAITHFULNESS,
            "frozen_clean_L1_mean_PR_AUC": FROZEN_L1_MEAN_PR_AUC,
            "frozen_clean_TA2_mean_PR_AUC": FROZEN_TA2_MEAN_PR_AUC,
        },
        "primary_architectures": ARCH_SPECS,
        "objectives": OBJECTIVES,
        "inner_conditions": list(INNER_CONDITIONS),
        "lambdas": {"teacher": LAMBDA_TEACHER, "route": LAMBDA_ROUTE, "search": False},
        "clean_preservation_margin": CLEAN_PRESERVATION_MARGIN,
        "screening_seed": SCREENING_SEED,
        "official_seeds": list(PRIMARY_SEEDS),
        "teacher_target": {
            "t(x)": "mean[T-OPT42(x), T-OPT52(x), T-OPT62(x)]",
            "teacher_input": "CLEAN x only",
            "student_robustness_input": "degraded x_tilde",
            "teacher_parameters": "frozen",
            "no_teacher_prediction_on_degraded_for_primary_consistency_target": True,
        },
        "route_target": {
            "teacher_route": "matched seed-specific T-OPT on CLEAN x",
            "student_route": "degraded x_tilde",
            "loss": "KL(clean_teacher_route, degraded_student_route)",
            "implementation": "editor012_rescue.losses.route_consistency_loss",
        },
        "terminology_allowed": list(ALLOWED_TERMS),
        "terminology_forbidden": list(FORBIDDEN_THREAT_TERMS),
        "objective_is_not_another_clean_ODST_search": True,
        "producing_pins": pins,
        "train_sha256": EXPECTED_TRAIN_SHA256,
        "val_sha256": EXPECTED_VAL_SHA256,
        "user_mapping_sha256": EXPECTED_USER_MAPPING_SHA256,
        "train_npz": str(TRAIN_NPZ),
        "val_npz": str(VAL_NPZ),
        "scaler_json": str(SCALER_JSON),
        "frozen_clean_val_PR_AUC": FROZEN_CLEAN_VAL_PR_AUC,
    }
    write_json(_review("00_protocol", "EDITOR020_PROTOCOL.json"), protocol)

    audit = {
        "EDITOR017_perturbation_code_hash_matched": True,
        "source_sha256": hashes["objective3_missing_source_robustness.py"],
        "gaussian_sha256": hashes["objective3_perturbations.py"],
        "scaler_sha256": hashes["EDITOR006A_SCALER.json"],
        "expected_source_sha256": EXPECTED_SOURCE_ABLATION_SHA256,
        "expected_gaussian_sha256": EXPECTED_GAUSSIAN_SHA256,
        "expected_scaler_sha256": EXPECTED_SCALER_JSON_SHA256,
        "source_channels": list(SOURCE_CHANNELS),
        "noise_levels": list(NOISE_LEVELS),
        "noise_perturbation_seed": NOISE_PERTURBATION_SEED,
        "severities_unchanged": True,
        "no_invented_corruptions": True,
        "protocol_lock": lock,
        "review_rel": str(REVIEW_REL),
    }
    write_json(_review("00_protocol", "EDITOR020_PERTURBATION_AUDIT.json"), audit)
    write_json(_review("00_protocol", "EDITOR020_TRAINING_SAMPLER_FREEZE.json"), sampler)

    model_objectives = {
        "architectures": ARCH_SPECS,
        "objectives": OBJECTIVES,
        "matched_fairness": {
            "critical_comparison": "robust TA2 versus robust L1 under the matched robustness objective",
            "pairs": [
                "L1-R1 vs TA2-R1",
                "L1-R2 vs F10-R2 / TA2-R2",
                "L1-R3 vs F10-R3 / TA2-R3",
                "TA2-R4 vs TA2-R3",
            ],
            "R1_and_R3_differ_only_by_teacher_consistency": True,
            "R3_and_R4_differ_only_by_robust_route_consistency": True,
            "matched_L1_and_TA2_use_same_corruption_sampler": True,
            "TA2_clean_route_is_architecture_identity": True,
            "R0_is_existing_clean_training": True,
        },
        "lambda_teacher": LAMBDA_TEACHER,
        "lambda_route": LAMBDA_ROUTE,
        "SAMPLER_SEED": SAMPLER_SEED,
        "P_source": FAMILY_P_SOURCE,
        "P_noise": FAMILY_P_NOISE,
    }
    write_json(_review("00_protocol", "EDITOR020_MODEL_OBJECTIVES.json"), model_objectives)
    return {"protocol": protocol, "audit": audit, "sampler": sampler, "model_objectives": model_objectives}
