"""Figures without internal titles."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .safety import assert_output_namespace


def _save(fig: plt.Figure, path: Path) -> None:
    assert_output_namespace(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)


def figure1_same_information(summary_a: pd.DataFrame, out_dir: Path) -> Path:
    order = [
        "logistic_regression_flat260",
        "mlp_flat260",
        "random_forest_flat260",
        "xgboost_flat260",
        "attention_linear_seq",
        "teacher_anchored_odst_seq",
    ]
    df = summary_a.set_index("model").reindex(order).dropna(how="all")
    labels = [
        "LogReg\n260",
        "MLP\n260",
        "RF\n260",
        "XGB\n260",
        "Attn-Linear\n20x13",
        "TA-ODST\n20x13",
    ][: len(df)]
    x = np.arange(len(df))
    width = 0.35
    fig, ax = plt.subplots(figsize=(10, 4.5))
    ax.bar(x - width / 2, df["pr_auc_mean"], width, yerr=df["pr_auc_std"], capsize=3, label="PR-AUC")
    ax.bar(x + width / 2, df["f1_mean"], width, yerr=df["f1_std"], capsize=3, label="F1")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("Score")
    ax.set_ylim(0, 1.05)
    ax.legend(frameon=False)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    path = out_dir / "figure1_same_information_comparison.png"
    _save(fig, path)
    return path


def figure2_engineered_context(panel_a: pd.DataFrame, panel_b: pd.DataFrame, out_dir: Path) -> Path:
    # Means for RF/XGB flat vs engineered + TA context
    def mean_of(df: pd.DataFrame, model: str, col: str = "pr_auc") -> float:
        if "pr_auc_mean" in df.columns and model in set(df.get("model", [])):
            return float(df.set_index("model").loc[model, "pr_auc_mean"])
        sub = df[df["model"] == model]
        if sub.empty:
            return float("nan")
        return float(pd.to_numeric(sub[col], errors="coerce").mean())

    names = [
        "RF 260",
        "RF eng40",
        "XGB 260",
        "XGB eng40",
        "TA-ODST",
    ]
    vals = [
        mean_of(panel_a, "random_forest_flat260"),
        mean_of(panel_b, "engineered_random_forest_40"),
        mean_of(panel_a, "xgboost_flat260"),
        mean_of(panel_b, "engineered_xgboost_40"),
        mean_of(panel_a, "teacher_anchored_odst_seq"),
    ]
    colors = ["#4c78a8", "#f58518", "#4c78a8", "#f58518", "#54a24b"]
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.bar(names, vals, color=colors)
    ax.set_ylabel("PR-AUC (validation)")
    ax.set_ylim(0, 1.05)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    # Caption limitation goes in reports; annotate representation groups lightly via hatch
    for i, hatch in enumerate(["", "//", "", "//", ""]):
        if hatch:
            ax.patches[i].set_hatch(hatch)
    path = out_dir / "figure2_engineered_feature_context.png"
    _save(fig, path)
    return path


def figure3_perf_vs_train_cost(seed_df: pd.DataFrame, out_dir: Path) -> Path:
    g = (
        seed_df.groupby("model")
        .agg(pr_auc=("pr_auc", "mean"), train_sec=("training_duration_sec", "mean"))
        .reset_index()
    )
    g = g.dropna(subset=["train_sec"])
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.scatter(g["train_sec"], g["pr_auc"], s=60)
    for _, r in g.iterrows():
        ax.annotate(str(r["model"]).replace("_", "\n"), (r["train_sec"], r["pr_auc"]), fontsize=7)
    ax.set_xlabel("Training time (sec)")
    ax.set_ylabel("PR-AUC (validation)")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    path = out_dir / "figure3_performance_vs_training_cost.png"
    _save(fig, path)
    return path


def figure4_perf_vs_complexity(seed_df: pd.DataFrame, out_dir: Path) -> Path:
    g = seed_df.copy()
    # Prefer model_size_bytes; fall back to n_parameters
    size = pd.to_numeric(g["model_size_bytes"], errors="coerce")
    params = pd.to_numeric(g["n_parameters"], errors="coerce")
    g["complexity"] = size.fillna(params)
    gg = g.groupby("model").agg(pr_auc=("pr_auc", "mean"), complexity=("complexity", "mean")).reset_index()
    gg = gg.dropna(subset=["complexity"])
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.scatter(gg["complexity"], gg["pr_auc"], s=60)
    for _, r in gg.iterrows():
        ax.annotate(str(r["model"]).replace("_", "\n"), (r["complexity"], r["pr_auc"]), fontsize=7)
    ax.set_xlabel("Model size (bytes) or parameter count")
    ax.set_ylabel("PR-AUC (validation)")
    ax.set_xscale("log")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    path = out_dir / "figure4_performance_vs_complexity.png"
    _save(fig, path)
    return path
