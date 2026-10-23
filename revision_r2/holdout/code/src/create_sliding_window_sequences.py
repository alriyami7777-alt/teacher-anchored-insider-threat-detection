#!/usr/bin/env python3
"""Auditable sliding-window sequence labelling for CERT r4.2 (no modelling)."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime
from pathlib import Path

import duckdb
import pandas as pd
import pyarrow.parquet as pq

EXPECTED_USERS = 1_000
EXPECTED_DAYS = 501
EXPECTED_ROWS = 501_000
WINDOW_LENGTH = 20
STRIDE = 1
TRAIN_FRAC = 0.80
VAL_FRAC = 0.10
# Test gets the remainder.

FORBIDDEN_FEATURE_PATTERNS = (
    "is_malicious",
    "malicious",
    "label",
    "insider",
    "scenario",
    "answer",
)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def posix(path: Path) -> str:
    return str(path).replace("\\", "/")


def is_forbidden_feature(column: str) -> bool:
    lc = column.lower()
    return any(tok in lc for tok in FORBIDDEN_FEATURE_PATTERNS)


def safe_feature_columns(columns: list[str]) -> list[str]:
    """Columns that are safe to use later as model inputs (not identifiers alone)."""
    identity_or_meta = {
        "user",
        "interval_date",
        "sequence_id",
        "split",
        "start_date",
        "end_date",
        "window_length",
        "stride",
        "y",
    }
    safe = []
    for col in columns:
        if col in identity_or_meta:
            continue
        if is_forbidden_feature(col):
            continue
        safe.append(col)
    return safe


def confirm_dense_shape(path: Path) -> dict:
    con = duckdb.connect()
    try:
        row = con.execute(
            f"""
            SELECT
                COUNT(*) AS n_rows,
                COUNT(DISTINCT "user") AS n_users,
                COUNT(DISTINCT interval_date) AS n_days,
                MIN(interval_date) AS earliest,
                MAX(interval_date) AS latest,
                CAST(SUM(is_malicious_interval) AS BIGINT) AS malicious_intervals
            FROM read_parquet('{posix(path)}')
            """
        ).fetchone()
    finally:
        con.close()

    n_rows, n_users, n_days, earliest, latest, mal_intervals = row
    ok = (
        int(n_users) == EXPECTED_USERS
        and int(n_days) == EXPECTED_DAYS
        and int(n_rows) == EXPECTED_ROWS
    )
    return {
        "n_rows": int(n_rows),
        "n_users": int(n_users),
        "n_days": int(n_days),
        "earliest": str(earliest),
        "latest": str(latest),
        "malicious_intervals": int(mal_intervals),
        "shape_ok": ok,
    }


def split_day_counts(n_days: int) -> tuple[int, int, int]:
    n_train = int(n_days * TRAIN_FRAC)
    n_val = int(n_days * VAL_FRAC)
    n_test = n_days - n_train - n_val
    if n_train < WINDOW_LENGTH or n_val < WINDOW_LENGTH or n_test < WINDOW_LENGTH:
        raise ValueError(
            f"Split sizes too small for T={WINDOW_LENGTH}: "
            f"train={n_train}, val={n_val}, test={n_test}"
        )
    return n_train, n_val, n_test


def assign_split_for_index(idx: int, n_train: int, n_val: int) -> str:
    if idx < n_train:
        return "train"
    if idx < n_train + n_val:
        return "validation"
    return "test"


def build_sequence_metadata(dense_path: Path) -> tuple[pd.DataFrame, dict]:
    """Create sliding-window metadata without materialising 3D feature tensors."""
    print("Loading dense intervals (selected columns) ...")
    table = pq.read_table(
        dense_path,
        columns=["user", "interval_date", "is_malicious_interval", "is_active_day"],
    )
    df = table.to_pandas()
    df["interval_date"] = pd.to_datetime(df["interval_date"]).dt.normalize()
    df = df.sort_values(["user", "interval_date"], kind="mergesort").reset_index(drop=True)

    users = sorted(df["user"].astype(str).unique().tolist())
    calendar = sorted(df["interval_date"].unique().tolist())
    n_days = len(calendar)
    n_train, n_val, n_test = split_day_counts(n_days)

    split_index_ranges = {
        "train": (0, n_train),
        "validation": (n_train, n_train + n_val),
        "test": (n_train + n_val, n_days),
    }
    split_ranges = {
        name: (calendar[lo], calendar[hi - 1])
        for name, (lo, hi) in split_index_ranges.items()
    }

    print(
        f"Date-order split sizes (days): train={n_train}, "
        f"validation={n_val}, test={n_test}"
    )
    for split_name, (start, end) in split_ranges.items():
        print(f"  {split_name}: {start.date()} -> {end.date()}")

    records: list[dict] = []
    seq_counter = 0
    window_crosses_boundary = False

    # Precompute per-user arrays for speed.
    grouped = {
        str(user): grp
        for user, grp in df.groupby(df["user"].astype(str), sort=False)
    }

    for user_i, user in enumerate(users, start=1):
        user_df = grouped[user]
        dates = user_df["interval_date"].tolist()
        mal = user_df["is_malicious_interval"].astype(int).to_numpy()
        active = user_df["is_active_day"].astype(int).to_numpy()

        if len(dates) != n_days:
            raise ValueError(
                f"User {user} has {len(dates)} days; expected {n_days} dense days"
            )

        for split_name, (lo, hi) in split_index_ranges.items():
            # Windows must lie entirely inside [lo, hi).
            max_start = hi - WINDOW_LENGTH
            start_idx = lo
            while start_idx <= max_start:
                end_idx = start_idx + WINDOW_LENGTH  # exclusive
                # Boundary audit: window must stay inside split span.
                if start_idx < lo or end_idx > hi:
                    window_crosses_boundary = True

                y = 1 if int(mal[start_idx:end_idx].max()) == 1 else 0
                n_active = int(active[start_idx:end_idx].sum())
                seq_counter += 1
                records.append(
                    {
                        "sequence_id": f"seq_{seq_counter:08d}",
                        "user": user,
                        "split": split_name,
                        "start_date": dates[start_idx].date().isoformat(),
                        "end_date": dates[end_idx - 1].date().isoformat(),
                        "window_length": WINDOW_LENGTH,
                        "stride": STRIDE,
                        "n_active_days": n_active,
                        "y": y,
                    }
                )
                start_idx += STRIDE

        if user_i % 100 == 0 or user_i == len(users):
            print(f"  processed users {user_i}/{len(users)}; sequences so far={seq_counter:,}")

    meta = pd.DataFrame.from_records(records)

    # Coverage: every malicious user-day should appear in >=1 window of its split.
    mal_days = df.loc[df["is_malicious_interval"].astype(int) == 1, ["user", "interval_date"]].copy()
    mal_days["user"] = mal_days["user"].astype(str)
    mal_days["interval_date"] = pd.to_datetime(mal_days["interval_date"]).dt.normalize()
    mal_days["day"] = mal_days["interval_date"].dt.date.astype(str)

    meta_cov = meta.copy()
    meta_cov["start_date"] = pd.to_datetime(meta_cov["start_date"])
    meta_cov["end_date"] = pd.to_datetime(meta_cov["end_date"])

    # Expand each sequence to covered days via merge on user, then filter date range.
    # For ~400k sequences this is heavy; instead check per malicious day with grouped windows.
    windows_by_user = {
        u: g[["start_date", "end_date"]].to_numpy()
        for u, g in meta_cov.groupby("user", sort=False)
    }

    uncovered = []
    for _, row in mal_days.iterrows():
        u = row["user"]
        d = row["interval_date"]
        wins = windows_by_user.get(u)
        if wins is None or len(wins) == 0:
            uncovered.append((u, row["day"]))
            continue
        # Vectorized containment: start <= d <= end
        starts = wins[:, 0]
        ends = wins[:, 1]
        if not (((starts <= d) & (ends >= d)).any()):
            uncovered.append((u, row["day"]))

    all_malicious_covered = len(uncovered) == 0

    summary_extra = {
        "n_train_days": n_train,
        "n_validation_days": n_val,
        "n_test_days": n_test,
        "split_ranges": {
            k: (v[0].date().isoformat(), v[1].date().isoformat())
            for k, v in split_ranges.items()
        },
        "window_crosses_split_boundaries": window_crosses_boundary,
        "all_malicious_intervals_covered": all_malicious_covered,
        "uncovered_malicious_intervals": len(uncovered),
        "malicious_interval_count": int(len(mal_days)),
    }
    return meta, summary_extra


def build_summary(meta: pd.DataFrame, shape: dict, extra: dict, safe_features: list[str]) -> list[dict]:
    rows: list[dict] = [
        {"metric": "confirmed_users", "split": "", "value": shape["n_users"]},
        {"metric": "confirmed_calendar_days", "split": "", "value": shape["n_days"]},
        {"metric": "confirmed_dense_rows", "split": "", "value": shape["n_rows"]},
        {"metric": "window_length_T", "split": "", "value": WINDOW_LENGTH},
        {"metric": "stride", "split": "", "value": STRIDE},
        {"metric": "total_sequences", "split": "", "value": int(len(meta))},
        {
            "metric": "window_crosses_split_boundaries",
            "split": "",
            "value": bool(extra["window_crosses_split_boundaries"]),
        },
        {
            "metric": "all_malicious_intervals_covered_by_at_least_one_sequence",
            "split": "",
            "value": bool(extra["all_malicious_intervals_covered"]),
        },
        {
            "metric": "malicious_interval_count",
            "split": "",
            "value": extra["malicious_interval_count"],
        },
        {
            "metric": "uncovered_malicious_intervals",
            "split": "",
            "value": extra["uncovered_malicious_intervals"],
        },
        {
            "metric": "safe_feature_columns",
            "split": "",
            "value": "; ".join(safe_features),
        },
        {
            "metric": "excluded_ground_truth_style_columns_rule",
            "split": "",
            "value": ", ".join(FORBIDDEN_FEATURE_PATTERNS),
        },
    ]

    for split_name in ("train", "validation", "test"):
        part = meta.loc[meta["split"] == split_name]
        n_seq = int(len(part))
        n_mal = int((part["y"] == 1).sum())
        n_ben = n_seq - n_mal
        pct = (100.0 * n_mal / n_seq) if n_seq else 0.0
        n_users = int(part["user"].nunique())
        date_min = part["start_date"].min() if n_seq else ""
        date_max = part["end_date"].max() if n_seq else ""
        split_start, split_end = extra["split_ranges"][split_name]

        rows.extend(
            [
                {"metric": "sequences", "split": split_name, "value": n_seq},
                {"metric": "malicious_sequences", "split": split_name, "value": n_mal},
                {"metric": "benign_sequences", "split": split_name, "value": n_ben},
                {
                    "metric": "malicious_sequence_percentage",
                    "split": split_name,
                    "value": round(pct, 6),
                },
                {"metric": "users", "split": split_name, "value": n_users},
                {
                    "metric": "split_calendar_date_range",
                    "split": split_name,
                    "value": f"{split_start} to {split_end}",
                },
                {
                    "metric": "sequence_window_date_range",
                    "split": split_name,
                    "value": f"{date_min} to {date_max}",
                },
            ]
        )
    return rows


def append_notes(
    notes_path: Path,
    shape: dict,
    meta: pd.DataFrame,
    extra: dict,
    safe_features: list[str],
    meta_rel: Path,
    summary_rel: Path,
) -> None:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with notes_path.open("a", encoding="utf-8") as f:
        f.write(f"\n\n## CERT r4.2 sliding-window sequence labelling ({stamp})\n\n")
        f.write(
            "Created auditable sliding-window sequence metadata from the dense user-day "
            "interval table. No 3D feature tensors were materialised. Raw files were not "
            "modified. No model training was performed.\n\n"
        )
        f.write(
            f"Input: `data/processed/interval_level/r42_user_day_intervals_dense.parquet`\n\n"
        )
        f.write(
            f"Confirmed dense shape: **{shape['n_users']:,} users**, "
            f"**{shape['n_days']:,} calendar days**, "
            f"**{shape['n_rows']:,} rows** "
            f"({'OK' if shape['shape_ok'] else 'MISMATCH'}).\n\n"
        )
        f.write(
            f"Window settings: **T = {WINDOW_LENGTH}**, **stride = {STRIDE}**.\n\n"
        )
        f.write(
            "Split protocol: per shared calendar, chronological **80% / 10% / 10%** "
            f"(train={extra['n_train_days']} days, validation={extra['n_validation_days']} days, "
            f"test={extra['n_test_days']} days). Sliding windows are generated **only inside** "
            "each split and therefore cannot cross split boundaries.\n\n"
        )
        f.write(
            "Label rule: `y = 1` if the window contains at least one "
            "`is_malicious_interval = 1` user-day; else `y = 0`.\n\n"
        )

        f.write("### Sequence counts\n\n")
        f.write(f"- Total sequences: **{len(meta):,}**\n")
        for split_name in ("train", "validation", "test"):
            part = meta.loc[meta["split"] == split_name]
            n_seq = len(part)
            n_mal = int((part["y"] == 1).sum())
            n_ben = n_seq - n_mal
            pct = (100.0 * n_mal / n_seq) if n_seq else 0.0
            start, end = extra["split_ranges"][split_name]
            f.write(
                f"- **{split_name}**: sequences={n_seq:,}, malicious={n_mal:,}, "
                f"benign={n_ben:,}, malicious%={pct:.4f}%, users={part['user'].nunique():,}, "
                f"calendar={start} to {end}\n"
            )
        f.write("\n")

        f.write("### Integrity checks\n\n")
        f.write(
            f"- Any window crosses train/validation/test boundaries: "
            f"**{extra['window_crosses_split_boundaries']}**\n"
        )
        f.write(
            f"- All malicious user-day intervals covered by ≥1 sequence: "
            f"**{extra['all_malicious_intervals_covered']}** "
            f"(uncovered={extra['uncovered_malicious_intervals']})\n\n"
        )

        f.write("### Safe feature columns for later modelling\n\n")
        f.write(
            "Ground-truth-derived columns matching "
            "`is_malicious` / `malicious` / `label` / `insider` / `scenario` / `answer` "
            "are excluded from candidate features. Safe interval fields:\n\n"
        )
        for col in safe_features:
            f.write(f"- `{col}`\n")
        f.write(
            "\nNote: `user` / `interval_date` are identifiers/temporal keys used to build "
            "sequences; labels are stored only in metadata as `y`.\n\n"
        )

        f.write("### Generated output files\n\n")
        f.write(f"- `{meta_rel}`\n")
        f.write(f"- `{summary_rel}`\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create CERT r4.2 sliding-window sequence metadata (no modelling)."
    )
    parser.add_argument(
        "--input",
        default="data/processed/interval_level/r42_user_day_intervals_dense.parquet",
    )
    parser.add_argument(
        "--metadata-output",
        default="outputs/sequences/r42_sliding_window_T20_s1_metadata.parquet",
    )
    parser.add_argument(
        "--summary-output",
        default="outputs/sequences/r42_sliding_window_T20_s1_summary.csv",
    )
    args = parser.parse_args()

    root = repo_root()
    input_path = Path(args.input)
    if not input_path.is_absolute():
        input_path = (root / input_path).resolve()
    meta_path = Path(args.metadata_output)
    if not meta_path.is_absolute():
        meta_path = (root / meta_path).resolve()
    summary_path = Path(args.summary_output)
    if not summary_path.is_absolute():
        summary_path = (root / summary_path).resolve()
    notes_path = root / "docs" / "cert_r42_notes.md"

    meta_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.parent.mkdir(parents=True, exist_ok=True)

    print("=" * 90)
    print("CERT r4.2 sliding-window sequence labelling")
    print("=" * 90)
    print(f"Input: {input_path}")
    print()

    if not input_path.exists():
        raise FileNotFoundError(input_path)

    shape = confirm_dense_shape(input_path)
    print("Dense shape confirmation:")
    for k, v in shape.items():
        print(f"  {k}: {v}")
    if not shape["shape_ok"]:
        raise SystemExit(
            f"Dense shape mismatch: expected users={EXPECTED_USERS}, "
            f"days={EXPECTED_DAYS}, rows={EXPECTED_ROWS}"
        )
    print()

    schema_cols = list(pq.read_schema(input_path).names)
    safe_features = safe_feature_columns(schema_cols)
    print("Safe feature columns for later modelling:")
    for col in safe_features:
        print(f"  - {col}")
    print("Excluded ground-truth-style columns present in file:")
    for col in schema_cols:
        if is_forbidden_feature(col):
            print(f"  - {col}")
    print()

    meta, extra = build_sequence_metadata(input_path)
    meta = meta.sort_values(["split", "user", "start_date"], kind="mergesort").reset_index(
        drop=True
    )

    # Write metadata parquet
    if meta_path.exists():
        meta_path.unlink()
    meta.to_parquet(meta_path, index=False)
    print(f"Wrote metadata: {meta_path} ({len(meta):,} sequences)")

    summary_rows = build_summary(meta, shape, extra, safe_features)
    with summary_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["metric", "split", "value"])
        writer.writeheader()
        writer.writerows(summary_rows)
    print(f"Wrote summary: {summary_path}")

    print()
    print("Sequence summary")
    print("-" * 60)
    print(f"total_sequences: {len(meta):,}")
    for split_name in ("train", "validation", "test"):
        part = meta.loc[meta["split"] == split_name]
        n_seq = len(part)
        n_mal = int((part["y"] == 1).sum())
        n_ben = n_seq - n_mal
        pct = (100.0 * n_mal / n_seq) if n_seq else 0.0
        print(
            f"{split_name}: seq={n_seq:,}, mal={n_mal:,}, ben={n_ben:,}, "
            f"mal%={pct:.4f}, users={part['user'].nunique():,}"
        )
    print(f"window_crosses_split_boundaries: {extra['window_crosses_split_boundaries']}")
    print(
        f"all_malicious_intervals_covered: {extra['all_malicious_intervals_covered']} "
        f"(uncovered={extra['uncovered_malicious_intervals']})"
    )
    print()

    try:
        meta_rel = meta_path.relative_to(root)
    except ValueError:
        meta_rel = meta_path
    try:
        summary_rel = summary_path.relative_to(root)
    except ValueError:
        summary_rel = summary_path

    append_notes(notes_path, shape, meta, extra, safe_features, meta_rel, summary_rel)
    print(f"Appended notes: {notes_path}")

    if extra["window_crosses_split_boundaries"]:
        raise SystemExit("Integrity failure: a window crossed split boundaries.")
    if not extra["all_malicious_intervals_covered"]:
        raise SystemExit("Integrity failure: some malicious intervals are uncovered.")


if __name__ == "__main__":
    main()
