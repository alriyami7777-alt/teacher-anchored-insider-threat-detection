#!/usr/bin/env python3
"""Shared helpers for Objective 2 final locked consolidation and evaluation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

SEEDS = (42, 52, 62)

DISPLAY_NAMES = {
    "standalone_bilstm": "Standalone Bi-LSTM",
    "attention_linear": "Attention–Linear Ablation",
    "fragmented_bilstm_rf": "Fragmented Bi-LSTM–RF",
    "fragmented_bilstm_xgboost": "Fragmented Bi-LSTM–XGBoost",
    "joint_bilstm_attention_soft_forest": "Joint Bi-LSTM–Attention–Soft Forest",
    "standalone_soft_forest": "Standalone Soft Forest",
    "classical_rf": "Classical RF",
    "classical_xgboost": "Classical XGBoost",
}

MODEL_FAMILIES = {
    "standalone_bilstm": "sequence_neural",
    "attention_linear": "sequence_ensemble_ablation",
    "fragmented_bilstm_rf": "fragmented_hybrid",
    "fragmented_bilstm_xgboost": "fragmented_hybrid",
    "joint_bilstm_attention_soft_forest": "sequence_ensemble_joint",
    "standalone_soft_forest": "reference_tabular_soft_forest",
    "classical_rf": "reference_tabular_classical",
    "classical_xgboost": "reference_tabular_classical",
}

INPUT_REPRESENTATION = {
    "standalone_bilstm": "T=20 sequence tensors (13 raw day features)",
    "attention_linear": "T=20 sequence tensors (13 raw day features)",
    "fragmented_bilstm_rf": "Frozen Bi-LSTM+attention representations (128-d) from pretrain encoder",
    "fragmented_bilstm_xgboost": "Frozen Bi-LSTM+attention representations (128-d) from pretrain encoder",
    "joint_bilstm_attention_soft_forest": "T=20 sequence tensors (13 raw day features); joint fine-tune",
    "standalone_soft_forest": "Aggregated sequence feature table (40 engineered features); DIFFERENT representation",
    "classical_rf": "Aggregated sequence feature table (40 engineered features); DIFFERENT representation",
    "classical_xgboost": "Aggregated sequence feature table (40 engineered features); DIFFERENT representation",
}

PRETRAIN_DIRS = {
    42: "stage11_A_attn_linear",
    52: "pretrain_attn_linear_seed52",
    62: "pretrain_attn_linear_seed62",
}

JOINT_DIRS = {
    42: "stage11_D_pretrained_seed42_best",
    52: "stage11_D_pretrained_seed52_best",
    62: "stage11_D_pretrained_seed62_best",
}

PRIMARY_MODEL_IDS = (
    "standalone_bilstm",
    "attention_linear",
    "fragmented_bilstm_rf",
    "fragmented_bilstm_xgboost",
    "joint_bilstm_attention_soft_forest",
)

REFERENCE_MODEL_IDS = (
    "standalone_soft_forest",
    "classical_rf",
    "classical_xgboost",
)

SUMMARY_METRIC_COLS = [
    "validation_pr_auc",
    "validation_precision",
    "validation_recall",
    "validation_f1",
    "validation_fp",
    "validation_fn",
    "validation_threshold",
    "best_epoch",
    "training_time_sec",
    "inference_time_sec",
    "attention_entropy",
]

PAIRWISE_METRIC_COLS = [
    "validation_pr_auc",
    "validation_precision",
    "validation_recall",
    "validation_f1",
    "validation_fp",
    "validation_fn",
]


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def resolve(root: Path, rel: str | Path) -> Path:
    path = Path(rel)
    return path if path.is_absolute() else (root / path).resolve()


def sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def rel_to_root(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


def summarise_numeric(df: pd.DataFrame, cols: list[str], group_cols: list[str]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for keys, g in df.groupby(group_cols, dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        base = dict(zip(group_cols, keys))
        for col in cols:
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


def paired_seed_differences(
    comparison: pd.DataFrame,
    metric_cols: list[str] | None = None,
    model_ids: tuple[str, ...] | None = None,
) -> pd.DataFrame:
    """Paired same-seed differences between primary models (model_a - model_b)."""
    metric_cols = metric_cols or PAIRWISE_METRIC_COLS
    model_ids = model_ids or PRIMARY_MODEL_IDS
    primary = comparison[comparison["model_id"].isin(model_ids)].copy()
    rows: list[dict[str, Any]] = []
    seeds = sorted(int(s) for s in primary["seed"].dropna().unique())
    for seed in seeds:
        sub = primary[primary["seed"] == seed].set_index("model_id")
        ids = [m for m in model_ids if m in sub.index]
        for i, a in enumerate(ids):
            for b in ids[i + 1 :]:
                for col in metric_cols:
                    if col not in sub.columns:
                        continue
                    va = sub.loc[a, col]
                    vb = sub.loc[b, col]
                    if pd.isna(va) or pd.isna(vb):
                        continue
                    rows.append(
                        {
                            "seed": seed,
                            "model_a": DISPLAY_NAMES[a],
                            "model_a_id": a,
                            "model_b": DISPLAY_NAMES[b],
                            "model_b_id": b,
                            "metric": col,
                            "value_a": float(va),
                            "value_b": float(vb),
                            "difference_a_minus_b": float(va) - float(vb),
                        }
                    )
    return pd.DataFrame(rows)


def metrics_at_threshold(y_true: np.ndarray, probs: np.ndarray, threshold: float) -> dict[str, Any]:
    from sklearn.metrics import (
        average_precision_score,
        confusion_matrix,
        f1_score,
        precision_score,
        recall_score,
        roc_auc_score,
    )

    y_pred = (probs >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()
    fpr = float(fp / (fp + tn)) if (fp + tn) else 0.0
    fnr = float(fn / (fn + tp)) if (fn + tp) else 0.0
    return {
        "threshold": float(threshold),
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "f1": float(f1_score(y_true, y_pred, zero_division=0)),
        "pr_auc": float(average_precision_score(y_true, probs)),
        "roc_auc": float(roc_auc_score(y_true, probs)),
        "fpr": fpr,
        "fnr": fnr,
        "tn": int(tn),
        "fp": int(fp),
        "fn": int(fn),
        "tp": int(tp),
    }


def hash_artefact(root: Path, path: Path, role: str) -> dict[str, str]:
    path = path.resolve()
    if not path.exists():
        raise FileNotFoundError(f"Missing artefact ({role}): {path}")
    return {
        "path": rel_to_root(root, path),
        "absolute_path": str(path),
        "role": role,
        "sha256": sha256_file(path),
        "size_bytes": str(path.stat().st_size),
    }


def verify_artefact_hash(root: Path, entry: dict[str, Any]) -> None:
    path = Path(entry.get("absolute_path") or (root / entry["path"]))
    if not path.exists():
        raise FileNotFoundError(f"Locked artefact missing: {path}")
    digest = sha256_file(path)
    expected = entry["sha256"]
    if digest != expected:
        raise ValueError(
            f"SHA-256 mismatch for {entry.get('role', 'artefact')} at {path}: "
            f"expected {expected}, got {digest}"
        )


def default_output_dir(root: Path) -> Path:
    return root / "outputs" / "objective2"


def locked_manifest_path(root: Path) -> Path:
    return default_output_dir(root) / "objective2_final_locked_manifest.json"


def test_evaluation_manifest_path(root: Path) -> Path:
    return default_output_dir(root) / "objective2_test_evaluation_manifest.json"
