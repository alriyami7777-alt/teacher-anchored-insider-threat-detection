"""Consolidate comparisons and draft test preregistration."""

from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any

import pandas as pd

from . import OUTPUT_NAMESPACE, SEEDS
from .safety import ProtocolAccessError, assert_output_namespace, refuse_overwrite, write_json_atomic


METRIC_KEYS = [
    "pr_auc",
    "f1",
    "precision",
    "recall",
    "fp",
    "fn",
    "fpr",
    "brier_score",
    "log_loss",
    "training_time_sec",
    "inference_time_sec",
]


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _neural_row(model: str, seed: int, summary: dict[str, Any]) -> dict[str, Any]:
    vm = summary.get("validation_metrics", {})
    cal = summary.get("calibration", {})
    # Prefer nested metrics; fall back to calibration for older seed-42 ODST artefact.
    brier = vm.get("brier_score", cal.get("brier_score"))
    logl = vm.get("log_loss")
    fpr = vm.get("fpr")
    if fpr is None and vm.get("fp") is not None and vm.get("tn") is not None:
        fpr = float(vm["fp"]) / float(vm["fp"] + vm["tn"])
    fnr = vm.get("fnr")
    if fnr is None and vm.get("fn") is not None and vm.get("tp") is not None:
        denom = float(vm["fn"] + vm["tp"])
        fnr = float(vm["fn"]) / denom if denom else None
    n_alerts = vm.get("n_alerts")
    if n_alerts is None and vm.get("tp") is not None and vm.get("fp") is not None:
        n_alerts = int(vm["tp"] + vm["fp"])
    return {
        "family": model,
        "model": model,
        "seed": seed,
        "pr_auc": vm.get("pr_auc"),
        "roc_auc": vm.get("roc_auc"),
        "f1": vm.get("f1"),
        "precision": vm.get("precision"),
        "recall": vm.get("recall"),
        "threshold": vm.get("threshold"),
        "tp": vm.get("tp"),
        "tn": vm.get("tn"),
        "fp": vm.get("fp"),
        "fn": vm.get("fn"),
        "fpr": fpr,
        "fnr": fnr,
        "n_alerts": n_alerts,
        "brier_score": brier,
        "log_loss": logl,
        "training_time_sec": summary.get("duration_sec"),
        "inference_time_sec": summary.get("validation_inference_duration_sec"),
        "model_hash": (
            (summary.get("checkpoint_hashes") or {}).get("best.pt")
            or summary.get("model_hash")
        ),
        "source": "r52_odst_confirmation",
    }


def _classical_row(summary: dict[str, Any]) -> dict[str, Any]:
    vm = summary["validation_metrics"]
    return {
        "family": summary["model"],
        "model": summary["model"],
        "seed": summary["seed"],
        "pr_auc": vm["pr_auc"],
        "roc_auc": vm["roc_auc"],
        "f1": vm["f1"],
        "precision": vm["precision"],
        "recall": vm["recall"],
        "threshold": vm["threshold"],
        "tp": vm["tp"],
        "tn": vm["tn"],
        "fp": vm["fp"],
        "fn": vm["fn"],
        "fpr": vm["fpr"],
        "fnr": vm["fnr"],
        "n_alerts": vm["n_alerts"],
        "brier_score": vm["brier_score"],
        "log_loss": vm["log_loss"],
        "training_time_sec": summary.get("training_duration_sec", summary.get("duration_sec")),
        "inference_time_sec": summary.get("validation_inference_duration_sec"),
        "model_hash": summary.get("model_hash"),
        "source": "r52_locked_baselines",
    }


def _summarise(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for model, g in df.groupby("model"):
        row: dict[str, Any] = {"model": model, "n_seeds": len(g)}
        for key in METRIC_KEYS:
            vals = [float(v) for v in g[key].tolist() if v is not None and pd.notna(v)]
            if not vals:
                row[f"{key}_mean"] = None
                row[f"{key}_std"] = None
                row[f"{key}_min"] = None
                row[f"{key}_max"] = None
                row[f"{key}_seeds"] = None
                continue
            row[f"{key}_mean"] = float(statistics.fmean(vals))
            row[f"{key}_std"] = float(statistics.stdev(vals)) if len(vals) > 1 else 0.0
            row[f"{key}_min"] = float(min(vals))
            row[f"{key}_max"] = float(max(vals))
            row[f"{key}_seeds"] = ";".join(f"{v:.8g}" for v in vals)
        # Do not average thresholds as operational recommendation.
        thr_vals = [float(v) for v in g["threshold"].tolist() if v is not None and pd.notna(v)]
        row["threshold_per_seed"] = ";".join(f"{v:.8g}" for v in thr_vals)
        row["threshold_note"] = "per-seed validation-selected; not averaged for operations"
        rows.append(row)
    return pd.DataFrame(rows)


def _status_for_conventional(mean_pr: float, attn_mean: float, odst_mean: float) -> str:
    """Transparent relative status vs neural means; not a post-hoc gate favouring any model."""
    neural_floor = min(attn_mean, odst_mean)
    gap = mean_pr - neural_floor
    if gap >= -0.02:
        return "strong_conventional_baseline"
    if gap >= -0.10:
        return "competitive_conventional_baseline"
    return "weak_conventional_baseline"


def consolidate(root: Path, classical_summaries: list[dict[str, Any]]) -> dict[str, Any]:
    out = assert_output_namespace(root / OUTPUT_NAMESPACE, root)
    neural_root = root / "outputs" / "objective2" / "r52_odst_confirmation"

    rows: list[dict[str, Any]] = []
    for model, prefix in (
        ("attention_linear", "attention_linear_seed"),
        ("odst", "odst_seed"),
    ):
        for seed in SEEDS:
            path = neural_root / f"{prefix}{seed}" / "summary.json"
            if not path.exists():
                raise ProtocolAccessError(f"Missing neural summary: {path}")
            rows.append(_neural_row(model, seed, _load_json(path)))

    for s in classical_summaries:
        rows.append(_classical_row(s))

    all_df = pd.DataFrame(rows)
    conv_df = all_df[all_df["model"].isin(["xgboost", "random_forest"])].copy()
    all_summary = _summarise(all_df)
    conv_summary = _summarise(conv_df)

    for path, df in (
        (out / "r52_conventional_baseline_comparison.csv", conv_df),
        (out / "r52_conventional_baseline_summary.csv", conv_summary),
        (out / "r52_all_validation_model_comparison.csv", all_df),
        (out / "r52_all_validation_model_summary.csv", all_summary),
    ):
        refuse_overwrite(path)
        df.to_csv(path, index=False)

    attn_mean = float(all_summary.loc[all_summary["model"] == "attention_linear", "pr_auc_mean"].iloc[0])
    odst_mean = float(all_summary.loc[all_summary["model"] == "odst", "pr_auc_mean"].iloc[0])

    statuses: dict[str, str] = {}
    for model in ("xgboost", "random_forest"):
        mean_pr = float(all_summary.loc[all_summary["model"] == model, "pr_auc_mean"].iloc[0])
        statuses[model] = _status_for_conventional(mean_pr, attn_mean, odst_mean)

    # Completeness checks for preregistration readiness.
    required_dirs = [
        *[out / f"xgboost_seed{s}" for s in SEEDS],
        *[out / f"random_forest_seed{s}" for s in SEEDS],
    ]
    complete = True
    missing: list[str] = []
    for d in required_dirs:
        for name in ("summary.json", "threshold.json", "model_hash.json"):
            p = d / name
            if not p.exists():
                complete = False
                missing.append(str(p))
        # model artefact
        if not (d / "model.json").exists() and not (d / "model.joblib").exists():
            complete = False
            missing.append(str(d / "model.*"))

    if complete and missing == []:
        overall = "validation_models_ready_for_test_preregistration"
    else:
        overall = "implementation_failure"

    interpretation = {
        "conventional_model_status": statuses,
        "status_rule": {
            "strong_conventional_baseline": "mean PR-AUC within 0.02 of min(attention_linear, odst) mean",
            "competitive_conventional_baseline": "mean PR-AUC within 0.10 of min(attention_linear, odst) mean",
            "weak_conventional_baseline": "mean PR-AUC more than 0.10 below neural floor",
        },
        "neural_pr_auc_means": {
            "attention_linear": attn_mean,
            "odst": odst_mean,
        },
        "overall_validation_status": overall,
        "missing_artefacts": missing,
        "test_evaluated": False,
        "r52_test_accessed": False,
        "r62_accessed": False,
        "r42_test_accessed": False,
        "architecture_or_hyperparameter_search": False,
    }
    write_json_atomic(out / "interpretation_status.json", interpretation)

    # Draft preregistration (no test loader).
    models_prereg: list[dict[str, Any]] = []
    for _, row in all_df.iterrows():
        models_prereg.append(
            {
                "model": row["model"],
                "seed": int(row["seed"]),
                "validation_selected_threshold": float(row["threshold"]) if pd.notna(row["threshold"]) else None,
                "model_or_checkpoint_hash": row["model_hash"],
                "validation_pr_auc": float(row["pr_auc"]) if pd.notna(row["pr_auc"]) else None,
            }
        )

    prereg = {
        "status": "draft",
        "dataset": "CERT r5.2",
        "partition_to_evaluate_later": "test",
        "models_to_evaluate": models_prereg,
        "seed_list": list(SEEDS),
        "test_metrics_to_report": [
            "PR-AUC",
            "ROC-AUC",
            "precision",
            "recall",
            "F1",
            "TP",
            "TN",
            "FP",
            "FN",
            "FPR",
            "FNR",
            "n_alerts",
            "log_loss",
            "Brier",
        ],
        "aggregation_procedure": {
            "primary": "mean and std across seeds 42/52/62 for each model family",
            "also_report": "min, max, and all individual seed values",
            "thresholds": "use each seed's validation-selected threshold; do not average thresholds for operations",
        },
        "prohibitions": [
            "no best-seed selection after test access",
            "no threshold re-selection on test",
            "no hyperparameter changes after seeing test",
            "no r6.2 access",
        ],
        "note": "This is a draft only. No test loader or test predictions were created in this task.",
    }
    write_json_atomic(out / "r52_test_preregistration_draft.json", prereg)
    return interpretation
