"""Frozen EDITOR-011 identities, paths, and historical references."""

from __future__ import annotations

from pathlib import Path
from typing import Any

TASK_ID = "EDITOR-011"
SEEDS = (42, 52, 62)
PRIMARY_METRIC = "PR_AUC"

REVIEW_REL = Path("review/editor011_matched_route_confirmation")
OUTPUT_REL = Path("outputs/editor011_matched_route_confirmation")

TRAIN_NAME = "r52_T20_s1_train.npz"
VAL_NAME = "r52_T20_s1_validation.npz"
EXPECTED_TRAIN_SHAPE = (788000, 20, 13)
EXPECTED_VAL_SHAPE = (64000, 20, 13)
EXPECTED_TRAIN_POS = 3957
EXPECTED_VAL_POS = 728

SEQUENCE_LENGTH = 20
FEATURE_DIM = 13
MAX_EPOCHS = 15
PATIENCE = 4
BATCH_SIZE = 1024
GRAD_CLIP_NORM = 1.0
POS_WEIGHT_MULT = 0.25
LR_ENCODER = 3e-5
LR_ATTENTION = 3e-5
LR_ODST = 1e-3
WEIGHT_DECAY = 0.0

LAMBDA_ROUTE_R2 = 0.5
LAMBDA_LOGIT_R2 = 0.0
LAMBDA_ROUTE_C2 = 0.0
LAMBDA_LOGIT_C2 = 0.0
LAMBDA_ROUTE_TEACHER = 0.0
LAMBDA_LOGIT_TEACHER = 0.0

BOOTSTRAP_SEED = 42
BOOTSTRAP_RESAMPLES = 2000

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

ATTENTION_LINEAR = {
    42: {
        "checkpoint": Path(
            r"C:\PhD\07_Projects\cert-r42-feasibility\outputs\objective2\r52_odst_confirmation\attention_linear_seed42\best.pt"
        ),
        "sha256": "b807a82343b432343b7e3cbc86ee76cba7011066827f3baa089aa78a02c02b53",
    },
    52: {
        "checkpoint": Path(
            r"C:\PhD\07_Projects\cert-r42-feasibility\outputs\objective2\r52_odst_confirmation\attention_linear_seed52\best.pt"
        ),
        "sha256": "5e5e2a136bedba3d3477d05c5b1215331cb97339b74003bcb60f8cb4885ba86c",
    },
    62: {
        "checkpoint": Path(
            r"C:\PhD\07_Projects\cert-r42-feasibility\outputs\objective2\r52_odst_confirmation\attention_linear_seed62\best.pt"
        ),
        "sha256": "4543c167fdab3b0376087731571f7b3bcecadd43f8ff05c6b5371f0073ba425a",
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
    },
}
