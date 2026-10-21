#!/usr/bin/env python3
"""Summarise distribution and data quality of labelled r4.2 event logs (no modelling)."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

EVENT_TYPES = ("logon", "device", "file", "email", "http")
DATE_FORMATS = (
    "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y %H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
)
QUALITY_COLUMNS = ("id", "date", "user", "is_malicious")
CHUNK_ROWS = 1_000_000


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def detect_timestamp_column(columns: list[str]) -> str:
    lower = {c.lower(): c for c in columns}
    for candidate in ("date", "timestamp", "time", "datetime"):
        if candidate in lower:
            return lower[candidate]
    for c in columns:
        lc = c.lower()
        if "date" in lc or "time" in lc:
            return c
    return ""


def detect_user_column(columns: list[str]) -> str:
    lower = {c.lower(): c for c in columns}
    for candidate in ("user", "user_id", "userid", "employee", "employee_id"):
        if candidate in lower:
            return lower[candidate]
    for c in columns:
        if "user" in c.lower():
            return c
    return ""


def is_missing_series(series: pd.Series) -> pd.Series:
    text = series.fillna("").astype(str).str.strip()
    return series.isna() | text.eq("") | text.str.lower().isin({"nan", "none", "null"})


def parse_timestamps(series: pd.Series) -> pd.Series:
    # Prefer the known CERT format first for speed/accuracy.
    parsed = pd.to_datetime(series, format=DATE_FORMATS[0], errors="coerce")
    if parsed.notna().any() and parsed.isna().mean() < 0.5:
        return parsed
    return pd.to_datetime(series, errors="coerce")


def summarize_event_type(event_type: str, path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Labelled parquet not found: {path}")

    pf = pq.ParquetFile(path)
    columns = list(pf.schema_arrow.names)
    total_rows = pf.metadata.num_rows
    n_columns = len(columns)

    ts_col = detect_timestamp_column(columns)
    user_col = detect_user_column(columns)
    id_col = "id" if "id" in columns else ""

    needed = [c for c in (id_col, ts_col, user_col, "is_malicious") if c and c in columns]
    # Always try to include quality columns when present.
    for c in QUALITY_COLUMNS:
        if c in columns and c not in needed:
            needed.append(c)

    missing_id = 0
    missing_user = 0
    missing_ts = 0
    malicious_events = 0
    benign_events = 0
    unique_users: set[str] = set()
    seen_ids: set[str] = set()
    duplicate_ids: set[str] = set()
    non_missing_id_rows = 0
    min_ts: pd.Timestamp | None = None
    max_ts: pd.Timestamp | None = None
    rows_seen = 0

    print(f"Scanning {path.name} ({total_rows:,} rows)...")

    for batch in pf.iter_batches(batch_size=CHUNK_ROWS, columns=needed):
        chunk = batch.to_pandas()
        rows_seen += len(chunk)

        if id_col:
            missing_mask = is_missing_series(chunk[id_col])
            missing_id += int(missing_mask.sum())
            ids = chunk.loc[~missing_mask, id_col].astype(str).str.strip()
            ids = ids[(ids != "") & (~ids.str.lower().isin({"nan", "none", "null"}))]
            non_missing_id_rows += len(ids)
            chunk_id_set = set(ids.tolist())
            # IDs already seen in prior chunks.
            duplicate_ids.update(chunk_id_set & seen_ids)
            # IDs duplicated within this chunk.
            within = ids.value_counts()
            duplicate_ids.update(within[within > 1].index.tolist())
            seen_ids.update(chunk_id_set)

        if user_col:
            missing_user += int(is_missing_series(chunk[user_col]).sum())
            users = chunk[user_col].fillna("").astype(str).str.strip()
            users = users[(users != "") & (~users.str.lower().isin({"nan", "none", "null"}))]
            unique_users.update(users.unique().tolist())

        if ts_col:
            missing_ts += int(is_missing_series(chunk[ts_col]).sum())
            parsed = parse_timestamps(chunk[ts_col])
            valid = parsed.dropna()
            if len(valid) > 0:
                chunk_min = valid.min()
                chunk_max = valid.max()
                min_ts = chunk_min if min_ts is None else min(min_ts, chunk_min)
                max_ts = chunk_max if max_ts is None else max(max_ts, chunk_max)

        if "is_malicious" in chunk.columns:
            mal = pd.to_numeric(chunk["is_malicious"], errors="coerce").fillna(0).astype(int)
            malicious_events += int((mal == 1).sum())
            benign_events += int((mal != 1).sum())
        else:
            benign_events += len(chunk)

        if rows_seen % (CHUNK_ROWS * 5) == 0 or rows_seen >= total_rows:
            print(f"  {event_type}: processed {rows_seen:,}/{total_rows:,}")

    duplicate_id_count = len(duplicate_ids)
    duplicate_id_extra_rows = max(0, non_missing_id_rows - len(seen_ids))
    # Free large ID sets before returning.
    seen_ids.clear()
    duplicate_ids.clear()

    pct = (100.0 * malicious_events / total_rows) if total_rows else 0.0

    return {
        "event_type": event_type,
        "total_rows": total_rows,
        "number_of_columns": n_columns,
        "column_names": "; ".join(columns),
        "timestamp_column_name": ts_col,
        "earliest_timestamp": str(min_ts) if min_ts is not None else "",
        "latest_timestamp": str(max_ts) if max_ts is not None else "",
        "unique_users": len(unique_users),
        "missing_id_count": missing_id,
        "missing_user_count": missing_user,
        "missing_timestamp_count": missing_ts,
        "duplicate_id_count": duplicate_id_count,
        "duplicate_id_extra_rows": duplicate_id_extra_rows,
        "malicious_events": malicious_events,
        "benign_events": benign_events,
        "malicious_percentage": round(pct, 6),
    }


def print_summary_table(rows: list[dict]) -> None:
    headers = [
        "event_type",
        "total_rows",
        "number_of_columns",
        "unique_users",
        "missing_id_count",
        "missing_user_count",
        "missing_timestamp_count",
        "duplicate_id_count",
        "malicious_events",
        "benign_events",
        "malicious_percentage",
        "earliest_timestamp",
        "latest_timestamp",
    ]
    widths = {
        h: max(len(h), max(len(str(r.get(h, ""))) for r in rows))
        for h in headers
    }
    print()
    print("  ".join(h.ljust(widths[h]) for h in headers))
    print("  ".join("-" * widths[h] for h in headers))
    for r in rows:
        print("  ".join(str(r.get(h, "")).ljust(widths[h]) for h in headers))
    print()


def append_notes(notes_path: Path, rows: list[dict], summary_path: Path, input_dir: Path) -> None:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total_rows = sum(r["total_rows"] for r in rows)
    total_mal = sum(r["malicious_events"] for r in rows)
    total_benign = sum(r["benign_events"] for r in rows)
    pct = (100.0 * total_mal / total_rows) if total_rows else 0.0

    with notes_path.open("a", encoding="utf-8") as f:
        f.write(f"\n\n## CERT r4.2 labelled event-log quality summary ({stamp})\n\n")
        f.write(
            "Distribution and data-quality scan of the event-level labelled Parquet logs. "
            "Raw files were not modified. No model training was performed.\n\n"
        )
        f.write(f"Input directory: `{input_dir}`\n\n")

        f.write("### Per-event-type quality\n\n")
        f.write(
            "| Event type | Rows | Cols | Users | Missing id | Missing user | Missing ts | Duplicate ids | Malicious | Benign | Mal % | Earliest | Latest |\n"
        )
        f.write(
            "|------------|------|------|-------|------------|--------------|------------|---------------|-----------|--------|-------|----------|--------|\n"
        )
        for r in rows:
            f.write(
                f"| {r['event_type']} | {r['total_rows']:,} | {r['number_of_columns']} | "
                f"{r['unique_users']:,} | {r['missing_id_count']:,} | {r['missing_user_count']:,} | "
                f"{r['missing_timestamp_count']:,} | {r['duplicate_id_count']:,} | "
                f"{r['malicious_events']:,} | {r['benign_events']:,} | {r['malicious_percentage']:.4f}% | "
                f"{r['earliest_timestamp']} | {r['latest_timestamp']} |\n"
            )
        f.write(
            f"| **ALL** | **{total_rows:,}** | — | — | — | — | — | — | "
            f"**{total_mal:,}** | **{total_benign:,}** | **{pct:.4f}%** | — | — |\n\n"
        )

        f.write("### Notes\n\n")
        f.write("- Timestamp column across activity logs is `date` (`MM/DD/YYYY HH:MM:SS`).\n")
        f.write("- User column is `user`; event key is `id`.\n")
        f.write(
            "- `duplicate_id_count` is the number of distinct `id` values that appear more than once "
            "(not the number of extra rows).\n"
        )
        any_missing = any(
            r["missing_id_count"] or r["missing_user_count"] or r["missing_timestamp_count"]
            for r in rows
        )
        any_dups = any(r["duplicate_id_count"] for r in rows)
        if not any_missing and not any_dups:
            f.write("- No missing `id`/`user`/`date` values and no duplicate event IDs were detected.\n")
        else:
            if any_missing:
                f.write("- Some missing values were detected (see table).\n")
            if any_dups:
                f.write("- Some duplicate event IDs were detected (see table).\n")
        f.write("\n")

        f.write("### Column inventories\n\n")
        for r in rows:
            f.write(f"- `{r['event_type']}`: {r['column_names']}\n")
        f.write("\n")

        f.write("### Generated output files\n\n")
        f.write(f"- `{summary_path}`\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Summarise labelled CERT r4.2 event-level Parquet logs."
    )
    parser.add_argument(
        "--input-dir",
        default="data/processed/event_level",
        help="Directory containing *_labelled.parquet files",
    )
    parser.add_argument(
        "--output",
        default="outputs/eda/r42_labelled_event_log_quality_summary.csv",
        help="Output CSV path",
    )
    args = parser.parse_args()

    root = repo_root()
    input_dir = Path(args.input_dir)
    if not input_dir.is_absolute():
        input_dir = (root / input_dir).resolve()
    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = (root / output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    notes_path = root / "docs" / "cert_r42_notes.md"

    print("=" * 90)
    print("CERT r4.2 labelled event-log quality summary")
    print("=" * 90)
    print(f"Input:  {input_dir}")
    print(f"Output: {output_path}")
    print()

    rows: list[dict] = []
    for event_type in EVENT_TYPES:
        path = input_dir / f"{event_type}_labelled.parquet"
        rows.append(summarize_event_type(event_type, path))

    summary_df = pd.DataFrame(rows)
    # Keep requested columns prominent; retain helper duplicate_id_extra_rows as well.
    preferred = [
        "event_type",
        "total_rows",
        "number_of_columns",
        "column_names",
        "timestamp_column_name",
        "earliest_timestamp",
        "latest_timestamp",
        "unique_users",
        "missing_id_count",
        "missing_user_count",
        "missing_timestamp_count",
        "duplicate_id_count",
        "malicious_events",
        "benign_events",
        "malicious_percentage",
        "duplicate_id_extra_rows",
    ]
    summary_df = summary_df[[c for c in preferred if c in summary_df.columns]]
    summary_df.to_csv(output_path, index=False)

    print_summary_table(rows)

    try:
        summary_rel = output_path.relative_to(root)
    except ValueError:
        summary_rel = output_path

    append_notes(notes_path, rows, summary_rel, input_dir)
    print(f"Wrote: {output_path}")
    print(f"Appended notes: {notes_path}")


if __name__ == "__main__":
    main()
