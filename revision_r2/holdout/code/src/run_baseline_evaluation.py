#!/usr/bin/env python3
"""Preliminary baseline evaluation on CERT r4.2 sequence features (no deep models)."""

from __future__ import annotations

import argparse
import csv
import re
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from xgboost import XGBClassifier

EXPECTED_FEATS = 40
META_COLS = {
    "sequence_id",
    "user",
    "split",
    "start_date",
    "end_date",
    "window_length",
    "stride",
    "y",
}
FORBIDDEN_RE = re.compile(
    r"(^y$|is_malicious|malicious|label|insider|scenario|answer)",
    re.IGNORECASE,
)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def select_model_features(columns: list[str]) -> list[str]:
    feats = [c for c in columns if c not in META_COLS and not FORBIDDEN_RE.search(c)]
    if len(feats) != EXPECTED_FEATS:
        raise SystemExit(
            f"Expected {EXPECTED_FEATS} model features; found {len(feats)}: {feats}"
        )
    return feats


def binary_rates(y_true: np.ndarray, y_pred: np.ndarray) -> tuple[float, float]:
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()
    fpr = fp / (fp + tn) if (fp + tn) else 0.0
    fnr = fn / (fn + tp) if (fn + tp) else 0.0
    return float(fpr), float(fnr)


def predict_proba_positive(model, x: np.ndarray) -> np.ndarray:
    if hasattr(model, "predict_proba"):
        proba = model.predict_proba(x)
        # Positive class column.
        if proba.shape[1] == 1:
            return proba[:, 0]
        classes = list(getattr(model, "classes_", [0, 1]))
        if 1 in classes:
            return proba[:, classes.index(1)]
        return proba[:, -1]
    if hasattr(model, "decision_function"):
        scores = model.decision_function(x)
        # Map to [0,1] via rank-preserving sigmoid-like transform for threshold search.
        scores = scores.astype(np.float64)
        return 1.0 / (1.0 + np.exp(-scores))
    pred = model.predict(x).astype(np.float64)
    return pred


def choose_threshold(y_val: np.ndarray, p_val: np.ndarray) -> tuple[float, float]:
    """Grid-search threshold on validation F1; return (threshold, best_f1)."""
    # Include endpoints and dense grid; also unique probability quantiles for robustness.
    candidates = set(np.linspace(0.01, 0.99, 99).tolist())
    qs = np.quantile(p_val, np.linspace(0.01, 0.99, 50))
    candidates.update(float(q) for q in qs)
    best_t, best_f1 = 0.5, -1.0
    for t in sorted(candidates):
        y_hat = (p_val >= t).astype(int)
        f1 = f1_score(y_val, y_hat, zero_division=0)
        if f1 > best_f1:
            best_f1 = float(f1)
            best_t = float(t)
    return best_t, best_f1


def evaluate_split(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    y_proba: np.ndarray,
) -> dict:
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()
    fpr, fnr = binary_rates(y_true, y_pred)
    # Guard AUC when only one class present (should not happen here).
    try:
        pr_auc = float(average_precision_score(y_true, y_proba))
    except ValueError:
        pr_auc = float("nan")
    try:
        roc_auc = float(roc_auc_score(y_true, y_proba))
    except ValueError:
        roc_auc = float("nan")
    return {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "f1": float(f1_score(y_true, y_pred, zero_division=0)),
        "pr_auc": pr_auc,
        "roc_auc": roc_auc,
        "false_positive_rate": fpr,
        "false_negative_rate": fnr,
        "tn": int(tn),
        "fp": int(fp),
        "fn": int(fn),
        "tp": int(tp),
    }


def run_model(
    name: str,
    model,
    x_train: np.ndarray,
    y_train: np.ndarray,
    x_val: np.ndarray,
    y_val: np.ndarray,
    x_test: np.ndarray,
    y_test: np.ndarray,
    fixed_threshold: float | None = None,
) -> tuple[list[dict], list[dict], dict]:
    t0 = time.perf_counter()
    model.fit(x_train, y_train)
    train_time = time.perf_counter() - t0

    t1 = time.perf_counter()
    p_val = predict_proba_positive(model, x_val)
    p_test = predict_proba_positive(model, x_test)
    infer_time = time.perf_counter() - t1

    if fixed_threshold is None:
        threshold, val_f1_at_t = choose_threshold(y_val, p_val)
    else:
        threshold = fixed_threshold
        val_f1_at_t = float(
            f1_score(y_val, (p_val >= threshold).astype(int), zero_division=0)
        )

    y_val_pred = (p_val >= threshold).astype(int)
    y_test_pred = (p_test >= threshold).astype(int)

    metrics_rows = []
    cm_rows = []
    for split_name, yt, yp, pp in (
        ("validation", y_val, y_val_pred, p_val),
        ("test", y_test, y_test_pred, p_test),
    ):
        m = evaluate_split(yt, yp, pp)
        metrics_rows.append(
            {
                "model": name,
                "split": split_name,
                "threshold": threshold,
                "accuracy": m["accuracy"],
                "precision": m["precision"],
                "recall": m["recall"],
                "f1": m["f1"],
                "pr_auc": m["pr_auc"],
                "roc_auc": m["roc_auc"],
                "false_positive_rate": m["false_positive_rate"],
                "false_negative_rate": m["false_negative_rate"],
                "training_time_sec": train_time,
                "inference_time_sec": infer_time,
            }
        )
        cm_rows.append(
            {
                "model": name,
                "split": split_name,
                "threshold": threshold,
                "tn": m["tn"],
                "fp": m["fp"],
                "fn": m["fn"],
                "tp": m["tp"],
            }
        )

    threshold_row = {
        "model": name,
        "selected_threshold": threshold,
        "selection_criterion": "max_validation_f1",
        "validation_f1_at_selected_threshold": val_f1_at_t,
        "training_time_sec": train_time,
        "inference_time_sec_val_plus_test": infer_time,
    }
    return metrics_rows, cm_rows, threshold_row


def update_chapter4_manifest(path: Path) -> None:
    df = pd.read_csv(path)
    df = df.loc[df["step_number"] != 13].copy()
    new_row = {
        "step_number": 13,
        "chapter4_section": "1.5 Initial Baseline Evaluation",
        "related_research_objective": "Objective 1 and Objective 2 preparation",
        "input_files": "data/processed/sequences/r42_T20_s1_sequence_feature_table.parquet",
        "script_used": "scripts/run_baseline_evaluation.py",
        "output_files": (
            "outputs/baselines/r42_T20_s1_baseline_metrics.csv; "
            "outputs/baselines/r42_T20_s1_confusion_matrices.csv; "
            "outputs/baselines/r42_T20_s1_selected_thresholds.csv; "
            "outputs/baselines/r42_T20_s1_baseline_feature_list.csv; "
            "outputs/baselines/r42_T20_s1_baseline_summary.txt"
        ),
        "key_result": (
            "Initial RF and XGBoost baseline evaluation completed using "
            "leakage-checked sequence-level features"
        ),
        "why_this_step_matters": (
            "Establishes preliminary classical baselines under a chronological split "
            "before deep or ensemble sequence models are trained"
        ),
        "status": "Complete",
    }
    df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    df = df.sort_values("step_number").reset_index(drop=True)
    df.to_csv(path, index=False)


def write_summary(
    path: Path,
    metrics: pd.DataFrame,
    thresholds: pd.DataFrame,
    n_features: int,
    train_pos_weight: float,
) -> None:
    lines = []
    lines.append("CERT r4.2 preliminary baseline evaluation (T=20, stride=1)")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.append("Scope: preliminary only. Not final model performance.")
    lines.append("Models: Majority dummy, Random Forest, XGBoost.")
    lines.append("Bi-LSTM / differentiable ensemble: NOT trained.")
    lines.append("")
    lines.append(f"Model features used: {n_features}")
    lines.append(f"XGBoost scale_pos_weight (train-only): {train_pos_weight:.6f}")
    lines.append("Thresholds selected on validation F1; applied unchanged to test.")
    lines.append("")
    lines.append("Selected thresholds:")
    for _, row in thresholds.iterrows():
        lines.append(
            f"- {row['model']}: t={row['selected_threshold']:.6f} "
            f"(val F1={row['validation_f1_at_selected_threshold']:.6f})"
        )
    lines.append("")
    lines.append("Test metrics (preliminary):")
    test = metrics.loc[metrics["split"] == "test"].copy()
    for _, row in test.iterrows():
        lines.append(
            f"- {row['model']}: Acc={row['accuracy']:.4f}, P={row['precision']:.4f}, "
            f"R={row['recall']:.4f}, F1={row['f1']:.4f}, PR-AUC={row['pr_auc']:.4f}, "
            f"ROC-AUC={row['roc_auc']:.4f}, FPR={row['false_positive_rate']:.4f}, "
            f"FNR={row['false_negative_rate']:.4f}"
        )
    lines.append("")
    lines.append("Interpretation note: results are exploratory baselines for Chapter 4 §1.5.")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def append_notes(
    notes_path: Path,
    metrics: pd.DataFrame,
    thresholds: pd.DataFrame,
    n_features: int,
) -> None:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    test = metrics.loc[metrics["split"] == "test"]
    with notes_path.open("a", encoding="utf-8") as f:
        f.write(f"\n\n## CERT r4.2 preliminary baseline evaluation ({stamp})\n\n")
        f.write(
            "Ran initial classical baselines on the leakage-checked T=20/stride=1 "
            "sequence-level feature table. Thresholds were tuned on validation F1 and "
            "applied unchanged to test. **No Bi-LSTM or differentiable ensemble training.** "
            "Raw files unchanged. Results are preliminary only.\n\n"
        )
        f.write(f"Model features used: **{n_features}** (confirmed).\n\n")
        f.write("### Selected thresholds (validation F1)\n\n")
        for _, row in thresholds.iterrows():
            f.write(
                f"- `{row['model']}`: {row['selected_threshold']:.6f} "
                f"(val F1={row['validation_f1_at_selected_threshold']:.4f})\n"
            )
        f.write("\n### Preliminary test metrics\n\n")
        f.write("| Model | Acc | P | R | F1 | PR-AUC | ROC-AUC | FPR | FNR |\n")
        f.write("|-------|-----|---|---|----|--------|---------|-----|-----|\n")
        for _, row in test.iterrows():
            f.write(
                f"| {row['model']} | {row['accuracy']:.4f} | {row['precision']:.4f} | "
                f"{row['recall']:.4f} | {row['f1']:.4f} | {row['pr_auc']:.4f} | "
                f"{row['roc_auc']:.4f} | {row['false_positive_rate']:.4f} | "
                f"{row['false_negative_rate']:.4f} |\n"
            )
        f.write("\n### Outputs\n\n")
        f.write("- `outputs/baselines/r42_T20_s1_baseline_metrics.csv`\n")
        f.write("- `outputs/baselines/r42_T20_s1_confusion_matrices.csv`\n")
        f.write("- `outputs/baselines/r42_T20_s1_selected_thresholds.csv`\n")
        f.write("- `outputs/baselines/r42_T20_s1_baseline_feature_list.csv`\n")
        f.write("- `outputs/baselines/r42_T20_s1_baseline_summary.txt`\n")
        f.write("- Updated `outputs/chapter4/chapter4_results_manifest.csv` (Step 13)\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run preliminary CERT r4.2 baseline evaluation."
    )
    parser.add_argument(
        "--features",
        default="data/processed/sequences/r42_T20_s1_sequence_feature_table.parquet",
    )
    parser.add_argument("--output-dir", default="outputs/baselines")
    args = parser.parse_args()

    root = repo_root()
    feat_path = Path(args.features)
    if not feat_path.is_absolute():
        feat_path = (root / feat_path).resolve()
    out_dir = Path(args.output_dir)
    if not out_dir.is_absolute():
        out_dir = (root / out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 90)
    print("CERT r4.2 preliminary baseline evaluation")
    print("=" * 90)
    print(f"Input: {feat_path}")

    df = pd.read_parquet(feat_path)
    feature_cols = select_model_features(list(df.columns))
    print(f"Confirmed model features: {len(feature_cols)}")

    train = df.loc[df["split"] == "train"]
    val = df.loc[df["split"] == "validation"]
    test = df.loc[df["split"] == "test"]

    x_train = train[feature_cols].to_numpy(dtype=np.float32)
    y_train = train["y"].to_numpy(dtype=np.int32)
    x_val = val[feature_cols].to_numpy(dtype=np.float32)
    y_val = val["y"].to_numpy(dtype=np.int32)
    x_test = test[feature_cols].to_numpy(dtype=np.float32)
    y_test = test["y"].to_numpy(dtype=np.int32)

    n_pos = int((y_train == 1).sum())
    n_neg = int((y_train == 0).sum())
    scale_pos_weight = (n_neg / n_pos) if n_pos else 1.0
    print(f"Train class counts: neg={n_neg:,}, pos={n_pos:,}")
    print(f"XGBoost scale_pos_weight (train-only): {scale_pos_weight:.6f}")

    models = [
        (
            "majority_dummy",
            DummyClassifier(strategy="most_frequent"),
            None,  # threshold unused meaningfully; still run search on constant scores
        ),
        (
            "random_forest",
            RandomForestClassifier(
                n_estimators=200,
                max_depth=20,
                min_samples_leaf=2,
                n_jobs=-1,
                class_weight="balanced_subsample",
                random_state=42,
            ),
            None,
        ),
        (
            "xgboost",
            XGBClassifier(
                n_estimators=300,
                max_depth=6,
                learning_rate=0.1,
                subsample=0.8,
                colsample_bytree=0.8,
                reg_lambda=1.0,
                objective="binary:logistic",
                eval_metric="aucpr",
                scale_pos_weight=scale_pos_weight,
                n_jobs=-1,
                random_state=42,
                tree_method="hist",
            ),
            None,
        ),
    ]

    all_metrics: list[dict] = []
    all_cms: list[dict] = []
    all_thresholds: list[dict] = []

    for name, model, fixed_t in models:
        print(f"\nTraining {name} ...")
        # Dummy: probabilities are constant 0 for majority class; force threshold 0.5
        # so predictions remain majority class (all zeros).
        if name == "majority_dummy":
            fixed_t = 0.5
        m_rows, cm_rows, t_row = run_model(
            name,
            model,
            x_train,
            y_train,
            x_val,
            y_val,
            x_test,
            y_test,
            fixed_threshold=fixed_t,
        )
        all_metrics.extend(m_rows)
        all_cms.extend(cm_rows)
        all_thresholds.append(t_row)
        test_row = next(r for r in m_rows if r["split"] == "test")
        print(
            f"  done: test F1={test_row['f1']:.4f}, PR-AUC={test_row['pr_auc']:.4f}, "
            f"threshold={t_row['selected_threshold']:.4f}, "
            f"train_s={t_row['training_time_sec']:.1f}"
        )

    metrics_df = pd.DataFrame(all_metrics)
    cm_df = pd.DataFrame(all_cms)
    thr_df = pd.DataFrame(all_thresholds)

    metrics_path = out_dir / "r42_T20_s1_baseline_metrics.csv"
    cm_path = out_dir / "r42_T20_s1_confusion_matrices.csv"
    thr_path = out_dir / "r42_T20_s1_selected_thresholds.csv"
    feat_list_path = out_dir / "r42_T20_s1_baseline_feature_list.csv"
    summary_path = out_dir / "r42_T20_s1_baseline_summary.txt"

    metrics_df.to_csv(metrics_path, index=False)
    cm_df.to_csv(cm_path, index=False)
    thr_df.to_csv(thr_path, index=False)

    with feat_list_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["feature_index", "feature_name", "used_as_model_feature"],
        )
        writer.writeheader()
        for i, name in enumerate(feature_cols):
            writer.writerow(
                {
                    "feature_index": i,
                    "feature_name": name,
                    "used_as_model_feature": True,
                }
            )

    write_summary(summary_path, metrics_df, thr_df, len(feature_cols), scale_pos_weight)
    update_chapter4_manifest(root / "outputs" / "chapter4" / "chapter4_results_manifest.csv")
    append_notes(root / "docs" / "cert_r42_notes.md", metrics_df, thr_df, len(feature_cols))

    print()
    print("Saved:")
    print(f"  {metrics_path}")
    print(f"  {cm_path}")
    print(f"  {thr_path}")
    print(f"  {feat_list_path}")
    print(f"  {summary_path}")
    print("Updated Chapter 4 manifest Step 13 and notes.")


if __name__ == "__main__":
    main()
