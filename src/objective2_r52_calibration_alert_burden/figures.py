"""Figures without internal titles for calibration + alert-burden audit."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .constants import METHOD_TEMP, METHOD_UNCAL, MODEL_AL, MODEL_ODST, MODEL_XGB
from .safety import assert_output_namespace, write_csv_atomic


def _save(fig: plt.Figure, path: Path) -> None:
    assert_output_namespace(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)


def _label(model: str) -> str:
    return {
        MODEL_ODST: "ODST",
        MODEL_AL: "Attn–linear",
        MODEL_XGB: "XGBoost",
    }.get(model, model)


def write_figures(
    out_dir: Path,
    *,
    metrics: pd.DataFrame,
    bins: pd.DataFrame,
    burden: pd.DataFrame,
    episodes: pd.DataFrame,
    budgets: pd.DataFrame,
    user_agg: pd.DataFrame,
) -> list[Path]:
    fig_dir = out_dir / "figures"
    src_dir = out_dir / "figure_sources"
    fig_dir.mkdir(parents=True, exist_ok=True)
    src_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []

    # Figure 1 — reliability diagrams
    src1 = bins[
        (bins.scheme == "fixed")
        & (bins.method.isin([METHOD_UNCAL, METHOD_TEMP]))
        & (bins.model.isin([MODEL_ODST, MODEL_AL]))
    ].copy()
    write_csv_atomic(src_dir / "figure1_reliability_diagrams.csv", src1)
    fig, axes = plt.subplots(1, 2, figsize=(8.5, 3.6), sharey=True)
    for ax, model in zip(axes, (MODEL_ODST, MODEL_AL)):
        for method, ls in ((METHOD_UNCAL, "-"), (METHOD_TEMP, "--")):
            g = src1[(src1.model == model) & (src1.method == method) & (src1.seed == 42)]
            g = g.sort_values("bin")
            ax.plot(
                g.mean_confidence,
                g.empirical_positive_rate,
                ls,
                marker="o",
                ms=3,
                label=method,
            )
        ax.plot([0, 1], [0, 1], ":", color="gray", lw=1)
        ax.set_xlabel("confidence")
        ax.set_ylabel("empirical rate")
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.text(0.05, 0.92, _label(model), transform=ax.transAxes, fontsize=9)
        ax.legend(fontsize=7)
    paths.append(fig_dir / "figure1_reliability_diagrams.png")
    _save(fig, paths[-1])

    # Figure 2 — Brier / logloss / ECE
    src2_rows = []
    for _, r in metrics[metrics.model.isin([MODEL_ODST, MODEL_AL])].iterrows():
        for metric in ("brier", "logloss", "ece_fixed"):
            src2_rows.append(
                {
                    "model": r.model,
                    "seed": r.seed,
                    "method": r.method,
                    "metric": metric,
                    "value": float(r[metric]),
                }
            )
    src2 = pd.DataFrame(src2_rows)
    write_csv_atomic(src_dir / "figure2_brier_logloss_ece.csv", src2)
    metric_names = ["brier", "logloss", "ece_fixed"]
    fig, axes = plt.subplots(1, 3, figsize=(10, 3.4))
    for ax, metric in zip(axes, metric_names):
        for i, model in enumerate((MODEL_ODST, MODEL_AL)):
            for j, method in enumerate((METHOD_UNCAL, METHOD_TEMP)):
                g = src2[(src2.model == model) & (src2.method == method) & (src2.metric == metric)]
                vals = [g[g.seed == s]["value"].mean() for s in sorted(g.seed.unique())]
                seeds = sorted(g.seed.unique())
                ax.scatter(
                    np.arange(len(seeds)) + (i - 0.5) * 0.2 + (j - 0.5) * 0.05,
                    vals,
                    label=f"{_label(model)}/{method}",
                    s=28,
                )
        ax.set_xticks(range(len(seeds)))
        ax.set_xticklabels([str(s) for s in seeds])
        ax.set_xlabel("seed")
        ax.set_ylabel(metric)
        ax.legend(fontsize=6)
    paths.append(fig_dir / "figure2_brier_logloss_ece.png")
    _save(fig, paths[-1])

    # Figure 3 — sequence alerts vs unique users
    src3 = burden[burden.model.isin([MODEL_ODST, MODEL_AL, MODEL_XGB])][
        ["model", "seed", "n_sequence_alerts", "n_unique_alerted_users"]
    ].copy()
    write_csv_atomic(src_dir / "figure3_sequence_vs_users.csv", src3)
    fig, ax = plt.subplots(figsize=(5.5, 4))
    for model in (MODEL_ODST, MODEL_AL, MODEL_XGB):
        g = src3[src3.model == model]
        if g.empty:
            continue
        ax.scatter(g.n_sequence_alerts, g.n_unique_alerted_users, label=_label(model), s=45)
    ax.set_xlabel("sequence alerts")
    ax.set_ylabel("unique alerted users")
    ax.legend(fontsize=8)
    paths.append(fig_dir / "figure3_sequence_vs_users.png")
    _save(fig, paths[-1])

    # Figure 4 — sequence alerts vs episodes
    src4 = episodes.merge(
        burden[["model", "seed", "n_sequence_alerts"]],
        on=["model", "seed"],
        how="left",
        suffixes=("", "_burden"),
    )
    if "n_sequence_alerts_burden" in src4.columns:
        src4["n_sequence_alerts"] = src4["n_sequence_alerts_burden"]
    write_csv_atomic(
        src_dir / "figure4_sequence_vs_episodes.csv",
        src4[["model", "seed", "n_sequence_alerts", "n_alert_episodes"]],
    )
    fig, ax = plt.subplots(figsize=(5.5, 4))
    for model in (MODEL_ODST, MODEL_AL, MODEL_XGB):
        g = src4[src4.model == model]
        if g.empty:
            continue
        ax.scatter(g.n_sequence_alerts, g.n_alert_episodes, label=_label(model), s=45)
    ax.set_xlabel("sequence alerts")
    ax.set_ylabel("consolidated episodes")
    ax.legend(fontsize=8)
    paths.append(fig_dir / "figure4_sequence_vs_episodes.png")
    _save(fig, paths[-1])

    # Figure 5 — budget curves
    src5 = budgets[budgets.model.isin([MODEL_ODST, MODEL_AL, MODEL_XGB])].copy()
    write_csv_atomic(src_dir / "figure5_budget_curves.csv", src5)
    fig, ax = plt.subplots(figsize=(6, 4))
    for model in (MODEL_ODST, MODEL_AL, MODEL_XGB):
        g = src5[src5.model == model]
        if g.empty:
            continue
        # average across seeds
        agg = g.groupby("budget_fraction", as_index=False).agg(
            recall=("malicious_sequence_recall", "mean"),
            benign=("n_benign_users_alerted", "mean"),
        )
        ax.plot(agg.benign, agg.recall, marker="o", label=_label(model))
    ax.set_xlabel("benign users alerted")
    ax.set_ylabel("malicious sequence recall")
    ax.legend(fontsize=8)
    paths.append(fig_dir / "figure5_budget_curves.png")
    _save(fig, paths[-1])

    # Figure 6 — user-level score distribution proxy via PR-AUC by aggregation
    src6 = user_agg[user_agg.model.isin([MODEL_ODST, MODEL_AL])].copy()
    write_csv_atomic(src_dir / "figure6_user_score_distribution.csv", src6)
    fig, ax = plt.subplots(figsize=(6, 3.8))
    for model in (MODEL_ODST, MODEL_AL):
        for agg_name, marker in (("max", "o"), ("mean_top3", "s")):
            g = src6[(src6.model == model) & (src6.aggregation == agg_name)]
            if g.empty:
                continue
            # one PR-AUC per seed (constant across budgets)
            vals = g.groupby("seed")["user_pr_auc"].first()
            ax.scatter(
                [f"{_label(model)}\n{agg_name}"] * len(vals),
                vals.values,
                marker=marker,
                s=40,
                label=f"{_label(model)}/{agg_name}",
            )
    ax.set_ylabel("user-level PR-AUC")
    ax.legend(fontsize=7)
    paths.append(fig_dir / "figure6_user_score_distribution.png")
    _save(fig, paths[-1])

    return paths
