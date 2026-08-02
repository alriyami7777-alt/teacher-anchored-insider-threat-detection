"""Protocol constants for bounded end-to-end refinement micro-runs."""

from __future__ import annotations

from typing import Any

SEEDS_SCREENING = (42,)
SEEDS_CONFIRMATION = (52, 62)
MAX_SEED42_RUNS = 4  # T0, T2, T1, optional T3
MAX_TOTAL_RUNS = 6
MAX_EPOCHS = 5
BATCH_SIZE = 1024
POS_WEIGHT_MULT = 0.25
LR_ODST = 3e-4
LR_ENCODER = 3e-5
LR_ATTENTION = 3e-5
GRAD_CLIP_T3 = 0.5
THRESHOLD_RULE = "maximum_validation_f1"
PRIMARY_METRIC = "pr_auc"
SEQUENCE_LENGTH = 20
N_FEATURES = 13
DIAGNOSTIC_VAL_SUBSET_SIZE = 256
DIAGNOSTIC_VAL_SUBSET_SEED = 42

# T2 schedule for single-layer Bi-LSTM encoder (preregistered; do not change post hoc).
T2_SCHEDULE: dict[int, dict[str, bool]] = {
    1: {"lstm": False, "attention": False, "odst": True},
    2: {"lstm": False, "attention": True, "odst": True},
    3: {"lstm": True, "attention": True, "odst": True},
    4: {"lstm": True, "attention": True, "odst": True},
    5: {"lstm": True, "attention": True, "odst": True},
}

PROBE_PROTOCOL: dict[str, Any] = {
    "optimiser": "adam",
    "learning_rate": 1e-3,
    "weight_decay": 1e-4,
    "epochs": 5,
    "batch_size": 1024,
    "pos_weight_mult": POS_WEIGHT_MULT,
    "seed": 42,
    "standardize": True,
    "primary_metric": PRIMARY_METRIC,
    "train_partition": "r42_T20_s1_train",
    "validation_partition": "r42_T20_s1_validation",
}

ADVANCEMENT = {
    "pr_auc_gate_a_delta": 0.01,
    "pr_auc_gate_b_tolerance": 0.005,
    "unused_leaf_max_worse_than_t0_pp": 5.0,
    "unused_leaf_improvement_pp": 10.0,
    "recall_tolerance_gate_b": 0.02,
}


def condition_configs() -> dict[str, dict[str, Any]]:
    return {
        "T0": {
            "name": "frozen_control",
            "schedule": "frozen_odst_only",
            "lr_lstm": 0.0,
            "lr_attention": 0.0,
            "lr_odst": LR_ODST,
            "grad_clip": None,
        },
        "T2": {
            "name": "gradual_unfreezing",
            "schedule": "t2_gradual",
            "lr_lstm": LR_ENCODER,
            "lr_attention": LR_ATTENTION,
            "lr_odst": LR_ODST,
            "grad_clip": None,
            "epoch_flags": T2_SCHEDULE,
        },
        "T1": {
            "name": "immediate_differential_e2e",
            "schedule": "immediate_all",
            "lr_lstm": LR_ENCODER,
            "lr_attention": LR_ATTENTION,
            "lr_odst": LR_ODST,
            "grad_clip": None,
        },
        "T3": {
            "name": "clipping_condition",
            "schedule": "immediate_all",
            "lr_lstm": LR_ENCODER,
            "lr_attention": LR_ATTENTION,
            "lr_odst": LR_ODST,
            "grad_clip": GRAD_CLIP_T3,
            "optional": True,
        },
    }
