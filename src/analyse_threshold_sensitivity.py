#!/usr/bin/env python3
"""
Threshold-sensitivity analysis for standalone Bi-LSTM and Soft Decision Forest models.

Preliminary standalone-model analysis (Research Objective 2 / Chapter 3 Phase 2).
Loads saved validation and test prediction probabilities; does not retrain models.

Threshold selection uses validation data only. Test metrics are reported for
sensitivity analysis after the validation-based threshold is fixed.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.metrics import (
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
)

# ---------------------------------------------------------------------------
# Model configuration
# ---------------------------------------------------------------------------

MODELS = {
    "bilstm": {
        "display_name": "Bi-LSTM",
        "val_predictions": "outputs/baselines/bilstm/bilstm_T20_s1_val_predictions.parquet",
        "test_predictions": "outputs/baselines/bilstm/bilstm_T20_s1_test_predictions.parquet",
        "threshold_json": "outputs/baselines/bilstm/bilstm_T20_s1_threshold.json",
        "checkpoint": "outputs/baselines/bilstm/bilstm_T20_s1_checkpoint.pt",
        "reported_threshold": 0.76,
        "reported_test": {
            "tp": 75,
            "fn": 9,
            "fp": 71,
            "precision": 0.514,
            "recall": 0.893,
            "f1": 0.652,
        },
        "csv_prefix": "threshold_sensitivity_bilstm",
        "figure_name": "bilstm_threshold_sensitivity.png",
    },
    "soft_forest": {
        "display_name": "Soft Decision Forest",
        "val_predictions": "outputs/baselines/soft_decision_forest/sdf_T20_s1_val_predictions.parquet",
        "test_predictions": "outputs/baselines/soft_decision_forest/sdf_T20_s1_test_predictions.parquet",
        "threshold_json": "outputs/baselines/soft_decision_forest/sdf_T20_s1_threshold.json",
        "checkpoint": "outputs/baselines/soft_decision_forest/sdf_T20_s1_checkpoint.pt",
        "reported_threshold": 0.86,
        "reported_test": {
            "tp": 54,
            "fn": 30,
            "fp": 75,
            "precision": 0.419,
            "recall": 0.643,
            "f1": 0.507,
        },
        "csv_prefix": "threshold_sensitivity_soft_forest",
        "figure_name": "soft_forest_threshold_sensitivity.png",
    },
}


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def resolve(root: Path, rel: str | Path) -> Path:
    path = Path(rel)
    return path if path.is_absolute() else root / path


def build_threshold_grid(extra: float | None = None) -> np.ndarray:
    """Thresholds from 0.05 to 0.95 (step 0.05), plus any model-specific values."""
    grid = np.round(np.arange(0.05, 1.0, 0.05), 2)
    if extra is not None:
        grid = np.unique(np.concatenate([grid, np.array([float(extra)])]))
    return np.sort(grid)


def metrics_at_threshold(y_true: np.ndarray, y_prob: np.ndarray, threshold: float) -> dict:
    """
    Convert probabilities to hard predictions and compute classification metrics.

    Prediction rule: y_pred = 1 if y_prob >= threshold, else 0.
    This is the standard binary decision rule for probabilistic classifiers.
    """
    y_pred = (y_prob >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()
    fpr = float(fp / (fp + tn)) if (fp + tn) else 0.0
    fnr = float(fn / (fn + tp)) if (fn + tp) else 0.0
    return {
        "threshold": float(threshold),
        "true_positives": int(tp),
        "true_negatives": int(tn),
        "false_positives": int(fp),
        "false_negatives": int(fn),
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "f1_score": float(f1_score(y_true, y_pred, zero_division=0)),
        "false_positive_rate": fpr,
        "false_negative_rate": fnr,
    }


def sweep_thresholds(y_true: np.ndarray, y_prob: np.ndarray, thresholds: np.ndarray) -> pd.DataFrame:
    rows = [metrics_at_threshold(y_true, y_prob, float(t)) for t in thresholds]
    return pd.DataFrame(rows)


def select_validation_threshold(val_df: pd.DataFrame) -> float:
    """
    Pick the threshold with the highest validation F1-score.

    Threshold selection must use validation data rather than test data because
    the test set must remain an unbiased, held-out estimate of generalisation.
    Optimising on test labels would leak test information into the decision rule
    and produce optimistically biased performance estimates.
    """
    best_idx = val_df["f1_score"].idxmax()
    return float(val_df.loc[best_idx, "threshold"])


def load_predictions(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """
    Load saved labels and probabilities from evaluation parquet files.

    Assumes columns y_true (int) and y_prob (float32) as written by
    run_bilstm_baseline.py and run_soft_decision_forest.py.
    """
    df = pd.read_parquet(path)
    if "y_true" not in df.columns or "y_prob" not in df.columns:
        raise ValueError(f"{path} must contain y_true and y_prob columns")
    return df["y_true"].to_numpy(), df["y_prob"].to_numpy()


def plot_threshold_sensitivity(
    val_df: pd.DataFrame,
    model_name: str,
    selected_threshold: float,
    out_path: Path,
) -> None:
    """Precision, recall, and F1 vs threshold; mark validation-selected threshold."""
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(val_df["threshold"], val_df["precision"], label="Precision", linewidth=2)
    ax.plot(val_df["threshold"], val_df["recall"], label="Recall", linewidth=2)
    ax.plot(val_df["threshold"], val_df["f1_score"], label="F1-score", linewidth=2)
    ax.axvline(
        selected_threshold,
        color="black",
        linestyle="--",
        linewidth=1.5,
        label=f"Validation-selected ({selected_threshold:.2f})",
    )
    ax.set_xlabel("Classification threshold")
    ax.set_ylabel("Score")
    ax.set_title(f"{model_name}: threshold sensitivity (validation sweep)")
    ax.set_xlim(0.0, 1.0)
    ax.set_ylim(0.0, 1.05)
    ax.grid(True, alpha=0.3)
    ax.legend(loc="best")
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def compare_reported(
    model_key: str,
    cfg: dict,
    test_df: pd.DataFrame,
    root: Path,
) -> None:
    """Check whether Chapter 4 reported test metrics reproduce at the historical threshold."""
    reported_thr = cfg["reported_threshold"]
    reported = cfg["reported_test"]
    row = test_df.loc[np.isclose(test_df["threshold"], reported_thr)]
    if row.empty:
        print(f"\n[{cfg['display_name']}] Reproduction check at threshold {reported_thr:.2f}:")
        print("  WARNING: reported threshold not present in sweep grid.")
        return

    r = row.iloc[0]
    fields = ["true_positives", "false_negatives", "false_positives", "precision", "recall", "f1_score"]
    print(f"\n[{cfg['display_name']}] Reproduction check at reported threshold {reported_thr:.2f}:")
    print(f"  Source checkpoint: {resolve(root, cfg['checkpoint'])}")
    print(f"  Source predictions: {resolve(root, cfg['test_predictions'])}")
    thr_json = resolve(root, cfg["threshold_json"])
    if thr_json.exists():
        payload = json.loads(thr_json.read_text(encoding="utf-8"))
        print(f"  Original evaluation selected threshold: {payload.get('selected_threshold')}")

    mismatches = []
    mapping = {
        "true_positives": "tp",
        "false_negatives": "fn",
        "false_positives": "fp",
        "precision": "precision",
        "recall": "recall",
        "f1_score": "f1",
    }
    for col, key in mapping.items():
        repro = r[col]
        expected = reported[key]
        if key in ("tp", "fn", "fp"):
            diff = int(repro) - int(expected)
            match = diff == 0
        else:
            diff = float(repro) - float(expected)
            match = abs(diff) < 0.01
        status = "OK" if match else "DIFF"
        print(f"  {col}: reproduced={repro:.4f}" if isinstance(repro, float) else f"  {col}: reproduced={int(repro)}", end="")
        print(f", reported={expected}, diff={diff:+.4f}" if isinstance(diff, float) else f", reported={expected}, diff={diff:+d}", end="")
        print(f" [{status}]")
        if not match:
            mismatches.append((col, repro, expected, diff))

    if mismatches:
        print("  Likely reason for differences: different prediction files, checkpoint, or")
        print("  threshold grid relative to the original evaluation run.")
        print("  Chapter 4 tables are NOT modified by this script.")
    else:
        print("  All reported values reproduced within tolerance.")


def analyse_model(model_key: str, cfg: dict, root: Path, results_dir: Path, figures_dir: Path) -> dict:
    val_path = resolve(root, cfg["val_predictions"])
    test_path = resolve(root, cfg["test_predictions"])
    for path in (val_path, test_path):
        if not path.exists():
            raise FileNotFoundError(f"Missing prediction file: {path}")

    y_val, p_val = load_predictions(val_path)
    y_test, p_test = load_predictions(test_path)

    thresholds = build_threshold_grid(extra=cfg["reported_threshold"])
    val_df = sweep_thresholds(y_val, p_val, thresholds)
    test_df = sweep_thresholds(y_test, p_test, thresholds)

    selected_thr = select_validation_threshold(val_df)
    val_at_sel = val_df.loc[np.isclose(val_df["threshold"], selected_thr)].iloc[0]
    test_at_sel = test_df.loc[np.isclose(test_df["threshold"], selected_thr)].iloc[0]

    results_dir.mkdir(parents=True, exist_ok=True)
    val_csv = results_dir / f"{cfg['csv_prefix']}_validation.csv"
    test_csv = results_dir / f"{cfg['csv_prefix']}_test.csv"
    val_df.to_csv(val_csv, index=False)
    test_df.to_csv(test_csv, index=False)

    plot_threshold_sensitivity(
        val_df,
        cfg["display_name"],
        selected_thr,
        figures_dir / cfg["figure_name"],
    )

    compare_reported(model_key, cfg, test_df, root)

    return {
        "model": cfg["display_name"],
        "selected_threshold": selected_thr,
        "validation_precision": float(val_at_sel["precision"]),
        "validation_recall": float(val_at_sel["recall"]),
        "validation_f1": float(val_at_sel["f1_score"]),
        "test_precision": float(test_at_sel["precision"]),
        "test_recall": float(test_at_sel["recall"]),
        "test_f1": float(test_at_sel["f1_score"]),
        "test_fp": int(test_at_sel["false_positives"]),
        "test_fn": int(test_at_sel["false_negatives"]),
        "val_csv": val_csv,
        "test_csv": test_csv,
        "figure": figures_dir / cfg["figure_name"],
    }


def print_summary(summaries: list[dict]) -> None:
    print("\n" + "=" * 72)
    print("THRESHOLD SENSITIVITY SUMMARY (preliminary standalone-model analysis)")
    print("=" * 72)
    for s in summaries:
        print(f"\n{s['model']}")
        print(f"  Validation-selected threshold (max validation F1): {s['selected_threshold']:.2f}")
        print(
            f"  Validation @ selected: P={s['validation_precision']:.4f}, "
            f"R={s['validation_recall']:.4f}, F1={s['validation_f1']:.4f}"
        )
        print(
            f"  Test @ selected (fixed): P={s['test_precision']:.4f}, "
            f"R={s['test_recall']:.4f}, F1={s['test_f1']:.4f}"
        )
        print(f"  Test @ selected: FP={s['test_fp']}, FN={s['test_fn']}")

    print("\n" + "-" * 72)
    print("Threshold interpretation (standalone preliminary analysis):")
    print("  - Lowering the threshold classifies more samples as positive (y_pred=1).")
    print("  - Recall normally increases because more true positives are captured.")
    print("  - Precision often falls and false positives rise for the same reason.")
    print("  - Validation-only threshold selection preserves an unbiased test estimate.")
    print("-" * 72)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Threshold-sensitivity analysis for Bi-LSTM and Soft Decision Forest."
    )
    p.add_argument(
        "--results-dir",
        type=Path,
        default=None,
        help="Directory for CSV outputs (default: <repo>/results)",
    )
    p.add_argument(
        "--figures-dir",
        type=Path,
        default=None,
        help="Directory for figures (default: <repo>/results/figures)",
    )
    p.add_argument(
        "--models",
        nargs="+",
        choices=list(MODELS.keys()),
        default=list(MODELS.keys()),
        help="Models to analyse (default: both)",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    root = repo_root()
    results_dir = args.results_dir or (root / "results")
    figures_dir = args.figures_dir or (results_dir / "figures")

    summaries = []
    for key in args.models:
        summaries.append(analyse_model(key, MODELS[key], root, results_dir, figures_dir))

    print_summary(summaries)

    print("\nGenerated files:")
    for s in summaries:
        print(f"  {s['val_csv']}")
        print(f"  {s['test_csv']}")
        print(f"  {s['figure']}")


if __name__ == "__main__":
    main()
