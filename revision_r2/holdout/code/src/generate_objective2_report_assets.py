#!/usr/bin/env python3
"""
Generate Chapter 4 / paper result assets from saved Objective 2 metrics only.

Does not train or evaluate models. Reads consolidation (and optional test) CSVs.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from objective2_locked_common import (  # noqa: E402
    DISPLAY_NAMES,
    JOINT_DIRS,
    PRETRAIN_DIRS,
    PRIMARY_MODEL_IDS,
    default_output_dir,
    repo_root,
    resolve,
)

# Stable display order for publication figures/tables.
MODEL_ORDER = [
    DISPLAY_NAMES["standalone_bilstm"],
    DISPLAY_NAMES["attention_linear"],
    DISPLAY_NAMES["fragmented_bilstm_rf"],
    DISPLAY_NAMES["fragmented_bilstm_xgboost"],
    DISPLAY_NAMES["joint_bilstm_attention_soft_forest"],
    DISPLAY_NAMES["standalone_soft_forest"],
    DISPLAY_NAMES["classical_rf"],
    DISPLAY_NAMES["classical_xgboost"],
]

PRIMARY_ORDER = [DISPLAY_NAMES[m] for m in PRIMARY_MODEL_IDS]


def _ordered(names: list[str], order: list[str]) -> list[str]:
    rank = {n: i for i, n in enumerate(order)}
    return sorted(names, key=lambda n: rank.get(n, 10_000 + hash(n) % 1000))


def _mean_std_table(summary: pd.DataFrame, metrics: list[str]) -> pd.DataFrame:
    rows = []
    for model_name, g in summary.groupby("model_name"):
        row = {"model_name": model_name}
        for metric in metrics:
            sub = g[g["metric"] == metric]
            if sub.empty:
                row[f"{metric}_mean"] = np.nan
                row[f"{metric}_std"] = np.nan
            else:
                row[f"{metric}_mean"] = float(sub.iloc[0]["mean"])
                row[f"{metric}_std"] = float(sub.iloc[0]["std"])
        rows.append(row)
    out = pd.DataFrame(rows)
    out["model_name"] = pd.Categorical(out["model_name"], categories=MODEL_ORDER, ordered=True)
    return out.sort_values("model_name").reset_index(drop=True)


def write_validation_tables(comparison: pd.DataFrame, summary: pd.DataFrame, out: Path) -> None:
    primary = comparison[~comparison["is_reference_baseline"]].copy()
    refs = comparison[comparison["is_reference_baseline"]].copy()

    wide = _mean_std_table(
        summary[summary["model_id"].isin(list(PRIMARY_MODEL_IDS) + ["standalone_soft_forest"])],
        [
            "validation_pr_auc",
            "validation_precision",
            "validation_recall",
            "validation_f1",
            "validation_fp",
            "validation_fn",
        ],
    )
    # Append classical single-run means (std=0) from comparison.
    for _, r in refs[refs["model_id"].isin(["classical_rf", "classical_xgboost"])].iterrows():
        wide = pd.concat(
            [
                wide,
                pd.DataFrame(
                    [
                        {
                            "model_name": r["model_name"],
                            "validation_pr_auc_mean": r["validation_pr_auc"],
                            "validation_pr_auc_std": 0.0,
                            "validation_precision_mean": r["validation_precision"],
                            "validation_precision_std": 0.0,
                            "validation_recall_mean": r["validation_recall"],
                            "validation_recall_std": 0.0,
                            "validation_f1_mean": r["validation_f1"],
                            "validation_f1_std": 0.0,
                            "validation_fp_mean": r["validation_fp"],
                            "validation_fp_std": 0.0,
                            "validation_fn_mean": r["validation_fn"],
                            "validation_fn_std": 0.0,
                        }
                    ]
                ),
            ],
            ignore_index=True,
        )
    wide["model_name"] = pd.Categorical(wide["model_name"], categories=MODEL_ORDER, ordered=True)
    wide = wide.sort_values("model_name").drop_duplicates("model_name").reset_index(drop=True)
    wide.to_csv(out / "table_validation_model_comparison.csv", index=False)

    # Ablation table: attention-linear vs joint (+ note fragmented).
    abl = primary[
        primary["model_id"].isin(
            [
                "attention_linear",
                "joint_bilstm_attention_soft_forest",
                "standalone_bilstm",
                "fragmented_bilstm_rf",
                "fragmented_bilstm_xgboost",
            ]
        )
    ][
        [
            "model_name",
            "seed",
            "validation_pr_auc",
            "validation_f1",
            "validation_precision",
            "validation_recall",
            "validation_fp",
            "validation_fn",
            "validation_threshold",
            "attention_entropy",
        ]
    ].copy()
    abl.to_csv(out / "table_ablation.csv", index=False)

    # Repeated-seed stability.
    stab = _mean_std_table(
        summary[summary["model_id"].isin(PRIMARY_MODEL_IDS)],
        ["validation_pr_auc", "validation_f1", "validation_fp", "validation_fn"],
    )
    stab.to_csv(out / "table_repeated_seed_stability.csv", index=False)

    # Timing table.
    timing = comparison[
        [
            "model_name",
            "model_id",
            "seed",
            "training_time_sec",
            "inference_time_sec",
            "is_reference_baseline",
            "input_representation",
        ]
    ].copy()
    timing.to_csv(out / "table_training_inference_time.csv", index=False)


def write_test_tables(test_summary: pd.DataFrame, test_seeds: pd.DataFrame, out: Path) -> None:
    wide = _mean_std_table(
        test_summary,
        ["test_pr_auc", "test_precision", "test_recall", "test_f1", "test_fp", "test_fn"],
    )
    wide.to_csv(out / "table_test_model_comparison.csv", index=False)
    test_seeds.to_csv(out / "table_test_seed_results.csv", index=False)


def _errorbar_figure(
    summary: pd.DataFrame,
    metric: str,
    ylabel: str,
    out_path: Path,
    primary_only: bool = True,
) -> None:
    if primary_only:
        summary = summary[summary["model_id"].isin(PRIMARY_MODEL_IDS)]
    names = _ordered(summary["model_name"].unique().tolist(), PRIMARY_ORDER if primary_only else MODEL_ORDER)
    means, stds = [], []
    for name in names:
        sub = summary[(summary["model_name"] == name) & (summary["metric"] == metric)]
        if sub.empty:
            means.append(np.nan)
            stds.append(0.0)
        else:
            means.append(float(sub.iloc[0]["mean"]))
            stds.append(float(sub.iloc[0]["std"]))
    fig, ax = plt.subplots(figsize=(9, 4.5))
    x = np.arange(len(names))
    ax.bar(x, means, yerr=stds, capsize=4, color="#4C78A8", ecolor="#333333", alpha=0.9)
    ax.set_xticks(x)
    ax.set_xticklabels(names, rotation=25, ha="right")
    ax.set_ylabel(ylabel)
    ax.set_title(f"{ylabel} across seeds (mean ± sample SD)")
    ax.grid(axis="y", linestyle=":", alpha=0.5)
    fig.tight_layout()
    fig.savefig(out_path, dpi=200)
    plt.close(fig)


def _precision_recall_scatter(comparison: pd.DataFrame, out_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(7, 5.5))
    primary = comparison[~comparison["is_reference_baseline"]]
    for model_name, g in primary.groupby("model_name"):
        ax.scatter(
            g["validation_recall"],
            g["validation_precision"],
            label=model_name,
            s=55,
            alpha=0.85,
        )
    # Reference baselines as distinct markers.
    refs = comparison[comparison["is_reference_baseline"]]
    for model_name, g in refs.groupby("model_name"):
        ax.scatter(
            g["validation_recall"],
            g["validation_precision"],
            label=f"{model_name} (ref)",
            marker="x",
            s=70,
        )
    ax.set_xlabel("Validation recall")
    ax.set_ylabel("Validation precision")
    ax.set_title("Precision–recall trade-off (validation)")
    ax.set_xlim(0, 1.02)
    ax.set_ylim(0, 1.02)
    ax.legend(fontsize=8, loc="best")
    ax.grid(linestyle=":", alpha=0.5)
    fig.tight_layout()
    fig.savefig(out_path, dpi=200)
    plt.close(fig)


def _fp_fn_figure(summary: pd.DataFrame, out_path: Path) -> None:
    summary = summary[summary["model_id"].isin(PRIMARY_MODEL_IDS)]
    names = _ordered(summary["model_name"].unique().tolist(), PRIMARY_ORDER)
    fp_m, fp_s, fn_m, fn_s = [], [], [], []
    for name in names:
        fp = summary[(summary["model_name"] == name) & (summary["metric"] == "validation_fp")]
        fn = summary[(summary["model_name"] == name) & (summary["metric"] == "validation_fn")]
        fp_m.append(float(fp.iloc[0]["mean"]) if not fp.empty else np.nan)
        fp_s.append(float(fp.iloc[0]["std"]) if not fp.empty else 0.0)
        fn_m.append(float(fn.iloc[0]["mean"]) if not fn.empty else np.nan)
        fn_s.append(float(fn.iloc[0]["std"]) if not fn.empty else 0.0)
    x = np.arange(len(names))
    width = 0.38
    fig, ax = plt.subplots(figsize=(9, 4.5))
    ax.bar(x - width / 2, fp_m, width, yerr=fp_s, capsize=3, label="FP", color="#E45756")
    ax.bar(x + width / 2, fn_m, width, yerr=fn_s, capsize=3, label="FN", color="#F58518")
    ax.set_xticks(x)
    ax.set_xticklabels(names, rotation=25, ha="right")
    ax.set_ylabel("Count")
    ax.set_title("Validation FP / FN (mean ± sample SD)")
    ax.legend()
    ax.grid(axis="y", linestyle=":", alpha=0.5)
    fig.tight_layout()
    fig.savefig(out_path, dpi=200)
    plt.close(fig)


def _training_curves(root: Path, out_path: Path) -> None:
    """Validation PR-AUC curves for main ablations (seed 42 where available)."""
    ens = root / "outputs" / "baselines" / "sequence_ensemble"
    bilstm = root / "outputs" / "objective2" / "bilstm_seed42" / "training_history.csv"
    series = []
    if bilstm.exists():
        h = pd.read_csv(bilstm)
        series.append(("Standalone Bi-LSTM (seed 42)", h["epoch"], h["val_pr_auc"]))
    attn = ens / PRETRAIN_DIRS[42] / "training_history.csv"
    if attn.exists():
        h = pd.read_csv(attn)
        series.append(("Attention–Linear Ablation (seed 42)", h["epoch"], h["val_pr_auc"]))
    joint = ens / JOINT_DIRS[42] / "training_history.csv"
    if joint.exists():
        h = pd.read_csv(joint)
        series.append(("Joint Bi-LSTM–Attention–Soft Forest (seed 42)", h["epoch"], h["val_pr_auc"]))
    # From-scratch joint pilot (ablation C) if present.
    scratch = ens / "stage11_C_attn_sf_pw025_lr3e4" / "training_history.csv"
    if scratch.exists():
        h = pd.read_csv(scratch)
        series.append(("From-scratch attn+soft-forest (seed 42)", h["epoch"], h["val_pr_auc"]))

    fig, ax = plt.subplots(figsize=(8, 4.8))
    for label, epochs, vals in series:
        ax.plot(epochs, vals, marker="o", markersize=3, label=label)
    ax.set_xlabel("Epoch")
    ax.set_ylabel("Validation PR-AUC")
    ax.set_title("Validation training-curve comparison (main ablations)")
    ax.legend(fontsize=8)
    ax.grid(linestyle=":", alpha=0.5)
    fig.tight_layout()
    fig.savefig(out_path, dpi=200)
    plt.close(fig)


def _pretrained_vs_scratch(root: Path, comparison: pd.DataFrame, out_path: Path) -> None:
    """From-scratch (ablation C, seed 42) vs pretrained joint fine-tune seeds."""
    ens = root / "outputs" / "baselines" / "sequence_ensemble"
    scratch_thr = ens / "stage11_C_attn_sf_pw025_lr3e4" / "threshold.json"
    joint = comparison[comparison["model_id"] == "joint_bilstm_attention_soft_forest"]
    labels = []
    pr = []
    f1 = []
    if scratch_thr.exists():
        import json

        thr = json.loads(scratch_thr.read_text(encoding="utf-8"))
        vm = thr["validation_metrics"]
        labels.append("From-scratch\nattn+soft-forest\n(seed 42)")
        pr.append(float(vm["pr_auc"]))
        f1.append(float(vm["f1"]))
    for _, r in joint.sort_values("seed").iterrows():
        labels.append(f"Joint pretrained\nfine-tune\n(seed {int(r['seed'])})")
        pr.append(float(r["validation_pr_auc"]))
        f1.append(float(r["validation_f1"]))
    x = np.arange(len(labels))
    width = 0.38
    fig, ax = plt.subplots(figsize=(9, 4.8))
    ax.bar(x - width / 2, pr, width, label="PR-AUC", color="#4C78A8")
    ax.bar(x + width / 2, f1, width, label="F1", color="#54A24B")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=8)
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("Validation metric")
    ax.set_title("From-scratch versus pretrained joint training")
    ax.legend()
    ax.grid(axis="y", linestyle=":", alpha=0.5)
    fig.tight_layout()
    fig.savefig(out_path, dpi=200)
    plt.close(fig)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate Objective 2 report assets from saved metrics.")
    p.add_argument("--output-dir", default="outputs/objective2/report_assets")
    p.add_argument(
        "--objective2-dir",
        default="outputs/objective2",
        help="Directory containing consolidation / test result CSVs.",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    root = repo_root()
    obj_dir = resolve(root, args.objective2_dir)
    out = resolve(root, args.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    comparison_path = obj_dir / "objective2_validation_model_comparison.csv"
    summary_path = obj_dir / "objective2_validation_model_summary.csv"
    if not comparison_path.exists() or not summary_path.exists():
        raise SystemExit(
            "Missing consolidation CSVs. Run scripts/consolidate_objective2_final.py first."
        )

    comparison = pd.read_csv(comparison_path)
    summary = pd.read_csv(summary_path)

    write_validation_tables(comparison, summary, out)
    _errorbar_figure(
        summary,
        "validation_pr_auc",
        "Validation PR-AUC",
        out / "fig_validation_pr_auc_mean_error.png",
    )
    _errorbar_figure(
        summary,
        "validation_f1",
        "Validation F1",
        out / "fig_validation_f1_mean_error.png",
    )
    _precision_recall_scatter(comparison, out / "fig_precision_recall_tradeoff.png")
    _fp_fn_figure(summary, out / "fig_fp_fn_comparison.png")
    _training_curves(root, out / "fig_validation_training_curves.png")
    _pretrained_vs_scratch(root, comparison, out / "fig_from_scratch_vs_pretrained.png")

    test_summary = obj_dir / "objective2_test_model_summary.csv"
    test_seeds = obj_dir / "objective2_test_seed_results.csv"
    if test_summary.exists() and test_seeds.exists():
        ts = pd.read_csv(test_summary)
        write_test_tables(ts, pd.read_csv(test_seeds), out)
        if "model_id" in ts.columns:
            _errorbar_figure(
                ts,
                "test_pr_auc",
                "Test PR-AUC",
                out / "fig_test_pr_auc_mean_error.png",
                primary_only=False,
            )
            _errorbar_figure(
                ts,
                "test_f1",
                "Test F1",
                out / "fig_test_f1_mean_error.png",
                primary_only=False,
            )
        print("Test result tables/figures generated.")
    else:
        print("Test results not found; skipped test tables/figures.")

    print("=" * 72)
    print("OBJECTIVE 2 REPORT ASSETS")
    print("=" * 72)
    for p in sorted(out.glob("*")):
        print(f"  {p}")


if __name__ == "__main__":
    main()
