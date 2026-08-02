#!/usr/bin/env python3
"""Controlled comparison of daily (T=1), weekly (T=7), and 20-day representations."""

from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from sklearn.metrics import (
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from xgboost import XGBClassifier

# Fixed chronological split sizes (shared dense calendar).
N_TRAIN_DAYS = 400
N_VAL_DAYS = 50
N_TEST_DAYS = 51
EXPECTED_USERS = 1000
EXPECTED_DAYS = 501
STRIDE = 1
WINDOW_LENGTHS = (1, 7, 20)

SAFE_DAILY_FEATURES = [
    "total_events",
    "logon_count",
    "device_count",
    "file_count",
    "email_count",
    "http_count",
    "active_duration_minutes",
    "has_logon_activity",
    "has_device_activity",
    "has_file_activity",
    "has_email_activity",
    "has_http_activity",
    "is_active_day",
]

NUMERIC_FEATURES = [
    "total_events",
    "logon_count",
    "device_count",
    "file_count",
    "email_count",
    "http_count",
    "active_duration_minutes",
]

BINARY_FEATURES = [
    "has_logon_activity",
    "has_device_activity",
    "has_file_activity",
    "has_email_activity",
    "has_http_activity",
    "is_active_day",
]

META_COLS = {
    "sequence_id",
    "user",
    "split",
    "start_date",
    "end_date",
    "window_length",
    "stride",
    "y",
    "n_active_days",
}

FORBIDDEN_RE = re.compile(
    r"(^y$|is_malicious|malicious|label|insider|scenario|answer)",
    re.IGNORECASE,
)

EXISTING_T20_FEATURES = (
    "data/processed/sequences/r42_T20_s1_sequence_feature_table.parquet"
)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def resolve(root: Path, p: str | Path) -> Path:
    path = Path(p)
    return path if path.is_absolute() else (root / path).resolve()


def model_feature_columns(columns: list[str]) -> list[str]:
    feats = [c for c in columns if c not in META_COLS and not FORBIDDEN_RE.search(c)]
    # Deterministic order for fair comparison.
    return sorted(feats)


def split_index_ranges() -> dict[str, tuple[int, int]]:
    return {
        "train": (0, N_TRAIN_DAYS),
        "validation": (N_TRAIN_DAYS, N_TRAIN_DAYS + N_VAL_DAYS),
        "test": (N_TRAIN_DAYS + N_VAL_DAYS, EXPECTED_DAYS),
    }


def build_windows_and_features(
    dense: pd.DataFrame,
    window_length: int,
) -> tuple[pd.DataFrame, dict]:
    """Create in-split sliding windows and aggregated tabular features for one T."""
    ranges = split_index_ranges()
    users = sorted(dense["user"].astype(str).unique().tolist())
    calendar = sorted(pd.to_datetime(dense["interval_date"]).dt.normalize().unique().tolist())
    if len(calendar) != EXPECTED_DAYS:
        raise SystemExit(f"Expected {EXPECTED_DAYS} calendar days; found {len(calendar)}")
    if len(users) != EXPECTED_USERS:
        raise SystemExit(f"Expected {EXPECTED_USERS} users; found {len(users)}")

    dense = dense.sort_values(["user", "interval_date"], kind="mergesort")
    grouped = {str(u): g.reset_index(drop=True) for u, g in dense.groupby("user", sort=False)}

    all_rows: list[pd.DataFrame] = []
    crosses = False
    mal_days_global: set[tuple[str, str]] = set()
    covered_mal_days: set[tuple[str, str]] = set()
    seq_counter = 0

    for user in users:
        ud = grouped[user]
        dates = pd.to_datetime(ud["interval_date"]).dt.normalize()
        date_strs = dates.dt.strftime("%Y-%m-%d").to_numpy()
        mal = ud["is_malicious_interval"].to_numpy(dtype=np.int8)
        active = ud["is_active_day"].to_numpy(dtype=np.float64)
        num = ud[NUMERIC_FEATURES].to_numpy(dtype=np.float64)
        binary = ud[BINARY_FEATURES].to_numpy(dtype=np.float64)

        mal_idx = np.flatnonzero(mal == 1)
        for i in mal_idx:
            mal_days_global.add((user, date_strs[i]))

        user_parts: list[dict[str, np.ndarray | object]] = []

        for split_name, (lo, hi) in ranges.items():
            n_split = hi - lo
            n_win = n_split - window_length + 1
            if n_win <= 0:
                raise SystemExit(f"Split {split_name} too short for T={window_length}")

            starts = np.arange(lo, lo + n_win, STRIDE, dtype=np.int64)
            if np.any(starts < lo) or np.any(starts + window_length > hi):
                crosses = True

            n = len(starts)
            # Gather windows: (n, T, F)
            offs = np.arange(window_length, dtype=np.int64)
            gather = starts[:, None] + offs[None, :]
            num_w = num[gather]  # (n, T, n_num)
            bin_w = binary[gather]
            mal_w = mal[gather]
            act_w = active[gather]

            y = (mal_w.max(axis=1) == 1).astype(np.int8)
            # Coverage for positive windows.
            pos = np.flatnonzero(y == 1)
            for pi in pos:
                for off in np.flatnonzero(mal_w[pi] == 1):
                    covered_mal_days.add((user, date_strs[starts[pi] + off]))

            row: dict[str, object] = {
                "sequence_id": np.array(
                    [f"T{window_length}_seq_{seq_counter + i + 1:08d}" for i in range(n)],
                    dtype=object,
                ),
                "user": np.full(n, user, dtype=object),
                "split": np.full(n, split_name, dtype=object),
                "start_date": date_strs[starts],
                "end_date": date_strs[starts + window_length - 1],
                "window_length": np.full(n, window_length, dtype=np.int16),
                "stride": np.full(n, STRIDE, dtype=np.int16),
                "y": y,
                "n_active_days": act_w.sum(axis=1),
            }
            seq_counter += n

            for j, col in enumerate(NUMERIC_FEATURES):
                vals = num_w[:, :, j]
                row[f"{col}_sum"] = vals.sum(axis=1)
                row[f"{col}_mean"] = vals.mean(axis=1)
                row[f"{col}_max"] = vals.max(axis=1)
                row[f"{col}_std"] = vals.std(axis=1, ddof=0)  # 0 for T=1

            for j, col in enumerate(BINARY_FEATURES):
                vals = bin_w[:, :, j]
                row[f"{col}_active_days"] = vals.sum(axis=1)
                row[f"{col}_active_proportion"] = vals.mean(axis=1)

            user_parts.append(pd.DataFrame(row))

        all_rows.append(pd.concat(user_parts, ignore_index=True))

    features = pd.concat(all_rows, ignore_index=True)
    model_cols = model_feature_columns(list(features.columns))
    arr = features[model_cols].to_numpy(dtype=np.float64)
    if np.isnan(arr).any() or np.isinf(arr).any():
        features[model_cols] = np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)

    n_mal_total = len(mal_days_global)
    n_covered = len(covered_mal_days)
    summary = {
        "window_length": window_length,
        "stride": STRIDE,
        "n_users": len(users),
        "calendar_start": pd.Timestamp(calendar[0]).date().isoformat(),
        "calendar_end": pd.Timestamp(calendar[-1]).date().isoformat(),
        "train_days": N_TRAIN_DAYS,
        "validation_days": N_VAL_DAYS,
        "test_days": N_TEST_DAYS,
        "train_period": (
            f"{pd.Timestamp(calendar[0]).date().isoformat()} to "
            f"{pd.Timestamp(calendar[N_TRAIN_DAYS - 1]).date().isoformat()}"
        ),
        "validation_period": (
            f"{pd.Timestamp(calendar[N_TRAIN_DAYS]).date().isoformat()} to "
            f"{pd.Timestamp(calendar[N_TRAIN_DAYS + N_VAL_DAYS - 1]).date().isoformat()}"
        ),
        "test_period": (
            f"{pd.Timestamp(calendar[N_TRAIN_DAYS + N_VAL_DAYS]).date().isoformat()} to "
            f"{pd.Timestamp(calendar[-1]).date().isoformat()}"
        ),
        "total_sequences": int(len(features)),
        "windows_cross_split_boundaries": bool(crosses),
        "malicious_user_day_intervals_total": n_mal_total,
        "malicious_user_day_intervals_covered": n_covered,
        "malicious_user_day_coverage_pct": (
            round(100.0 * n_covered / n_mal_total, 6) if n_mal_total else 0.0
        ),
        "n_model_features": len(model_cols),
        "safe_daily_feature_source": ";".join(SAFE_DAILY_FEATURES),
    }

    for split_name in ("train", "validation", "test"):
        part = features.loc[features["split"] == split_name]
        n = len(part)
        n_mal = int((part["y"] == 1).sum())
        summary[f"{split_name}_sequences"] = n
        summary[f"{split_name}_malicious"] = n_mal
        summary[f"{split_name}_benign"] = n - n_mal
        summary[f"{split_name}_malicious_pct"] = (
            round(100.0 * n_mal / n, 6) if n else 0.0
        )

    return features, summary


def choose_threshold(y_val: np.ndarray, p_val: np.ndarray) -> float:
    candidates = set(np.linspace(0.01, 0.99, 99).tolist())
    candidates.update(float(q) for q in np.quantile(p_val, np.linspace(0.01, 0.99, 50)))
    best_t, best_f1 = 0.5, -1.0
    for t in sorted(candidates):
        f1 = f1_score(y_val, (p_val >= t).astype(int), zero_division=0)
        if f1 > best_f1:
            best_f1 = float(f1)
            best_t = float(t)
    return best_t


def make_xgb(scale_pos_weight: float) -> XGBClassifier:
    return XGBClassifier(
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
    )


def evaluate_representation(
    features: pd.DataFrame,
    window_length: int,
) -> tuple[dict, dict, dict]:
    feature_cols = model_feature_columns(list(features.columns))
    # Assertions on feature hygiene.
    if any(FORBIDDEN_RE.search(c) for c in feature_cols):
        raise SystemExit(f"Label-derived columns in model features for T={window_length}")
    if len(feature_cols) != 40:
        raise SystemExit(
            f"Expected 40 model features for T={window_length}; got {len(feature_cols)}"
        )

    train = features.loc[features["split"] == "train"]
    val = features.loc[features["split"] == "validation"]
    test = features.loc[features["split"] == "test"]

    x_train = train[feature_cols].to_numpy(dtype=np.float32)
    y_train = train["y"].to_numpy(dtype=np.int32)
    x_val = val[feature_cols].to_numpy(dtype=np.float32)
    y_val = val["y"].to_numpy(dtype=np.int32)
    x_test = test[feature_cols].to_numpy(dtype=np.float32)
    y_test = test["y"].to_numpy(dtype=np.int32)

    if (
        np.isnan(x_train).any()
        or np.isinf(x_train).any()
        or np.isnan(x_val).any()
        or np.isinf(x_val).any()
        or np.isnan(x_test).any()
        or np.isinf(x_test).any()
    ):
        raise SystemExit(f"Non-finite values in features for T={window_length}")

    # Train-only scaling (z-score), then transform val/test.
    mean = x_train.mean(axis=0)
    scale = x_train.std(axis=0, ddof=0)
    scale[scale == 0] = 1.0
    x_train_s = ((x_train - mean) / scale).astype(np.float32)
    x_val_s = ((x_val - mean) / scale).astype(np.float32)
    x_test_s = ((x_test - mean) / scale).astype(np.float32)

    n_pos = int((y_train == 1).sum())
    n_neg = int((y_train == 0).sum())
    spw = (n_neg / n_pos) if n_pos else 1.0

    model = make_xgb(spw)
    t0 = time.perf_counter()
    model.fit(x_train_s, y_train)
    train_time = time.perf_counter() - t0

    t1 = time.perf_counter()
    p_val = model.predict_proba(x_val_s)[:, 1]
    p_test = model.predict_proba(x_test_s)[:, 1]
    infer_time = time.perf_counter() - t1

    threshold = choose_threshold(y_val, p_val)
    y_hat = (p_test >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y_test, y_hat, labels=[0, 1]).ravel()
    fpr = fp / (fp + tn) if (fp + tn) else 0.0
    fnr = fn / (fn + tp) if (fn + tp) else 0.0

    result = {
        "window_length": window_length,
        "n_model_features": len(feature_cols),
        "scale_pos_weight_train": spw,
        "selected_threshold": threshold,
        "training_time_sec": train_time,
        "test_inference_time_sec": infer_time,
        "test_precision": float(precision_score(y_test, y_hat, zero_division=0)),
        "test_recall": float(recall_score(y_test, y_hat, zero_division=0)),
        "test_f1": float(f1_score(y_test, y_hat, zero_division=0)),
        "test_pr_auc": float(average_precision_score(y_test, p_test)),
        "test_roc_auc": float(roc_auc_score(y_test, p_test)),
        "test_fpr": float(fpr),
        "test_fnr": float(fnr),
        "test_fp": int(fp),
        "test_fn": int(fn),
        "test_tn": int(tn),
        "test_tp": int(tp),
        "scaling_fitted_on_train_only": True,
        "threshold_selected_on_validation_only": True,
        "test_not_used_for_tuning": True,
    }
    cm = {
        "window_length": window_length,
        "split": "test",
        "threshold": threshold,
        "tn": int(tn),
        "fp": int(fp),
        "fn": int(fn),
        "tp": int(tp),
    }
    thr = {
        "window_length": window_length,
        "selected_threshold": threshold,
        "selection_criterion": "max_validation_f1",
        "scale_pos_weight_train": spw,
    }
    return result, cm, thr


def run_assertions(
    dataset_summaries: list[dict],
    feature_tables: dict[int, pd.DataFrame],
) -> list[str]:
    messages = []
    sources = {s["safe_daily_feature_source"] for s in dataset_summaries}
    if len(sources) != 1:
        raise SystemExit("Feature source mismatch across window lengths.")
    messages.append("PASS: all datasets use the same 13 safe daily feature source")

    for s in dataset_summaries:
        if s["windows_cross_split_boundaries"]:
            raise SystemExit(f"Boundary crossing detected for T={s['window_length']}")
    messages.append("PASS: no windows cross split boundaries")

    for t, df in feature_tables.items():
        feats = model_feature_columns(list(df.columns))
        if any(FORBIDDEN_RE.search(c) for c in feats):
            raise SystemExit(f"Forbidden features present for T={t}")
        arr = df[feats].to_numpy(dtype=np.float64)
        if np.isnan(arr).any() or np.isinf(arr).any():
            raise SystemExit(f"Non-finite values for T={t}")
        # Chronology: within user/split, start_date non-decreasing.
        for (user, split), g in df.groupby(["user", "split"], sort=False):
            starts = pd.to_datetime(g["start_date"]).to_numpy()
            if np.any(starts[1:] < starts[:-1]):
                raise SystemExit(f"Chronology broken for user={user}, split={split}, T={t}")
    messages.append("PASS: no label-derived columns in model features")
    messages.append("PASS: no missing/infinite model feature values")
    messages.append("PASS: chronological ordering preserved within user/split")

    for s in dataset_summaries:
        if s["malicious_user_day_intervals_covered"] != s["malicious_user_day_intervals_total"]:
            # For T>1 every malicious day in a split of adequate length is coverable;
            # require full coverage for all T given split sizes >= T.
            raise SystemExit(
                f"Incomplete malicious coverage for T={s['window_length']}: "
                f"{s['malicious_user_day_intervals_covered']}/"
                f"{s['malicious_user_day_intervals_total']}"
            )
    messages.append(
        "PASS: all malicious user-day intervals are covered and traceable to verified labels"
    )
    messages.append("PASS: test data not used for training or threshold selection (by protocol)")
    return messages


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare T=1, T=7, T=20 temporal representations with XGBoost."
    )
    parser.add_argument(
        "--dense",
        default="data/processed/interval_level/r42_user_day_intervals_dense.parquet",
    )
    parser.add_argument(
        "--output-dir",
        default="outputs/temporal_windows",
    )
    parser.add_argument(
        "--reuse-t20",
        default=EXISTING_T20_FEATURES,
        help="Existing T=20 feature table to reuse (copy, not overwrite source).",
    )
    args = parser.parse_args()

    root = repo_root()
    dense_path = resolve(root, args.dense)
    out_dir = resolve(root, args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    reuse_t20 = resolve(root, args.reuse_t20)

    print("=" * 90)
    print("CERT r4.2 temporal window comparison (T=1, 7, 20)")
    print("=" * 90)
    print(f"Dense source: {dense_path}")
    print(f"Output dir:   {out_dir}")

    dense = pq.read_table(
        dense_path,
        columns=["user", "interval_date", "is_malicious_interval", *SAFE_DAILY_FEATURES],
    ).to_pandas()
    dense["user"] = dense["user"].astype(str)
    dense["interval_date"] = pd.to_datetime(dense["interval_date"]).dt.normalize()

    if dense["user"].nunique() != EXPECTED_USERS or dense["interval_date"].nunique() != EXPECTED_DAYS:
        raise SystemExit("Dense dataset shape mismatch.")

    feature_tables: dict[int, pd.DataFrame] = {}
    dataset_summaries: list[dict] = []
    results: list[dict] = []
    cms: list[dict] = []
    thresholds: dict[str, dict] = {}

    filename_map = {
        1: "daily_t1_features.parquet",
        7: "weekly_t7_features.parquet",
        20: "sliding_t20_features.parquet",
    }

    for t in WINDOW_LENGTHS:
        print(f"\n--- Building representation T={t} ---")
        out_feat = out_dir / filename_map[t]
        features, summary = build_windows_and_features(dense, t)
        features.to_parquet(out_feat, index=False)
        if t == 20 and reuse_t20.exists():
            print(
                f"  Original T=20 table left untouched at {reuse_t20.name}; "
                f"wrote fair-comparison copy to {out_feat.name}"
            )

        print(
            f"  sequences={summary['total_sequences']:,}; "
            f"malicious coverage="
            f"{summary['malicious_user_day_intervals_covered']}/"
            f"{summary['malicious_user_day_intervals_total']}"
        )
        feature_tables[t] = features
        dataset_summaries.append(summary)

        print(f"  Training XGBoost for T={t} ...")
        result, cm, thr = evaluate_representation(features, t)
        for key in (
            "train_sequences",
            "validation_sequences",
            "test_sequences",
            "train_malicious",
            "validation_malicious",
            "test_malicious",
            "train_benign",
            "validation_benign",
            "test_benign",
            "train_malicious_pct",
            "validation_malicious_pct",
            "test_malicious_pct",
            "n_users",
            "train_period",
            "validation_period",
            "test_period",
            "malicious_user_day_intervals_total",
            "malicious_user_day_intervals_covered",
            "malicious_user_day_coverage_pct",
        ):
            result[key] = summary[key]
        results.append(result)
        cms.append(cm)
        thresholds[f"T{t}"] = thr
        print(
            f"  test F1={result['test_f1']:.4f}, Recall={result['test_recall']:.4f}, "
            f"PR-AUC={result['test_pr_auc']:.4f}, FPR={result['test_fpr']:.6f}"
        )

    assertion_msgs = run_assertions(dataset_summaries, feature_tables)
    print("\nValidation assertions:")
    for msg in assertion_msgs:
        print(f"  {msg}")

    # Save summaries.
    ds_path = out_dir / "temporal_window_dataset_summary.csv"
    res_path = out_dir / "temporal_window_baseline_results.csv"
    cm_path = out_dir / "temporal_window_confusion_matrices.csv"
    thr_path = out_dir / "temporal_window_thresholds.json"

    pd.DataFrame(dataset_summaries).to_csv(ds_path, index=False)
    pd.DataFrame(results).to_csv(res_path, index=False)
    pd.DataFrame(cms).to_csv(cm_path, index=False)
    thr_path.write_text(json.dumps(thresholds, indent=2), encoding="utf-8")

    # Chapter 4 manifest + notes.
    chapter_manifest = root / "outputs" / "chapter4" / "chapter4_results_manifest.csv"
    if chapter_manifest.exists():
        man = pd.read_csv(chapter_manifest)
        man = man.loc[man["step_number"] != 14].copy()
        man = pd.concat(
            [
                man,
                pd.DataFrame(
                    [
                        {
                            "step_number": 14,
                            "chapter4_section": "1.5 Temporal representation comparison",
                            "related_research_objective": "Objective 1 / Objective 2 preparation",
                            "input_files": str(dense_path.relative_to(root)),
                            "script_used": "scripts/compare_temporal_windows.py",
                            "output_files": (
                                f"{out_dir.relative_to(root)}/daily_t1_features.parquet; "
                                f"{out_dir.relative_to(root)}/weekly_t7_features.parquet; "
                                f"{out_dir.relative_to(root)}/sliding_t20_features.parquet; "
                                f"{ds_path.relative_to(root)}; "
                                f"{res_path.relative_to(root)}; "
                                f"{cm_path.relative_to(root)}; "
                                f"{thr_path.relative_to(root)}"
                            ),
                            "key_result": (
                                "Controlled XGBoost comparison of T=1, T=7, T=20 "
                                "under identical splits/features/training protocol"
                            ),
                            "why_this_step_matters": (
                                "Identifies which temporal grain best supports preliminary "
                                "detection performance before deep sequence modelling"
                            ),
                            "status": "Complete",
                        }
                    ]
                ),
            ],
            ignore_index=True,
        )
        man = man.sort_values("step_number").reset_index(drop=True)
        man.to_csv(chapter_manifest, index=False)

    # Best metrics.
    res_df = pd.DataFrame(results)
    best_recall = int(res_df.loc[res_df["test_recall"].idxmax(), "window_length"])
    best_f1 = int(res_df.loc[res_df["test_f1"].idxmax(), "window_length"])
    best_pr = int(res_df.loc[res_df["test_pr_auc"].idxmax(), "window_length"])
    best_fpr = int(res_df.loc[res_df["test_fpr"].idxmin(), "window_length"])

    notes_path = root / "docs" / "cert_r42_notes.md"
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with notes_path.open("a", encoding="utf-8") as f:
        f.write(f"\n\n## CERT r4.2 temporal window comparison T=1/7/20 ({stamp})\n\n")
        f.write(
            "Compared daily (T=1), weekly (T=7), and 20-day (T=20) representations using "
            "identical chronological splits, the same 13 safe daily features, identical "
            "aggregations, and the same XGBoost protocol. Thresholds selected on validation "
            "only. Original dense dataset and prior T=20 artefacts were not overwritten at source.\n\n"
        )
        f.write("### Test metrics\n\n")
        f.write("| T | Precision | Recall | F1 | PR-AUC | ROC-AUC | FPR | FNR | FP | FN |\n")
        f.write("|---|-----------|--------|----|--------|---------|-----|-----|----|----|\n")
        for _, r in res_df.sort_values("window_length").iterrows():
            f.write(
                f"| {int(r['window_length'])} | {r['test_precision']:.4f} | {r['test_recall']:.4f} | "
                f"{r['test_f1']:.4f} | {r['test_pr_auc']:.4f} | {r['test_roc_auc']:.4f} | "
                f"{r['test_fpr']:.6f} | {r['test_fnr']:.4f} | {int(r['test_fp'])} | {int(r['test_fn'])} |\n"
            )
        f.write("\n### Best by metric\n\n")
        f.write(f"- Best Recall: **T={best_recall}**\n")
        f.write(f"- Best F1: **T={best_f1}**\n")
        f.write(f"- Best PR-AUC: **T={best_pr}**\n")
        f.write(f"- Best (lowest) FPR: **T={best_fpr}**\n\n")
        f.write("### Outputs\n\n")
        f.write(f"- `{out_dir.relative_to(root)}/`\n")

    # Terminal comparison summary.
    print("\n" + "=" * 90)
    print("COMPARISON SUMMARY (test split)")
    print("=" * 90)
    print(
        f"{'T':>4} {'Seq':>10} {'Mal%':>8} {'P':>8} {'R':>8} {'F1':>8} "
        f"{'PR-AUC':>8} {'ROC-AUC':>8} {'FPR':>10} {'FP':>6} {'FN':>6}"
    )
    for _, r in res_df.sort_values("window_length").iterrows():
        print(
            f"{int(r['window_length']):>4} {int(r['test_sequences']):>10,} "
            f"{r['test_malicious_pct']:>7.3f}% "
            f"{r['test_precision']:>8.4f} {r['test_recall']:>8.4f} {r['test_f1']:>8.4f} "
            f"{r['test_pr_auc']:>8.4f} {r['test_roc_auc']:>8.4f} {r['test_fpr']:>10.6f} "
            f"{int(r['test_fp']):>6} {int(r['test_fn']):>6}"
        )
    print()
    print(f"Best Recall : T={best_recall}")
    print(f"Best F1     : T={best_f1}")
    print(f"Best PR-AUC : T={best_pr}")
    print(f"Best FPR    : T={best_fpr} (lowest)")
    print()
    print("Saved:")
    print(f"  {ds_path}")
    print(f"  {res_path}")
    print(f"  {cm_path}")
    print(f"  {thr_path}")
    for t, name in filename_map.items():
        print(f"  {out_dir / name}")


if __name__ == "__main__":
    main()
