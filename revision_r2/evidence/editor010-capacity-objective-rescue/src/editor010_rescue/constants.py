"""Frozen EDITOR-010 constants, paths, ODST grid, and objective families."""

from __future__ import annotations

from pathlib import Path
from typing import Any

PROTOCOL_COMMIT = "bb9def6630386480e3396bd54e8da6c18727a834"
TASK_ID = "EDITOR-010"
SCREENING_SEED = 42
FULL_CONFIRMATION_SEEDS = (42, 52, 62)
PRIMARY_METRIC = "PR_AUC"

REVIEW_REL = Path("review/editor010_capacity_objective_teacher_rescue")
OUTPUT_REL = Path("outputs/editor010_capacity_objective_teacher_rescue")

TRAIN_NAME = "r52_T20_s1_train.npz"
VAL_NAME = "r52_T20_s1_validation.npz"
EXPECTED_TRAIN_SHA256 = "b268328d3bf2e98f712d1145958dabe175ce2c07a7c390da4b84a663317ebc2e"
EXPECTED_VAL_SHA256 = "5ac2e7e8fbd50eb62638cdb8c9d444464e02ff2ea20ba55989c36926dd751a5c"
EXPECTED_TRAIN_SHAPE = (788000, 20, 13)
EXPECTED_VAL_SHAPE = (64000, 20, 13)
EXPECTED_TRAIN_POS = 3957
EXPECTED_VAL_POS = 728

TENSOR_CANDIDATE_ROOTS = (
    Path(r"C:\PhD\07_Projects\cert-r42-feasibility\data\processed\r5.2\tensors"),
    Path(r"C:\PhD\07_Projects\cert-r52-teacher-anchored-reproducibility\data\processed\r5.2\tensors"),
)

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

INNER_TRAIN_FRACTION = 0.80
SEQUENCE_LENGTH = 20
FEATURE_DIM = 13
ATTENTION_DIM_OUT = 128

MAX_EPOCHS = 15
PATIENCE = 4
BATCH_SIZE = 1024
GRAD_CLIP_NORM = 1.0
POS_WEIGHT_MULT_O0 = 0.25
POS_WEIGHT_MULT_O1 = 1.0
LR_ATTENTION_LINEAR = 1e-3
LR_ODST_PRODUCING = 3e-4
MLP_HIDDEN = 64

PAIR_MAX_PER_BATCH = 512
PAIR_NEG_PER_POS = 8
LAMBDA_RANK_GRID = (0.1, 0.5, 1.0)
FOCAL_GAMMA = (1.0, 2.0)
ET1_LOGIT_DISTILL_WEIGHT = 0.5

BOOTSTRAP_SEED = 42
BOOTSTRAP_RESAMPLES = 2000

HEADROOM_PR_AUC_MARGIN = 0.010
OBJECTIVE_CONSISTENCY_MARGIN = 0.005

PRODUCING_ODST = dict(
    n_trees=8,
    depth=4,
    temperature=1.0,
    lr=3e-4,
    weight_decay=0.0,
    num_layers=2,
    dropout=0.0,
    leaf_init_std=0.05,
    choice_function="sparsemax_sigmoid",
    readout="canonical_tree_average",
)

ENCODER_ARCH = dict(
    input_dim=13,
    hidden_size=64,
    dropout=0.2,
    attention_dim=64,
    classification_head="linear",
    temporal_aggregation="attention",
)

C5_DENYLIST_SHA256 = {
    42: "a5a08dc24a89014fd1bb92c6c6342ed50511b33804e95246e480e90c4692b214",
    52: "3203455562ec6ff4018cc5cb3299bc2530bc8eff95aa523e6b7746f43731d971",
    62: "54f879d6b163185073ea586fa50a68edf89b603c269c6208c8b48156dccd4e22",
}

BASELINES: dict[str, dict[int, dict[str, Any]]] = {
    "teacher": {
        42: {
            "checkpoint": Path(r"C:\PhD\07_Projects\cert-r42-feasibility\outputs\objective2\r52_odst_confirmation\odst_seed42\best.pt"),
            "sha256": "783d0913f85d492ddacec83a274ba2d4f13ad25eaf1a34ebcc64a960bda8ff86",
            "kind": "attention_node",
        },
        52: {
            "checkpoint": Path(r"C:\PhD\07_Projects\cert-r42-feasibility\outputs\objective2\r52_odst_confirmation\odst_seed52\best.pt"),
            "sha256": "7273327495bbe463cfb3d50fa94c81c82de7b304370a816343046f559fc3d191",
            "kind": "attention_node",
        },
        62: {
            "checkpoint": Path(r"C:\PhD\07_Projects\cert-r42-feasibility\outputs\objective2\r52_odst_confirmation\odst_seed62\best.pt"),
            "sha256": "247d6e71353b49ea0a77a073a8606fbf35b88106faae7dae6ec53361621e9d92",
            "kind": "attention_node",
        },
    },
    "attention-linear": {
        42: {
            "checkpoint": Path(r"C:\PhD\07_Projects\cert-r42-feasibility\outputs\objective2\r52_odst_confirmation\attention_linear_seed42\best.pt"),
            "sha256": "b807a82343b432343b7e3cbc86ee76cba7011066827f3baa089aa78a02c02b53",
            "kind": "attention_linear",
        },
        52: {
            "checkpoint": Path(r"C:\PhD\07_Projects\cert-r42-feasibility\outputs\objective2\r52_odst_confirmation\attention_linear_seed52\best.pt"),
            "sha256": "5e5e2a136bedba3d3477d05c5b1215331cb97339b74003bcb60f8cb4885ba86c",
            "kind": "attention_linear",
        },
        62: {
            "checkpoint": Path(r"C:\PhD\07_Projects\cert-r42-feasibility\outputs\objective2\r52_odst_confirmation\attention_linear_seed62\best.pt"),
            "sha256": "4543c167fdab3b0376087731571f7b3bcecadd43f8ff05c6b5371f0073ba425a",
            "kind": "attention_linear",
        },
    },
    "C2": {
        42: {
            "checkpoint": Path(r"C:\PhD\07_Projects\cert-r42-feasibility\outputs\objective2\r52_teacher_anchoring_ablation_v1\C2\seed42\best_student.pt"),
            "sha256": "c5b8ab96a6f347afb85708857cef56b4a632f6092dfda9339ab9a3558daf863e",
            "kind": "attention_node",
        },
        52: {
            "checkpoint": Path(r"C:\PhD\07_Projects\cert-r42-feasibility\outputs\objective2\r52_teacher_anchoring_ablation_v1\C2\seed52\best_student.pt"),
            "sha256": "2215b36edd015f783de86ecb1b40cdd535fb6f082adc16a377574a24a8d0c22b",
            "kind": "attention_node",
        },
        62: {
            "checkpoint": Path(r"C:\PhD\07_Projects\cert-r42-feasibility\outputs\objective2\r52_teacher_anchoring_ablation_v1\C2\seed62\best_student.pt"),
            "sha256": "595a5e57ec78d6d34e2811609dc97514b0703cab807b7dffe873128a92ecc5c2",
            "kind": "attention_node",
        },
    },
    "C5_original_paper": {
        42: {
            "checkpoint": Path(r"C:\PhD\07_Projects\cert-r52-teacher-anchored-reproducibility\outputs\objective2\r52_teacher_anchored_reproducibility_v1\seed42\best_student.pt"),
            "sha256": "2b6452698dd0da53f0229bc43040a877017ac9299b277f2f98c1d7ca64c1cc42",
            "kind": "attention_node",
        },
        52: {
            "checkpoint": Path(r"C:\PhD\07_Projects\cert-r52-teacher-anchored-reproducibility\outputs\objective2\r52_teacher_anchored_reproducibility_v1\seed52\best_student.pt"),
            "sha256": "9c9d035fe81f54898dee4ecf4d2ecaf8423a21ecc3551793dc16d1980af1eb0d",
            "kind": "attention_node",
        },
        62: {
            "checkpoint": Path(r"C:\PhD\07_Projects\cert-r52-teacher-anchored-reproducibility\outputs\objective2\r52_teacher_anchored_reproducibility_v1\seed62\best_student.pt"),
            "sha256": "f5e8eb5260113a0aeabfb95ef198e1aa80022a26dfe91f3bf9262acbf5453ec9",
            "kind": "attention_node",
        },
    },
}

C2_PRODUCING_PR_AUC = {42: 0.9318417313473917, 52: 0.9241053967437384, 62: 0.9311900972327212}
C5_PRODUCING_PR_AUC = {42: 0.9335775615746195, 52: 0.9246065839750892, 62: 0.9356969431665507}
AL_REPLAY_PR_AUC = {42: 0.9378816467540203, 52: 0.9096510434894257, 62: 0.9458481407834319}
TEACHER_PRODUCING_PR_AUC = {42: 0.9334002969575846, 52: 0.9244539797126647, 62: 0.9347250477760537}


def _cfg(**kw: Any) -> dict[str, Any]:
    out = dict(PRODUCING_ODST)
    out.update(kw)
    return out


def _grid_key(c: dict[str, Any]) -> tuple:
    return (
        int(c["n_trees"]),
        int(c["depth"]),
        float(c["temperature"]),
        float(c["lr"]),
        float(c["weight_decay"]),
        float(c["dropout"]),
    )


def build_odst_grid() -> list[dict[str, Any]]:
    """Deterministic 48-or-fewer structured grid frozen before results."""
    raw: list[dict[str, Any]] = [_cfg()]
    for n in (4, 16):
        raw.append(_cfg(n_trees=n))
    for d in (3, 5):
        raw.append(_cfg(depth=d))
    for t in (0.5, 2.0):
        raw.append(_cfg(temperature=t))
    for lr in (1e-4, 1e-3):
        raw.append(_cfg(lr=lr))
    for wd in (1e-5, 1e-4):
        raw.append(_cfg(weight_decay=wd))
    for n, d in ((4, 3), (4, 5), (16, 3), (16, 5)):
        raw.append(_cfg(n_trees=n, depth=d))
    for n, t in ((4, 0.5), (4, 2.0), (16, 0.5), (16, 2.0)):
        raw.append(_cfg(n_trees=n, temperature=t))
    for n, lr in ((4, 1e-4), (4, 1e-3), (16, 1e-4), (16, 1e-3)):
        raw.append(_cfg(n_trees=n, lr=lr))
    for d, t in ((3, 0.5), (3, 2.0), (5, 0.5), (5, 2.0)):
        raw.append(_cfg(depth=d, temperature=t))
    for lr, t in ((1e-4, 0.5), (1e-4, 2.0), (1e-3, 0.5), (1e-3, 2.0)):
        raw.append(_cfg(lr=lr, temperature=t))
    for wd, n in ((1e-5, 4), (1e-5, 16), (1e-4, 4), (1e-4, 16)):
        raw.append(_cfg(weight_decay=wd, n_trees=n))
    for kw in (
        dict(n_trees=16, depth=5, temperature=2.0, lr=1e-3, weight_decay=0.0),
        dict(n_trees=16, depth=5, temperature=0.5, lr=1e-4, weight_decay=1e-4),
        dict(n_trees=4, depth=3, temperature=2.0, lr=1e-3, weight_decay=0.0),
        dict(n_trees=4, depth=3, temperature=0.5, lr=1e-4, weight_decay=1e-4),
        dict(n_trees=16, depth=4, temperature=2.0, lr=1e-3, weight_decay=1e-5),
        dict(n_trees=8, depth=5, temperature=2.0, lr=1e-3, weight_decay=0.0),
        dict(n_trees=8, depth=3, temperature=0.5, lr=1e-4, weight_decay=0.0),
        dict(n_trees=16, depth=3, temperature=1.0, lr=1e-3, weight_decay=0.0),
        dict(n_trees=4, depth=5, temperature=1.0, lr=3e-4, weight_decay=1e-5),
        dict(n_trees=8, depth=4, temperature=0.5, lr=1e-3, weight_decay=1e-4),
        dict(n_trees=8, depth=4, temperature=2.0, lr=1e-4, weight_decay=1e-5),
        dict(n_trees=4, depth=4, temperature=0.5, lr=1e-3, weight_decay=0.0),
        dict(dropout=0.1),
    ):
        raw.append(_cfg(**kw))
    seen: set[tuple] = set()
    uniq: list[dict[str, Any]] = []
    for cand in raw:
        k = _grid_key(cand)
        if k in seen:
            continue
        seen.add(k)
        uniq.append(cand)
    if len(uniq) > 48:
        raise RuntimeError(f"ODST grid size {len(uniq)} exceeds frozen maximum 48")
    out: list[dict[str, Any]] = []
    for i, cand in enumerate(uniq):
        rec = dict(cand)
        rec["candidate_id"] = f"ODST-{i:03d}"
        rec["is_producing_current"] = i == 0
        out.append(rec)
    return out


ODST_GRID = build_odst_grid()
ODST_GRID_BY_ID = {c["candidate_id"]: c for c in ODST_GRID}
