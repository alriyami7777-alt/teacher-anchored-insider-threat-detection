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


def figure1_order(seed_summary: pd.DataFrame, out_dir: Path) -> Path:
    models = [
        "teacher_anchored_odst_seq",
        "attention_linear_seq",
        "xgboost_flat260",
        "random_forest_flat260",
        "mlp_flat260",
    ]
    labels = ["ODST", "Attn-Lin", "XGB", "RF", "MLP"]
    g = seed_summary[seed_summary["model_id"].isin(models)].groupby("model_id")
    means = {m: g.get_group(m) if m in g.groups else None for m in models}
    # Need condition columns from condition metrics aggregated
    # Expect seed_summary to have t0/t1/t2 pr_auc means already, else caller passes prepared frame.
    x = np.arange(len(models))
    width = 0.25
    fig, ax = plt.subplots(figsize=(9, 4.5))
    for i, cond in enumerate(["t0_pr_auc", "t1_pr_auc", "t2_pr_auc"]):
        vals = []
        for m in models:
            sub = seed_summary[seed_summary["model_id"] == m]
            vals.append(float(sub[cond].mean()) if cond in sub.columns and len(sub) else np.nan)
        ax.bar(x + (i - 1) * width, vals, width, label=cond.replace("_pr_auc", "").upper())
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("PR-AUC")
    ax.set_ylim(0, 1.05)
    ax.legend(frameon=False)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    path = out_dir / "figure1_chronological_order.png"
    _save(fig, path)
    return path


def figure2_partial_history(partial: pd.DataFrame, out_dir: Path) -> Path:
    models = [
        "teacher_anchored_odst_seq",
        "attention_linear_seq",
        "xgboost_flat260",
        "random_forest_flat260",
        "mlp_flat260",
    ]
    days = [1, 5, 10, 20]
    day_map = {1: "T3", 5: "T4", 10: "T5", 20: "T6"}
    fig, ax = plt.subplots(figsize=(8, 5))
    for m in models:
        ys = []
        for d in days:
            sub = partial[(partial["model_id"] == m) & (partial["condition"] == day_map[d])]
            ys.append(float(sub["pr_auc"].mean()) if len(sub) else np.nan)
        ax.plot(days, ys, marker="o", label=m.replace("_flat260", "").replace("_seq", ""))
    ax.set_xlabel("History days")
    ax.set_ylabel("PR-AUC")
    ax.set_xticks(days)
    ax.set_ylim(0, 1.05)
    ax.legend(frameon=False, fontsize=7)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    path = out_dir / "figure2_partial_history_pr_auc.png"
    _save(fig, path)
    return path


def figure3_detection(partial: pd.DataFrame, out_dir: Path) -> Path:
    models = [
        "teacher_anchored_odst_seq",
        "attention_linear_seq",
        "xgboost_flat260",
        "random_forest_flat260",
        "mlp_flat260",
    ]
    days = [1, 5, 10, 20]
    day_map = {1: "T3", 5: "T4", 10: "T5", 20: "T6"}
    fig, ax = plt.subplots(figsize=(8, 5))
    for m in models:
        ys = []
        for d in days:
            sub = partial[(partial["model_id"] == m) & (partial["condition"] == day_map[d])]
            ys.append(float(sub["malicious_detection_rate"].mean()) if len(sub) else np.nan)
        ax.plot(days, ys, marker="o", label=m.replace("_flat260", "").replace("_seq", ""))
    ax.set_xlabel("History days")
    ax.set_ylabel("Malicious detection rate")
    ax.set_xticks(days)
    ax.set_ylim(0, 1.05)
    ax.legend(frameon=False, fontsize=7)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    path = out_dir / "figure3_malicious_detection_by_history.png"
    _save(fig, path)
    return path


def figure4_forest(effects_boot: pd.DataFrame, out_dir: Path) -> Path:
    df = effects_boot.copy()
    df["label"] = df["model_id"].str.replace("_flat260", "").str.replace("_seq", "") + " " + df["effect"]
    df = df.sort_values(["model_id", "effect", "seed"])
    # Aggregate across seeds: mean observed, mean CI bounds (descriptive display)
    g = (
        df.groupby(["model_id", "effect"], as_index=False)
        .agg(observed=("observed_delta", "mean"), lo=("ci95_low", "mean"), hi=("ci95_high", "mean"))
    )
    g["label"] = g["model_id"].str.replace("_flat260", "").str.replace("_seq", "") + " / " + g["effect"]
    y = np.arange(len(g))
    fig, ax = plt.subplots(figsize=(9, 8))
    ax.axvline(0.0, color="black", linewidth=1)
    ax.hlines(y, g["lo"], g["hi"], color="#4c78a8", linewidth=2)
    ax.plot(g["observed"], y, "o", color="#4c78a8")
    ax.set_yticks(y)
    ax.set_yticklabels(g["label"].tolist(), fontsize=7)
    ax.set_xlabel("PR-AUC difference")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    path = out_dir / "figure4_temporal_effect_intervals.png"
    _save(fig, path)
    return path


def figure5_sequence_vs_flat(partial: pd.DataFrame, out_dir: Path) -> Path:
    models = [
        "teacher_anchored_odst_seq",
        "attention_linear_seq",
        "xgboost_flat260",
        "random_forest_flat260",
        "mlp_flat260",
    ]
    labels = ["ODST", "Attn-Lin", "XGB", "RF", "MLP"]
    conds = [("T4", "5d"), ("T5", "10d"), ("T6", "20d")]
    x = np.arange(len(models))
    width = 0.25
    fig, ax = plt.subplots(figsize=(9, 4.5))
    for i, (cid, name) in enumerate(conds):
        vals = []
        for m in models:
            sub = partial[(partial["model_id"] == m) & (partial["condition"] == cid)]
            vals.append(float(sub["pr_auc"].mean()) if len(sub) else np.nan)
        ax.bar(x + (i - 1) * width, vals, width, label=name)
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("PR-AUC")
    ax.set_ylim(0, 1.05)
    ax.legend(frameon=False)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    path = out_dir / "figure5_sequence_vs_flat_history.png"
    _save(fig, path)
    return path
