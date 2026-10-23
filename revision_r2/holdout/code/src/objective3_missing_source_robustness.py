#!/usr/bin/env python3
"""CERT r4.2 missing-log-source / source-channel robustness helpers.

Intervention uses train-scaler absence values (raw zero → scaled −μ/σ), not
numerical zeroing of already-scaled channels. ``total_events`` and
``is_active_day`` are recomputed from remaining source counts.
``active_duration_minutes`` cannot be recomputed without event timestamps, so
single-source removals retain residual multi-source duration information and
the intervention is classified as ``source_channel_ablation_only``.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from objective3_locked_common import N_FEATURES, SAFE_FEATURES, SEQ_LEN, sha256_file

PROTOCOL_SEED = 20260724
EXPECTED_VAL_N = 31000
EXPECTED_VAL_MAL = 252
EXPECTED_COHORT_N = 484
EXPECTED_COHORT_SHA256 = (
    "a0fed0b123f01792d216c49231e64166dab6f4e8dc98a9dcda78b422a8f6d69a"
)
SCALER_REL_PATH = "outputs/tensors/r42_T20_s1_train_scaler_stats.json"

IDX_TOTAL = 0
IDX_DURATION = 6
IDX_ACTIVE = 12
SOURCE_COUNT_INDICES = {
    "logon": 1,
    "device": 2,
    "file": 3,
    "email": 4,
    "http": 5,
}
SOURCE_HAS_INDICES = {
    "logon": 7,
    "device": 8,
    "file": 9,
    "email": 10,
    "http": 11,
}
BEHAVIOURAL_SOURCES = ("logon", "device", "file", "email", "http")

CONDITIONS = (
    "baseline_unmodified",
    "without_logon",
    "without_device",
    "without_file",
    "without_email",
    "without_http",
    "without_all_behavioural_sources",
    "no_op_mask_control",
)

INTERVENTION_VALIDITY = "source_channel_ablation_only"


def load_scaler_stats(root: Path) -> dict[str, np.ndarray]:
    path = root / SCALER_REL_PATH
    data = json.loads(path.read_text(encoding="utf-8"))
    feats = list(data["features"])
    if feats != list(SAFE_FEATURES):
        raise ValueError(f"Scaler feature order mismatch: {feats}")
    return {
        "mean": np.asarray(data["mean"], dtype=np.float64),
        "scale": np.asarray(data["scale"], dtype=np.float64),
        "path": str(path),
        "sha256": sha256_file(path),
    }


def scaled_absence_values(scaler: dict[str, np.ndarray]) -> np.ndarray:
    """Transformed value of raw zero under the train StandardScaler."""
    return (-scaler["mean"] / scaler["scale"]).astype(np.float64)


def inverse_scale(x_scaled: np.ndarray, scaler: dict[str, np.ndarray]) -> np.ndarray:
    return x_scaled.astype(np.float64) * scaler["scale"] + scaler["mean"]


def forward_scale(x_raw: np.ndarray, scaler: dict[str, np.ndarray]) -> np.ndarray:
    return ((x_raw.astype(np.float64) - scaler["mean"]) / scaler["scale"]).astype(
        np.float32
    )


def sources_removed_for_condition(condition: str) -> tuple[str, ...]:
    if condition in ("baseline_unmodified", "no_op_mask_control"):
        return ()
    if condition == "without_all_behavioural_sources":
        return BEHAVIOURAL_SOURCES
    if condition.startswith("without_"):
        src = condition.replace("without_", "", 1)
        if src not in SOURCE_COUNT_INDICES:
            raise ValueError(f"Unknown source condition: {condition}")
        return (src,)
    raise ValueError(f"Unknown condition: {condition}")


def apply_missing_source_condition(
    x: np.ndarray,
    condition: str,
    scaler: dict[str, np.ndarray],
) -> np.ndarray:
    """Apply source-loss intervention. Returns a new float32 array; never mutates x."""
    x = np.asarray(x, dtype=np.float32)
    if x.ndim != 3 or x.shape[-1] != N_FEATURES:
        raise ValueError(f"Expected (N,T,{N_FEATURES}); got {x.shape}")
    if condition in ("baseline_unmodified", "no_op_mask_control"):
        return np.array(x, dtype=np.float32, copy=True)

    removed = sources_removed_for_condition(condition)
    raw = inverse_scale(x, scaler)
    for src in removed:
        ci = SOURCE_COUNT_INDICES[src]
        hi = SOURCE_HAS_INDICES[src]
        raw[:, :, ci] = 0.0
        raw[:, :, hi] = 0.0

    count_idxs = list(SOURCE_COUNT_INDICES.values())
    raw[:, :, IDX_TOTAL] = raw[:, :, count_idxs].sum(axis=-1)
    active = (raw[:, :, count_idxs].sum(axis=-1) > 0).astype(np.float64)
    raw[:, :, IDX_ACTIVE] = active
    # Duration: zero only when the day becomes inactive. Otherwise retain prior
    # raw duration (residual multi-source span) — documented validity limit.
    inactive = active < 0.5
    raw[:, :, IDX_DURATION] = np.where(inactive, 0.0, raw[:, :, IDX_DURATION])
    if condition == "without_all_behavioural_sources":
        raw[:, :, IDX_DURATION] = 0.0

    return forward_scale(raw, scaler)


def build_feature_mapping_rows(scaler: dict[str, np.ndarray]) -> list[dict[str, Any]]:
    abs_scaled = scaled_absence_values(scaler)
    rows = []
    meta = {
        0: ("total_events", "multi", "count", "sum of modality event counts", "high"),
        1: ("logon_count", "logon", "count", "daily logon event count", "high"),
        2: ("device_count", "device", "count", "daily device event count", "high"),
        3: ("file_count", "file", "count", "daily file event count", "high"),
        4: ("email_count", "email", "count", "daily email event count", "high"),
        5: ("http_count", "http", "count", "daily HTTP event count", "high"),
        6: (
            "active_duration_minutes",
            "multi/temporal",
            "continuous",
            "minute span first→last event across sources",
            "high",
        ),
        7: ("has_logon_activity", "logon", "binary", "1 if logon_count>0", "high"),
        8: ("has_device_activity", "device", "binary", "1 if device_count>0", "high"),
        9: ("has_file_activity", "file", "binary", "1 if file_count>0", "high"),
        10: ("has_email_activity", "email", "binary", "1 if email_count>0", "high"),
        11: ("has_http_activity", "http", "binary", "1 if http_count>0", "high"),
        12: (
            "is_active_day",
            "contextual/densify",
            "binary",
            "1 if any activity that calendar day",
            "high",
        ),
    }
    for i, name in enumerate(SAFE_FEATURES):
        _, source, ftype, definition, conf = meta[i]
        rule = "scaled_raw_zero_absence"
        if i == IDX_TOTAL:
            rule = "recompute_sum_remaining_source_counts_then_scale"
        elif i == IDX_DURATION:
            rule = "zero_if_day_inactive_else_retain_residual_span"
        elif i == IDX_ACTIVE:
            rule = "recompute_any_remaining_source_activity_then_scale"
        elif source in BEHAVIOURAL_SOURCES:
            rule = "set_raw_zero_then_scale_for_removed_source"
        rows.append(
            {
                "feature_index": i,
                "feature_name": name,
                "raw_definition": definition,
                "source_log": source,
                "transformation": "none_before_scaler",
                "scaler": "StandardScaler_train_only",
                "raw_value_representing_absence": 0.0,
                "transformed_value_representing_absence": float(abs_scaled[i]),
                "feature_type": ftype,
                "dependency_on_other_features_or_sources": (
                    "all_behavioural_sources"
                    if source.startswith("multi") or source.startswith("contextual")
                    else source
                ),
                "missing_source_replacement_rule": rule,
                "confidence_in_mapping": conf,
                "evidence_path": (
                    "scripts/objective3_locked_common.py::SAFE_FEATURES;"
                    "outputs/tensors/r42_T20_s1_train_scaler_stats.json;"
                    "scripts/create_sequence_tensors.py;"
                    "scripts/check_and_densify_user_day_intervals.py"
                ),
                "notes": (
                    "Scaled tensors already z-scored; absence is -mean/scale not 0.0"
                ),
                "scaler_mean": float(scaler["mean"][i]),
                "scaler_scale": float(scaler["scale"][i]),
            }
        )
    return rows


def build_dependency_matrix_rows() -> list[dict[str, Any]]:
    rows = []
    for i, name in enumerate(SAFE_FEATURES):
        deps = {
            "feature_index": i,
            "feature_name": name,
            "depends_logon": 0,
            "depends_device": 0,
            "depends_file": 0,
            "depends_email": 0,
            "depends_http": 0,
            "depends_temporal_context": 0,
            "depends_multiple_sources": 0,
        }
        if name in ("logon_count", "has_logon_activity"):
            deps["depends_logon"] = 1
        elif name in ("device_count", "has_device_activity"):
            deps["depends_device"] = 1
        elif name in ("file_count", "has_file_activity"):
            deps["depends_file"] = 1
        elif name in ("email_count", "has_email_activity"):
            deps["depends_email"] = 1
        elif name in ("http_count", "has_http_activity"):
            deps["depends_http"] = 1
        elif name == "total_events":
            for k in (
                "depends_logon",
                "depends_device",
                "depends_file",
                "depends_email",
                "depends_http",
                "depends_multiple_sources",
            ):
                deps[k] = 1
        elif name == "active_duration_minutes":
            deps["depends_temporal_context"] = 1
            deps["depends_multiple_sources"] = 1
            for k in (
                "depends_logon",
                "depends_device",
                "depends_file",
                "depends_email",
                "depends_http",
            ):
                deps[k] = 1
        elif name == "is_active_day":
            deps["depends_multiple_sources"] = 1
            deps["depends_temporal_context"] = 1
            for k in (
                "depends_logon",
                "depends_device",
                "depends_file",
                "depends_email",
                "depends_http",
            ):
                deps[k] = 1
        rows.append(deps)
    return rows


def intervention_action_for_feature(condition: str, feature_index: int) -> str:
    removed = set(sources_removed_for_condition(condition))
    name = SAFE_FEATURES[feature_index]
    if not removed:
        return "retain_unchanged"
    if name == "total_events":
        return "recomputed_from_remaining_raw_evidence"
    if name == "is_active_day":
        return "recomputed_from_remaining_raw_evidence"
    if name == "active_duration_minutes":
        if set(removed) == set(BEHAVIOURAL_SOURCES):
            return "assigned_valid_absence_value"
        return "retained_unchanged_with_residual_multi_source_span"
    for src, ci in SOURCE_COUNT_INDICES.items():
        if feature_index == ci and src in removed:
            return "assigned_valid_absence_value"
    for src, hi in SOURCE_HAS_INDICES.items():
        if feature_index == hi and src in removed:
            return "assigned_valid_absence_value"
    return "retain_unchanged"


def classify_intervention_validity() -> dict[str, Any]:
    return {
        "status": INTERVENTION_VALIDITY,
        "rationale": (
            "Per-source count/binary channels use documented scaled raw-zero absence; "
            "total_events and is_active_day are recomputed from remaining counts; "
            "active_duration_minutes cannot be reconstructed without event timestamps "
            "and retains residual multi-source information under single-source removal."
        ),
        "complete_missing_source_simulation": False,
        "channel_ablation_with_additive_recompute": True,
        "unresolved_derived_dependencies": ["active_duration_minutes"],
    }


def verify_cohort_manifest(path: Path, expected_sha: str = EXPECTED_COHORT_SHA256) -> dict[str, Any]:
    digest = sha256_file(path)
    if digest != expected_sha:
        raise ValueError(f"Cohort hash mismatch: {digest} != {expected_sha}")
    df = pd.read_csv(path)
    if len(df) != EXPECTED_COHORT_N:
        raise ValueError(f"Expected {EXPECTED_COHORT_N} cohort rows; got {len(df)}")
    mal = int((df.ground_truth == 1).sum())
    ben = int((df.ground_truth == 0).sum())
    if mal != 242 or ben != 242:
        raise ValueError(f"Expected 242/242; got {mal}/{ben}")
    n_users = int(df.user_id.nunique())
    if n_users != 151:
        raise ValueError(f"Expected 151 users; got {n_users}")
    return {
        "ok": True,
        "sha256": digest,
        "n": len(df),
        "malicious": mal,
        "benign": ben,
        "unique_users": n_users,
    }


def binary_classification_metrics(
    y_true: np.ndarray,
    probs: np.ndarray,
    preds: np.ndarray,
) -> dict[str, float]:
    from sklearn.metrics import (
        average_precision_score,
        brier_score_loss,
        log_loss,
        precision_recall_fscore_support,
    )

    y_true = np.asarray(y_true).astype(int)
    probs = np.asarray(probs, dtype=np.float64)
    preds = np.asarray(preds).astype(int)
    tp = int(((preds == 1) & (y_true == 1)).sum())
    tn = int(((preds == 0) & (y_true == 0)).sum())
    fp = int(((preds == 1) & (y_true == 0)).sum())
    fn = int(((preds == 0) & (y_true == 1)).sum())
    prec, rec, f1, _ = precision_recall_fscore_support(
        y_true, preds, average="binary", zero_division=0
    )
    n_pos = int((y_true == 1).sum())
    n_neg = int((y_true == 0).sum())
    pr_auc = float(average_precision_score(y_true, probs)) if n_pos and n_neg else float("nan")
    # clip probs for log loss stability
    p_clip = np.clip(probs, 1e-15, 1 - 1e-15)
    return {
        "pr_auc": pr_auc,
        "precision": float(prec),
        "recall": float(rec),
        "f1": float(f1),
        "tp": tp,
        "tn": tn,
        "fp": fp,
        "fn": fn,
        "fpr": float(fp / n_neg) if n_neg else float("nan"),
        "fnr": float(fn / n_pos) if n_pos else float("nan"),
        "brier": float(brier_score_loss(y_true, probs)),
        "log_loss": float(log_loss(y_true, p_clip, labels=[0, 1])),
    }


def channels_changed_mask(
    x0: np.ndarray, x1: np.ndarray, atol: float = 1e-6
) -> np.ndarray:
    """Return boolean (F,) whether each feature channel differs anywhere."""
    diff = np.abs(x0.astype(np.float64) - x1.astype(np.float64))
    return diff.reshape(-1, diff.shape[-1]).max(axis=0) > atol


__all__ = [
    "BEHAVIOURAL_SOURCES",
    "CONDITIONS",
    "EXPECTED_COHORT_SHA256",
    "EXPECTED_VAL_MAL",
    "EXPECTED_VAL_N",
    "INTERVENTION_VALIDITY",
    "PROTOCOL_SEED",
    "SAFE_FEATURES",
    "SEQ_LEN",
    "apply_missing_source_condition",
    "binary_classification_metrics",
    "build_dependency_matrix_rows",
    "build_feature_mapping_rows",
    "channels_changed_mask",
    "classify_intervention_validity",
    "forward_scale",
    "intervention_action_for_feature",
    "inverse_scale",
    "load_scaler_stats",
    "scaled_absence_values",
    "sources_removed_for_condition",
    "verify_cohort_manifest",
]
