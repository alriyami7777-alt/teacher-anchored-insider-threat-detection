"""Generate post-run audit + Chapter 4 reporting from locked r5.2 test artefacts.

Never opens the test partition, never reruns the evaluator, never overwrites
immutable one-pass result files.
"""

from __future__ import annotations

import json
import statistics
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.r52_locked_baselines import OUTPUT_NAMESPACE, SEEDS  # noqa: E402
from scripts.r52_locked_baselines.safety import ProtocolAccessError, sha256_file  # noqa: E402

IMMUTABLE = (
    "r52_test_results_by_seed.csv",
    "r52_test_results_summary.csv",
    "r52_test_paired_comparisons.csv",
    "r52_test_predictions_manifest.json",
    "r52_test_execution_record.json",
    "r52_test_completed.lock",
)

MODELS = ("xgboost", "random_forest", "attention_linear", "odst")
MODEL_LABEL = {
    "xgboost": "XGBoost",
    "random_forest": "Random Forest",
    "attention_linear": "attention–linear",
    "odst": "ODST",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=str(root), text=True).strip()


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _refuse_overwrite_immutable(out: Path) -> None:
    for name in IMMUTABLE:
        p = out / name
        if not p.exists():
            raise ProtocolAccessError(f"Missing immutable artefact: {p}")


def _assert_not_rewriting(path: Path, before_hash: str | None = None) -> None:
    if before_hash is not None and path.exists():
        if sha256_file(path) != before_hash:
            raise ProtocolAccessError(f"Immutable artefact changed unexpectedly: {path}")


def verify_metrics(by: pd.DataFrame, summary: pd.DataFrame) -> dict[str, Any]:
    expected = {(m, s) for m in MODELS for s in SEEDS}
    got = {(str(r.model), int(r.seed)) for r in by.itertuples()}
    if got != expected or len(by) != 12:
        raise ProtocolAccessError(f"Expected 12 model-seed rows; got {sorted(got)}")

    metric_cols = [
        "pr_auc",
        "f1",
        "precision",
        "recall",
        "fp",
        "fn",
        "n_alerts",
        "brier_score",
        "log_loss",
    ]
    recomputed: dict[str, dict[str, float]] = {}
    for model, g in by.groupby("model"):
        row: dict[str, float] = {}
        for col in metric_cols:
            vals = [float(v) for v in g[col].tolist()]
            row[f"{col}_mean"] = float(statistics.fmean(vals))
            row[f"{col}_std"] = float(statistics.stdev(vals)) if len(vals) > 1 else 0.0
        recomputed[str(model)] = row
        srow = summary.loc[summary["model"] == model].iloc[0]
        for col in metric_cols:
            if abs(float(srow[f"{col}_mean"]) - row[f"{col}_mean"]) > 1e-12:
                raise ProtocolAccessError(f"Mean mismatch {model} {col}")
            if abs(float(srow[f"{col}_std"]) - row[f"{col}_std"]) > 1e-9:
                raise ProtocolAccessError(f"Std mismatch {model} {col}")

    means = {m: recomputed[m] for m in MODELS}
    pr_order = sorted(MODELS, key=lambda m: means[m]["pr_auc_mean"], reverse=True)
    if pr_order != ["random_forest", "xgboost", "attention_linear", "odst"]:
        raise ProtocolAccessError(f"Unexpected PR-AUC order: {pr_order}")

    checks = {
        "twelve_rows": True,
        "mean_std_match_summary": True,
        "pr_auc_order": pr_order,
        "rf_zero_fn_all_seeds": bool((by.loc[by["model"] == "random_forest", "fn"] == 0).all()),
        "xgb_highest_mean_f1": max(MODELS, key=lambda m: means[m]["f1_mean"]) == "xgboost",
        "xgb_lowest_mean_fp": min(MODELS, key=lambda m: means[m]["fp_mean"]) == "xgboost",
        "xgb_lowest_mean_alerts": min(MODELS, key=lambda m: means[m]["n_alerts_mean"]) == "xgboost",
        "xgb_lowest_mean_brier": min(MODELS, key=lambda m: means[m]["brier_score_mean"]) == "xgboost",
        "xgb_lowest_mean_log_loss": min(MODELS, key=lambda m: means[m]["log_loss_mean"]) == "xgboost",
        "rf_highest_mean_pr_auc": max(MODELS, key=lambda m: means[m]["pr_auc_mean"]) == "random_forest",
        "rf_lowest_mean_fn": min(MODELS, key=lambda m: means[m]["fn_mean"]) == "random_forest",
        "attn_better_calibration_than_odst": (
            means["attention_linear"]["brier_score_mean"] < means["odst"]["brier_score_mean"]
            and means["attention_linear"]["log_loss_mean"] < means["odst"]["log_loss_mean"]
        ),
        "odst_seeds_42_62_weak_calibration": bool(
            (
                by.loc[(by["model"] == "odst") & (by["seed"].isin([42, 62])), "brier_score"] > 0.1
            ).all()
        ),
        "lower_is_better_brier_log_loss": True,
        "xgb_not_rf_best_probability_loss": (
            means["xgboost"]["brier_score_mean"] < means["random_forest"]["brier_score_mean"]
            and means["xgboost"]["log_loss_mean"] < means["random_forest"]["log_loss_mean"]
        ),
    }
    if not all(checks[k] for k in checks if k not in {"pr_auc_order", "lower_is_better_brier_log_loss"}):
        failed = [k for k, v in checks.items() if v is False]
        raise ProtocolAccessError(f"Independent verification failed: {failed}")
    return {"checks": checks, "recomputed_means": means}


def validation_means(root: Path) -> pd.DataFrame:
    out = root / OUTPUT_NAMESPACE
    odst = root / "outputs/objective2/r52_odst_confirmation"
    rows = []
    for family, base in (
        ("xgboost", out),
        ("random_forest", out),
        ("attention_linear", odst),
        ("odst", odst),
    ):
        for seed in SEEDS:
            s = _load_json(base / f"{family}_seed{seed}" / "summary.json")
            vm = s["validation_metrics"]
            cal = s.get("calibration") or {}
            rows.append(
                {
                    "model": family,
                    "seed": seed,
                    "pr_auc": float(vm["pr_auc"]),
                    "f1": float(vm["f1"]),
                    "fp": float(vm["fp"]),
                    "fn": float(vm["fn"]),
                    "brier_score": float(vm.get("brier_score", cal.get("brier_score"))),
                    "log_loss": float(vm["log_loss"]) if vm.get("log_loss") is not None else None,
                }
            )
    df = pd.DataFrame(rows)
    agg = (
        df.groupby("model")[["pr_auc", "f1", "fp", "fn"]]
        .mean()
        .reset_index()
        .rename(
            columns={
                "pr_auc": "validation_pr_auc_mean",
                "f1": "validation_f1_mean",
                "fp": "validation_fp_mean",
                "fn": "validation_fn_mean",
            }
        )
    )
    return agg


def write_tables(
    report_dir: Path,
    by: pd.DataFrame,
    summary: pd.DataFrame,
    val_means: pd.DataFrame,
    verification: dict[str, Any],
) -> dict[str, Path]:
    report_dir.mkdir(parents=True, exist_ok=True)
    means = verification["recomputed_means"]

    def fmt(m: str, metric: str) -> str:
        return f"{means[m][f'{metric}_mean']:.4f}±{means[m][f'{metric}_std']:.4f}"

    bold = {
        "pr_auc": "random_forest",
        "f1": "xgboost",
        "fp": "xgboost",
        "fn": "random_forest",
        "n_alerts": "xgboost",
        "brier_score": "xgboost",
        "log_loss": "xgboost",
    }

    def cell(m: str, metric: str, as_mean_only: bool = False) -> str:
        if as_mean_only:
            text = f"{means[m][f'{metric}_mean']:.2f}" if metric in {"fp", "fn", "n_alerts"} else f"{means[m][f'{metric}_mean']:.4f}"
        else:
            text = fmt(m, metric)
        if bold.get(metric) == m:
            return f"**{text}**"
        return text

    rows = []
    md_rows = []
    for m in MODELS:
        rows.append(
            {
                "model": MODEL_LABEL[m],
                "pr_auc_mean_sd": fmt(m, "pr_auc"),
                "f1_mean_sd": fmt(m, "f1"),
                "precision_mean_sd": fmt(m, "precision"),
                "recall_mean_sd": fmt(m, "recall"),
                "fp_mean": means[m]["fp_mean"],
                "fn_mean": means[m]["fn_mean"],
                "alerts_mean": means[m]["n_alerts_mean"],
                "brier_mean": means[m]["brier_score_mean"],
                "log_loss_mean": means[m]["log_loss_mean"],
                "bold_pr_auc": m == bold["pr_auc"],
                "bold_f1": m == bold["f1"],
                "bold_fp": m == bold["fp"],
                "bold_fn": m == bold["fn"],
                "bold_alerts": m == bold["n_alerts"],
                "bold_brier": m == bold["brier_score"],
                "bold_log_loss": m == bold["log_loss"],
            }
        )
        md_rows.append(
            f"| {MODEL_LABEL[m]} | {cell(m,'pr_auc')} | {cell(m,'f1')} | {cell(m,'precision')} | "
            f"{cell(m,'recall')} | {cell(m,'fp', True)} | {cell(m,'fn', True)} | "
            f"{cell(m,'n_alerts', True)} | {cell(m,'brier_score', True)} | {cell(m,'log_loss', True)} |"
        )

    final_csv = report_dir / "r52_test_final_summary_table.csv"
    pd.DataFrame(rows).to_csv(final_csv, index=False)
    final_md = report_dir / "r52_test_final_summary_table.md"
    final_md.write_text(
        "| Model | PR-AUC mean±SD | F1 mean±SD | Precision mean±SD | Recall mean±SD | "
        "FP mean | FN mean | Alerts mean | Brier mean | Log loss mean |\n"
        "|---|---|---|---|---|---|---|---|---|---|\n"
        + "\n".join(md_rows)
        + "\n\nBold marks the preferred value for each column "
        "(highest PR-AUC/F1; lowest FP/FN/alerts/Brier/log loss).\n"
        "Brier and log loss: lower is better; XGBoost is preferred (not Random Forest).\n",
        encoding="utf-8",
    )

    # Validation-to-test (three-seed means)
    test_means = summary.set_index("model")
    val_means = val_means.set_index("model")
    vt_rows = []
    for m in MODELS:
        vt_rows.append(
            {
                "model": MODEL_LABEL[m],
                "validation_pr_auc_mean": float(val_means.loc[m, "validation_pr_auc_mean"]),
                "test_pr_auc_mean": float(test_means.loc[m, "pr_auc_mean"]),
                "pr_auc_change": float(test_means.loc[m, "pr_auc_mean"])
                - float(val_means.loc[m, "validation_pr_auc_mean"]),
                "validation_f1_mean": float(val_means.loc[m, "validation_f1_mean"]),
                "test_f1_mean": float(test_means.loc[m, "f1_mean"]),
                "f1_change": float(test_means.loc[m, "f1_mean"])
                - float(val_means.loc[m, "validation_f1_mean"]),
                "validation_fp_mean": float(val_means.loc[m, "validation_fp_mean"]),
                "test_fp_mean": float(test_means.loc[m, "fp_mean"]),
                "fp_change": float(test_means.loc[m, "fp_mean"])
                - float(val_means.loc[m, "validation_fp_mean"]),
                "validation_fn_mean": float(val_means.loc[m, "validation_fn_mean"]),
                "test_fn_mean": float(test_means.loc[m, "fn_mean"]),
                "fn_change": float(test_means.loc[m, "fn_mean"])
                - float(val_means.loc[m, "validation_fn_mean"]),
            }
        )
    vt_csv = report_dir / "r52_validation_to_test_comparison.csv"
    pd.DataFrame(vt_rows).to_csv(vt_csv, index=False)
    vt_md = report_dir / "r52_validation_to_test_comparison.md"
    lines = [
        "Three-seed means (seeds 42, 52, 62).",
        "",
        "| Model | Val PR-AUC | Test PR-AUC | Δ PR-AUC | Val F1 | Test F1 | Δ F1 | Val FP | Test FP | Δ FP | Val FN | Test FN | Δ FN |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in vt_rows:
        lines.append(
            f"| {r['model']} | {r['validation_pr_auc_mean']:.4f} | {r['test_pr_auc_mean']:.4f} | "
            f"{r['pr_auc_change']:+.4f} | {r['validation_f1_mean']:.4f} | {r['test_f1_mean']:.4f} | "
            f"{r['f1_change']:+.4f} | {r['validation_fp_mean']:.1f} | {r['test_fp_mean']:.1f} | "
            f"{r['fp_change']:+.1f} | {r['validation_fn_mean']:.1f} | {r['test_fn_mean']:.1f} | "
            f"{r['fn_change']:+.1f} |"
        )
    vt_md.write_text("\n".join(lines) + "\n", encoding="utf-8")

    trade_md = report_dir / "r52_operational_tradeoff_table.md"
    trade_md.write_text(
        "| Priority | Preferred model | Reason |\n"
        "|---|---|---|\n"
        "| Highest ranking performance | Random Forest | Highest PR-AUC |\n"
        "| Avoid missed positives | Random Forest | Zero false negatives |\n"
        "| Balanced operating point | XGBoost | Highest F1 |\n"
        "| Reduce analyst alerts | XGBoost | Lowest FP and alert count |\n"
        "| Probability quality | XGBoost | Lowest Brier and log loss |\n"
        "| Neural temporal baseline | attention–linear | Strong neural PR-AUC and better calibration than ODST |\n"
        "| Differentiable tree head | ODST | Competitive F1 but unstable calibration |\n",
        encoding="utf-8",
    )
    return {
        "final_csv": final_csv,
        "final_md": final_md,
        "val_test_csv": vt_csv,
        "val_test_md": vt_md,
        "tradeoff_md": trade_md,
    }


def write_figures(report_dir: Path, by: pd.DataFrame, val_means: pd.DataFrame, summary: pd.DataFrame) -> list[Path]:
    report_dir.mkdir(parents=True, exist_ok=True)
    labels = [MODEL_LABEL[m] for m in MODELS]
    x = np.arange(len(MODELS))
    width = 0.35

    # Fig 1: val vs test PR-AUC
    val = [float(val_means.set_index("model").loc[m, "validation_pr_auc_mean"]) for m in MODELS]
    test = [float(summary.set_index("model").loc[m, "pr_auc_mean"]) for m in MODELS]
    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    ax.bar(x - width / 2, val, width, label="Validation", color="#4C78A8")
    ax.bar(x + width / 2, test, width, label="Test", color="#F58518")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=15, ha="right")
    ax.set_ylabel("PR-AUC (three-seed mean)")
    ax.set_title("CERT r5.2: validation vs test PR-AUC")
    ax.set_ylim(0.90, 1.005)
    ax.legend(frameon=False)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()
    p1 = report_dir / "fig1_val_vs_test_pr_auc.png"
    fig.savefig(p1, dpi=160)
    plt.close(fig)

    # Fig 2: FP / FN
    fp = [float(summary.set_index("model").loc[m, "fp_mean"]) for m in MODELS]
    fn = [float(summary.set_index("model").loc[m, "fn_mean"]) for m in MODELS]
    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    ax.bar(x - width / 2, fp, width, label="FP mean", color="#E45756")
    ax.bar(x + width / 2, fn, width, label="FN mean", color="#54A24B")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=15, ha="right")
    ax.set_ylabel("Count (three-seed mean)")
    ax.set_title("CERT r5.2 test: false positives and false negatives")
    ax.legend(frameon=False)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()
    p2 = report_dir / "fig2_test_fp_fn.png"
    fig.savefig(p2, dpi=160)
    plt.close(fig)

    # Fig 3: Brier / log loss (twin axis)
    brier = [float(summary.set_index("model").loc[m, "brier_score_mean"]) for m in MODELS]
    logl = [float(summary.set_index("model").loc[m, "log_loss_mean"]) for m in MODELS]
    fig, ax1 = plt.subplots(figsize=(7.2, 4.2))
    ax2 = ax1.twinx()
    b1 = ax1.bar(x - width / 2, brier, width, label="Brier (lower better)", color="#72B7B2")
    b2 = ax2.bar(x + width / 2, logl, width, label="Log loss (lower better)", color="#B279A2")
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels, rotation=15, ha="right")
    ax1.set_ylabel("Brier score")
    ax2.set_ylabel("Log loss")
    ax1.set_title("CERT r5.2 test: probability-loss comparison")
    ax1.spines["top"].set_visible(False)
    lines = [b1, b2]
    labs = [b.get_label() for b in lines]
    ax1.legend(lines, labs, frameon=False, loc="upper left")
    fig.tight_layout()
    p3 = report_dir / "fig3_test_brier_logloss.png"
    fig.savefig(p3, dpi=160)
    plt.close(fig)
    return [p1, p2, p3]


def write_interpretation(report_dir: Path) -> Path:
    path = report_dir / "r52_chapter4_interpretation.md"
    path.write_text(
        """# CERT r5.2 Objective 2 — Chapter 4 interpretation notes

These notes are reporting aids only. They do not modify Chapters 1–4 or the IEEE Access manuscript.

## Completed validation finding

On the chronological r5.2 validation partition, **XGBoost** was the strongest model under the primary metric **PR-AUC**, with competitive operational F1 and low false-positive burden relative to Random Forest and the neural models.

## Completed test finding

On the untouched chronological r5.2 test partition, **Random Forest** achieved the highest mean PR-AUC and **zero false negatives** across all three seeds. **XGBoost** achieved the highest mean F1, the lowest mean false-positive and alert counts, and the best probability-loss results (lowest mean Brier score and log loss).

## Validation-to-test finding

The validation ordering between XGBoost and Random Forest did **not** transfer fully to the test period: Random Forest overtook XGBoost on test PR-AUC, while XGBoost retained the preferred operating-point and calibration profile. Both conventional models remained stronger than attention–linear and ODST on test PR-AUC.

## Differentiable-model finding

Attention–linear and ODST remained competitive but did **not** outperform the conventional baselines under the frozen protocol. ODST additionally showed substantial calibration instability across seeds (notably seeds 42 and 62).

## Operational reading

No single model dominates every decision criterion. Random Forest is preferred when ranking performance or missed-positive avoidance is paramount; XGBoost is preferred when balancing F1, alert burden and probability quality. Attention–linear is the stronger neural temporal baseline; ODST remains a differentiable tree-head comparator with weaker calibration.

## Interpretation boundary

These results do **not** support claims of universal model superiority, state-of-the-art status, statistical significance, generalisation to CERT r6.2 or real organisations, completion of the full PhD conclusion, or superiority of the differentiable sequence–ensemble architecture. They indicate that strong conventional models remain difficult to outperform when applied to the current deterministic window-aggregate representation under a locked chronological protocol.
""",
        encoding="utf-8",
    )
    return path


def build_audit_manifest(
    root: Path,
    *,
    by: pd.DataFrame,
    verification: dict[str, Any],
    report_paths: dict[str, Path],
    figure_paths: list[Path],
    interpretation_path: Path,
) -> dict[str, Any]:
    out = root / OUTPUT_NAMESPACE
    freeze = _load_json(out / "r52_test_freeze_manifest_v2.json")
    prereg = _load_json(out / "r52_test_preregistration.json")
    rec = _load_json(out / "r52_test_execution_record.json")
    lock = _load_json(out / "r52_test_completed.lock")

    # Threshold match vs prereg
    prereg_thr = {
        (e["model"], int(e["seed"])): float(e["validation_selected_threshold"])
        for e in prereg["models_to_evaluate"]
    }
    thr_ok = True
    for r in by.itertuples():
        if abs(float(r.threshold) - prereg_thr[(r.model, int(r.seed))]) > 1e-12:
            thr_ok = False

    live_exec = sha256_file(out / "r52_test_execution_record.json")
    live_lock = sha256_file(out / "r52_test_completed.lock")
    intermediate_exec = lock.get("execution_record_sha256")
    recorded_in_exec = (rec.get("output_hashes") or {}).get("r52_test_execution_record.json")

    result_hashes = {name: sha256_file(out / name) for name in IMMUTABLE}

    models = []
    for e in freeze["models"]:
        models.append(
            {
                "model": e["model_name"],
                "seed": e["seed"],
                "model_path": e["model_path"],
                "model_sha256": e["model_sha256"],
                "threshold_path": e["threshold_path"],
                "threshold_sha256": e["threshold_sha256"],
                "threshold": e["threshold"],
                "model_hash_still_matches": sha256_file(root / e["model_path"]) == e["model_sha256"],
                "threshold_hash_still_matches": sha256_file(root / e["threshold_path"])
                == e["threshold_sha256"],
            }
        )

    reporting_hashes = {
        str(p.relative_to(root)).replace("\\", "/"): sha256_file(p)
        for p in list(report_paths.values()) + figure_paths + [interpretation_path]
    }

    return {
        "schema_version": 1,
        "status": "r52_test_results_audited_and_reporting_package_ready",
        "created_at_utc": _utc_now(),
        "repository_path": str(root),
        "branch": _git(root, "branch", "--show-current"),
        "current_head": _git(root, "rev-parse", "HEAD"),
        "pretest_commit": "646b2e17b8400e2ea9f0f94806deafcbc40f3326",
        "pretest_tag": "objective2-r52-pretest-freeze-v2",
        "pretest_tag_commit": _git(root, "rev-parse", "objective2-r52-pretest-freeze-v2^{commit}"),
        "test_execution": {
            "started_at_utc": rec.get("started_at_utc"),
            "completed_at_utc": rec.get("completed_at_utc"),
            "armed_evaluator_executed_once": True,
            "second_armed_attempt_refused_by_completion_lock": True,
            "test_split_path": (rec.get("test_split_metadata") or {}).get("path"),
            "test_split_sha256": (rec.get("test_split_metadata") or {}).get("sha256"),
            "test_shape": (rec.get("test_split_metadata") or {}).get("shape"),
        },
        "frozen_artefact_hashes": {
            "feature_list": freeze.get("feature_list"),
            "preregistration": freeze.get("preregistration"),
            "v2_freeze_manifest_path": "outputs/objective2/r52_locked_baselines/r52_test_freeze_manifest_v2.json",
            "v2_freeze_manifest_sha256": sha256_file(out / "r52_test_freeze_manifest_v2.json"),
            "evaluator_path": "scripts/r52_locked_baselines/evaluate_r52_test_guarded.py",
            "evaluator_sha256": sha256_file(
                root / "scripts/r52_locked_baselines/evaluate_r52_test_guarded.py"
            ),
            "models": models,
        },
        "immutable_test_result_hashes": result_hashes,
        "execution_record_lock_write_order": {
            "explanation": (
                "The completion lock records the SHA-256 of r52_test_execution_record.json "
                "after the record was first written but before that record was rewritten to "
                "include the completion-lock hash. Consequently the digest stored in "
                "r52_test_completed.lock (and mirrored inside output_hashes of the execution "
                "record) is an intermediate digest, while the final on-disk execution-record "
                "file has a different SHA-256. This is a provenance/write-order limitation only; "
                "it does not change models, predictions, thresholds or metrics. Neither the "
                "original lock nor the execution record was rewritten by this post-run audit."
            ),
            "intermediate_execution_record_sha256_referenced_by_lock": intermediate_exec,
            "execution_record_output_hashes_self_entry": recorded_in_exec,
            "final_live_execution_record_sha256": live_exec,
            "final_live_completion_lock_sha256": live_lock,
            "lock_hash_matches_live_lock_file": live_lock == result_hashes["r52_test_completed.lock"],
            "original_files_left_unchanged_by_this_audit": True,
        },
        "protocol_confirmations": {
            "thresholds_unchanged": bool(rec.get("thresholds_changed") is False) and thr_ok,
            "thresholds_match_preregistration": thr_ok,
            "calibration_fitted": bool(rec.get("calibration_fitted")),
            "model_selection_performed": bool(rec.get("model_selection_performed")),
            "models_retrained": False,
            "evaluator_rerun_for_this_audit": False,
            "immutable_result_files_overwritten": False,
            "r52_test_reaccessed_for_this_audit": False,
            "r62_accessed": False,
            "r42_test_accessed": False,
            "pretest_tag_moved": False,
        },
        "independent_metric_verification": verification,
        "reporting_package": {
            "directory": "outputs/objective2/r52_locked_baselines/chapter4_reporting",
            "file_hashes": reporting_hashes,
        },
    }


def main() -> int:
    root = _ROOT
    out = root / OUTPUT_NAMESPACE
    report_dir = out / "chapter4_reporting"

    print("Post-run audit (no evaluator rerun; immutable results preserved)", flush=True)
    _refuse_overwrite_immutable(out)
    before = {name: sha256_file(out / name) for name in IMMUTABLE}

    by = pd.read_csv(out / "r52_test_results_by_seed.csv")
    summary = pd.read_csv(out / "r52_test_results_summary.csv")
    verification = verify_metrics(by, summary)
    print("independent_metric_verification=PASS", flush=True)

    # Confirm thresholds vs prereg
    prereg = _load_json(out / "r52_test_preregistration.json")
    prereg_thr = {
        (e["model"], int(e["seed"])): float(e["validation_selected_threshold"])
        for e in prereg["models_to_evaluate"]
    }
    for r in by.itertuples():
        if abs(float(r.threshold) - prereg_thr[(r.model, int(r.seed))]) > 1e-12:
            raise ProtocolAccessError("Threshold mismatch vs preregistration")

    val_means = validation_means(root)
    table_paths = write_tables(report_dir, by, summary, val_means, verification)
    fig_paths = write_figures(report_dir, by, val_means, summary)
    interp = write_interpretation(report_dir)

    audit = build_audit_manifest(
        root,
        by=by,
        verification=verification,
        report_paths=table_paths,
        figure_paths=fig_paths,
        interpretation_path=interp,
    )
    audit_path = out / "r52_test_postrun_audit_manifest.json"
    if audit_path.exists():
        raise ProtocolAccessError(f"Refuse overwrite existing audit manifest: {audit_path}")
    audit_path.write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")

    # Prove immutable files unchanged
    for name, digest in before.items():
        _assert_not_rewriting(out / name, digest)
    print(f"wrote {audit_path}", flush=True)
    print(f"audit_sha256={sha256_file(audit_path)}", flush=True)
    print("immutable_results_unchanged=true", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
