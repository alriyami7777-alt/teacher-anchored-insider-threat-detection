#!/usr/bin/env python3
"""
Compare validation-based threshold-selection criteria for standalone Bi-LSTM and
Soft Decision Forest models.

Preliminary standalone-model analysis (Research Objective 2 / Chapter 3 Phase 2).
Uses saved prediction probabilities only; does not retrain models.

Criteria compared:
  - default threshold (0.50);
  - maximum validation F1-score;
  - maximum validation Youden's J (recall - false_positive_rate).

Threshold selection uses validation data only. Test metrics are diagnostic only.
"""

from __future__ import annotations

import argparse
from pathlib import Path

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
        "reported_f1_threshold": 0.76,
    },
    "soft_forest": {
        "display_name": "Soft Decision Forest",
        "val_predictions": "outputs/baselines/soft_decision_forest/sdf_T20_s1_val_predictions.parquet",
        "test_predictions": "outputs/baselines/soft_decision_forest/sdf_T20_s1_test_predictions.parquet",
        "reported_f1_threshold": 0.86,
    },
}

DEFAULT_THRESHOLD = 0.50
CRITERIA = ("default_0.50", "max_validation_f1", "max_validation_youden_j")


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def resolve(root: Path, rel: str | Path) -> Path:
    path = Path(rel)
    return path if path.is_absolute() else root / path


def build_threshold_grid(probs: np.ndarray) -> list[float]:
    """
    Original threshold grid from run_bilstm_baseline.py / run_soft_decision_forest.py:
    linspace(0.01, 0.99, 99) union validation probability quantiles.
    """
    candidates = set(np.linspace(0.01, 0.99, 99).tolist())
    candidates.update(float(q) for q in np.quantile(probs, np.linspace(0.01, 0.99, 50)))
    return sorted(candidates)


def load_predictions(path: Path) -> tuple[np.ndarray, np.ndarray]:
    df = pd.read_parquet(path)
    if "y_true" not in df.columns or "y_prob" not in df.columns:
        raise ValueError(f"{path} must contain y_true and y_prob columns")
    return df["y_true"].to_numpy(), df["y_prob"].to_numpy()


def metrics_at_threshold(y_true: np.ndarray, y_prob: np.ndarray, threshold: float) -> dict:
    """
    Prediction rule: y_pred = 1 if y_prob >= threshold, else 0.
    Youden's J = recall - false_positive_rate (equivalently TPR - FPR).
    """
    y_pred = (y_prob >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()
    fpr = float(fp / (fp + tn)) if (fp + tn) else 0.0
    fnr = float(fn / (fn + tp)) if (fn + tp) else 0.0
    recall = float(recall_score(y_true, y_pred, zero_division=0))
    youden_j = recall - fpr
    alert_count = int(tp + fp)
    return {
        "threshold": float(threshold),
        "TP": int(tp),
        "TN": int(tn),
        "FP": int(fp),
        "FN": int(fn),
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": recall,
        "f1_score": float(f1_score(y_true, y_pred, zero_division=0)),
        "false_positive_rate": fpr,
        "false_negative_rate": fnr,
        "youden_j": float(youden_j),
        "alert_count": alert_count,
    }


def sweep_validation(y_true: np.ndarray, y_prob: np.ndarray, grid: list[float]) -> pd.DataFrame:
    rows = [metrics_at_threshold(y_true, y_prob, t) for t in grid]
    return pd.DataFrame(rows)


def select_max_f1(val_df: pd.DataFrame, grid: list[float]) -> tuple[float, str | None]:
    """
    Tie-breaking matches run_bilstm_baseline.py / run_soft_decision_forest.py:
    iterate thresholds in ascending order; update only when f1 strictly increases.
    On ties, the lowest threshold among tied values is retained.
    """
    best_t, best_f1 = 0.5, -1.0
    tied: list[float] = []
    for t in grid:
        row = val_df.loc[np.isclose(val_df["threshold"], t)].iloc[0]
        f1 = float(row["f1_score"])
        if f1 > best_f1:
            best_f1 = f1
            best_t = float(t)
            tied = [best_t]
        elif np.isclose(f1, best_f1):
            tied.append(float(t))
    tie_note = None
    if len(tied) > 1:
        tie_note = (
            f"F1 tie at {best_f1:.4f} across {len(tied)} thresholds; "
            f"selected lowest threshold {best_t:.4f} (ascending tie-break)."
        )
    return best_t, tie_note


def select_max_youden_j(val_df: pd.DataFrame, grid: list[float]) -> tuple[float, str | None]:
    """
    Same ascending tie-break as F1 selection: on equal Youden's J, keep the
    lowest threshold.
    """
    best_t, best_j = 0.5, -2.0
    tied: list[float] = []
    for t in grid:
        row = val_df.loc[np.isclose(val_df["threshold"], t)].iloc[0]
        j = float(row["youden_j"])
        if j > best_j:
            best_j = j
            best_t = float(t)
            tied = [best_t]
        elif np.isclose(j, best_j):
            tied.append(float(t))
    tie_note = None
    if len(tied) > 1:
        tie_note = (
            f"Youden's J tie at {best_j:.4f} across {len(tied)} thresholds; "
            f"selected lowest threshold {best_t:.4f} (ascending tie-break)."
        )
    return best_t, tie_note


def prefix_metrics(metrics: dict, split: str) -> dict:
    return {f"{split}_{k}": v for k, v in metrics.items()}


def analyse_model(cfg: dict, root: Path) -> tuple[list[dict], list[str]]:
    y_val, p_val = load_predictions(resolve(root, cfg["val_predictions"]))
    y_test, p_test = load_predictions(resolve(root, cfg["test_predictions"]))
    grid = build_threshold_grid(p_val)
    val_df = sweep_validation(y_val, p_val, grid)

    f1_thr, f1_tie = select_max_f1(val_df, grid)
    youden_thr, youden_tie = select_max_youden_j(val_df, grid)

    selections = {
        "default_0.50": (DEFAULT_THRESHOLD, None),
        "max_validation_f1": (f1_thr, f1_tie),
        "max_validation_youden_j": (youden_thr, youden_tie),
    }

    rows: list[dict] = []
    tie_notes: list[str] = []
    for criterion, (thr, tie_note) in selections.items():
        val_m = metrics_at_threshold(y_val, p_val, thr)
        test_m = metrics_at_threshold(y_test, p_test, thr)
        row = {
            "model": cfg["display_name"],
            "selection_criterion": criterion,
            "selected_threshold": thr,
            "tie_break_note": tie_note or "",
            **prefix_metrics(val_m, "validation"),
            **prefix_metrics(test_m, "test"),
        }
        rows.append(row)
        if tie_note:
            tie_notes.append(f"{cfg['display_name']} / {criterion}: {tie_note}")

    return rows, tie_notes


def concise_table(df: pd.DataFrame, model_name: str) -> pd.DataFrame:
    cols = [
        "selection_criterion",
        "selected_threshold",
        "validation_f1_score",
        "validation_youden_j",
        "test_precision",
        "test_recall",
        "test_f1_score",
        "test_FP",
        "test_FN",
        "test_alert_count",
    ]
    sub = df.loc[df["model"] == model_name, cols].copy()
    sub.columns = [
        "criterion",
        "threshold",
        "val_F1",
        "val_Youden_J",
        "test_P",
        "test_R",
        "test_F1",
        "test_FP",
        "test_FN",
        "test_alerts",
    ]
    return sub


def print_interpretation(full_df: pd.DataFrame) -> None:
    print("\n" + "=" * 72)
    print("INTERPRETATION (diagnostic; test set not used for selection)")
    print("=" * 72)

    print(
        "\nCriterion definitions:"
        "\n  - Maximum F1 prioritises the balance between precision and recall."
        "\n  - Youden's J (recall - FPR) prioritises the balance between true-positive"
        "\n    rate and false-positive rate."
        "\n  - Because the negative class is very large, a numerically small FPR may"
        "\n    still represent a substantial number of false-positive alerts."
    )

    for model in full_df["model"].unique():
        sub = full_df.loc[full_df["model"] == model]
        f1_row = sub.loc[sub["selection_criterion"] == "max_validation_f1"].iloc[0]
        y_row = sub.loc[sub["selection_criterion"] == "max_validation_youden_j"].iloc[0]

        same = np.isclose(f1_row["selected_threshold"], y_row["selected_threshold"])
        print(f"\n--- {model} ---")
        print(
            f"  Same threshold for max F1 and max Youden's J? "
            f"{'Yes' if same else 'No'} "
            f"(F1={f1_row['selected_threshold']:.4f}, "
            f"Youden={y_row['selected_threshold']:.4f})"
        )

        # Fewer FP / higher recall / better test F1 among F1 vs Youden
        fp_winner = "max_validation_f1" if f1_row["test_FP"] < y_row["test_FP"] else (
            "max_validation_youden_j" if y_row["test_FP"] < f1_row["test_FP"] else "tie"
        )
        rec_winner = "max_validation_f1" if f1_row["test_recall"] > y_row["test_recall"] else (
            "max_validation_youden_j" if y_row["test_recall"] > f1_row["test_recall"] else "tie"
        )
        test_f1_winner = "max_validation_f1" if f1_row["test_f1_score"] > y_row["test_f1_score"] else (
            "max_validation_youden_j" if y_row["test_f1_score"] > f1_row["test_f1_score"] else "tie"
        )
        print(f"  Fewer test false positives: {fp_winner}")
        print(f"  Higher test recall: {rec_winner}")
        print(f"  Better test F1 (diagnostic only): {test_f1_winner}")

    print(
        "\nWhy F1 and Youden's J may diverge under severe class imbalance:"
        "\n  F1 weights precision and recall equally in the harmonic mean, so it"
        "\n  responds to the rarity of positives through precision. Youden's J"
        "\n  subtracts FPR from recall; with ~31k negatives, even a low FPR can"
        "\n  yield hundreds of false alerts while still appearing numerically small."
        "\n  The criteria therefore optimise different operating points on the ROC-like"
        "\n  trade-off curve."
    )
    print(
        "\nNote: test-set comparisons are diagnostic only. Do not select a criterion"
        "\nmerely because it yields the best test result."
    )


def print_f1_threshold_diff(full_df: pd.DataFrame) -> None:
    print("\n" + "-" * 72)
    print("Reproduced max-validation-F1 thresholds vs previously reported values:")
    reported = {
        "Bi-LSTM": 0.76,
        "Soft Decision Forest": 0.86,
    }
    for model, rep_thr in reported.items():
        row = full_df.loc[
            (full_df["model"] == model)
            & (full_df["selection_criterion"] == "max_validation_f1")
        ].iloc[0]
        repro = float(row["selected_threshold"])
        diff = repro - rep_thr
        status = "match" if np.isclose(repro, rep_thr, atol=1e-4) else "difference"
        print(
            f"  {model}: reproduced={repro:.4f}, reported={rep_thr:.2f}, "
            f"diff={diff:+.4f} [{status}]"
        )
    print(
        "  (Uses original evaluation grid: linspace(0.01,0.99,99) + val quantiles;"
        "\n   ascending tie-break on strict improvement, matching baseline scripts.)"
    )
    print("-" * 72)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Compare validation threshold-selection criteria for standalone models."
    )
    p.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output CSV path (default: <repo>/results/threshold_selection_criteria_comparison.csv)",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    root = repo_root()
    out_path = args.output or (root / "results" / "threshold_selection_criteria_comparison.csv")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    all_rows: list[dict] = []
    all_tie_notes: list[str] = []
    for cfg in MODELS.values():
        rows, tie_notes = analyse_model(cfg, root)
        all_rows.extend(rows)
        all_tie_notes.extend(tie_notes)

    full_df = pd.DataFrame(all_rows)
    full_df.to_csv(out_path, index=False)

    print(f"Saved: {out_path}\n")

    if all_tie_notes:
        print("Tie-breaking notes:")
        for note in all_tie_notes:
            print(f"  - {note}")
    else:
        print("No ties detected; each criterion selected a unique best threshold.")

    for model in [cfg["display_name"] for cfg in MODELS.values()]:
        print(f"\n{model} — concise comparison")
        table = concise_table(full_df, model)
        print(table.to_string(index=False, float_format=lambda x: f"{x:.4f}"))

    print_interpretation(full_df)
    print_f1_threshold_diff(full_df)

    print(f"\nGenerated file:\n  {out_path}")


if __name__ == "__main__":
    main()
