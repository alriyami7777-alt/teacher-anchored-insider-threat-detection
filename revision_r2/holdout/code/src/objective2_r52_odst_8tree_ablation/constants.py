"""Locked constants for post-primary reduced-capacity ODST 8-tree ablation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

OUTPUT_REL = Path("outputs/objective2/r52_odst_8tree_ablation_v1")
RECORDED_REL = Path("scripts/objective2_r52_odst_8tree_ablation/recorded_results")
BRANCH = "objective2-r52-odst-8tree-ablation"
BASE_COMMIT = "5109e3817e683941c76547cc214e7bd08ffe2477"

# Only change: trees per layer 8 → 4  ⇒  M = 2 × 4 = 8
NODE_NUM_LAYERS = 2
NODE_N_TREES = 4  # was 8 in the 16-unit forest
NODE_DEPTH = 4
M_TREES = NODE_NUM_LAYERS * NODE_N_TREES  # 8
assert M_TREES == 8

# Comparator: frozen 16-unit forest (2×8)
COMPARATOR_M = 16
COMPARATOR_NODE_N_TREES = 8

TENSOR_DIR_REL = Path("data/processed/r5.2/tensors")
TRAIN_NAME = "r52_T20_s1_train.npz"
VAL_NAME = "r52_T20_s1_validation.npz"
EXPECTED_TRAIN_SHA256 = "b268328d3bf2e98f712d1145958dabe175ce2c07a7c390da4b84a663317ebc2e"
EXPECTED_VAL_SHA256 = "5ac2e7e8fbd50eb62638cdb8c9d444464e02ff2ea20ba55989c36926dd751a5c"
EXPECTED_TRAIN_SHAPE = (788000, 20, 13)
EXPECTED_VAL_SHAPE = (64000, 20, 13)
EXPECTED_TRAIN_POS = 3957
EXPECTED_VAL_POS = 728

# Frozen Stage-A attention–linear encoders (unchanged)
ENCODERS: dict[int, dict[str, Any]] = {
    42: {
        "ckpt_rel": "outputs/objective2/r52_odst_confirmation/attention_linear_seed42/best.pt",
        "encoder_weight_sha256": "4b82de8a33d6c32ef576ac409f7a48ffc746dd07463d383b84229783beb8a7e1",
    },
    52: {
        "ckpt_rel": "outputs/objective2/r52_odst_confirmation/attention_linear_seed52/best.pt",
        "encoder_weight_sha256": "eda28da07f82417928225fb81717b096692f39d6a5ba255620866b378816775f",
    },
    62: {
        "ckpt_rel": "outputs/objective2/r52_odst_confirmation/attention_linear_seed62/best.pt",
        "encoder_weight_sha256": "c377eb422617083a25e3b6d2cd94730eae9a4446c373f69f38bcdbf1adc4a72a",
    },
}

# Frozen 16-tree teacher-anchored students (read-only comparator)
COMPARATOR_16: dict[int, dict[str, Any]] = {
    42: {
        "ckpt_rel": "read_only_evidence/r52_teacher_anchored_reproducibility_v1/seed42/best_student.pt",
        "expected_sha256": "2b6452698dd0da53f0229bc43040a877017ac9299b277f2f98c1d7ca64c1cc42",
        "pr_auc": 0.9335775615746195,
        "f1": 0.9200863930885529,
        "threshold": 0.56,
        "fp": 22.0,
        "fn": 89.0,
        "unused_leaves_pct": 44.53125,
        "latency_bs32_sec": 0.0023308499876293354,
    },
    52: {
        "ckpt_rel": "read_only_evidence/r52_teacher_anchored_reproducibility_v1/seed52/best_student.pt",
        "expected_sha256": "9c9d035fe81f54898dee4ecf4d2ecaf8423a21ecc3551793dc16d1980af1eb0d",
        "pr_auc": 0.9246065839750892,
        "f1": 0.9075144508670521,
        "threshold": 0.85,
        "fp": 28.0,
        "fn": 100.0,
        "unused_leaves_pct": 60.15625,
        "latency_bs32_sec": None,  # measured live if needed
    },
    62: {
        "ckpt_rel": "read_only_evidence/r52_teacher_anchored_reproducibility_v1/seed62/best_student.pt",
        "expected_sha256": "f5e8eb5260113a0aeabfb95ef198e1aa80022a26dfe91f3bf9262acbf5453ec9",
        "pr_auc": 0.9356969431665507,
        "f1": 0.9015471167369902,
        "threshold": 0.55,
        "fp": 53.0,
        "fn": 87.0,
        "unused_leaves_pct": 45.3125,
        "latency_bs32_sec": None,
    },
}

# Identical training protocol (except tree count)
MAX_EPOCHS = 15
PATIENCE = 4
BATCH_SIZE = 1024
POS_WEIGHT_MULT = 0.25
STAGE_B_LR = 3e-4
LR_ODST = 3e-4
LR_ENCODER = 3e-5
LR_ATTENTION = 3e-5
GRAD_CLIP_NORM = 1.0
LOGIT_CONSISTENCY_WEIGHT = 0.5
ROUTE_CONSISTENCY_WEIGHT = 0.5
NODE_AUX_WEIGHT = 0.0
LINEAR_AUX_WEIGHT = 0.0
RESIDUAL_PENALTY_WEIGHT = 1e-3
ANTI_COLLAPSE_WEIGHT = 1e-3

ARCHITECTURE: dict[str, Any] = {
    "input_dim": 13,
    "hidden_size": 64,
    "dropout": 0.2,
    "attention_dim": 64,
    "fusion_variant": "sparsemax_sigmoid_odst",
    "node_num_layers": NODE_NUM_LAYERS,
    "node_n_trees": NODE_N_TREES,
    "node_depth": NODE_DEPTH,
    "node_tree_dim": 1,
    "node_temperature": 1.0,
    "node_dropout": 0.0,
    "leaf_init_std": 0.05,
    "gate_hidden_dim": 32,
}

# Seed-42 viability margins vs frozen 16-tree student
PR_AUC_MAX_DROP = 0.010
F1_MAX_DROP = 0.020
LATENCY_MIN_REDUCTION = 0.25  # batch-32 at least 25% lower
FP_CATASTROPHIC_MULT = 3.0
FN_CATASTROPHIC_MULT = 3.0
UNUSED_LEAVES_MAX_WORSE_PP = 10.0

# Explanation fidelity (reference-centred)
FIDELITY_K = (1, 3, 5)
N_BOOTSTRAP = 2000
N_BOOTSTRAP_MAX = 5000
BOOTSTRAP_SEED = 2026
RANDOM_CTRL_SEED = 20260725
N_RANDOM_CONTROLS = 12
MIN_K_PASS = 2  # at least two of three k, including k=3

SEEDS_ORDER = (42, 52, 62)
PRIMARY_SEED = 42

FORBIDDEN_PATH_MARKERS = (
    "r52_t20_s1_test",
    "r5.2_test",
    "r52_test",
    "/test.npz",
    "r42_t20_s1_test",
    "later-development",
    "later_development",
    "r6.2",
    "r62",
    "processed/r6.2",
)

STATUS_MULTI_SUPPORTED = "objective2_odst_8tree_multiseed_supported"
STATUS_MULTI_LIMITS = "objective2_odst_8tree_multiseed_supported_with_limits"
STATUS_SEED42_FAIL = "objective2_odst_8tree_seed42_failed_viability"
STATUS_MULTI_NOT = "objective2_odst_8tree_multiseed_not_supported"
STATUS_GPU = "objective2_odst_8tree_prepared_gpu_blocked"
STATUS_PROV = "objective2_odst_8tree_blocked_provenance"
STATUS_INCOMPLETE = "objective2_odst_8tree_incomplete"
STATUS_SAFETY = "objective2_odst_8tree_stopped_safety_failure"
