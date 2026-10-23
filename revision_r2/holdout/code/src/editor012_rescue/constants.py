"""Frozen EDITOR-012 identities. No architecture or dataset search."""

from __future__ import annotations

from pathlib import Path
from typing import Any

TASK_ID = "EDITOR-012"
PRIMARY_SEEDS = (42, 52, 62)
SCREENING_SEED = 42
EXTENDED_SEEDS = (72, 82, 92, 102, 112, 122, 132)
ALL_STABILITY_SEEDS = PRIMARY_SEEDS + EXTENDED_SEEDS
PRIMARY_METRIC = "PR_AUC"

REVIEW_REL = Path("review/editor012_teacher_anchor_rescue")
OUTPUT_REL = Path("outputs/editor012_teacher_anchor_rescue")

EDITOR009_RESULTS_COMMIT = "0182685656ec99fe2edcda2d00179a7400db9d06"
EDITOR010_RESULTS_COMMIT = "3c5ac01d6739df91f50dcc3ba0258a019dcb3119"
EDITOR011_RESULTS_COMMIT = "65214bdeb51f9a04925be41d3b4c778de75cf088"
BASE_COMMIT = "cde793de9135c8d4f6491d204f586ce8e00c3e0d"

EDITOR010_WORKTREE = Path(r"C:\PhD\07_Projects\teacher-anchored-insider-threat-detection-editor010")
EDITOR011_WORKTREE = Path(r"C:\PhD\07_Projects\teacher-anchored-insider-threat-detection-editor011")
EDITOR009_WORKTREE = Path(r"C:\PhD\07_Projects\teacher-anchored-insider-threat-detection")

TRAIN_NAME = "r52_T20_s1_train.npz"
VAL_NAME = "r52_T20_s1_validation.npz"
EXPECTED_TRAIN_SHA256 = "b268328d3bf2e98f712d1145958dabe175ce2c07a7c390da4b84a663317ebc2e"
EXPECTED_VAL_SHA256 = "5ac2e7e8fbd50eb62638cdb8c9d444464e02ff2ea20ba55989c36926dd751a5c"
EXPECTED_TRAIN_SHAPE = (788000, 20, 13)
EXPECTED_VAL_SHAPE = (64000, 20, 13)
EXPECTED_TRAIN_POS = 3957
EXPECTED_VAL_POS = 728
EXPECTED_INNER_TRAIN_N = 622000
EXPECTED_INNER_SELECT_N = 128000
EXPECTED_INNER_TRAIN_POS = 2457
EXPECTED_INNER_SELECT_POS = 1214
EXPECTED_INNER_DROPPED = 38000
EXPECTED_VAL_USERS = 2000
EXPECTED_VAL_WINDOWS_PER_USER = 32
EXPECTED_VAL_MALICIOUS_USERS = 31
EXPECTED_USER_MAPPING_SHA256 = "851385f9c926cf945b3c74b5c9442e3ccb94cf1d9dabb98106a29cbfea01c5c0"

SEQUENCE_LENGTH = 20
FEATURE_DIM = 13
INNER_TRAIN_FRACTION = 0.80
MAX_EPOCHS = 15
PATIENCE = 4
BATCH_SIZE = 1024
GRAD_CLIP_NORM = 1.0
POS_WEIGHT_MULT = 0.25
LR_ENCODER = 3e-5
LR_ATTENTION = 3e-5
LR_ODST = 1e-3
WEIGHT_DECAY = 0.0

# Frozen ET1 predictive teacher-anchor (EDITOR-010 producing artefacts).
ET1_LOGIT_DISTILL_WEIGHT = 0.5
ET1_TEMPERATURE = None  # logit-level MSE; no softened KL
ET1_EQUAL_WEIGHT = True
ET1_ROUTE_ANCHOR = False
LAMBDA_ROUTE = 0.5
LAMBDA_HISTORICAL_SINGLE_TEACHER_LOGIT = 0.0  # retired; must stay 0

BOOTSTRAP_SEED = 42
BOOTSTRAP_RESAMPLES = 2000
PROMOTION_MARGIN = 0.001

SAFE_FEATURES = (
    "total_events",
    "logon_count",
    "device_count",
    "file_count",
    "email_count",
    "http_count",
    "active_duration_minutes",
    "has_logon_activity",
    "has_device_activity",
    "has_file_activity",
    "has_email_activity",
    "has_http_activity",
    "is_active_day",
)

ODST046: dict[str, Any] = dict(
    n_trees=4,
    depth=4,
    temperature=0.5,
    lr=1e-3,
    weight_decay=0.0,
    num_layers=2,
    dropout=0.0,
    leaf_init_std=0.05,
    choice_function="sparsemax_sigmoid",
    readout="canonical_tree_average",
    candidate_id="ODST-046",
    tree_dim=1,
    fusion_variant="sparsemax_sigmoid_odst",
)

ENCODER_ARCH: dict[str, Any] = dict(
    input_dim=13,
    hidden_size=64,
    dropout=0.2,
    attention_dim=64,
    fusion_variant="sparsemax_sigmoid_odst",
    node_num_layers=2,
    node_n_trees=4,
    node_depth=4,
    node_tree_dim=1,
    node_temperature=0.5,
    node_dropout=0.0,
    leaf_init_std=0.05,
    gate_hidden_dim=32,
)

TOPT_CHECKPOINTS = {
    42: {
        "checkpoint": EDITOR011_WORKTREE
        / "outputs/editor011_matched_route_confirmation/T-OPT/seed42/best_teacher.pt",
        "sha256": "b007f48085ef42b146b22a0d5ace5bb9c8380874405622281a5903831599fb20",
        "validation_PR_AUC": 0.9423486577182849,
    },
    52: {
        "checkpoint": EDITOR011_WORKTREE
        / "outputs/editor011_matched_route_confirmation/T-OPT/seed52/best_teacher.pt",
        "sha256": "5b4c17e15a8f49ba8cf240c0092b893e6e665232967fafce8eb13e0650227f2a",
        "validation_PR_AUC": 0.9228451512846401,
    },
    62: {
        "checkpoint": EDITOR011_WORKTREE
        / "outputs/editor011_matched_route_confirmation/T-OPT/seed62/best_teacher.pt",
        "sha256": "24bf2efa2343e4aaf5f32871c0a9bffb3d511f345375ce754e9f081f82eac02c",
        "validation_PR_AUC": 0.9405909178207581,
    },
}

C2OPT_CHECKPOINTS = {
    42: {
        "checkpoint": EDITOR011_WORKTREE
        / "outputs/editor011_matched_route_confirmation/C2-OPT/seed42/best_student.pt",
        "sha256": "d64651d25e48b3bcd4cad7d107d3bc55a4c555a2827f3656a087624e94ac4baf",
        "validation_PR_AUC": 0.9443205892331505,
    },
    52: {
        "checkpoint": EDITOR011_WORKTREE
        / "outputs/editor011_matched_route_confirmation/C2-OPT/seed52/best_student.pt",
        "sha256": "f0eea90099ba7dd3e721efb930e367e868049c94f6542d5b2156d9fe469acb7e",
        "validation_PR_AUC": 0.9214711755922543,
    },
    62: {
        "checkpoint": EDITOR011_WORKTREE
        / "outputs/editor011_matched_route_confirmation/C2-OPT/seed62/best_student.pt",
        "sha256": "50512aa5392ee7f4d93dc5f84471fc1074baeb757ae9fb5b96caed141ee586da",
        "validation_PR_AUC": 0.9401799007272055,
    },
}

R2OPT_CHECKPOINTS = {
    42: {
        "checkpoint": EDITOR011_WORKTREE
        / "outputs/editor011_matched_route_confirmation/R2-OPT/seed42/best_student.pt",
        "sha256": "ecc7ec7c3b1628ffc2bbec62efbb006d867fcbefe577f556d058de79d161ba63",
        "validation_PR_AUC": 0.9471384496065599,
    },
    52: {
        "checkpoint": EDITOR011_WORKTREE
        / "outputs/editor011_matched_route_confirmation/R2-OPT/seed52/best_student.pt",
        "sha256": "917bce3a2c9e783791f01f3b642c1bdaa79ed0a2e7c402c04d3c0151e76915b1",
        "validation_PR_AUC": 0.9257403375052433,
    },
    62: {
        "checkpoint": EDITOR011_WORKTREE
        / "outputs/editor011_matched_route_confirmation/R2-OPT/seed62/best_student.pt",
        "sha256": "9e3e7d92de7ac30a48229127a0784ac7514f620359499a3c84b8e00e1a7670bc",
        "validation_PR_AUC": 0.9396079561231327,
    },
}

FACTORIAL = {
    "F00": {
        "condition": "F00_C2OPT",
        "alias": "C2-OPT",
        "ensemble_teacher_predictive_anchor": False,
        "route_anchor": False,
        "lambda_et1": 0.0,
        "lambda_route": 0.0,
        "historical_single_teacher_logit_anchor": False,
        "import_editor011": "C2-OPT",
    },
    "F10": {
        "condition": "F10_DOPT",
        "alias": "D-OPT",
        "ensemble_teacher_predictive_anchor": True,
        "route_anchor": False,
        "lambda_et1": ET1_LOGIT_DISTILL_WEIGHT,
        "lambda_route": 0.0,
        "historical_single_teacher_logit_anchor": False,
        "anchor_id": "A0",
    },
    "F01": {
        "condition": "F01_R2OPT",
        "alias": "R2-OPT",
        "ensemble_teacher_predictive_anchor": False,
        "route_anchor": True,
        "lambda_et1": 0.0,
        "lambda_route": LAMBDA_ROUTE,
        "historical_single_teacher_logit_anchor": False,
        "import_editor011": "R2-OPT",
    },
    "F11": {
        "condition": "F11_DROPT",
        "alias": "DR-OPT",
        "ensemble_teacher_predictive_anchor": True,
        "route_anchor": True,
        "lambda_et1": ET1_LOGIT_DISTILL_WEIGHT,
        "lambda_route": LAMBDA_ROUTE,
        "historical_single_teacher_logit_anchor": False,
        "anchor_id": "A0",
    },
}

ANCHOR_FORMULATIONS = {
    "A0": {
        "name": "frozen_ET1_equal_weight_logit_mse",
        "confidence_weight": False,
        "agreement_weight": False,
        "class_balanced_reduction": False,
        "simplicity_rank": 0,
    },
    "A1": {
        "name": "consensus_confidence_weighting",
        "confidence_weight": True,
        "agreement_weight": False,
        "class_balanced_reduction": False,
        "simplicity_rank": 1,
    },
    "A2": {
        "name": "ensemble_agreement_weighting",
        "confidence_weight": False,
        "agreement_weight": True,
        "class_balanced_reduction": False,
        "simplicity_rank": 1,
    },
    "A3": {
        "name": "class_balanced_ensemble_anchor",
        "confidence_weight": False,
        "agreement_weight": False,
        "class_balanced_reduction": True,
        "simplicity_rank": 1,
    },
    "A4": {
        "name": "confidence_plus_class_balance",
        "confidence_weight": True,
        "agreement_weight": False,
        "class_balanced_reduction": True,
        "simplicity_rank": 2,
    },
    "A5": {
        "name": "agreement_plus_class_balance",
        "confidence_weight": False,
        "agreement_weight": True,
        "class_balanced_reduction": True,
        "simplicity_rank": 2,
    },
}

HISTORICAL = {
    "Original_Teacher": {
        "mean_PR_AUC": 0.9308597983767313,
        "seeds": {42: 0.9334004808363426, 52: 0.924453959562666, 62: 0.9347249547311853},
    },
    "Original_C2": {
        "mean_PR_AUC": 0.9290457851613539,
        "seeds": {42: 0.9318418728771596, 52: 0.9241053910575397, 62: 0.9311900915493624},
        "paper_facing_mean": 0.929046,
    },
    "Original_C5": {
        "mean_PR_AUC": 0.9312938562868864,
        "seeds": {42: 0.933577847233109, 52: 0.9246065766655331, 62: 0.9356971449620174},
        "paper_facing_mean": 0.931294,
    },
    "Attention_linear": {
        "mean_PR_AUC": 0.9311180134363881,
        "seeds": {42: 0.9378754065901991, 52: 0.9096388064417844, 62: 0.9458398272771807},
        "paper_facing_mean": 0.931118,
    },
    "EDITOR009_R2": {
        "mean_PR_AUC": 0.9336159387038109,
        "seeds": {42: 0.9362682765673592, 52: 0.9276629748956063, 62: 0.9369165646484672},
        "paper_facing_mean": 0.933616,
    },
    "EDITOR010_P1": {
        "mean_PR_AUC": 0.9334244121760161,
        "seeds": {42: 0.9442589619072768, 52: 0.9093076134797793, 62: 0.9467066611409923},
    },
    "EDITOR010_P4_ET1": {
        "mean_PR_AUC": 0.939519755421061,
        "seeds": {42: 0.9433583258622973, 52: 0.9332850649053038, 62: 0.9419158754955818},
        "paper_facing_mean": 0.93952,
        "identity": "ODST-046 + equal-weight ensemble logit distillation + route anchoring OFF",
        "lambda_distill": 0.5,
        "temperature": None,
    },
    "EDITOR011_TOPT": {
        "mean_PR_AUC": 0.9352615756078944,
        "seeds": {42: 0.9423486577182849, 52: 0.9228451512846401, 62: 0.9405909178207581},
    },
    "EDITOR011_C2OPT": {
        "mean_PR_AUC": 0.9353238885175368,
        "seeds": {42: 0.9443205892331505, 52: 0.9214711755922543, 62: 0.9401799007272055},
    },
    "EDITOR011_R2OPT": {
        "mean_PR_AUC": 0.9374955810783120,
        "seeds": {42: 0.9471384496065599, 52: 0.9257403375052433, 62: 0.9396079561231327},
    },
}

ORIGINAL_SINGLE_TEACHER_LOGIT_ANCHOR = "RETIRED_AFTER_GRADIENT_CONFLICT_DIAGNOSIS"
