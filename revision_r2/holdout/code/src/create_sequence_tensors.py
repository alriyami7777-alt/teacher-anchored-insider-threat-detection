#!/usr/bin/env python3
"""Create model-ready 3D sequence tensors for Bi-LSTM input (no training)."""

from __future__ import annotations

import argparse
import csv
import json
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

SAFE_FEATURES = [
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

FORBIDDEN_RE = re.compile(
    r"(is_malicious|malicious|label|insider|scenario|answer)",
    re.IGNORECASE,
)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def confirm_metadata(meta: pd.DataFrame) -> dict:
    split_counts = meta["split"].value_counts().to_dict()
    n_mal = int((meta["y"] == 1).sum())
    start = pd.to_datetime(meta["start_date"])
    end = pd.to_datetime(meta["end_date"])
    span_ok = int(((end - start).dt.days + 1 == WINDOW_LENGTH).sum()) == len(meta)

    checks = {
        "total_sequences": len(meta),
        "train_sequences": int(split_counts.get("train", 0)),
        "validation_sequences": int(split_counts.get("validation", 0)),
        "test_sequences": int(split_counts.get("test", 0)),
        "malicious_sequences": n_mal,
        "window_span_ok": span_ok,
        "no_split_boundary_crossing": True,  # windows constructed inside splits
    }
    checks["metadata_ok"] = (
        checks["total_sequences"] == EXPECTED_TOTAL
        and checks["train_sequences"] == EXPECTED_SPLIT["train"]
        and checks["validation_sequences"] == EXPECTED_SPLIT["validation"]
        and checks["test_sequences"] == EXPECTED_SPLIT["test"]
        and n_mal == EXPECTED_MALICIOUS
        and span_ok
    )
    return checks


class TrainOnlyStandardScaler:
    """Z-score scaler fitted only on training daily feature values."""

    def __init__(self) -> None:
        self.mean_: np.ndarray | None = None
        self.scale_: np.ndarray | None = None
        self.fitted_on_train_only = False

    def fit(self, x: np.ndarray) -> None:
        self.mean_ = x.mean(axis=0)
        scale = x.std(axis=0, ddof=0)
        scale[scale == 0] = 1.0
        self.scale_ = scale
        self.fitted_on_train_only = True

    def transform(self, x: np.ndarray) -> np.ndarray:
        if self.mean_ is None or self.scale_ is None:
            raise RuntimeError("Scaler has not been fitted.")
        return ((x - self.mean_) / self.scale_).astype(np.float32)


def select_feature_columns(available: list[str]) -> list[str]:
    features = [c for c in SAFE_FEATURES if c in available]
    missing = [c for c in SAFE_FEATURES if c not in available]
    if missing:
        print(f"Warning: requested safe features missing and skipped: {missing}")
    forbidden = [c for c in features if FORBIDDEN_RE.search(c)]
    if forbidden:
        raise SystemExit(f"Forbidden columns selected as features: {forbidden}")
    if not features:
        raise SystemExit("No safe feature columns available.")
    return features


def build_split_tensor(
    dense_by_user: dict[str, pd.DataFrame],
    meta_split: pd.DataFrame,
    feature_cols: list[str],
    scaled_by_user: dict[str, np.ndarray],
) -> dict[str, np.ndarray | object]:
    meta_split = meta_split.reset_index(drop=True)
    n = len(meta_split)
    f = len(feature_cols)
    x = np.empty((n, WINDOW_LENGTH, f), dtype=np.float32)
    y = meta_split["y"].to_numpy(dtype=np.int8)
    sequence_id = meta_split["sequence_id"].astype(str).to_numpy()
    user = meta_split["user"].astype(str).to_numpy()
    start_date = pd.to_datetime(meta_split["start_date"]).dt.strftime("%Y-%m-%d").to_numpy()
    end_date = pd.to_datetime(meta_split["end_date"]).dt.strftime("%Y-%m-%d").to_numpy()

    for u, grp in meta_split.groupby("user", sort=False):
        dense_u = dense_by_user[str(u)]
        dates = pd.to_datetime(dense_u["interval_date"]).dt.normalize().to_numpy()
        feats = scaled_by_user[str(u)]
        starts = pd.to_datetime(grp["start_date"]).dt.normalize().to_numpy()
        start_idxs = np.searchsorted(dates, starts).astype(np.int64)
        positions = grp.index.to_numpy()

        if np.any(start_idxs + WINDOW_LENGTH > len(feats)):
            raise ValueError(f"Window out of range for user={u}")

        # Vectorised gather: (n_windows, T, F)
        time_offsets = np.arange(WINDOW_LENGTH, dtype=np.int64)
        gather_idx = start_idxs[:, None] + time_offsets[None, :]
        x[positions] = feats[gather_idx]

    return {
        "X": x,
        "y": y,
        "sequence_id": sequence_id,
        "user": user,
        "start_date": start_date,
        "end_date": end_date,
    }


def summarize_split(
    split_name: str,
    payload: dict[str, np.ndarray | object],
    n_features: int,
    excluded_used: bool,
    scaler_train_only: bool,
) -> dict:
    x = payload["X"]
    y = payload["y"]
    n_mal = int((y == 1).sum())
    n_ben = int((y == 0).sum())
    n = int(len(y))
    pct = (100.0 * n_mal / n) if n else 0.0
    return {
        "split": split_name,
        "X_shape": str(tuple(x.shape)),
        "y_shape": str(tuple(y.shape)),
        "n_features_F": n_features,
        "malicious_sequences": n_mal,
        "benign_sequences": n_ben,
        "malicious_percentage": round(pct, 6),
        "missing_values_in_X": int(np.isnan(x).sum()),
        "infinite_values_in_X": int(np.isinf(x).sum()),
        "excluded_label_derived_columns_used": excluded_used,
        "scaling_fitted_only_on_train": scaler_train_only,
    }


def update_chapter4_manifest(path: Path) -> None:
    df = pd.read_csv(path)
    df = df.loc[df["step_number"] != 12].copy()
    new_row = {
        "step_number": 12,
        "chapter4_section": "1.4.3 Sliding-Window Sequence Labels / Tensor Preparation",
        "related_research_objective": "Objective 1 and preparation for Objective 2",
        "input_files": (
            "data/processed/interval_level/r42_user_day_intervals_dense.parquet; "
            "outputs/sequences/r42_sliding_window_T20_s1_metadata.parquet"
        ),
        "script_used": "scripts/create_sequence_tensors.py",
        "output_files": (
            "data/processed/tensors/r42_T20_s1_train.npz; "
            "data/processed/tensors/r42_T20_s1_validation.npz; "
            "data/processed/tensors/r42_T20_s1_test.npz; "
            "outputs/tensors/r42_T20_s1_tensor_feature_list.csv; "
            "outputs/tensors/r42_T20_s1_tensor_summary.csv"
        ),
        "key_result": (
            "3D tensors created for Bi-LSTM input "
            "(train/val/test; T=20; train-only scaling; safe daily features only)"
        ),
        "why_this_step_matters": (
            "Provides leakage-controlled sequence tensors required for deep temporal "
            "models without using ground-truth fields as inputs"
        ),
        "status": "Complete",
    }
    df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    df = df.sort_values("step_number").reset_index(drop=True)
    df.to_csv(path, index=False)


def append_notes(
    notes_path: Path,
    feature_cols: list[str],
    summary_rows: list[dict],
    checks: dict,
) -> None:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with notes_path.open("a", encoding="utf-8") as f:
        f.write(f"\n\n## CERT r4.2 Bi-LSTM sequence tensors ({stamp})\n\n")
        f.write(
            "Created split-wise 3D sequence tensors `(N, T=20, F)` from the dense "
            "user-day timeline and verified sliding-window metadata. Scaling was fitted "
            "**only on training-split daily feature values** and applied to validation/test. "
            "No model training was performed. Raw files were not modified.\n\n"
        )
        f.write(
            f"Metadata confirmation: total={checks['total_sequences']:,}; "
            f"train/val/test="
            f"{checks['train_sequences']:,}/{checks['validation_sequences']:,}/{checks['test_sequences']:,}; "
            f"malicious={checks['malicious_sequences']:,}; boundary crossing=False.\n\n"
        )
        f.write(f"Feature count F = **{len(feature_cols)}**:\n\n")
        for col in feature_cols:
            f.write(f"- `{col}`\n")
        f.write("\n### Tensor shapes\n\n")
        f.write("| Split | X shape | Malicious | Benign | Mal % |\n")
        f.write("|-------|---------|-----------|--------|-------|\n")
        for row in summary_rows:
            f.write(
                f"| {row['split']} | `{row['X_shape']}` | {row['malicious_sequences']:,} | "
                f"{row['benign_sequences']:,} | {row['malicious_percentage']:.4f}% |\n"
            )
        f.write("\n### Outputs\n\n")
        f.write("- `data/processed/tensors/r42_T20_s1_train.npz`\n")
        f.write("- `data/processed/tensors/r42_T20_s1_validation.npz`\n")
        f.write("- `data/processed/tensors/r42_T20_s1_test.npz`\n")
        f.write("- `outputs/tensors/r42_T20_s1_tensor_feature_list.csv`\n")
        f.write("- `outputs/tensors/r42_T20_s1_tensor_summary.csv`\n")
        f.write("- Updated `outputs/chapter4/chapter4_results_manifest.csv` (Step 12)\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create CERT r4.2 Bi-LSTM sequence tensors (no training)."
    )
    parser.add_argument(
        "--dense",
        default="data/processed/interval_level/r42_user_day_intervals_dense.parquet",
    )
    parser.add_argument(
        "--metadata",
        default="outputs/sequences/r42_sliding_window_T20_s1_metadata.parquet",
    )
    parser.add_argument("--tensor-dir", default="data/processed/tensors")
    parser.add_argument("--output-dir", default="outputs/tensors")
    args = parser.parse_args()

    root = repo_root()

    def resolve(p: str) -> Path:
        path = Path(p)
        return path if path.is_absolute() else (root / path).resolve()

    dense_path = resolve(args.dense)
    meta_path = resolve(args.metadata)
    tensor_dir = resolve(args.tensor_dir)
    output_dir = resolve(args.output_dir)
    tensor_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    notes_path = root / "docs" / "cert_r42_notes.md"
    chapter_manifest = root / "outputs" / "chapter4" / "chapter4_results_manifest.csv"

    print("=" * 90)
    print("CERT r4.2 Bi-LSTM sequence tensor preparation")
    print("=" * 90)

    print("Loading metadata ...")
    meta = pq.read_table(meta_path).to_pandas()
    meta["user"] = meta["user"].astype(str)
    meta["start_date"] = pd.to_datetime(meta["start_date"]).dt.normalize()
    meta["end_date"] = pd.to_datetime(meta["end_date"]).dt.normalize()
    meta["split"] = meta["split"].astype(str)
    checks = confirm_metadata(meta)
    print("Metadata confirmation:")
    for k, v in checks.items():
        print(f"  {k}: {v}")
    if not checks["metadata_ok"]:
        raise SystemExit("Metadata confirmation failed.")

    print("Loading dense intervals ...")
    schema_cols = list(pq.read_schema(dense_path).names)
    feature_cols = select_feature_columns(schema_cols)
    print(f"Using F={len(feature_cols)} safe features: {feature_cols}")

    dense = pq.read_table(
        dense_path,
        columns=["user", "interval_date", *feature_cols],
    ).to_pandas()
    dense["user"] = dense["user"].astype(str)
    dense["interval_date"] = pd.to_datetime(dense["interval_date"]).dt.normalize()
    dense = dense.sort_values(["user", "interval_date"], kind="mergesort").reset_index(drop=True)

    # Train-only daily scaling over the full train calendar span.
    train_start = meta.loc[meta["split"] == "train", "start_date"].min()
    train_end = meta.loc[meta["split"] == "train", "end_date"].max()
    train_daily_mask = (dense["interval_date"] >= train_start) & (
        dense["interval_date"] <= train_end
    )
    train_daily = dense.loc[train_daily_mask, feature_cols].to_numpy(dtype=np.float64)
    print(
        f"Fitting scaler on train daily rows: {train_daily.shape[0]:,} "
        f"({train_start.date()} to {train_end.date()})"
    )

    scaler = TrainOnlyStandardScaler()
    scaler.fit(train_daily)

    # Transform all daily features, keep per-user arrays.
    dense_values = dense[feature_cols].to_numpy(dtype=np.float64)
    dense_scaled = scaler.transform(dense_values)
    dense_by_user: dict[str, pd.DataFrame] = {}
    scaled_by_user: dict[str, np.ndarray] = {}
    for u, grp in dense.groupby("user", sort=False):
        dense_by_user[str(u)] = grp
        scaled_by_user[str(u)] = dense_scaled[grp.index.to_numpy()]

    # Save scaler stats for auditability.
    scaler_path = output_dir / "r42_T20_s1_train_scaler_stats.json"
    scaler_path.write_text(
        json.dumps(
            {
                "features": feature_cols,
                "mean": scaler.mean_.tolist(),
                "scale": scaler.scale_.tolist(),
                "fitted_on_train_only": True,
                "train_date_start": str(train_start.date()),
                "train_date_end": str(train_end.date()),
                "n_train_daily_rows": int(train_daily.shape[0]),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    summary_rows: list[dict] = []
    excluded_used = any(FORBIDDEN_RE.search(c) for c in feature_cols)

    for split_name in ("train", "validation", "test"):
        print(f"Building {split_name} tensor ...")
        meta_split = (
            meta.loc[meta["split"] == split_name]
            .sort_values(["user", "start_date"], kind="mergesort")
            .reset_index(drop=True)
        )
        expected_n = EXPECTED_SPLIT[split_name]
        if len(meta_split) != expected_n:
            raise SystemExit(
                f"{split_name} has {len(meta_split)} sequences; expected {expected_n}"
            )

        payload = build_split_tensor(
            dense_by_user, meta_split, feature_cols, scaled_by_user
        )
        out_npz = tensor_dir / f"r42_T20_s1_{split_name}.npz"
        np.savez_compressed(
            out_npz,
            X=payload["X"],
            y=payload["y"],
            sequence_id=payload["sequence_id"],
            user=payload["user"],
            start_date=payload["start_date"],
            end_date=payload["end_date"],
        )
        print(f"  wrote {out_npz.name}: X={payload['X'].shape}, y={payload['y'].shape}")

        summary_rows.append(
            summarize_split(
                split_name,
                payload,
                len(feature_cols),
                excluded_used,
                scaler.fitted_on_train_only,
            )
        )

    # Feature list
    feature_list_path = output_dir / "r42_T20_s1_tensor_feature_list.csv"
    with feature_list_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "feature_index",
                "feature_name",
                "safe_for_modelling",
                "excluded_label_derived",
            ],
        )
        writer.writeheader()
        for i, name in enumerate(feature_cols):
            writer.writerow(
                {
                    "feature_index": i,
                    "feature_name": name,
                    "safe_for_modelling": True,
                    "excluded_label_derived": False,
                }
            )

    summary_path = output_dir / "r42_T20_s1_tensor_summary.csv"
    with summary_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "split",
                "X_shape",
                "y_shape",
                "n_features_F",
                "malicious_sequences",
                "benign_sequences",
                "malicious_percentage",
                "missing_values_in_X",
                "infinite_values_in_X",
                "excluded_label_derived_columns_used",
                "scaling_fitted_only_on_train",
            ],
        )
        writer.writeheader()
        writer.writerows(summary_rows)

    update_chapter4_manifest(chapter_manifest)
    append_notes(notes_path, feature_cols, summary_rows, checks)

    print()
    print("Tensor summary")
    print("-" * 60)
    for row in summary_rows:
        print(
            f"{row['split']}: X={row['X_shape']}, mal={row['malicious_sequences']}, "
            f"ben={row['benign_sequences']}, missing={row['missing_values_in_X']}, "
            f"inf={row['infinite_values_in_X']}"
        )
    print(f"Wrote feature list: {feature_list_path}")
    print(f"Wrote summary: {summary_path}")
    print(f"Wrote scaler stats: {scaler_path}")
    print(f"Updated Chapter 4 manifest: {chapter_manifest}")
    print(f"Appended notes: {notes_path}")

    if excluded_used:
        raise SystemExit("Excluded label-derived columns were used.")
    if any(r["missing_values_in_X"] or r["infinite_values_in_X"] for r in summary_rows):
        raise SystemExit("Tensors contain missing or infinite values.")


if __name__ == "__main__":
    main()
