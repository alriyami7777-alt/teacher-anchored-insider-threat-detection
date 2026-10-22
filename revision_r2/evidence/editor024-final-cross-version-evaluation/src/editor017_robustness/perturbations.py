"""Hash-gated wrappers around the recovered authoritative Objective-3 implementations.

Chosen BEFORE any model result is viewed:

* source ablation = paper-style inverse-scale raw-zero with the frozen r5.2
  TRAIN scaler (EDITOR006A). This is CONTROLLED_SOURCE_CHANNEL_ABLATION.
* Gaussian noise = ``gaussian_noise_continuous`` via ``apply_paired_perturbation``
  at historical levels 0.05 / 0.10 / 0.20 and perturbation seed 101.

Do not mix scaled-space zeroing or additive-all-feature noise into these paths.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from objective3_missing_source_robustness import apply_missing_source_condition
from objective3_perturbations import apply_paired_perturbation

from .constants import (
    AUTHORITATIVE_GAUSSIAN,
    AUTHORITATIVE_SOURCE_ABLATION,
    CONTROLLED_GAUSSIAN_INPUT_NOISE,
    CONTROLLED_SOURCE_CHANNEL_ABLATION,
    EXPECTED_SCALER_JSON_SHA256,
    NOISE_LEVELS,
    NOISE_PERTURBATION_SEED,
    NOISE_SCENARIO,
    SAFE_FEATURES,
    SCALER_ID,
    SCALER_JSON,
    SOURCE_CHANNELS,
    SOURCE_CONDITIONS,
)
from .safety import Editor017Blocked, Editor017ProtocolError, require_hash, sha256_file


def load_r52_train_scaler() -> dict[str, Any]:
    path = Path(SCALER_JSON)
    require_hash(path, EXPECTED_SCALER_JSON_SHA256, role="r52_train_scaler")
    data = json.loads(path.read_text(encoding="utf-8"))
    feats = list(data["features"])
    if feats != list(SAFE_FEATURES):
        raise Editor017ProtocolError(f"scaler feature order mismatch: {feats}")
    if data.get("scaler_id") != SCALER_ID:
        raise Editor017ProtocolError(f"unexpected scaler_id {data.get('scaler_id')}")
    if str(data.get("dataset_fitted_on", "")).upper().find("VALIDATION") >= 0:
        raise Editor017Blocked("scaler must be TRAIN-only")
    return {
        "mean": np.asarray(data["mean"], dtype=np.float64),
        "scale": np.asarray(data["scale"], dtype=np.float64),
        "path": str(path),
        "sha256": EXPECTED_SCALER_JSON_SHA256,
        "scaler_id": SCALER_ID,
        "features": feats,
    }


def apply_source_ablation(x: np.ndarray, source: str, scaler: dict[str, Any]) -> np.ndarray:
    if source not in SOURCE_CHANNELS:
        raise Editor017Blocked(f"source {source!r} is not in the frozen five-channel list")
    condition = f"without_{source}"
    if condition not in SOURCE_CONDITIONS:
        raise Editor017Blocked(f"unauthorised source condition {condition}")
    out = apply_missing_source_condition(x, condition, scaler)
    return np.asarray(out, dtype=np.float32)


def apply_gaussian_noise(x: np.ndarray, level: float) -> np.ndarray:
    if float(level) not in NOISE_LEVELS:
        raise Editor017Blocked(f"unauthorised noise level {level}; frozen={NOISE_LEVELS}")
    out = apply_paired_perturbation(
        x,
        NOISE_SCENARIO,
        float(level),
        perturbation_seed=NOISE_PERTURBATION_SEED,
    )
    return np.asarray(out, dtype=np.float32)


def perturbation_module_hashes(repo_root: Path) -> dict[str, str]:
    src = repo_root / "src"
    return {
        "objective3_missing_source_robustness.py": sha256_file(
            src / "objective3_missing_source_robustness.py"
        ),
        "objective3_perturbations.py": sha256_file(src / "objective3_perturbations.py"),
        "EDITOR006A_SCALER.json": sha256_file(SCALER_JSON),
    }


def protocol_lock() -> dict[str, Any]:
    return {
        "source_ablation": {
            **AUTHORITATIVE_SOURCE_ABLATION,
            "terminology": CONTROLLED_SOURCE_CHANNEL_ABLATION,
        },
        "gaussian_noise": {
            **AUTHORITATIVE_GAUSSIAN,
            "terminology": CONTROLLED_GAUSSIAN_INPUT_NOISE,
        },
        "rejected_mixins": [
            "scaled_space_zero_ablation_used_only_as_r52_fallback_when_scaler_unverified",
            "additive_all_feature_gaussian_from_value_audit_and_tradeoff",
            "paper_r42_scaler_must_not_be_applied_to_r52_tensors",
        ],
        "severities_frozen_before_results": True,
        "source_list_frozen_before_results": True,
        "validation_derived_noise_parameter": False,
        "validation_derived_source_selection": False,
        "labels_unchanged": True,
    }
