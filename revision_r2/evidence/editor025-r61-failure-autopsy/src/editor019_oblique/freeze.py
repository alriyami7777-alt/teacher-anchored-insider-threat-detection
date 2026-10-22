"""Protocol freeze writers. Must precede training results."""

from __future__ import annotations

from typing import Any

from editor012_rescue.producing import pin_producing_sources
from editor017_robustness.constants import AUTHORITATIVE_GAUSSIAN, AUTHORITATIVE_SOURCE_ABLATION
from editor018_cross_view.aggregate40 import audit_record

from .boost import prove_stagewise_freeze
from .capacity import select_tree_count
from .constants import (
    BASE_COMMIT,
    BATCH_SIZE,
    CONDITION_SPECS,
    DIRECTIONAL_KS,
    EDITOR017_RESULTS_COMMIT,
    EDITOR018_RESULTS_COMMIT,
    ENSEMBLE_CACHE,
    EXPECTED_INNER_SELECT_N,
    EXPECTED_INNER_SELECT_POS,
    EXPECTED_INNER_TRAIN_N,
    EXPECTED_INNER_TRAIN_POS,
    EXPECTED_TRAIN_SHA256,
    EXPECTED_USER_MAPPING_SHA256,
    EXPECTED_VAL_SHA256,
    F11_CHECKPOINTS,
    FACTORIAL,
    FROZEN_L1_MEAN_PR_AUC,
    FROZEN_TA2_MEAN_PR_AUC,
    GLOBAL_TOPK_PR_AUC_FAITHFULNESS,
    INNER_CONDITIONS,
    L1_CHECKPOINTS,
    LAMBDA_TEACHER,
    LOCKED_AGG_FEATURES,
    LR_BRANCH,
    MAX_EPOCHS,
    NEW_TREE_FAMILIES,
    NOISE_LEVELS,
    ODST40_SPEC,
    PATIENCE,
    PRIMARY_SEEDS,
    PROMOTION_MARGIN,
    SCREENING_SEED,
    SO_ODST40_SPEC,
    SOURCE_CHANNELS,
    SUMMARY_DIM,
    TEACHER_GUIDANCE_VS_INITIALISATION,
    TOPT_CHECKPOINTS,
    XGB40_EXPECTED_SHA256,
    XGB40_PATH,
    XGB_TRIGGER_MLP_BAND,
    XGB_TRIGGER_ODST_MARGIN,
)
from .geometry import audit_current_odst_geometry
from .io_util import write_json
from .models import prove_function_preserving
from .safety import REVIEW_ROOT, TRAIN_NPZ, VAL_NPZ, sha256_file, utc_now


def _rev(*parts: str):
    return REVIEW_ROOT.joinpath(*parts)


def write_protocol_packet() -> dict[str, Any]:
    for name in (
        "00_protocol",
        "01_inner",
        "02_xgb_teacher",
        "03_validation",
        "04_statistics",
        "05_explainability",
        "06_robustness",
        "07_editor_response",
        "08_paper_handover",
    ):
        _rev(name).mkdir(parents=True, exist_ok=True)

    pins = pin_producing_sources()
    geom = audit_current_odst_geometry()
    write_json(_rev("00_protocol", "EDITOR019_ODST_GEOMETRY_AUDIT.json"), geom)

    cap = select_tree_count()
    write_json(_rev("00_protocol", "EDITOR019_CAPACITY_MATCH.json"), cap)
    n_trees = int(cap["CAPACITY_MATCHED_TREE_COUNT"])

    proofs = {}
    for fam in ("MLP40", "ODST40", "SO-ODST40", "SO-DTE40", "BSO-DTE40"):
        proofs[fam] = prove_function_preserving(fam, n_trees=n_trees if fam in {"SO-DTE40", "BSO-DTE40"} else None)
    proofs["BSO_STAGEWISE"] = prove_stagewise_freeze(n_trees=max(3, min(n_trees, 4)))
    agg = audit_record()

    protocol = {
        "task_id": "EDITOR-019",
        "campaign": "SPARSE SIGNED-OBLIQUE BOOSTED DIFFERENTIABLE TREE RESCUE",
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
        "teacher_weight": LAMBDA_TEACHER,
        "no_instance_wise_weighting_search": True,
        "no_attention_placement_search": True,
        "no_latent_odst_search": True,
        "no_uncertainty_gating_search": True,
        "no_tree_temperature_grid": True,
        "no_generic_loss_search": True,
        "no_sparsity_hyperparameter": True,
        "no_l1_regularisation_search": True,
        "no_projection_temperature_search": True,
        "no_shrinkage_grid": True,
        "no_boosting_round_search": True,
        "no_later_tree_count_search": True,
        "joint_finetune_predeclared": True,
        "EDITOR017_RESULTS_COMMIT": EDITOR017_RESULTS_COMMIT,
        "EDITOR018_RESULTS_COMMIT": EDITOR018_RESULTS_COMMIT,
        "BASE_COMMIT": BASE_COMMIT,
        "historical_packets": "READ_ONLY",
        "CURRENT_ODST_SPLIT_GEOMETRY": {
            "SIGNED": geom["CURRENT_SPLIT_SIGNED"],
            "OBLIVIOUS": geom["CURRENT_SPLIT_OBLIVIOUS"],
            "NODE_SPECIFIC": geom["CURRENT_SPLIT_NODE_SPECIFIC"],
        },
        "capacity": cap,
        "factorial": FACTORIAL,
        "so_odst40": dict(SO_ODST40_SPEC),
        "odst40": dict(ODST40_SPEC),
        "inner_conditions": list(INNER_CONDITIONS),
        "condition_specs": CONDITION_SPECS,
        "screening_seed": SCREENING_SEED,
        "primary_seeds": list(PRIMARY_SEEDS),
        "batch_size": BATCH_SIZE,
        "max_epochs": MAX_EPOCHS,
        "patience": PATIENCE,
        "lr_branch": LR_BRANCH,
        "lambda_teacher": LAMBDA_TEACHER,
        "promotion_margin": PROMOTION_MARGIN,
        "promotion_margin_may_be_lowered_after_results": False,
        "xgb_trigger": {
            "only_if_no_section_16_promotion": True,
            "best_so_dte_or_bso_minus_odst40_d": XGB_TRIGGER_ODST_MARGIN,
            "within_mlp40_d": XGB_TRIGGER_MLP_BAND,
            "artefact": str(XGB40_PATH),
            "expected_sha256": XGB40_EXPECTED_SHA256,
            "never_retrain": True,
        },
        "user_mapping": {
            "n_users": 2000,
            "windows_per_user": 32,
            "malicious_users": 31,
            "expected_sha256": EXPECTED_USER_MAPPING_SHA256,
        },
        "inner_split_expected": {
            "n_inner_train": EXPECTED_INNER_TRAIN_N,
            "n_inner_select": EXPECTED_INNER_SELECT_N,
            "n_inner_train_pos": EXPECTED_INNER_TRAIN_POS,
            "n_inner_select_pos": EXPECTED_INNER_SELECT_POS,
        },
        "function_preserving": proofs,
        "TEACHER_GUIDANCE_VS_INITIALISATION": TEACHER_GUIDANCE_VS_INITIALISATION,
        "GLOBAL_TOPK_PR_AUC_FAITHFULNESS": GLOBAL_TOPK_PR_AUC_FAITHFULNESS,
        "frozen_L1_mean_PR_AUC": FROZEN_L1_MEAN_PR_AUC,
        "frozen_TA2_mean_PR_AUC": FROZEN_TA2_MEAN_PR_AUC,
        "directional_ks": list(DIRECTIONAL_KS),
        "source_channels": list(SOURCE_CHANNELS),
        "noise_levels": list(NOISE_LEVELS),
        "source_ablation": AUTHORITATIVE_SOURCE_ABLATION,
        "gaussian_noise": AUTHORITATIVE_GAUSSIAN,
        "L1": {str(s): {"checkpoint": str(L1_CHECKPOINTS[s]["checkpoint"]), "sha256": L1_CHECKPOINTS[s]["sha256"]} for s in PRIMARY_SEEDS},
        "TA2": {str(s): {"checkpoint": str(F11_CHECKPOINTS[s]["checkpoint"]), "sha256": F11_CHECKPOINTS[s]["sha256"]} for s in PRIMARY_SEEDS},
        "TOPT": {str(s): {"checkpoint": str(TOPT_CHECKPOINTS[s]["checkpoint"]), "sha256": TOPT_CHECKPOINTS[s]["sha256"]} for s in PRIMARY_SEEDS},
        "ensemble_cache": {k: str(v) for k, v in ENSEMBLE_CACHE.items()},
        "producing_pins": pins,
        "utc": utc_now(),
    }
    write_json(_rev("00_protocol", "EDITOR019_PROTOCOL.json"), protocol)

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
        "same_40_order_as_editor018": list(LOCKED_AGG_FEATURES),
    }
    if checksums["train_file_sha256"] != EXPECTED_TRAIN_SHA256:
        raise RuntimeError("TRAIN tensor hash mismatch")
    if checksums["validation_file_sha256"] != EXPECTED_VAL_SHA256:
        raise RuntimeError("VALIDATION tensor hash mismatch")
    write_json(_rev("00_protocol", "EDITOR019_INPUT_CHECKSUMS.json"), checksums)
    return {
        "geometry": geom,
        "capacity": cap,
        "protocol": protocol,
        "checksums": checksums,
        "n_trees": n_trees,
        "proofs": proofs,
    }
