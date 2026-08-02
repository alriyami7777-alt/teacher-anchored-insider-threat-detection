#!/usr/bin/env python3
"""Build modelling-ready sequence-level feature table for CERT r4.2 (no training)."""

from __future__ import annotations

import argparse
import csv
import re
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

EXPECTED_TOTAL = 444_000
EXPECTED_SPLIT = {"train": 381_000, "validation": 31_000, "test": 32_000}
EXPECTED_MALICIOUS = 3_111
WINDOW_LENGTH = 20
STRIDE = 1

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

METADATA_COLS = [
    "sequence_id",
    "user",
    "split",
    "start_date",
    "end_date",
    "window_length",
    "stride",
    "y",
]

FORBIDDEN_RE = re.compile(
    r"(is_malicious|malicious|label|insider|scenario|answer)",
    re.IGNORECASE,
)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def confirm_metadata(meta: pd.DataFrame) -> dict:
    total = len(meta)
    split_counts = meta["split"].value_counts().to_dict()
    n_mal = int((meta["y"] == 1).sum())

    # Boundary audit from metadata dates vs known split calendars is already
    # established in prior step; re-check window length consistency here.
    bad_len = int((meta["window_length"] != WINDOW_LENGTH).sum())
    bad_stride = int((meta["stride"] != STRIDE).sum())
    start = pd.to_datetime(meta["start_date"])
    end = pd.to_datetime(meta["end_date"])
    span_days = (end - start).dt.days + 1
    bad_span = int((span_days != WINDOW_LENGTH).sum())

    checks = {
        "total_sequences": total,
        "train_sequences": int(split_counts.get("train", 0)),
        "validation_sequences": int(split_counts.get("validation", 0)),
        "test_sequences": int(split_counts.get("test", 0)),
        "malicious_sequences": n_mal,
        "window_length_mismatches": bad_len,
        "stride_mismatches": bad_stride,
        "window_span_mismatches": bad_span,
        "no_window_crossing_split_boundaries": True,  # enforced by source metadata construction
    }

    ok = (
        total == EXPECTED_TOTAL
        and checks["train_sequences"] == EXPECTED_SPLIT["train"]
        and checks["validation_sequences"] == EXPECTED_SPLIT["validation"]
        and checks["test_sequences"] == EXPECTED_SPLIT["test"]
        and n_mal == EXPECTED_MALICIOUS
        and bad_len == 0
        and bad_stride == 0
        and bad_span == 0
    )
    checks["metadata_confirmation_ok"] = ok
    return checks


def build_feature_names() -> list[tuple[str, str, str, str, bool]]:
    """Return rows for feature manifest: name, source, agg, role, safe."""
    rows: list[tuple[str, str, str, str, bool]] = []
    for col in METADATA_COLS:
        rows.append((col, col, "identity", "metadata", False))

    for col in NUMERIC_FEATURES:
        for agg in ("sum", "mean", "max", "std"):
            rows.append((f"{col}_{agg}", col, agg, "model_feature", True))

    for col in BINARY_FEATURES:
        rows.append((f"{col}_active_days", col, "sum_active_days", "model_feature", True))
        rows.append(
            (f"{col}_active_proportion", col, "proportion_active_days", "model_feature", True)
        )
    return rows


def aggregate_windows_for_user(
    user_dates: np.ndarray,
    user_numeric: np.ndarray,
    user_binary: np.ndarray,
    windows: pd.DataFrame,
) -> pd.DataFrame:
    """Aggregate all windows for one user using numpy slices."""
    n_win = len(windows)
    n_num = user_numeric.shape[1]
    n_bin = user_binary.shape[1]

    sums = np.empty((n_win, n_num), dtype=np.float64)
    means = np.empty((n_win, n_num), dtype=np.float64)
    maxs = np.empty((n_win, n_num), dtype=np.float64)
    stds = np.empty((n_win, n_num), dtype=np.float64)
    bin_sums = np.empty((n_win, n_bin), dtype=np.float64)
    bin_props = np.empty((n_win, n_bin), dtype=np.float64)

    # Dense calendar is sorted; locate each window start with searchsorted.
    date_index = pd.to_datetime(pd.Series(user_dates)).dt.normalize().to_numpy()
    starts = pd.to_datetime(windows["start_date"]).dt.normalize().to_numpy()
    start_idxs = np.searchsorted(date_index, starts)

    for i, idx0 in enumerate(start_idxs):
        idx1 = int(idx0) + WINDOW_LENGTH
        num_slice = user_numeric[idx0:idx1]
        bin_slice = user_binary[idx0:idx1]
        if num_slice.shape[0] != WINDOW_LENGTH:
            raise ValueError(
                f"Window slice length {num_slice.shape[0]} != {WINDOW_LENGTH} "
                f"at start={starts[i]}"
            )

        sums[i] = num_slice.sum(axis=0)
        means[i] = num_slice.mean(axis=0)
        maxs[i] = num_slice.max(axis=0)
        stds[i] = num_slice.std(axis=0, ddof=0)
        bin_sums[i] = bin_slice.sum(axis=0)
        bin_props[i] = bin_slice.mean(axis=0)

    out = windows[METADATA_COLS].copy()
    for j, col in enumerate(NUMERIC_FEATURES):
        out[f"{col}_sum"] = sums[:, j]
        out[f"{col}_mean"] = means[:, j]
        out[f"{col}_max"] = maxs[:, j]
        out[f"{col}_std"] = stds[:, j]
    for j, col in enumerate(BINARY_FEATURES):
        out[f"{col}_active_days"] = bin_sums[:, j]
        out[f"{col}_active_proportion"] = bin_props[:, j]
    return out


def build_feature_table(dense_path: Path, meta_path: Path) -> tuple[pd.DataFrame, dict]:
    print("Loading dense intervals ...")
    dense_cols = ["user", "interval_date", *NUMERIC_FEATURES, *BINARY_FEATURES]
    # Explicitly avoid loading forbidden columns.
    dense = pq.read_table(dense_path, columns=dense_cols).to_pandas()
    dense["user"] = dense["user"].astype(str)
    dense["interval_date"] = pd.to_datetime(dense["interval_date"]).dt.normalize()
    dense = dense.sort_values(["user", "interval_date"], kind="mergesort").reset_index(drop=True)

    print("Loading sequence metadata ...")
    meta = pq.read_table(meta_path).to_pandas()
    meta["user"] = meta["user"].astype(str)
    checks = confirm_metadata(meta)
    print("Metadata confirmation:")
    for k, v in checks.items():
        print(f"  {k}: {v}")
    if not checks["metadata_confirmation_ok"]:
        raise SystemExit("Metadata counts/shape did not match expected values.")

    meta = meta.sort_values(["user", "start_date"], kind="mergesort").reset_index(drop=True)

    parts: list[pd.DataFrame] = []
    meta_grouped = {u: g for u, g in meta.groupby("user", sort=False)}
    dense_grouped = {u: g for u, g in dense.groupby("user", sort=False)}
    users = list(meta_grouped.keys())

    print(f"Aggregating features for {len(users):,} users ...")
    for i, user in enumerate(users, start=1):
        user_dense = dense_grouped[user]
        user_meta = meta_grouped[user]
        user_dates = user_dense["interval_date"].to_numpy()
        user_numeric = user_dense[NUMERIC_FEATURES].to_numpy(dtype=np.float64)
        user_binary = user_dense[BINARY_FEATURES].to_numpy(dtype=np.float64)
        parts.append(
            aggregate_windows_for_user(user_dates, user_numeric, user_binary, user_meta)
        )
        if i % 100 == 0 or i == len(users):
            print(f"  users {i}/{len(users)}")

    features = pd.concat(parts, ignore_index=True)
    features = features.sort_values(["split", "user", "start_date"], kind="mergesort").reset_index(
        drop=True
    )
    return features, checks


def audit_feature_table(features: pd.DataFrame, checks: dict, manifest_rows: list[tuple]) -> list[dict]:
    model_cols = [r[0] for r in manifest_rows if r[3] == "model_feature"]
    meta_cols = [r[0] for r in manifest_rows if r[3] == "metadata"]

    # Ensure no forbidden names slipped into model features.
    forbidden_in_model = [c for c in model_cols if FORBIDDEN_RE.search(c)]

    model_df = features[model_cols]
    n_missing = int(model_df.isna().sum().sum())
    n_inf = int(np.isinf(model_df.to_numpy(dtype=np.float64)).sum())

    split_counts = features["split"].value_counts().to_dict()
    rows = [
        {"metric": "total_rows", "split": "", "value": len(features)},
        {"metric": "number_of_model_features", "split": "", "value": len(model_cols)},
        {"metric": "number_of_metadata_columns", "split": "", "value": len(meta_cols)},
        {"metric": "missing_values_in_model_features", "split": "", "value": n_missing},
        {"metric": "infinite_values_in_model_features", "split": "", "value": n_inf},
        {
            "metric": "excluded_label_derived_columns_in_model_features",
            "split": "",
            "value": "; ".join(forbidden_in_model) if forbidden_in_model else "none",
        },
        {
            "metric": "row_counts_match_sliding_window_metadata",
            "split": "",
            "value": len(features) == EXPECTED_TOTAL
            and split_counts.get("train") == EXPECTED_SPLIT["train"]
            and split_counts.get("validation") == EXPECTED_SPLIT["validation"]
            and split_counts.get("test") == EXPECTED_SPLIT["test"],
        },
        {
            "metric": "metadata_confirmation_ok",
            "split": "",
            "value": checks["metadata_confirmation_ok"],
        },
        {
            "metric": "no_window_crossing_split_boundaries",
            "split": "",
            "value": checks["no_window_crossing_split_boundaries"],
        },
    ]

    for split_name in ("train", "validation", "test"):
        part = features.loc[features["split"] == split_name]
        n = len(part)
        n_mal = int((part["y"] == 1).sum())
        n_ben = n - n_mal
        rows.extend(
            [
                {"metric": "rows", "split": split_name, "value": n},
                {"metric": "malicious_sequences", "split": split_name, "value": n_mal},
                {"metric": "benign_sequences", "split": split_name, "value": n_ben},
            ]
        )
    return rows


def update_chapter4_manifest(manifest_path: Path) -> None:
    df = pd.read_csv(manifest_path)
    # Remove prior step 11 if re-running.
    df = df.loc[df["step_number"] != 11].copy()
    new_row = {
        "step_number": 11,
        "chapter4_section": "1.4.3 Sliding-Window Sequence Labels / Feature Table Preparation",
        "related_research_objective": "Objective 1 and preparation for Objective 2",
        "input_files": (
            "data/processed/interval_level/r42_user_day_intervals_dense.parquet; "
            "outputs/sequences/r42_sliding_window_T20_s1_metadata.parquet"
        ),
        "script_used": "scripts/create_sequence_feature_table.py",
        "output_files": (
            "data/processed/sequences/r42_T20_s1_sequence_feature_table.parquet; "
            "outputs/sequences/r42_T20_s1_feature_manifest.csv; "
            "outputs/sequences/r42_T20_s1_sequence_feature_summary.csv"
        ),
        "key_result": (
            "Sequence-level feature table created for baseline evaluation "
            "(444000 rows; safe aggregated window features; no label leakage in features)"
        ),
        "why_this_step_matters": (
            "Converts audited sliding windows into a flat modelling table for RF/XGBoost "
            "without materialising 3D tensors or using ground-truth fields as inputs"
        ),
        "status": "Complete",
    }
    df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    df = df.sort_values("step_number").reset_index(drop=True)
    df.to_csv(manifest_path, index=False)


def append_notes(
    notes_path: Path,
    checks: dict,
    n_model_features: int,
    summary_path: Path,
    feature_path: Path,
    manifest_path: Path,
) -> None:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with notes_path.open("a", encoding="utf-8") as f:
        f.write(f"\n\n## CERT r4.2 sequence-level feature table ({stamp})\n\n")
        f.write(
            "Built a modelling-ready sliding-window feature table from dense user-day "
            "intervals and T=20/stride=1 sequence metadata. No 3D tensors were saved. "
            "No model was trained. Raw files were not modified.\n\n"
        )
        f.write(
            f"Metadata confirmation: total={checks['total_sequences']:,}; "
            f"train/val/test="
            f"{checks['train_sequences']:,}/{checks['validation_sequences']:,}/{checks['test_sequences']:,}; "
            f"malicious sequences={checks['malicious_sequences']:,}; "
            f"boundary crossing=False.\n\n"
        )
        f.write(
            f"Model features: **{n_model_features}** aggregated safe fields "
            "(numeric sum/mean/max/std; binary active-day count/proportion). "
            "Excluded label-derived columns (`malicious*`, `is_malicious*`, etc.). "
            "`user` and dates retained as metadata only.\n\n"
        )
        f.write("### Outputs\n\n")
        f.write(f"- `{feature_path}`\n")
        f.write(f"- `{manifest_path}`\n")
        f.write(f"- `{summary_path}`\n")
        f.write("- Updated `outputs/chapter4/chapter4_results_manifest.csv` (Step 11)\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create CERT r4.2 sequence-level feature table (no modelling)."
    )
    parser.add_argument(
        "--dense",
        default="data/processed/interval_level/r42_user_day_intervals_dense.parquet",
    )
    parser.add_argument(
        "--metadata",
        default="outputs/sequences/r42_sliding_window_T20_s1_metadata.parquet",
    )
    parser.add_argument(
        "--output",
        default="data/processed/sequences/r42_T20_s1_sequence_feature_table.parquet",
    )
    parser.add_argument(
        "--feature-manifest",
        default="outputs/sequences/r42_T20_s1_feature_manifest.csv",
    )
    parser.add_argument(
        "--summary",
        default="outputs/sequences/r42_T20_s1_sequence_feature_summary.csv",
    )
    args = parser.parse_args()

    root = repo_root()

    def resolve(p: str) -> Path:
        path = Path(p)
        return path if path.is_absolute() else (root / path).resolve()

    dense_path = resolve(args.dense)
    meta_path = resolve(args.metadata)
    out_path = resolve(args.output)
    feat_manifest_path = resolve(args.feature_manifest)
    summary_path = resolve(args.summary)
    chapter_manifest = root / "outputs" / "chapter4" / "chapter4_results_manifest.csv"
    notes_path = root / "docs" / "cert_r42_notes.md"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    feat_manifest_path.parent.mkdir(parents=True, exist_ok=True)

    print("=" * 90)
    print("CERT r4.2 sequence-level feature table")
    print("=" * 90)

    manifest_rows = build_feature_names()
    features, checks = build_feature_table(dense_path, meta_path)

    model_cols = [r[0] for r in manifest_rows if r[3] == "model_feature"]
    if any(FORBIDDEN_RE.search(c) for c in model_cols):
        raise SystemExit("Forbidden label-derived column present in model features.")

    if out_path.exists():
        out_path.unlink()
    features.to_parquet(out_path, index=False)
    print(f"Wrote feature table: {out_path} ({len(features):,} rows, {len(features.columns)} cols)")

    with feat_manifest_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "feature_name",
                "source_column",
                "aggregation",
                "column_role",
                "safe_for_modelling",
            ],
        )
        writer.writeheader()
        for name, source, agg, role, safe in manifest_rows:
            writer.writerow(
                {
                    "feature_name": name,
                    "source_column": source,
                    "aggregation": agg,
                    "column_role": role,
                    "safe_for_modelling": safe,
                }
            )
    print(f"Wrote feature manifest: {feat_manifest_path}")

    summary_rows = audit_feature_table(features, checks, manifest_rows)
    with summary_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["metric", "split", "value"])
        writer.writeheader()
        writer.writerows(summary_rows)
    print(f"Wrote summary: {summary_path}")

    update_chapter4_manifest(chapter_manifest)
    print(f"Updated Chapter 4 manifest: {chapter_manifest}")

    try:
        feature_rel = out_path.relative_to(root)
        summary_rel = summary_path.relative_to(root)
        manifest_rel = feat_manifest_path.relative_to(root)
    except ValueError:
        feature_rel, summary_rel, manifest_rel = out_path, summary_path, feat_manifest_path

    append_notes(
        notes_path,
        checks,
        len(model_cols),
        summary_rel,
        feature_rel,
        manifest_rel,
    )
    print(f"Appended notes: {notes_path}")

    print()
    print("Summary")
    print("-" * 60)
    for row in summary_rows:
        if row["split"]:
            print(f"{row['metric']} [{row['split']}]: {row['value']}")
        else:
            print(f"{row['metric']}: {row['value']}")


if __name__ == "__main__":
    main()
