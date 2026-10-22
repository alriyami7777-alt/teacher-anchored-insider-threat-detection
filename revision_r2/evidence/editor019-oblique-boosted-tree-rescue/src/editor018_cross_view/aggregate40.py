"""Hash-gated authoritative 40-feature aggregation. Do not recreate from prose."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Any, Callable

import numpy as np
from sklearn.preprocessing import StandardScaler

from .constants import (
    AGGREGATE40_FUNCTION,
    AGGREGATE40_SOURCE,
    BINARY_AGGS,
    BINARY_FEATURES,
    EXPECTED_AGGREGATE40_SHA256,
    LOCKED_AGG_FEATURES,
    NUMERIC_AGGS,
    NUMERIC_FEATURES,
    STD_DEFINITION,
    SUMMARY_DIM,
)
from .safety import REPO_ROOT, Editor018Blocked, Editor018ProtocolError, sha256_bytes, sha256_file


def producer_path() -> Path:
    return REPO_ROOT / AGGREGATE40_SOURCE


def producer_sha256() -> str:
    observed = sha256_file(producer_path())
    if observed != EXPECTED_AGGREGATE40_SHA256:
        raise Editor018Blocked(
            f"40-feature producer hash mismatch expected={EXPECTED_AGGREGATE40_SHA256} observed={observed}"
        )
    return observed


def import_aggregate_common13_windows() -> Callable[[np.ndarray], tuple[np.ndarray, list[str]]]:
    producer_sha256()
    scripts = str(REPO_ROOT / "src" / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    from r52_locked_baselines.data import aggregate_common13_windows  # noqa: WPS433

    return aggregate_common13_windows


def aggregate40(X: np.ndarray) -> tuple[np.ndarray, list[str]]:
    fn = import_aggregate_common13_windows()
    feat, names = fn(np.asarray(X, dtype=np.float32))
    if list(names) != list(LOCKED_AGG_FEATURES):
        raise Editor018ProtocolError("aggregated feature order mismatch vs locked schema")
    if feat.shape[1] != SUMMARY_DIM:
        raise Editor018ProtocolError(f"expected 40 features; got {feat.shape[1]}")
    if feat.dtype != np.float32:
        feat = feat.astype(np.float32, copy=False)
    return feat, list(names)


def metadata_keys_only(
    user: np.ndarray,
    sequence_id: np.ndarray,
    start_date: np.ndarray,
    end_date: np.ndarray,
) -> dict[str, np.ndarray]:
    """Alignment keys. These must never enter predictive tensors."""
    return {
        "user": np.asarray(user).astype(str),
        "sequence_id": np.asarray(sequence_id).astype(str),
        "start_date": np.asarray(start_date).astype(str),
        "end_date": np.asarray(end_date).astype(str),
    }


def assert_no_metadata_in_features(X40: np.ndarray, meta: dict[str, np.ndarray]) -> None:
    if X40.ndim != 2 or X40.shape[1] != SUMMARY_DIM:
        raise Editor018ProtocolError(f"predictive 40-view shape {X40.shape} is invalid")
    if not np.issubdtype(X40.dtype, np.floating):
        raise Editor018ProtocolError("predictive 40-view must be floating")
    for key, values in meta.items():
        if values.dtype.kind in {"U", "S", "O"}:
            continue
        raise Editor018ProtocolError(f"metadata key {key} leaked a non-string array")


def fit_standard_scaler(X_fit: np.ndarray) -> StandardScaler:
    scaler = StandardScaler()
    scaler.fit(np.asarray(X_fit, dtype=np.float64))
    return scaler


def transform_standard(scaler: StandardScaler, X: np.ndarray) -> np.ndarray:
    return scaler.transform(np.asarray(X, dtype=np.float64)).astype(np.float32)


def scaler_payload(scaler: StandardScaler, *, fitted_on: str) -> dict[str, Any]:
    mean = np.asarray(scaler.mean_, dtype=np.float64)
    scale = np.asarray(scaler.scale_, dtype=np.float64)
    blob = np.concatenate([mean, scale]).tobytes()
    return {
        "class": "sklearn.preprocessing.StandardScaler",
        "fitted_on": fitted_on,
        "n_features": int(mean.size),
        "with_mean": True,
        "with_std": True,
        "mean_sha256": hashlib.sha256(mean.tobytes()).hexdigest(),
        "scale_sha256": hashlib.sha256(scale.tobytes()).hexdigest(),
        "state_sha256": hashlib.sha256(blob).hexdigest(),
        "n_fit_rows": int(getattr(scaler, "n_samples_seen_", 0)),
    }


def audit_record() -> dict[str, Any]:
    path = producer_path()
    return {
        "producing_implementation": {
            "source_path": str(path).replace("\\", "/"),
            "relative_path": str(AGGREGATE40_SOURCE).replace("\\", "/"),
            "function": AGGREGATE40_FUNCTION,
            "sha256": producer_sha256(),
            "recreated_from_prose": False,
        },
        "daily_numeric_features": list(NUMERIC_FEATURES),
        "daily_binary_features": list(BINARY_FEATURES),
        "numeric_aggregates": list(NUMERIC_AGGS),
        "binary_aggregates": list(BINARY_AGGS),
        "feature_names": list(LOCKED_AGG_FEATURES),
        "feature_order": list(LOCKED_AGG_FEATURES),
        "feature_count": SUMMARY_DIM,
        "exact_summary_formula": {
            "numeric": "for each of 7 numeric daily columns: sum, mean, max, std over T=20",
            "binary": "for each of 6 binary daily indicators: sum=active_days, mean=active_proportion over T=20",
            "std_definition": STD_DEFINITION,
            "std_ddof": 0,
        },
        "dtype": "float32",
        "producing_scaler_or_transformation": "none_beyond_aggregation",
        "neural_branch_transform": "StandardScaler fitted on authorised TRAIN partition only",
        "fitted_state_uses_train_only": True,
        "identifiers_enter_predictive_features": False,
    }


def alignment_keys_hash(meta: dict[str, np.ndarray]) -> str:
    blob = "\n".join(
        f"{u}|{s}|{a}|{b}"
        for u, s, a, b in zip(
            meta["user"], meta["sequence_id"], meta["start_date"], meta["end_date"], strict=True
        )
    )
    return sha256_bytes(blob.encode("utf-8"))
