"""Locked constants for read-only component latency audit."""

from __future__ import annotations

from pathlib import Path
from typing import Any

OUTPUT_REL = Path("outputs/objective2/r52_component_latency_audit_v1")
RECORDED_REL = Path("scripts/objective2_r52_component_latency_audit/recorded_results")
BRANCH = "objective2-r52-component-latency-audit"
BASE_COMMIT = "49b922616bc2ed1c428d39f27649a96a5d8188ce"

SEED = 42
BATCH_SIZES = (1, 32, 256)
WARMUP = 50
TIMED = 300

VAL_REL = Path("data/processed/r5.2/tensors/r52_T20_s1_validation.npz")
EXPECTED_VAL_SHA256 = "5ac2e7e8fbd50eb62638cdb8c9d444464e02ff2ea20ba55989c36926dd751a5c"
EXPECTED_VAL_SHAPE = (64000, 20, 13)

# Exact saved prior ablation latencies (seconds) — do not use swapped console narrative
PRIOR_ABLATION = {
    "latency_bs32_8tree_sec": 0.002502699993783608,
    "latency_bs32_16tree_sec": 0.0023308499876293354,
    "latency_reduction_8_vs_16": -0.07372847118705317,  # 8-tree slower by ~7.4%
    "note": "Saved CSV shows 8-tree slower than 16-tree at batch-32; not a 7.4% speedup.",
}

MODELS: dict[str, dict[str, Any]] = {
    "16tree": {
        "label": "teacher_anchored_16tree",
        "ckpt_rel": "read_only_evidence/r52_teacher_anchored_reproducibility_v1/seed42/best_student.pt",
        "expected_sha256": "2b6452698dd0da53f0229bc43040a877017ac9299b277f2f98c1d7ca64c1cc42",
        "node_n_trees": 8,
        "node_num_layers": 2,
        "M": 16,
    },
    "8tree": {
        "label": "teacher_anchored_8tree",
        "ckpt_rel": "read_only_evidence/r52_odst_8tree_ablation_v1/seed42/student/best_student.pt",
        "expected_sha256": "13673bc8c0d1185289f93e12a7b8d4b0b46d8be65937ef9f3debb4bee0339793",
        "node_n_trees": 4,
        "node_num_layers": 2,
        "M": 8,
    },
}

ARCHITECTURE_BASE: dict[str, Any] = {
    "input_dim": 13,
    "hidden_size": 64,
    "dropout": 0.2,
    "attention_dim": 64,
    "fusion_variant": "sparsemax_sigmoid_odst",
    "node_depth": 4,
    "node_tree_dim": 1,
    "node_temperature": 1.0,
    "node_dropout": 0.0,
    "leaf_init_std": 0.05,
    "gate_hidden_dim": 32,
}

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

STATUS_COMPLETE = "objective2_component_latency_audit_complete"
STATUS_LIMITS = "objective2_component_latency_audit_complete_with_limits"
STATUS_PROV = "objective2_component_latency_audit_blocked_provenance"
STATUS_PARITY = "objective2_component_latency_audit_blocked_clean_parity"
STATUS_INCOMPLETE = "objective2_component_latency_audit_incomplete"
STATUS_SAFETY = "objective2_component_latency_audit_stopped_safety_failure"

BOTTLENECK_ENCODER = "latency_dominated_by_shared_temporal_encoder"
BOTTLENECK_ODST = "latency_dominated_by_odst_head"
BOTTLENECK_OVERHEAD = "latency_dominated_by_framework_or_transfer_overhead"
BOTTLENECK_MIXED = "latency_bottleneck_mixed"
BOTTLENECK_UNVERIFIABLE = "latency_bottleneck_unverifiable"

PARITY_ATOL = 1e-5
