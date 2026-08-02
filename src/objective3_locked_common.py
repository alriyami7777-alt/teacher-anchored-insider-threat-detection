#!/usr/bin/env python3
"""Shared helpers for locked Objective 3 interpretability / robustness pilot.

Model paths and thresholds are read only from the completed Objective 2
test-evaluation manifest. Thresholds and checkpoints are never modified.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from objective2_locked_common import (
    DISPLAY_NAMES,
    metrics_at_threshold,
    rel_to_root,
    repo_root,
    resolve,
    sha256_file,
    test_evaluation_manifest_path,
    write_json,
)

SAFE_FEATURES = [
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
]

CONTINUOUS_FEATURE_INDICES = list(range(7))  # first 7 features are counts/duration
BINARY_FEATURE_INDICES = list(range(7, 13))

# Legacy Objective 3 pilot comparison set (superseded soft-forest era).
# Retained for historical pilot artefacts and existing unit tests only.
# Selected Objective 3 architectures live in objective3_model_registry.py
# (ODST + attention–linear). Do not treat soft-forest routing as ODST.
OBJECTIVE3_MODEL_IDS = (
    "joint_bilstm_attention_soft_forest",
    "standalone_bilstm",
    "attention_linear",
    "fragmented_bilstm_xgboost",
)

# Explicit alias: these IDs are superseded_model_only for new Obj3 work.
LEGACY_OBJECTIVE3_MODEL_IDS = OBJECTIVE3_MODEL_IDS

# Selected Objective 3 architectures (hash-pinned registry; not soft forest).
OBJECTIVE3_SELECTED_ARCHITECTURE_IDS = (
    "bi_lstm_attention_sparsemax_sigmoid_odst",
    "bi_lstm_attention_linear",
)

# Analysis applicability (True = technically supported).
# soft_tree applies only to the superseded soft-forest pilot model — never ODST.
ANALYSIS_APPLICABILITY = {
    "temporal_attention": {
        "joint_bilstm_attention_soft_forest": True,
        "standalone_bilstm": False,
        "attention_linear": True,
        "fragmented_bilstm_xgboost": True,  # frozen encoder attention
        "bi_lstm_attention_sparsemax_sigmoid_odst": True,
        "bi_lstm_attention_linear": True,
    },
    "soft_tree": {
        "joint_bilstm_attention_soft_forest": True,  # superseded_model_only
        "standalone_bilstm": False,
        "attention_linear": False,
        "fragmented_bilstm_xgboost": False,
        "bi_lstm_attention_sparsemax_sigmoid_odst": False,  # use native ODST extras
        "bi_lstm_attention_linear": False,
    },
    "odst_native": {
        "joint_bilstm_attention_soft_forest": False,
        "standalone_bilstm": False,
        "attention_linear": False,
        "fragmented_bilstm_xgboost": False,
        "bi_lstm_attention_sparsemax_sigmoid_odst": True,
        "bi_lstm_attention_linear": False,
    },
    "feature_masking": {
        "joint_bilstm_attention_soft_forest": True,
        "standalone_bilstm": True,
        "attention_linear": True,
        "fragmented_bilstm_xgboost": True,
        "bi_lstm_attention_sparsemax_sigmoid_odst": True,
        "bi_lstm_attention_linear": True,
    },
    "robustness": {
        "joint_bilstm_attention_soft_forest": True,
        "standalone_bilstm": True,
        "attention_linear": True,
        "fragmented_bilstm_xgboost": True,
        "bi_lstm_attention_sparsemax_sigmoid_odst": True,
        "bi_lstm_attention_linear": True,
    },
}

PERTURBATION_LEVELS = (0.05, 0.10, 0.20)
PERTURBATION_SCENARIOS = (
    "random_observation_masking",
    "missing_random_features",
    "missing_complete_days",
    "gaussian_noise_continuous",
)
DEFAULT_PERTURBATION_SEEDS = (101, 202, 303, 404, 505)

# Legacy scenario names retained in protocol metadata only.
SCENARIO_LEGACY_NAME_MAP = {
    "missing_random_events": "random_observation_masking",
}

FEATURE_GROUPS = {
    "continuous": SAFE_FEATURES[:7],
    "binary": SAFE_FEATURES[7:],
}

DEFAULT_UNUSED_LEAF_THRESHOLD = 1e-3
SEQ_LEN = 20
N_FEATURES = 13
ROBUSTNESS_METRIC_COLS = [
    "pr_auc_degradation",
    "f1_degradation",
    "recall_degradation",
    "fp_change",
    "fn_change",
    "prediction_agreement",
    "prediction_flip_rate",
    "explanation_cosine_mean",
    "explanation_l1_mean",
]


def default_output_dir(root: Path | None = None) -> Path:
    root = root or repo_root()
    return root / "outputs" / "objective3"


def load_test_evaluation_manifest(root: Path | None = None, path: Path | None = None) -> dict[str, Any]:
    root = root or repo_root()
    manifest_path = path or test_evaluation_manifest_path(root)
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"Objective 2 test evaluation manifest not found: {manifest_path}. "
            "Objective 3 requires a completed locked Obj2 test evaluation."
        )
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if payload.get("status") != "test_evaluation_complete":
        raise ValueError(
            f"Manifest status is {payload.get('status')!r}; expected 'test_evaluation_complete'."
        )
    return payload


def locked_model_entries(
    manifest: dict[str, Any],
    model_ids: tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    """Flatten models_evaluated into Objective 3 locked entries.

    Paths and thresholds come exclusively from the Obj2 test evaluation manifest.
    """
    model_ids = model_ids or OBJECTIVE3_MODEL_IDS
    wanted = set(model_ids)
    thresholds = manifest.get("thresholds_used", {})
    configs = manifest.get("configurations", {})
    entries: list[dict[str, Any]] = []
    for row in manifest.get("models_evaluated", []):
        model_id = row["model_id"]
        if model_id not in wanted:
            continue
        seed = int(row["seed"])
        key = f"{model_id}_seed{seed}"
        thr = thresholds.get(key, row.get("validation_threshold"))
        if thr is None:
            raise ValueError(f"Missing locked threshold for {key}")
        entries.append(
            {
                "model_id": model_id,
                "model_name": DISPLAY_NAMES.get(model_id, row.get("model_name", model_id)),
                "model_family": row.get("model_family", ""),
                "seed": seed,
                "validation_threshold": float(thr),
                "checkpoint_path": row.get("checkpoint_path") or "",
                "classifier_path": row.get("classifier_path") or "",
                "encoder_checkpoint_path": row.get("encoder_checkpoint_path") or "",
                "hyperparameters": configs.get(key, {}),
                "key": key,
            }
        )
    missing = wanted - {e["model_id"] for e in entries}
    if missing:
        raise ValueError(f"Manifest missing Objective 3 models: {sorted(missing)}")
    return sorted(entries, key=lambda e: (OBJECTIVE3_MODEL_IDS.index(e["model_id"]), e["seed"]))


def tensor_path_for_split(root: Path, split: str) -> Path:
    if split not in {"validation", "test"}:
        raise ValueError(f"Objective 3 pilot split must be validation or test; got {split!r}")
    return resolve(root, f"data/processed/tensors/r42_T20_s1_{split}.npz")


def load_sequence_meta(npz_path: Path) -> dict[str, np.ndarray]:
    z = np.load(npz_path, allow_pickle=True)
    meta: dict[str, np.ndarray] = {
        "y": np.asarray(z["y"]).astype(np.int8),
    }
    for key in ("sequence_id", "user", "start_date", "end_date"):
        if key in z.files:
            meta[key] = np.asarray(z[key]).astype(str)
    return meta


def entropy_np(p: np.ndarray, axis: int = -1, eps: float = 1e-8) -> np.ndarray:
    p = np.clip(p, eps, None)
    return -(p * np.log(p)).sum(axis=axis)


def temporal_concentration(attn: np.ndarray, top_k: int = 3) -> np.ndarray:
    """Fraction of attention mass in the top-k timesteps (per sequence)."""
    if attn.ndim != 2:
        raise ValueError(f"Expected (N, T) attention; got {attn.shape}")
    k = min(top_k, attn.shape[1])
    part = np.partition(attn, attn.shape[1] - k, axis=1)[:, -k:]
    return part.sum(axis=1)


def prediction_stability(y_pred_clean: np.ndarray, y_pred_pert: np.ndarray) -> dict[str, float]:
    y_pred_clean = np.asarray(y_pred_clean).astype(int)
    y_pred_pert = np.asarray(y_pred_pert).astype(int)
    agree = y_pred_clean == y_pred_pert
    return {
        "prediction_agreement": float(agree.mean()) if len(agree) else float("nan"),
        "prediction_flip_rate": float((~agree).mean()) if len(agree) else float("nan"),
        "n_flips": int((~agree).sum()),
    }


def explanation_stability(
    clean: np.ndarray | None,
    perturbed: np.ndarray | None,
    eps: float = 1e-8,
) -> dict[str, float]:
    """Cosine similarity / L1 drift between per-sequence explanation vectors."""
    if clean is None or perturbed is None:
        return {
            "explanation_cosine_mean": float("nan"),
            "explanation_l1_mean": float("nan"),
        }
    clean = np.asarray(clean, dtype=np.float64)
    perturbed = np.asarray(perturbed, dtype=np.float64)
    if clean.shape != perturbed.shape:
        raise ValueError(f"Explanation shape mismatch: {clean.shape} vs {perturbed.shape}")
    # Flatten trailing dims so each row is one explanation vector.
    c = clean.reshape(clean.shape[0], -1)
    p = perturbed.reshape(perturbed.shape[0], -1)
    c_norm = np.linalg.norm(c, axis=1)
    p_norm = np.linalg.norm(p, axis=1)
    denom = np.maximum(c_norm * p_norm, eps)
    cos = (c * p).sum(axis=1) / denom
    l1 = np.abs(c - p).sum(axis=1)
    return {
        "explanation_cosine_mean": float(np.nanmean(cos)),
        "explanation_l1_mean": float(np.nanmean(l1)),
    }


def degradation_row(
    clean_metrics: dict[str, Any],
    pert_metrics: dict[str, Any],
    *,
    model_id: str,
    seed: int,
    scenario: str,
    level: float | None,
    split: str,
    perturbation_seed: int | None = None,
    stability: dict[str, float] | None = None,
    explanation: dict[str, float] | None = None,
) -> dict[str, Any]:
    stability = stability or {}
    explanation = explanation or {}
    row = {
        "model_id": model_id,
        "model_name": DISPLAY_NAMES.get(model_id, model_id),
        "seed": int(seed),
        "split": split,
        "scenario": scenario,
        "level": None if level is None else float(level),
        "threshold": float(clean_metrics["threshold"]),
        "clean_pr_auc": float(clean_metrics["pr_auc"]),
        "pert_pr_auc": float(pert_metrics["pr_auc"]),
        "pr_auc_degradation": float(clean_metrics["pr_auc"] - pert_metrics["pr_auc"]),
        "clean_f1": float(clean_metrics["f1"]),
        "pert_f1": float(pert_metrics["f1"]),
        "f1_degradation": float(clean_metrics["f1"] - pert_metrics["f1"]),
        "clean_recall": float(clean_metrics["recall"]),
        "pert_recall": float(pert_metrics["recall"]),
        "recall_degradation": float(clean_metrics["recall"] - pert_metrics["recall"]),
        "clean_fp": int(clean_metrics["fp"]),
        "pert_fp": int(pert_metrics["fp"]),
        "fp_change": int(pert_metrics["fp"] - clean_metrics["fp"]),
        "clean_fn": int(clean_metrics["fn"]),
        "pert_fn": int(pert_metrics["fn"]),
        "fn_change": int(pert_metrics["fn"] - clean_metrics["fn"]),
        **stability,
        **explanation,
    }
    if perturbation_seed is not None:
        row["perturbation_seed"] = int(perturbation_seed)
    return row


def aggregate_robustness_replicates(
    replicates: pd.DataFrame,
    metric_cols: list[str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Aggregate replicate-level robustness rows.

    Returns:
      by_cell: mean/std/min/max over perturbation seeds for each
               (model_id, seed, scenario, level)
      by_model_seed: summaries over scenarios/levels/perturbation seeds per model seed
      overall: summaries across model seeds and perturbation seeds
               for each (model_id, scenario, level)
    """
    metric_cols = metric_cols or [
        c for c in ROBUSTNESS_METRIC_COLS if c in replicates.columns
    ]
    if replicates.empty:
        empty = pd.DataFrame()
        return empty, empty, empty

    by_cell = summarise_group(
        replicates,
        metric_cols,
        ["model_id", "model_name", "seed", "scenario", "level", "split"],
    )
    by_model_seed = summarise_group(
        replicates,
        metric_cols,
        ["model_id", "model_name", "seed", "split"],
    )
    overall = summarise_group(
        replicates,
        metric_cols,
        ["model_id", "model_name", "scenario", "level", "split"],
    )
    return by_cell, by_model_seed, overall


def build_protocol_manifest(
    *,
    root: Path,
    model_manifest_path: Path,
    validation_tensor_path: Path,
    scenarios: list[str],
    levels: list[float],
    perturbation_seeds: list[int],
    thresholds: dict[str, float],
    entries: list[dict[str, Any]] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Locked Objective 3 protocol manifest (test_evaluated always false here)."""
    payload: dict[str, Any] = {
        "status": "objective3_protocol_locked",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "model_manifest_path": rel_to_root(root, model_manifest_path),
        "model_manifest_sha256": sha256_file(model_manifest_path),
        "validation_tensor_path": rel_to_root(root, validation_tensor_path),
        "validation_tensor_sha256": sha256_file(validation_tensor_path),
        "scenarios": [SCENARIO_LEGACY_NAME_MAP.get(s, s) for s in scenarios],
        "scenario_legacy_name_map": dict(SCENARIO_LEGACY_NAME_MAP),
        "levels": [float(x) for x in levels],
        "perturbation_seeds": [int(s) for s in perturbation_seeds],
        "feature_names": list(SAFE_FEATURES),
        "feature_groups": {
            "continuous": list(FEATURE_GROUPS["continuous"]),
            "binary": list(FEATURE_GROUPS["binary"]),
        },
        "thresholds": {k: float(v) for k, v in thresholds.items()},
        "test_evaluated": False,
        "safety": {
            "validation_only_default": True,
            "test_requires": "--confirm-perturbed-test-evaluation",
            "no_retrain": True,
            "no_threshold_retune": True,
            "no_checkpoint_modification": True,
            "paired_perturbations": True,
            "perturbation_seed_independent_of_model_seed": True,
        },
    }
    if entries is not None:
        payload["locked_model_entries"] = [
            {
                "model_id": e["model_id"],
                "seed": int(e["seed"]),
                "validation_threshold": float(e["validation_threshold"]),
                "checkpoint_path": e.get("checkpoint_path", ""),
                "classifier_path": e.get("classifier_path", ""),
                "encoder_checkpoint_path": e.get("encoder_checkpoint_path", ""),
            }
            for e in entries
        ]
    if extra:
        payload.update(extra)
    return payload


def summarise_group(df: pd.DataFrame, metric_cols: list[str], group_cols: list[str]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if df.empty:
        return pd.DataFrame()
    for keys, g in df.groupby(group_cols, dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        base = dict(zip(group_cols, keys))
        for col in metric_cols:
            if col not in g.columns:
                continue
            s = pd.to_numeric(g[col], errors="coerce").dropna()
            if s.empty:
                continue
            rows.append(
                {
                    **base,
                    "metric": col,
                    "mean": float(s.mean()),
                    "std": float(s.std(ddof=1)) if len(s) > 1 else 0.0,
                    "min": float(s.min()),
                    "max": float(s.max()),
                    "n": int(len(s)),
                }
            )
    return pd.DataFrame(rows)


def experiment_matrix() -> pd.DataFrame:
    """Publication-ready experiment matrix describing validation-only pilot cells."""
    rows: list[dict[str, Any]] = []
    for model_id in OBJECTIVE3_MODEL_IDS:
        for analysis, appl in ANALYSIS_APPLICABILITY.items():
            applicable = bool(appl[model_id])
            if analysis == "robustness" and applicable:
                for scenario in PERTURBATION_SCENARIOS:
                    for level in PERTURBATION_LEVELS:
                        rows.append(
                            {
                                "model_id": model_id,
                                "model_name": DISPLAY_NAMES[model_id],
                                "analysis": analysis,
                                "scenario": scenario,
                                "level": level,
                                "applicable": True,
                                "split": "validation",
                                "notes": "Develop/select on validation only; locked thresholds unchanged",
                            }
                        )
            elif analysis == "feature_masking" and applicable:
                for feat in SAFE_FEATURES:
                    rows.append(
                        {
                            "model_id": model_id,
                            "model_name": DISPLAY_NAMES[model_id],
                            "analysis": analysis,
                            "scenario": f"mask_{feat}",
                            "level": None,
                            "applicable": True,
                            "split": "validation",
                            "notes": "Mask one feature channel across all timesteps",
                        }
                    )
            else:
                rows.append(
                    {
                        "model_id": model_id,
                        "model_name": DISPLAY_NAMES[model_id],
                        "analysis": analysis,
                        "scenario": analysis,
                        "level": None,
                        "applicable": applicable,
                        "split": "validation",
                        "notes": (
                            "Supported"
                            if applicable
                            else "Not applicable for this architecture"
                        ),
                    }
                )
    return pd.DataFrame(rows)


__all__ = [
    "ANALYSIS_APPLICABILITY",
    "BINARY_FEATURE_INDICES",
    "CONTINUOUS_FEATURE_INDICES",
    "DEFAULT_PERTURBATION_SEEDS",
    "DEFAULT_UNUSED_LEAF_THRESHOLD",
    "FEATURE_GROUPS",
    "LEGACY_OBJECTIVE3_MODEL_IDS",
    "N_FEATURES",
    "OBJECTIVE3_MODEL_IDS",
    "OBJECTIVE3_SELECTED_ARCHITECTURE_IDS",
    "PERTURBATION_LEVELS",
    "PERTURBATION_SCENARIOS",
    "ROBUSTNESS_METRIC_COLS",
    "SAFE_FEATURES",
    "SCENARIO_LEGACY_NAME_MAP",
    "SEQ_LEN",
    "aggregate_robustness_replicates",
    "build_protocol_manifest",
    "default_output_dir",
    "degradation_row",
    "entropy_np",
    "experiment_matrix",
    "explanation_stability",
    "load_sequence_meta",
    "load_test_evaluation_manifest",
    "locked_model_entries",
    "metrics_at_threshold",
    "prediction_stability",
    "repo_root",
    "resolve",
    "sha256_file",
    "summarise_group",
    "temporal_concentration",
    "tensor_path_for_split",
    "write_json",
]
