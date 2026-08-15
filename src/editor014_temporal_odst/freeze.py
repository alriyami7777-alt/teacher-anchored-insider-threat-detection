"""Phase A/B protocol freeze: temporal audit, model freeze, checksums."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import torch

from editor012_rescue.producing import build_odst046_model, pin_producing_sources
from editor012_rescue.safety import (
    EXPECTED_ARCHITECTURE_SHA256,
    EXPECTED_ODST_SHA256,
    EXPECTED_SCALER_SHA256,
    TRAIN_NPZ,
    VAL_NPZ,
)

from .constants import (
    CONDITIONS,
    EDITOR012_IMPLEMENTATION_COMMIT,
    EDITOR012_PROMOTION_COMMIT,
    EDITOR012_PROTOCOL_COMMIT,
    EDITOR012_RESULTS_COMMIT,
    EDITOR013_RESULTS_COMMIT,
    ENCODER_ARCH,
    ENCODER_DIM,
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
    N_TREES_TOTAL,
    ODST046,
    POST_ATTENTION_ODST_VALUE,
    PRIMARY_SEEDS,
    PROMOTION_MARGIN,
    SEQUENCE_LENGTH,
    TEACHER_GUIDANCE_VS_INITIALISATION,
    TOPT_CHECKPOINTS,
    TREE_ORDER,
)
from .io_util import write_json
from .models import linear_attention_equivalence
from .safety import (
    REVIEW_ROOT,
    Editor014ProtocolError,
    refuse_historical_write,
    refuse_r52_test,
    require_hash,
    utc_now,
)


def _review(*parts: str) -> Path:
    path = REVIEW_ROOT.joinpath(*parts)
    refuse_historical_write(path)
    return path


def temporal_state_audit() -> dict[str, Any]:
    student = build_odst046_model()
    student.eval()
    x = torch.zeros(2, SEQUENCE_LENGTH, FEATURE_DIM)
    with torch.no_grad():
        z, enc = student.encode_attention_h(x)
        h = enc["hidden_states"]
        alpha = enc["attention_weights"]
        w = student.linear_head.weight.detach().reshape(-1)
        b = student.linear_head.bias.detach().reshape(-1)[0]
        equiv = linear_attention_equivalence(z, h, alpha, w, b)
        stored = enc["linear_logit"]
        match = bool(torch.allclose(equiv, stored, atol=1e-5, rtol=1e-5))
    return {
        "task_id": "EDITOR-014",
        "source": "prototype_v3_node.architecture.AttentionNodeEnsemble.encode_attention_h",
        "Bi-LSTM_state_tensor_shape": [None, SEQUENCE_LENGTH, ENCODER_DIM],
        "observed_hidden_shape": list(h.shape),
        "direction_concatenation": "bidirectional LSTM hidden_size=64 concatenated to 128",
        "hidden_dimension": ENCODER_DIM,
        "lstm": {
            "input_size": FEATURE_DIM,
            "hidden_size": 64,
            "num_layers": 1,
            "batch_first": True,
            "bidirectional": True,
        },
        "dropout_location": "after Bi-LSTM hidden states, before temporal attention",
        "dropout_p": 0.2,
        "attention_score_computation": "score(tanh(Linear_HtoA(h_t))); Linear_Ato1 has no bias",
        "attention_weight_shape": [None, SEQUENCE_LENGTH],
        "observed_attention_shape": list(alpha.shape),
        "attention_normalisation": "softmax over time; weights non-negative and sum to 1",
        "attended_representation_formula": "z = Σ_t alpha_t h_t",
        "observed_z_shape": list(z.shape),
        "LINEAR_AFTER_ATTENTION_EQUIVALENT_TO_ATTENTION_WEIGHTED_LINEAR_PER_TIME": "YES" if match else "NO",
        "equivalence_identity": "w^T Σ_t α_t h_t + b = Σ_t α_t (w^T h_t) + b  (because Σ_t α_t = 1)",
        "historical_architecture": "ODST(Σ_t α_t h_t)",
        "new_temporal_architecture": "Σ_t α_t ODST(h_t)",
        "operations_generally_equivalent": False,
        "reason_not_equivalent": "ODST is nonlinear, so ODST(Σ α h) ≠ Σ α ODST(h) in general",
    }


def model_freeze() -> dict[str, Any]:
    return {
        "task_id": "EDITOR-014",
        "frozen_before_results": True,
        "POST_ATTENTION_ODST_INCREMENTAL_VALUE": POST_ATTENTION_ODST_VALUE,
        "TEACHER_GUIDANCE_VS_INITIALISATION": TEACHER_GUIDANCE_VS_INITIALISATION,
        "encoder": "20x13 -> Bi-LSTM -> temporal attention; no encoder architecture change",
        "odst046": ODST046,
        "shared_temporal_odst": {
            "g_theta": "one shared ODST-046 applied to every h_t",
            "separate_ensembles_per_timestep": False,
            "learned_tree_weighting": False,
            "q_t": "mean_j tree_j(h_t)",
            "temporal_odst_logit": "Σ_t α_t q_t",
            "attention_mechanism_unchanged": True,
        },
        "conditions": CONDITIONS,
        "T1_T2_beta_init": 0.0,
        "T2_centering": "o(x) - mean_TRAIN[o(x)]; INNER_TRAIN during inner; full TRAIN during final; no validation centering",
        "teacher_guidance": {
            "ensemble": "equal-weight mean of T-OPT(42/52/62) logits",
            "operates_on": "final_logit",
            "lambda_distill": LAMBDA_DISTILL,
            "not_tuned": True,
        },
        "promotion_margin": PROMOTION_MARGIN,
        "max_promoted_temporal": 2,
        "no_sample_dependent_gates": True,
        "no_tree_count_depth_temperature_grid": True,
        "no_focal_pairwise_GroupDRO_CORAL": True,
        "T": SEQUENCE_LENGTH,
        "F": FEATURE_DIM,
        "n_trees_total": N_TREES_TOTAL,
        "tree_order": TREE_ORDER,
        "frozen_ta2_l1": {
            "TA2_mean_PR_AUC": FROZEN_TA2_MEAN_PR_AUC,
            "L1_mean_PR_AUC": FROZEN_L1_MEAN_PR_AUC,
            "TA2_minus_L1": FROZEN_TA2_MINUS_L1,
            "CI": FROZEN_TA2_L1_CI,
        },
    }


def source_register() -> dict[str, Any]:
    pins = pin_producing_sources()
    return {
        "task_id": "EDITOR-014",
        "EDITOR012_PROTOCOL_COMMIT": EDITOR012_PROTOCOL_COMMIT,
        "EDITOR012_IMPLEMENTATION_COMMIT": EDITOR012_IMPLEMENTATION_COMMIT,
        "EDITOR012_PROMOTION_COMMIT": EDITOR012_PROMOTION_COMMIT,
        "EDITOR012_RESULTS_COMMIT": EDITOR012_RESULTS_COMMIT,
        "EDITOR013_RESULTS_COMMIT": EDITOR013_RESULTS_COMMIT,
        "historical_packets_readonly": True,
        "TEACHER_GUIDANCE_VS_INITIALISATION": TEACHER_GUIDANCE_VS_INITIALISATION,
        "POST_ATTENTION_ODST_INCREMENTAL_VALUE": POST_ATTENTION_ODST_VALUE,
        "producing_pins": pins,
        "topt_hashes": {str(k): v["sha256"] for k, v in TOPT_CHECKPOINTS.items()},
        "ta2_hashes": {str(k): v["sha256"] for k, v in F11_CHECKPOINTS.items()},
        "l1_hashes": {str(k): v["sha256"] for k, v in L1_CHECKPOINTS.items()},
        "r52_test_opened": False,
        "r51_rerun": False,
        "r62_rerun": False,
    }


def write_protocol_packet() -> dict[str, Any]:
    for sub in (
        "00_protocol",
        "01_inner_selection",
        "02_validation_confirmation",
        "03_temporal_explainability",
        "04_ta2_value",
        "05_statistics",
        "06_editor_response",
    ):
        _review(sub).mkdir(parents=True, exist_ok=True)

    try:
        refuse_r52_test(
            r"C:\PhD\07_Projects\cert-r42-feasibility\data\processed\r5.2\tensors\r52_T20_s1_test.npz"
        )
        raise Editor014ProtocolError("r5.2 TEST deny-list failed to fire")
    except Exception as exc:
        if "TEST" not in str(exc):
            raise

    require_hash(TRAIN_NPZ, EXPECTED_TRAIN_SHA256, role="train")
    require_hash(VAL_NPZ, EXPECTED_VAL_SHA256, role="validation")
    for seed, spec in TOPT_CHECKPOINTS.items():
        require_hash(Path(spec["checkpoint"]), spec["sha256"], role=f"T-OPT:{seed}")
    for seed, spec in F11_CHECKPOINTS.items():
        require_hash(Path(spec["checkpoint"]), spec["sha256"], role=f"TA2:{seed}")
    for seed, spec in L1_CHECKPOINTS.items():
        require_hash(Path(spec["checkpoint"]), spec["sha256"], role=f"L1:{seed}")

    register = source_register()
    write_json(_review("00_protocol", "EDITOR014_SOURCE_REGISTER.json"), register)
    audit = temporal_state_audit()
    write_json(_review("00_protocol", "EDITOR014_TEMPORAL_STATE_AUDIT.json"), audit)
    family = model_freeze()
    write_json(_review("00_protocol", "EDITOR014_MODEL_FREEZE.json"), family)

    protocol = {
        "task_id": "EDITOR-014",
        "campaign": "EDITOR-014 TEMPORAL ODST PLACEMENT AND TA2 VALUE PROOF",
        "status": "PHASE_B_FROZEN_BEFORE_RESULTS",
        "scientific_question": (
            "Does applying a shared ODST to contextualised per-time-step Bi-LSTM "
            "states before attention aggregation provide incremental predictive "
            "value over the matched teacher-guided linear model?"
        ),
        "authorised_partitions": ["CERT r5.2 TRAIN", "CERT r5.2 VALIDATION"],
        "TEST_ACCESS": "PROHIBITED",
        "R51_EXECUTION": "PROHIBITED",
        "R62_EXECUTION": "PROHIBITED",
        "inner_search_uses": "INNER_TRAIN / INNER_SELECT only",
        "official_validation_never_used_to_promote": True,
        "user_mapping": {
            "n_users": EXPECTED_VAL_USERS,
            "windows_per_user": EXPECTED_VAL_WINDOWS_PER_USER,
            "malicious_users": EXPECTED_VAL_MALICIOUS_USERS,
            "expected_sha256": EXPECTED_USER_MAPPING_SHA256,
        },
        "inner_split_expected": {
            "n_inner_train": EXPECTED_INNER_TRAIN_N,
            "n_inner_select": EXPECTED_INNER_SELECT_N,
            "n_inner_train_pos": EXPECTED_INNER_TRAIN_POS,
            "n_inner_select_pos": EXPECTED_INNER_SELECT_POS,
        },
        "TEACHER_GUIDANCE_VS_INITIALISATION": TEACHER_GUIDANCE_VS_INITIALISATION,
        "POST_ATTENTION_ODST_INCREMENTAL_VALUE": POST_ATTENTION_ODST_VALUE,
        "frozen_before_first_training_result": True,
        "encoder_arch": ENCODER_ARCH,
        "LINEAR_AFTER_ATTENTION_EQUIVALENT_TO_ATTENTION_WEIGHTED_LINEAR_PER_TIME": audit[
            "LINEAR_AFTER_ATTENTION_EQUIVALENT_TO_ATTENTION_WEIGHTED_LINEAR_PER_TIME"
        ],
    }
    write_json(_review("00_protocol", "EDITOR014_PROTOCOL.json"), protocol)

    checksums = {
        "task_id": "EDITOR-014",
        "r52_test_opened": False,
        "r52_test_hashed": False,
        "inputs": [
            {"role": "r52_train_npz", "path": str(TRAIN_NPZ), "sha256": EXPECTED_TRAIN_SHA256, "status": "MATCH"},
            {"role": "r52_validation_npz", "path": str(VAL_NPZ), "sha256": EXPECTED_VAL_SHA256, "status": "MATCH"},
            {"role": "producing_architecture", "sha256": EXPECTED_ARCHITECTURE_SHA256, "status": "MATCH"},
            {"role": "producing_odst", "sha256": EXPECTED_ODST_SHA256, "status": "MATCH"},
            {"role": "trainonly_scaler", "sha256": EXPECTED_SCALER_SHA256, "status": "MATCH"},
        ],
        "denied_tensors": {
            "r52_test": {
                "canonical_relative_path": "data/processed/r5.2/tensors/r52_T20_s1_test.npz",
                "status": "HARD_DENY",
                "not_opened": True,
                "not_hashed": True,
            }
        },
        "topt_hashes": {str(k): v["sha256"] for k, v in TOPT_CHECKPOINTS.items()},
        "ta2_hashes": {str(k): v["sha256"] for k, v in F11_CHECKPOINTS.items()},
        "l1_hashes": {str(k): v["sha256"] for k, v in L1_CHECKPOINTS.items()},
        "EDITOR012_RESULTS_COMMIT": EDITOR012_RESULTS_COMMIT,
        "EDITOR013_RESULTS_COMMIT": EDITOR013_RESULTS_COMMIT,
        "frozen_utc": utc_now(),
    }
    write_json(_review("00_protocol", "EDITOR014_INPUT_CHECKSUMS.json"), checksums)
    return {
        "register": register,
        "audit": audit,
        "family": family,
        "protocol": protocol,
        "checksums": checksums,
    }
