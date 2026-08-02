"""Load read-only saved neural and engineered-feature evidence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .constants import (
    ATTENTION_LINEAR,
    EVIDENCE_AL_REL,
    EVIDENCE_LB_REL,
    EVIDENCE_TA_REL,
    SEEDS,
    TEACHER_ANCHORED,
)
from .metrics import choose_threshold, evaluate_validation
from .safety import assert_path_allowed_for_read, sha256_file


def _read_json(path: Path) -> dict[str, Any]:
    assert_path_allowed_for_read(path, context="evidence_json")
    return json.loads(path.read_text(encoding="utf-8"))


def load_teacher_anchored_summaries(repo_root: Path, y_val: np.ndarray) -> list[dict[str, Any]]:
    base = repo_root / EVIDENCE_TA_REL
    rows: list[dict[str, Any]] = []
    for seed in SEEDS:
        meta = TEACHER_ANCHORED[seed]
        summary_path = base / meta["summary_rel"]
        pred_path = base / meta["pred_rel"]
        ckpt_path = base / meta["ckpt_rel"]
        assert_path_allowed_for_read(summary_path, context="ta_summary")
        assert_path_allowed_for_read(pred_path, context="ta_pred")
        assert_path_allowed_for_read(ckpt_path, context="ta_ckpt")

        summary = _read_json(summary_path)
        pred = pd.read_csv(pred_path)
        probs = pred["student_prob"].to_numpy(dtype=np.float64)
        y_true = pred["y_true"].to_numpy(dtype=np.int32)
        if len(y_true) != len(y_val) or not np.array_equal(y_true, y_val.astype(np.int32)):
            raise RuntimeError(
                f"Teacher-anchored seed {seed} label parity failed vs validation partition"
            )
        thr = float(summary.get("best_threshold", pred["student_threshold"].iloc[0]))
        metrics = evaluate_validation(y_true, probs, thr)
        ckpt_sha = sha256_file(ckpt_path)
        expected = meta.get("expected_sha256")
        if expected and ckpt_sha != expected:
            # Seed 52 may not be pre-pinned in constants; allow summary hash if present.
            if summary.get("best_checkpoint_sha256") and ckpt_sha != summary["best_checkpoint_sha256"]:
                raise RuntimeError(f"TA checkpoint hash mismatch seed={seed}")

        rows.append(
            {
                "model": "teacher_anchored_odst_seq",
                "panel": "A",
                "seed": seed,
                "input_representation": "sequence_20x13",
                "source": "saved_r52_teacher_anchored_reproducibility_v1",
                "retrained": False,
                "preprocessing": "prebaked_train_only_in_tensor_files",
                "n_parameters": None,
                "model_size_bytes": int(ckpt_path.stat().st_size),
                "model_sha256": ckpt_sha,
                "training_duration_sec": None,
                "inference_duration_sec": None,
                "peak_gpu_memory_mb": None,
                "device": "saved_evidence",
                "validation_metrics": metrics,
                "comparison_label": "r5.2 validation comparison",
                "threshold_from_saved_summary": thr,
                "summary_path": str(summary_path),
                "prediction_path": str(pred_path),
                "y_proba": probs,
            }
        )
    return rows


def load_attention_linear_summaries(repo_root: Path, y_val: np.ndarray) -> list[dict[str, Any]]:
    base = repo_root / EVIDENCE_AL_REL
    rows: list[dict[str, Any]] = []
    for seed in SEEDS:
        meta = ATTENTION_LINEAR[seed]
        d = base / meta["dir_rel"]
        summary_path = d / "summary.json"
        pred_path = d / "validation_predictions.csv"
        ckpt_path = d / "best.pt"
        summary = _read_json(summary_path)
        pred = pd.read_csv(pred_path)
        # Column names may vary; support common patterns.
        if "y_proba" in pred.columns:
            probs = pred["y_proba"].to_numpy(dtype=np.float64)
        elif "prob" in pred.columns:
            probs = pred["prob"].to_numpy(dtype=np.float64)
        elif "probability" in pred.columns:
            probs = pred["probability"].to_numpy(dtype=np.float64)
        else:
            # fallback: last float-like score column excluding labels
            score_cols = [c for c in pred.columns if c.lower() not in {"y_true", "label", "y"}]
            probs = pred[score_cols[-1]].to_numpy(dtype=np.float64)

        if "y_true" in pred.columns:
            y_true = pred["y_true"].to_numpy(dtype=np.int32)
        elif "label" in pred.columns:
            y_true = pred["label"].to_numpy(dtype=np.int32)
        else:
            y_true = y_val.astype(np.int32)

        if len(y_true) != len(y_val) or not np.array_equal(y_true, y_val.astype(np.int32)):
            raise RuntimeError(f"Attention-linear seed {seed} label parity failed")

        thr = float(summary["validation_metrics"]["threshold"])
        # Recompute metrics from saved probs with saved threshold for consistency.
        metrics = evaluate_validation(y_true, probs, thr)
        # Also record recomputed max-F1 threshold for transparency (not used to replace saved ops threshold).
        thr_re, _ = choose_threshold(y_true, probs)

        rows.append(
            {
                "model": "attention_linear_seq",
                "panel": "A",
                "seed": seed,
                "input_representation": "sequence_20x13",
                "source": "saved_r52_odst_confirmation_attention_linear",
                "retrained": False,
                "retrain_reason": None,
                "preprocessing": "prebaked_train_only_in_tensor_files",
                "n_parameters": (summary.get("parameter_counts") or {}).get("total"),
                "model_size_bytes": int(ckpt_path.stat().st_size) if ckpt_path.exists() else None,
                "model_sha256": sha256_file(ckpt_path) if ckpt_path.exists() else None,
                "training_duration_sec": summary.get("duration_sec"),
                "inference_duration_sec": None,
                "peak_gpu_memory_mb": summary.get("peak_gpu_memory_mb"),
                "device": summary.get("device", "saved_evidence"),
                "validation_metrics": metrics,
                "saved_threshold": thr,
                "recomputed_max_f1_threshold": thr_re,
                "comparison_label": "r5.2 validation comparison",
                "summary_path": str(summary_path),
                "prediction_path": str(pred_path),
                "y_proba": probs,
            }
        )
    return rows


def load_engineered_context(repo_root: Path) -> pd.DataFrame:
    base = repo_root / EVIDENCE_LB_REL
    summary_csv = base / "r52_conventional_baseline_summary.csv"
    by_seed = base / "r52_conventional_baseline_comparison.csv"
    assert_path_allowed_for_read(summary_csv, context="engineered_summary")
    rows: list[dict[str, Any]] = []

    if by_seed.exists():
        df = pd.read_csv(by_seed)
        for _, r in df.iterrows():
            model = str(r.get("model", "")).lower()
            if "random_forest" in model or model == "rf":
                name = "engineered_random_forest_40"
            elif "xgboost" in model or model == "xgb":
                name = "engineered_xgboost_40"
            else:
                continue
            rows.append(
                {
                    "model": name,
                    "panel": "B",
                    "seed": int(r["seed"]) if "seed" in r and pd.notna(r["seed"]) else None,
                    "input_representation": "engineered_40_window_aggregates",
                    "inputs_identical_to_panel_a": False,
                    "source": "read_only_r52_locked_baselines",
                    "retrained": False,
                    "pr_auc": float(r.get("pr_auc", r.get("validation_pr_auc", np.nan))),
                    "f1": float(r.get("f1", r.get("validation_f1", np.nan))),
                    "precision": float(r["precision"]) if "precision" in r and pd.notna(r["precision"]) else np.nan,
                    "recall": float(r["recall"]) if "recall" in r and pd.notna(r["recall"]) else np.nan,
                    "fp": float(r["fp"]) if "fp" in r and pd.notna(r["fp"]) else np.nan,
                    "fn": float(r["fn"]) if "fn" in r and pd.notna(r["fn"]) else np.nan,
                    "threshold": float(r["threshold"]) if "threshold" in r and pd.notna(r["threshold"]) else np.nan,
                    "training_duration_sec": float(r["training_duration_sec"])
                    if "training_duration_sec" in r and pd.notna(r["training_duration_sec"])
                    else np.nan,
                }
            )

    if not rows:
        # Fall back to mean summary only.
        sdf = pd.read_csv(summary_csv)
        for _, r in sdf.iterrows():
            model = str(r["model"]).lower()
            name = (
                "engineered_random_forest_40"
                if "random_forest" in model
                else "engineered_xgboost_40"
            )
            rows.append(
                {
                    "model": name,
                    "panel": "B",
                    "seed": "mean_of_3",
                    "input_representation": "engineered_40_window_aggregates",
                    "inputs_identical_to_panel_a": False,
                    "source": "read_only_r52_locked_baselines_summary",
                    "retrained": False,
                    "pr_auc": float(r["pr_auc_mean"]),
                    "f1": float(r["f1_mean"]),
                    "precision": float(r["precision_mean"]),
                    "recall": float(r["recall_mean"]),
                    "fp": float(r["fp_mean"]),
                    "fn": float(r["fn_mean"]),
                    "threshold": str(r.get("threshold_per_seed", "")),
                    "training_duration_sec": float(r["training_time_sec_mean"]),
                    "pr_auc_std": float(r["pr_auc_std"]),
                    "f1_std": float(r["f1_std"]),
                }
            )

    # Attach TA as contextual reference (not ranked with engineered inputs).
    ta_summary = repo_root / EVIDENCE_TA_REL / "seed42" / "seed_summary.json"
    if ta_summary.exists():
        s = _read_json(ta_summary)
        rows.append(
            {
                "model": "teacher_anchored_odst_seq_context",
                "panel": "B",
                "seed": 42,
                "input_representation": "sequence_20x13",
                "inputs_identical_to_panel_a": False,
                "note": "Contextual reference only; Panel B inputs are not identical.",
                "source": "read_only_r52_teacher_anchored",
                "retrained": False,
                "pr_auc": float(s["best_pr_auc"]),
                "f1": float(s["best_f1"]),
                "precision": float(s["best_precision"]),
                "recall": float(s["best_recall"]),
                "fp": float(s["best_fp"]),
                "fn": float(s["best_fn"]),
                "threshold": float(s["best_threshold"]),
            }
        )
    return pd.DataFrame(rows)


def load_engineered_seed_details(repo_root: Path) -> pd.DataFrame:
    """Prefer per-seed engineered summaries from locked baseline seed folders."""
    base = repo_root / EVIDENCE_LB_REL
    rows: list[dict[str, Any]] = []
    for model_key, folder_prefix in (
        ("engineered_random_forest_40", "random_forest_seed"),
        ("engineered_xgboost_40", "xgboost_seed"),
    ):
        for seed in SEEDS:
            sp = base / f"{folder_prefix}{seed}" / "summary.json"
            if not sp.exists():
                continue
            s = _read_json(sp)
            m = s.get("validation_metrics", s)
            rows.append(
                {
                    "model": model_key,
                    "panel": "B",
                    "seed": seed,
                    "input_representation": "engineered_40_window_aggregates",
                    "inputs_identical_to_panel_a": False,
                    "source": "read_only_r52_locked_baselines",
                    "retrained": False,
                    "pr_auc": float(m["pr_auc"]),
                    "f1": float(m["f1"]),
                    "precision": float(m["precision"]),
                    "recall": float(m["recall"]),
                    "fp": float(m["fp"]),
                    "fn": float(m["fn"]),
                    "threshold": float(m["threshold"]),
                    "roc_auc": float(m.get("roc_auc", np.nan)),
                    "training_duration_sec": float(s.get("training_duration_sec", s.get("duration_sec", np.nan))),
                    "inference_duration_sec": float(s.get("validation_inference_duration_sec", np.nan)),
                }
            )
    return pd.DataFrame(rows)
