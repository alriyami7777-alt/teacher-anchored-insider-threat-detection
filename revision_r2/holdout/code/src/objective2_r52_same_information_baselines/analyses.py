"""Analyses, bootstrap, and claim register helpers."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, f1_score

from .constants import BOOTSTRAP_POLICY


def seed_metrics_table(summaries: list[dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for s in summaries:
        m = s["validation_metrics"]
        rows.append(
            {
                "model": s["model"],
                "panel": s.get("panel", "A"),
                "seed": s["seed"],
                "input_representation": s.get("input_representation"),
                "pr_auc": m["pr_auc"],
                "precision": m["precision"],
                "recall": m["recall"],
                "f1": m["f1"],
                "fp": m["fp"],
                "fn": m["fn"],
                "roc_auc": m.get("roc_auc"),
                "threshold": m["threshold"],
                "training_duration_sec": s.get("training_duration_sec"),
                "inference_duration_sec": s.get("inference_duration_sec"),
                "peak_gpu_memory_mb": s.get("peak_gpu_memory_mb"),
                "model_size_bytes": s.get("model_size_bytes"),
                "n_parameters": s.get("n_parameters"),
                "device": s.get("device"),
                "retrained": s.get("retrained", True),
                "comparison_label": s.get("comparison_label", "r5.2 validation comparison"),
            }
        )
    return pd.DataFrame(rows)


def model_summary_table(seed_df: pd.DataFrame) -> pd.DataFrame:
    metrics = ["pr_auc", "f1", "precision", "recall", "fp", "fn", "roc_auc", "threshold"]
    cost = ["training_duration_sec", "inference_duration_sec", "model_size_bytes", "n_parameters"]
    rows = []
    for model, g in seed_df.groupby("model"):
        row: dict[str, Any] = {
            "model": model,
            "panel": g["panel"].iloc[0],
            "input_representation": g["input_representation"].iloc[0],
            "n_seeds": int(g["seed"].nunique()),
            "comparison_label": "r5.2 validation comparison",
        }
        for k in metrics + cost:
            vals = pd.to_numeric(g[k], errors="coerce").dropna().to_numpy(dtype=float)
            if len(vals) == 0:
                row[f"{k}_mean"] = np.nan
                row[f"{k}_std"] = np.nan
                row[f"{k}_min"] = np.nan
                row[f"{k}_max"] = np.nan
            else:
                row[f"{k}_mean"] = float(vals.mean())
                row[f"{k}_std"] = float(vals.std(ddof=1)) if len(vals) > 1 else 0.0
                row[f"{k}_min"] = float(vals.min())
                row[f"{k}_max"] = float(vals.max())
        rows.append(row)
    return pd.DataFrame(rows)


def pairwise_comparisons(summary_df: pd.DataFrame) -> pd.DataFrame:
    """Mean PR-AUC / F1 differences for predeclared analysis pairs."""
    means = summary_df.set_index("model")
    pairs = [
        ("A1", "random_forest_flat260", "xgboost_flat260", "same_information_trees"),
        ("A1", "xgboost_flat260", "teacher_anchored_odst_seq", "tree_vs_teacher_anchored"),
        ("A1", "random_forest_flat260", "teacher_anchored_odst_seq", "rf_vs_teacher_anchored"),
        ("A1", "xgboost_flat260", "attention_linear_seq", "xgb_vs_attention_linear"),
        ("A3", "logistic_regression_flat260", "mlp_flat260", "linear_vs_mlp"),
        ("A3", "mlp_flat260", "attention_linear_seq", "mlp_vs_sequential"),
        ("A3", "logistic_regression_flat260", "attention_linear_seq", "linear_vs_sequential"),
        ("A3", "attention_linear_seq", "teacher_anchored_odst_seq", "sequential_vs_odst_head"),
        ("A4", "attention_linear_seq", "teacher_anchored_odst_seq", "odst_head_value"),
        ("A2", "random_forest_flat260", "engineered_random_forest_40", "feature_engineering_rf"),
        ("A2", "xgboost_flat260", "engineered_xgboost_40", "feature_engineering_xgb"),
    ]
    rows = []
    for analysis, a, b, tag in pairs:
        if a not in means.index or b not in means.index:
            rows.append(
                {
                    "analysis": analysis,
                    "tag": tag,
                    "model_a": a,
                    "model_b": b,
                    "status": "missing_model",
                }
            )
            continue
        ra = float(means.loc[a, "pr_auc_mean"])
        rb = float(means.loc[b, "pr_auc_mean"])
        fa = float(means.loc[a, "f1_mean"])
        fb = float(means.loc[b, "f1_mean"])
        rows.append(
            {
                "analysis": analysis,
                "tag": tag,
                "model_a": a,
                "model_b": b,
                "pr_auc_a": ra,
                "pr_auc_b": rb,
                "delta_pr_auc_a_minus_b": ra - rb,
                "f1_a": fa,
                "f1_b": fb,
                "delta_f1_a_minus_b": fa - fb,
                "status": "ok",
                "note": "Association on r5.2 validation; not causal proof.",
            }
        )
    return pd.DataFrame(rows)


def user_bootstrap_pr_auc_f1(
    y_true: np.ndarray,
    probs_a: np.ndarray,
    probs_b: np.ndarray,
    users: np.ndarray,
    threshold_a: float,
    threshold_b: float,
    *,
    n_bootstrap: int | None = None,
    seed: int | None = None,
) -> dict[str, Any]:
    n_bootstrap = n_bootstrap or int(BOOTSTRAP_POLICY["n_bootstrap"])
    seed = seed if seed is not None else int(BOOTSTRAP_POLICY["seed"])
    rng = np.random.default_rng(seed)
    y_true = np.asarray(y_true).astype(int).ravel()
    probs_a = np.asarray(probs_a, dtype=np.float64).ravel()
    probs_b = np.asarray(probs_b, dtype=np.float64).ravel()
    users = np.asarray(users)
    codes, uniq = pd.factorize(users, sort=False)
    n_users = int(len(uniq))
    if n_users < 10:
        return {"valid": False, "reason": "insufficient_independent_user_groups"}

    # Precompute contiguous group slices via argsort for O(n) gathers.
    order = np.argsort(codes, kind="mergesort")
    sorted_codes = codes[order]
    boundaries = np.flatnonzero(np.r_[True, sorted_codes[1:] != sorted_codes[:-1], True])
    group_slices = [(boundaries[i], boundaries[i + 1]) for i in range(n_users)]

    deltas_pr: list[float] = []
    deltas_f1: list[float] = []
    for _ in range(n_bootstrap):
        chosen = rng.integers(0, n_users, size=n_users)
        parts = [order[group_slices[i][0] : group_slices[i][1]] for i in chosen]
        idx = np.concatenate(parts)
        ya = y_true[idx]
        if ya.sum() == 0 or ya.sum() == len(ya):
            continue
        pa = probs_a[idx]
        pb = probs_b[idx]
        pr_a = average_precision_score(ya, pa)
        pr_b = average_precision_score(ya, pb)
        f1_a = f1_score(ya, (pa >= threshold_a).astype(int), zero_division=0)
        f1_b = f1_score(ya, (pb >= threshold_b).astype(int), zero_division=0)
        deltas_pr.append(pr_a - pr_b)
        deltas_f1.append(f1_a - f1_b)

    if len(deltas_pr) < 100:
        return {"valid": False, "reason": "too_few_valid_bootstrap_replicates", "n_bootstrap": len(deltas_pr)}

    dpr = np.asarray(deltas_pr, dtype=float)
    df1 = np.asarray(deltas_f1, dtype=float)
    return {
        "valid": True,
        "grouping": "user",
        "n_users": n_users,
        "n_bootstrap": int(len(dpr)),
        "delta_pr_auc_mean": float(dpr.mean()),
        "delta_pr_auc_ci95_low": float(np.quantile(dpr, 0.025)),
        "delta_pr_auc_ci95_high": float(np.quantile(dpr, 0.975)),
        "delta_f1_mean": float(df1.mean()),
        "delta_f1_ci95_low": float(np.quantile(df1, 0.025)),
        "delta_f1_ci95_high": float(np.quantile(df1, 0.975)),
    }


def build_bootstrap_table(
    *,
    y_val: np.ndarray,
    users: np.ndarray,
    panel_a_rows: list[dict[str, Any]],
) -> pd.DataFrame:
    by_model: dict[str, dict[int, dict[str, Any]]] = {}
    for r in panel_a_rows:
        by_model.setdefault(r["model"], {})[int(r["seed"])] = r

    pairs = [
        ("xgboost_flat260", "teacher_anchored_odst_seq"),
        ("random_forest_flat260", "teacher_anchored_odst_seq"),
        ("attention_linear_seq", "teacher_anchored_odst_seq"),
        ("mlp_flat260", "attention_linear_seq"),
        ("logistic_regression_flat260", "mlp_flat260"),
        ("xgboost_flat260", "attention_linear_seq"),
    ]
    out = []
    for a, b in pairs:
        if a not in by_model or b not in by_model:
            out.append({"model_a": a, "model_b": b, "valid": False, "reason": "missing_model"})
            continue
        # Use seed 42 predictions where available for paired comparison.
        if 42 not in by_model[a] or 42 not in by_model[b]:
            out.append({"model_a": a, "model_b": b, "valid": False, "reason": "seed42_missing"})
            continue
        ra = by_model[a][42]
        rb = by_model[b][42]
        if "y_proba" not in ra or "y_proba" not in rb:
            out.append({"model_a": a, "model_b": b, "valid": False, "reason": "probs_unavailable"})
            continue
        boot = user_bootstrap_pr_auc_f1(
            y_val,
            ra["y_proba"],
            rb["y_proba"],
            users,
            float(ra["validation_metrics"]["threshold"]),
            float(rb["validation_metrics"]["threshold"]),
        )
        out.append({"model_a": a, "model_b": b, "seed": 42, **boot})
    return pd.DataFrame(out)


def claim_register(pairwise: pd.DataFrame, bootstrap: pd.DataFrame) -> pd.DataFrame:
    claims = [
        {
            "claim_id": "C1",
            "claim": "RF/XGBoost retain an advantage under identical 260-value inputs if their same-information PR-AUC exceeds sequential models.",
            "support_type": "supported_if_measured",
            "panel": "A",
            "caveat": "r5.2 validation comparison only; not independent test confirmation.",
        },
        {
            "claim_id": "C2",
            "claim": "A portion of historical RF/XGBoost advantage is associated with engineered 40-feature summaries versus flat 260 values.",
            "support_type": "qualified_association",
            "panel": "A_vs_B",
            "caveat": "Association, not causal proof; Panel B inputs are not identical.",
        },
        {
            "claim_id": "C3",
            "claim": "Sequential processing offers measurable value over flat logistic/MLP if attention-linear or ODST exceeds them on PR-AUC under same values.",
            "support_type": "supported_if_measured",
            "panel": "A",
            "caveat": "Same-information validation comparison only.",
        },
        {
            "claim_id": "C4",
            "claim": "ODST head improves predictive metrics over attention-linear if deltas are positive.",
            "support_type": "supported_if_measured",
            "panel": "A",
            "caveat": "Explanation capability is not predictive superiority.",
        },
        {
            "claim_id": "C5",
            "claim": "Added neural complexity is justified solely by predictive superiority.",
            "support_type": "unsupported_unless_results_show",
            "panel": "A",
            "caveat": "Complexity may instead be justified by temporal/explanation capability.",
        },
        {
            "claim_id": "C6",
            "claim": "RF/XGBoost are unfair baselines.",
            "support_type": "unsupported",
            "panel": "n/a",
            "caveat": "Explicitly forbidden unsupported conclusion.",
        },
        {
            "claim_id": "C7",
            "claim": "This study is an independent test confirmation.",
            "support_type": "unsupported",
            "panel": "n/a",
            "caveat": "Validation used for thresholding and comparison.",
        },
    ]
    df = pd.DataFrame(claims)
    df["pairwise_rows_available"] = len(pairwise)
    df["bootstrap_rows_available"] = len(bootstrap)
    return df
