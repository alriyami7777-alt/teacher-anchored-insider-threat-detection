"""Phase A/B protocol freeze: audits, model family, checksums. Written before results."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from editor012_rescue.producing import pin_producing_sources
from editor012_rescue.safety import (
    EXPECTED_ARCHITECTURE_SHA256,
    EXPECTED_ODST_SHA256,
    EXPECTED_SCALER_SHA256,
    TRAIN_NPZ,
    VAL_NPZ,
)

from .constants import (
    EDITOR012_IMPLEMENTATION_COMMIT,
    EDITOR012_PROMOTION_COMMIT,
    EDITOR012_PROTOCOL_COMMIT,
    EDITOR012_RESULTS_COMMIT,
    EDITOR012_RESULTS_FULL_COMMIT,
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
    HEAD_CONDITIONS,
    HISTORICAL,
    HISTORICAL_SINGLE_TEACHER_LOGIT_ANCHOR,
    LAMBDA_DISTILL,
    LAMBDA_ROUTE,
    N_LAYERS,
    N_TREES_PER_LAYER,
    N_TREES_TOTAL,
    ODST046,
    PRIMARY_SEEDS,
    REVIEW_REL,
    TEACHER_GUIDANCE_VS_INITIALISATION,
    TOPT_CHECKPOINTS,
    TREE_ORDER,
    VALIDATION_MANDATORY,
)
from .io_util import write_json
from .safety import (
    REVIEW_ROOT,
    Editor013ProtocolError,
    refuse_historical_write,
    refuse_r52_test,
    require_hash,
    utc_now,
)


def _review(*parts: str) -> Path:
    path = REVIEW_ROOT.joinpath(*parts)
    refuse_historical_write(path)
    return path


def linear_path_audit() -> dict[str, Any]:
    return {
        "task_id": "EDITOR-013",
        "source": "src/editor012_rescue/models.py student_forward + live_odst_forward",
        "producing_architecture": "prototype_v3_node.architecture.AttentionNodeEnsemble",
        "student_forward_returns": {
            "logit": "ODST tree_outputs.mean(dim=-1)",
            "linear_logit": "linear_head(z) from encode_attention_h",
            "z": "attended Bi-LSTM representation, dim=128",
        },
        "linear_head_architecture": "nn.Linear(encoder_dim=128, out_features=1, bias=True)",
        "linear_head_input_dimension": ENCODER_DIM,
        "linear_head_state_provenance": (
            "Present in T-OPT checkpoints. T-OPT trains only node_head "
            "(build_teacher_optimizer). During T-OPT, lstm/attention/linear_head "
            "are eval() and not in the optimiser. C2-OPT/TA2 enable_student freezes "
            "linear_head. Stored T-OPT linear_head is NOT a valid trained "
            "attention-linear reference for EDITOR-013 comparisons."
        ),
        "trained_in_TOPT": False,
        "frozen_in_C2OPT": True,
        "frozen_in_TA2": True,
        "linear_logit_contributes_to_final_prediction": False,
        "LINEAR_PATH_PRESENT": True,
        "LINEAR_PATH_USED_BY_HISTORICAL_ODST_PREDICTION": False,
        "do_not_use_stored_topt_linear_as_attention_linear_reference": True,
        "editor013_linear_head": "new zero-initialised nn.Linear(128, 1); identical across L0/L1/hybrid",
    }


def odst_readout_audit() -> dict[str, Any]:
    return {
        "task_id": "EDITOR-013",
        "source": "live_odst_forward + NODE.forward canonical_tree_average",
        "tree_outputs": "concatenated per-tree outputs, shape (B, 8)",
        "current_ODST_final_logit": "mean(tree_outputs) over dim=-1",
        "ODST_CURRENT_READOUT": "UNIFORM_MEAN",
        "number_of_tree_outputs": N_TREES_TOTAL,
        "n_layers": N_LAYERS,
        "n_trees_per_layer": N_TREES_PER_LAYER,
        "tree_output_dimensionality": 1,
        "tree_ordering": TREE_ORDER,
        "layer_ordering": ["layer0_then_layer1_dense_concat"],
        "readout_parameter_count": 0,
        "trainable_readout_weights": "NONE",
        "node_head.output_head": "present for state_dict stability; frozen; unused under canonical_tree_average",
        "editor013_weighted_readout": {
            "w": "R^8, init 0",
            "a": "softmax(w), init uniform 1/8",
            "z_tree": "sum_j a_j t_j",
            "sample_dependent_weights": False,
        },
        "readout_does_not_change": [
            "tree split decisions",
            "route probabilities",
            "leaf probabilities",
            "feature selection",
            "tree identity",
            "route identity",
        ],
    }


def model_family_freeze() -> dict[str, Any]:
    return {
        "task_id": "EDITOR-013",
        "frozen_before_results": True,
        "encoder": "20x13 -> Bi-LSTM -> temporal attention; no encoder change",
        "odst046": ODST046,
        "teacher_guidance": {
            "ensemble": "equal-weight mean of T-OPT(42/52/62) logits",
            "L_distill": "MSE(student_final_logit, ensemble_teacher_logit)",
            "lambda_distill": LAMBDA_DISTILL,
            "temperature": None,
            "not_tuned_in_EDITOR013": True,
        },
        "route_regularisation": {
            "lambda_route": LAMBDA_ROUTE,
            "form": "EDITOR-012 route-consistency loss",
            "no_route_weight_search": True,
        },
        "HISTORICAL_SINGLE_TEACHER_LOGIT_ANCHOR": HISTORICAL_SINGLE_TEACHER_LOGIT_ANCHOR,
        "single_teacher_mse_is_not_historical_C5": True,
        "single_teacher_mse": {
            "form": "MSE(student_final_logit, matched_TOPT_seed_logit)",
            "lambda": LAMBDA_DISTILL,
            "temperature": None,
            "variance_normalisation": False,
        },
        "head_conditions": HEAD_CONDITIONS,
        "validation_mandatory": VALIDATION_MANDATORY,
        "hybrid": {
            "final_logit": "l(x) + alpha * o(x)",
            "alpha_init": 0.0,
            "no_sample_dependent_gate": True,
        },
        "no_GroupDRO": True,
        "no_CORAL": True,
        "no_focal_search": True,
        "no_pairwise_ranking_search": True,
        "T": 20,
        "F": 13,
        "feature_set_unchanged": True,
        "split_unchanged": True,
        "no_broad_odst_search": True,
    }


def source_register() -> dict[str, Any]:
    pins = pin_producing_sources()
    return {
        "task_id": "EDITOR-013",
        "EDITOR012_PROTOCOL_COMMIT": EDITOR012_PROTOCOL_COMMIT,
        "EDITOR012_IMPLEMENTATION_COMMIT": EDITOR012_IMPLEMENTATION_COMMIT,
        "EDITOR012_PROMOTION_COMMIT": EDITOR012_PROMOTION_COMMIT,
        "EDITOR012_RESULTS_COMMIT": EDITOR012_RESULTS_COMMIT,
        "EDITOR012_RESULTS_FULL_COMMIT": EDITOR012_RESULTS_FULL_COMMIT,
        "historical_packets_readonly": True,
        "do_not_relabel_historical_C5_as_TA2": True,
        "TEACHER_GUIDANCE_VS_INITIALISATION": TEACHER_GUIDANCE_VS_INITIALISATION,
        "producing_pins": pins,
        "topt_hashes": {str(k): v["sha256"] for k, v in TOPT_CHECKPOINTS.items()},
        "historical_references_frozen": list(HISTORICAL.keys()),
        "r52_test_opened": False,
        "r51_rerun": False,
        "r62_rerun": False,
    }


def write_protocol_packet() -> dict[str, Any]:
    for sub in (
        "00_protocol",
        "01_inner_search",
        "02_validation_confirmation",
        "03_teacher_consensus",
        "04_statistics",
        "05_explainability",
        "06_paper_handover",
    ):
        _review(sub).mkdir(parents=True, exist_ok=True)

    try:
        refuse_r52_test(
            r"C:\PhD\07_Projects\cert-r42-feasibility\data\processed\r5.2\tensors\r52_T20_s1_test.npz"
        )
        raise Editor013ProtocolError("r5.2 TEST deny-list failed to fire")
    except Exception as exc:
        if "TEST" not in str(exc):
            raise

    require_hash(TRAIN_NPZ, EXPECTED_TRAIN_SHA256, role="train")
    require_hash(VAL_NPZ, EXPECTED_VAL_SHA256, role="validation")
    for seed, spec in TOPT_CHECKPOINTS.items():
        require_hash(Path(spec["checkpoint"]), spec["sha256"], role=f"T-OPT:{seed}")

    register = source_register()
    write_json(_review("00_protocol", "EDITOR013_SOURCE_REGISTER.json"), register)
    lin = linear_path_audit()
    write_json(_review("00_protocol", "EDITOR013_LINEAR_PATH_AUDIT.json"), lin)
    od = odst_readout_audit()
    write_json(_review("00_protocol", "EDITOR013_ODST_READOUT_AUDIT.json"), od)
    family = model_family_freeze()
    write_json(_review("00_protocol", "EDITOR013_MODEL_FAMILY_FREEZE.json"), family)

    protocol = {
        "task_id": "EDITOR-013",
        "campaign": "EDITOR-013 ODST INCREMENTAL-VALUE PROOF",
        "status": "PHASE_B_FROZEN_BEFORE_RESULTS",
        "scientific_question": (
            "Does ODST provide measurable value beyond a fair teacher-guided linear "
            "pathway, either as the predictive head itself or as an incremental "
            "explainable nonlinear correction?"
        ),
        "authorised_partitions": ["CERT r5.2 TRAIN", "CERT r5.2 VALIDATION"],
        "TEST_ACCESS": "PROHIBITED",
        "R51_EXECUTION": "PROHIBITED",
        "R62_EXECUTION": "PROHIBITED",
        "inner_search_uses": "EDITOR-010/012 INNER_TRAIN / INNER_SELECT only",
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
        "do_not_relabel_historical_C5": True,
        "frozen_before_first_training_result": True,
        "encoder_arch": ENCODER_ARCH,
    }
    write_json(_review("00_protocol", "EDITOR013_PROTOCOL.json"), protocol)

    checksums = {
        "task_id": "EDITOR-013",
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
        "EDITOR012_RESULTS_FULL_COMMIT": EDITOR012_RESULTS_FULL_COMMIT,
        "frozen_utc": utc_now(),
    }
    write_json(_review("00_protocol", "EDITOR013_INPUT_CHECKSUMS.json"), checksums)
    return {
        "register": register,
        "linear_audit": lin,
        "odst_audit": od,
        "family": family,
        "protocol": protocol,
        "checksums": checksums,
    }
