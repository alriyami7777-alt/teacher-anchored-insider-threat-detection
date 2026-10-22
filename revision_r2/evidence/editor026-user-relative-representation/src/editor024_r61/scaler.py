"""Frozen r5.2 TRAIN scaler. Transform only. Never fit on r6.1."""

from __future__ import annotations

from typing import Any

import numpy as np

from editor006b_harness.input_bundle import apply_persisted_scaler, load_persisted_scaler
from editor006b_harness.safety import EXPECTED_SCALER_SHA256

from .constants import FEATURE_ORDER, SCALER_JSON_REL, repo_root
from .safety import Editor024Blocked, sha256_file

SCALER_SOURCE = "R52_TRAIN"


def load_r52_train_scaler() -> dict[str, Any]:
    path = repo_root() / SCALER_JSON_REL
    observed = sha256_file(path)
    if observed != EXPECTED_SCALER_SHA256:
        raise Editor024Blocked(
            f"SCALER_GATE = FAIL expected={EXPECTED_SCALER_SHA256} observed={observed}"
        )
    loaded = load_persisted_scaler(path)
    features = tuple(loaded["obj"]["features"])
    if features != FEATURE_ORDER:
        raise Editor024Blocked(f"scaler feature order {features} != {FEATURE_ORDER}")
    mean = np.asarray(loaded["mean"], dtype=np.float64)
    scale = np.asarray(loaded["scale"], dtype=np.float64)
    scale = np.where(scale == 0.0, 1.0, scale)
    return {
        "path": str(path),
        "sha256": observed,
        "mean": mean,
        "scale": scale,
        "obj": loaded["obj"],
        "SCALER_SOURCE": SCALER_SOURCE,
        "TARGET_SCALER_FIT": "NO",
        "n_features": 13,
    }


def transform_only(raw: np.ndarray, scaler: dict[str, Any]) -> np.ndarray:
    """Apply the frozen r5.2 TRAIN scaler. Does not estimate any r6.1 statistic."""
    return apply_persisted_scaler(raw, scaler["mean"], scaler["scale"])
