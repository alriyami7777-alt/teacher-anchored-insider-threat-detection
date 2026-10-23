"""Figures and interpretation reports for temporal-value analysis."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd


def make_figures(out_dir: Path, metrics_df: pd.DataFrame) -> None:
    primary = metrics_df[(metrics_df["dataset"] == "r52") & (metrics_df["seed"] == 42)].copy()
    if primary.empty:
        return

    # Chronological vs reversed / shuffled
    fig, ax = plt.subplots(figsize=(6.8, 4.0))
    order = ["T0", "T1", "T2"]
    sub = primary[primary["condition"].isin(order)].set_index("condition").loc[order]
    ax.bar(range(len(order)), sub["pr_auc"].values, color=["#2c7bb6", "#d7191c", "#fdae61"])
    ax.set_xticks(range(len(order)))
    ax.set_xticklabels(["Original", "Reversed", "Shuffled"])
    ax.set_ylabel("Validation PR-AUC")
    fig.tight_layout()
    fig.savefig(out_dir / "chronological_vs_reversed_shuffled.png", dpi=300)
    plt.close(fig)

    # History length performance
    fig, ax = plt.subplots(figsize=(6.8, 4.0))
    hist_order = ["T3", "T4", "T5", "T6"]
    labels = ["1 day", "5 days", "10 days", "20 days"]
    sub = primary[primary["condition"].isin(hist_order)].set_index("condition").loc[hist_order]
    ax.plot(range(len(hist_order)), sub["pr_auc"].values, "o-", label="PR-AUC")
    ax.plot(range(len(hist_order)), sub["f1"].values, "s--", label="F1")
    ax.set_xticks(range(len(hist_order)))
    ax.set_xticklabels(labels)
    ax.set_ylabel("Score")
    ax.set_xlabel("Available history")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_dir / "history_length_performance.png", dpi=300)
    plt.close(fig)

    # Threshold crossing / history
    cross_path = out_dir / "partial_history_detection.csv"
    if cross_path.is_file():
        ph = pd.read_csv(cross_path)
        ph42 = ph[ph["seed"] == 42]
        if not ph42.empty and "first_alert_history_days" in ph42.columns:
            fig, ax = plt.subplots(figsize=(6.8, 4.0))
            counts = (
                ph42[ph42["y_true"] == 1]["first_alert_history_days"]
                .fillna(-1)
                .astype(int)
                .value_counts()
                .reindex([1, 5, 10, 20, -1], fill_value=0)
            )
            labels = ["1", "5", "10", "20", "never"]
            ax.bar(range(len(labels)), counts.values)
            ax.set_xticks(range(len(labels)))
            ax.set_xticklabels(labels)
            ax.set_xlabel("History length at first clean-threshold alert (malicious sequences)")
            ax.set_ylabel("Count")
            fig.tight_layout()
            fig.savefig(out_dir / "threshold_crossing_history.png", dpi=300)
            plt.close(fig)


def write_reports(
    out_dir: Path,
    *,
    status: str,
    meta: dict[str, Any],
    order_summary: dict[str, Any],
    timing_note: str,
) -> None:
    (out_dir / "TEMPORAL_VALUE_INTERPRETATION.md").write_text(
        f"""# TEMPORAL_VALUE_INTERPRETATION

## Final status
`{status}`

## Scientific question
Does the frozen teacher-anchored Bi-LSTM–attention–ODST candidate use chronological order and accumulated
behavioural history, rather than responding only to unordered value content?

## Clean parity
Clean (T0) validation metrics were reproduced against the locked r5.2 seed-42 / seed-62 student checkpoints
before any temporal transforms.

## Temporal-order findings
- T0 (original) vs T1 (reversed) vs T2 (fixed shuffle, seed 2026)
- Order advantage detected: {order_summary.get('order_advantage')}
- Seed-42 ΔPR-AUC (T0−T1): {order_summary.get('delta_pr_t1')}
- Seed-42 ΔPR-AUC (T0−T2): {order_summary.get('delta_pr_t2')}
- Interpretation: {order_summary.get('interpretation')}

## Partial-history findings
T3–T6 retain the most recent 1 / 5 / 10 / 20 days and fill earlier steps with **training-set feature medians**.
Threshold-crossing groups are reported as partial-history detection under the clean validation threshold,
not as exact real-world lead time.

## Timing metadata
{timing_note}

## Unsupported claims
- No claim that the model has verified early-warning lead time in calendar days unless event-relative
  day labels exist (they do not in the tensor schema used here).
- No claim of test-set temporal robustness (r5.2 test not used).
- No architecture or training change.

## Provenance
- worktree: {meta.get('worktree')}
- branch: {meta.get('branch')}
- HEAD: {meta.get('head')}
""",
        encoding="utf-8",
    )

    (out_dir / "PAPER_TEMPORAL_VALUE_RESULTS.md").write_text(
        f"""# PAPER_TEMPORAL_VALUE_RESULTS

Draft-only notes for Chapter / paper drafting. Do not paste unchecked.

- Study: forward-pass temporal-value and partial-history diagnostic on frozen teacher-anchored students.
- Primary: CERT r5.2 validation, seed 42 (T0–T6).
- Limited confirmation: seed 62 (T0, T2, T4, T6).
- Status: `{status}`
- Order finding: {order_summary.get('interpretation')}
- Partial history: detection rate and PR-AUC/F1 as retained recent history increases from 1→20 days.
- Lead-time language: avoid unless day-level incident boundaries are available; use partial-history detection wording.
""",
        encoding="utf-8",
    )

    (out_dir / "OBJECTIVE2_TEMPORAL_DEFENCE_EXPLANATION.md").write_text(
        f"""# OBJECTIVE2_TEMPORAL_DEFENCE_EXPLANATION

## Why this study
Objective 2’s final sequence–ensemble candidate is a Bi-LSTM–attention model. A natural defence question is whether
predictions depend on chronological structure and history length, or only on bag-of-values content.

## What was locked
Frozen teacher-anchored students (r5.2 reproducibility seeds 42 and 62). No retraining, retuning, or retagging.

## What was measured
- Order: original vs reverse vs one fixed global shuffle.
- History: most-recent 1 / 5 / 10 / 20 days with earlier steps replaced by train medians.

## Status
`{status}`
""",
        encoding="utf-8",
    )

    (out_dir / "EXPERIMENTAL_HANDOVER.md").write_text(
        f"""# EXPERIMENTAL_HANDOVER — temporal-value analysis

## Status
`{status}`

## Isolation
- Worktree: {meta.get('worktree')}
- Branch: {meta.get('branch')}
- HEAD: {meta.get('head')}
- Outputs: outputs/objective2/temporal_value_analysis_v1/

## Protections
- Forward-pass only (no optimiser / backward)
- r5.2 test blocked
- Frozen checkpoints not modified
- No automatic follow-on same-information baseline study

## Stop
Stop for review. Do not launch a same-information baseline study automatically.
""",
        encoding="utf-8",
    )
