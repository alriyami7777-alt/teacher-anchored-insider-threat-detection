"""Protocol freeze writers. Must precede training results."""

from __future__ import annotations

from typing import Any

from editor012_rescue.producing import pin_producing_sources
from editor017_robustness.constants import AUTHORITATIVE_GAUSSIAN, AUTHORITATIVE_SOURCE_ABLATION

from .aggregate40 import audit_record
from .constants import (
    BASE_COMMIT,
    BATCH_SIZE,
    BRANCH_FAMILIES,
    CONDITION_SPECS,
    DIRECTIONAL_KS,
    EDITOR012_RESULTS_COMMIT,
    EDITOR013_RESULTS_COMMIT,
    EDITOR014_RESULTS_COMMIT,
    EDITOR015_RESULTS_COMMIT,
    EDITOR016_RESULTS_COMMIT,
    EDITOR017_RESULTS_COMMIT,
    ENSEMBLE_CACHE,
    EXPECTED_INNER_SELECT_N,
    EXPECTED_INNER_SELECT_POS,
    EXPECTED_INNER_TRAIN_N,
    EXPECTED_INNER_TRAIN_POS,
    EXPECTED_TRAIN_SHA256,
    EXPECTED_USER_MAPPING_SHA256,
    EXPECTED_VAL_SHA256,
    F11_CHECKPOINTS,
    FROZEN_L1_MEAN_PR_AUC,
    FROZEN_TA2_MEAN_PR_AUC,
    GLOBAL_TOPK_PR_AUC_FAITHFULNESS,
    INNER_CONDITIONS,
    L1_CHECKPOINTS,
    LAMBDA_TEACHER,
    LOCKED_AGG_FEATURES,
    LR_ATTENTION,
    LR_BRANCH,
    LR_ENCODER,
    MAX_EPOCHS,
    MLP40_PROVENANCE,
    NOISE_LEVELS,
    ODST40_SPEC,
    PATIENCE,
    PRIMARY_SEEDS,
    PROMOTION_MARGIN,
    SCREENING_SEED,
    SOURCE_CHANNELS,
    SUMMARY_DIM,
    TEACHER_GUIDANCE_VS_INITIALISATION,
    TOPT_CHECKPOINTS,
)
from .io_util import write_json
from .models import prove_function_preserving
from .safety import REVIEW_ROOT, TRAIN_NPZ, VAL_NPZ, sha256_file, utc_now


def _rev(*parts: str):
    return REVIEW_ROOT.joinpath(*parts)


def write_protocol_packet() -> dict[str, Any]:
    _rev("00_protocol").mkdir(parents=True, exist_ok=True)
    for name in (
        "01_inner_cross_view",
        "02_validation_confirmation",
        "03_teacher_effect",
        "04_explainability",
        "05_robustness",
        "06_statistics",
        "07_editor_response",
        "08_paper_handover",
    ):
        _rev(name).mkdir(parents=True, exist_ok=True)

    pins = pin_producing_sources()
    proofs = {fam: prove_function_preserving(fam) for fam in BRANCH_FAMILIES}
    agg = audit_record()

    source = {
        "EDITOR012_RESULTS_COMMIT": EDITOR012_RESULTS_COMMIT,
        "EDITOR013_RESULTS_COMMIT": EDITOR013_RESULTS_COMMIT,
        "EDITOR014_RESULTS_COMMIT": EDITOR014_RESULTS_COMMIT,
        "EDITOR015_RESULTS_COMMIT": EDITOR015_RESULTS_COMMIT,
        "EDITOR016_RESULTS_COMMIT": EDITOR016_RESULTS_COMMIT,
        "EDITOR017_RESULTS_COMMIT": EDITOR017_RESULTS_COMMIT,
        "BASE_COMMIT": BASE_COMMIT,
        "historical_packets": "READ_ONLY",
        "L1": {str(s): {"checkpoint": str(L1_CHECKPOINTS[s]["checkpoint"]), "sha256": L1_CHECKPOINTS[s]["sha256"]} for s in PRIMARY_SEEDS},
        "TA2": {str(s): {"checkpoint": str(F11_CHECKPOINTS[s]["checkpoint"]), "sha256": F11_CHECKPOINTS[s]["sha256"]} for s in PRIMARY_SEEDS},
        "TOPT": {str(s): {"checkpoint": str(TOPT_CHECKPOINTS[s]["checkpoint"]), "sha256": TOPT_CHECKPOINTS[s]["sha256"]} for s in PRIMARY_SEEDS},
        "ensemble_cache": {k: str(v) for k, v in ENSEMBLE_CACHE.items()},
        "producing_pins": pins,
        "xgboost40_rf40": "diagnostic_context_only_not_selection_controls",
    }
    write_json(_rev("00_protocol", "EDITOR018_SOURCE_REGISTER.json"), source)
    write_json(_rev("00_protocol", "EDITOR018_AGGREGATE40_AUDIT.json"), agg)

    family = {
        "LIN40": {"type": "linear", "in_dim": SUMMARY_DIM, "init": "zeros"},
        "MLP40": {
            "type": "shallow_mlp",
            "in_dim": SUMMARY_DIM,
            "hidden": [128, 64],
            "activation": "relu",
            "dropout": 0.2,
            "weight_decay": 0.0,
            "optimizer": "Adam",
            "learning_rate": LR_BRANCH,
            "provenance": MLP40_PROVENANCE,
            "blocked": False,
        },
        "ODST40": dict(ODST40_SPEC),
        "IWODST40": {
            **dict(ODST40_SPEC),
            "instance_wise_gate": "softmax(W_g s + b_g)",
            "W_g_init": 0,
            "b_g_init": 0,
            "initial_weights": 1.0 / 8.0,
            "no_gate_hidden_layer": True,
            "no_gating_temperature_search": True,
            "no_regulariser_search": True,
            "distinct_from_editor013_global_tree_weights": True,
        },
        "function_preserving": proofs,
        "teacher_residual": "mean(T-OPT42, T-OPT52, T-OPT62) - L1_logit",
        "lambda_teacher": LAMBDA_TEACHER,
        "no_route_anchor_during_architecture_screen": True,
        "information_fairness": "ODST value requires beating matched LIN40/MLP40 on the same 40-vector",
    }
    write_json(_rev("00_protocol", "EDITOR018_MODEL_FAMILY_FREEZE.json"), family)

    protocol = {
        "task_id": "EDITOR-018",
        "campaign": "CROSS-VIEW TEACHER-ANCHORED DIFFERENTIABLE TREE RESCUE",
        "status": "PHASE_A_FROZEN_BEFORE_RESULTS",
        "authorised_partitions": ["CERT r5.2 TRAIN", "CERT r5.2 VALIDATION"],
        "TEST_ACCESS": "PROHIBITED",
        "R51_EXECUTION": "PROHIBITED",
        "R62_EXECUTION": "PROHIBITED",
        "inner_search_uses": "INNER_TRAIN / INNER_SELECT only",
        "official_validation_never_used_to_promote": True,
        "T": 20,
        "F": 13,
        "summary_dim": SUMMARY_DIM,
        "feature_names_40": list(LOCKED_AGG_FEATURES),
        "inner_split_expected": {
            "n_inner_train": EXPECTED_INNER_TRAIN_N,
            "n_inner_select": EXPECTED_INNER_SELECT_N,
            "n_inner_train_pos": EXPECTED_INNER_TRAIN_POS,
            "n_inner_select_pos": EXPECTED_INNER_SELECT_POS,
        },
        "user_mapping": {
            "n_users": 2000,
            "windows_per_user": 32,
            "malicious_users": 31,
            "expected_sha256": EXPECTED_USER_MAPPING_SHA256,
        },
        "inner_conditions": list(INNER_CONDITIONS),
        "condition_specs": CONDITION_SPECS,
        "screening_seed": SCREENING_SEED,
        "primary_seeds": list(PRIMARY_SEEDS),
        "batch_size": BATCH_SIZE,
        "max_epochs": MAX_EPOCHS,
        "patience": PATIENCE,
        "lr_encoder": LR_ENCODER,
        "lr_attention": LR_ATTENTION,
        "lr_branch": LR_BRANCH,
        "lambda_teacher": LAMBDA_TEACHER,
        "promotion_margin": PROMOTION_MARGIN,
        "promotion_margin_may_be_lowered_after_results": False,
        "TEACHER_GUIDANCE_VS_INITIALISATION": TEACHER_GUIDANCE_VS_INITIALISATION,
        "GLOBAL_TOPK_PR_AUC_FAITHFULNESS": GLOBAL_TOPK_PR_AUC_FAITHFULNESS,
        "frozen_L1_mean_PR_AUC": FROZEN_L1_MEAN_PR_AUC,
        "frozen_TA2_mean_PR_AUC": FROZEN_TA2_MEAN_PR_AUC,
        "directional_ks": list(DIRECTIONAL_KS),
        "source_channels": list(SOURCE_CHANNELS),
        "noise_levels": list(NOISE_LEVELS),
        "source_ablation": AUTHORITATIVE_SOURCE_ABLATION,
        "gaussian_noise": AUTHORITATIVE_GAUSSIAN,
        "robustness_recompute_40_from_perturbed_sequence": True,
        "utc": utc_now(),
    }
    write_json(_rev("00_protocol", "EDITOR018_PROTOCOL.json"), protocol)

    checksums = {
        "train_npz": str(TRAIN_NPZ),
        "train_sha256": EXPECTED_TRAIN_SHA256,
        "validation_npz": str(VAL_NPZ),
        "validation_sha256": EXPECTED_VAL_SHA256,
        "train_file_sha256": sha256_file(TRAIN_NPZ),
        "validation_file_sha256": sha256_file(VAL_NPZ),
        "aggregate40_sha256": agg["producing_implementation"]["sha256"],
        "producing_pins": pins,
        "r52_test_accessed": False,
    }
    if checksums["train_file_sha256"] != EXPECTED_TRAIN_SHA256:
        raise RuntimeError("TRAIN tensor hash mismatch")
    if checksums["validation_file_sha256"] != EXPECTED_VAL_SHA256:
        raise RuntimeError("VALIDATION tensor hash mismatch")
    write_json(_rev("00_protocol", "EDITOR018_INPUT_CHECKSUMS.json"), checksums)
    return {
        "source": source,
        "aggregate40": agg,
        "family": family,
        "protocol": protocol,
        "checksums": checksums,
    }
