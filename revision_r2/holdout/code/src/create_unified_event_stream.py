#!/usr/bin/env python3
"""Create a unified chronological CERT r4.2 event stream (no modelling)."""

from __future__ import annotations

import argparse
import csv
import shutil
from datetime import datetime
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

EVENT_TYPES = ("logon", "device", "file", "email", "http")

EXPECTED = {
    "total_events": 32_770_222,
    "malicious_events": 7_323,
    "benign_events": 32_762_899,
}

DATE_FORMAT = "%m/%d/%Y %H:%M:%S"
BATCH_SIZE = 500_000


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def empty_string_array(n: int) -> pa.Array:
    return pa.nulls(n, type=pa.string())


def normalize_batch(event_type: str, batch: pa.RecordBatch) -> pa.Table:
    """Map one Arrow batch onto the lean unified schema."""
    table = pa.Table.from_batches([batch])
    n = table.num_rows

    date_arr = table["date"].combine_chunks()
    if pa.types.is_timestamp(date_arr.type):
        parsed = date_arr
    else:
        parsed = pc.strptime(date_arr.cast(pa.string()), format=DATE_FORMAT, unit="s")

    is_mal = table["is_malicious"].combine_chunks()
    is_mal = pc.cast(is_mal, pa.int8())

    names = set(table.column_names)

    def get_str(name: str) -> pa.Array:
        if name in names:
            return table[name].combine_chunks().cast(pa.string())
        return empty_string_array(n)

    activity = get_str("activity") if event_type in {"logon", "device"} else empty_string_array(n)
    filename = get_str("filename") if event_type == "file" else empty_string_array(n)

    return pa.table(
        {
            "id": get_str("id"),
            "date": parsed,
            "user": get_str("user"),
            "pc": get_str("pc"),
            "event_type": pa.array([event_type] * n, type=pa.string()),
            "is_malicious": is_mal,
            "activity": activity,
            "filename": filename,
        }
    )


def columns_for_event_type(event_type: str, available: list[str]) -> list[str]:
    wanted = ["id", "date", "user", "is_malicious"]
    if "pc" in available:
        wanted.append("pc")
    if event_type in {"logon", "device"} and "activity" in available:
        wanted.append("activity")
    if event_type == "file" and "filename" in available:
        wanted.append("filename")
    return wanted


def write_unsorted_lean_stream(input_dir: Path, unsorted_path: Path) -> int:
    """Stream all modalities into one unsorted lean parquet."""
    if unsorted_path.exists():
        unsorted_path.unlink()

    writer: pq.ParquetWriter | None = None
    total = 0

    try:
        for event_type in EVENT_TYPES:
            src = input_dir / f"{event_type}_labelled.parquet"
            print(f"Reading {src.name} ...")
            pf = pq.ParquetFile(src)
            cols = columns_for_event_type(event_type, list(pf.schema_arrow.names))
            for batch in pf.iter_batches(batch_size=BATCH_SIZE, columns=cols):
                table = normalize_batch(event_type, batch)
                if writer is None:
                    writer = pq.ParquetWriter(
                        where=str(unsorted_path),
                        schema=table.schema,
                        compression="snappy",
                    )
                writer.write_table(table)
                total += table.num_rows
                if total % 2_000_000 < BATCH_SIZE:
                    print(f"  unsorted rows written: {total:,}")
            print(f"  finished {event_type}; cumulative={total:,}")
    finally:
        if writer is not None:
            writer.close()

    return total


def build_sorted_stream_by_user(unsorted_path: Path, output_path: Path, work_dir: Path) -> None:
    """Sort by user/date/event_type via per-user partitions (memory-safe)."""
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    # Prefer DuckDB hive partitioning when available.
    try:
        import duckdb

        print("Partitioning by user with DuckDB ...")
        con = duckdb.connect()
        try:
            con.execute("SET preserve_insertion_order=false")
            con.execute("SET memory_limit='8GB'")
            con.execute("PRAGMA threads=2")
            copy_sql = f"""
                COPY (
                    SELECT *
                    FROM read_parquet('{str(unsorted_path).replace(chr(92), "/")}')
                )
                TO '{str(work_dir).replace(chr(92), "/")}'
                (
                    FORMAT PARQUET,
                    PARTITION_BY ("user"),
                    COMPRESSION SNAPPY,
                    OVERWRITE_OR_IGNORE,
                    WRITE_PARTITION_COLUMNS true
                )
                """
            try:
                con.execute(copy_sql)
            except Exception:
                # Older DuckDB builds may not support WRITE_PARTITION_COLUMNS.
                con.execute(
                    f"""
                    COPY (
                        SELECT *
                        FROM read_parquet('{str(unsorted_path).replace(chr(92), "/")}')
                    )
                    TO '{str(work_dir).replace(chr(92), "/")}'
                    (
                        FORMAT PARQUET,
                        PARTITION_BY ("user"),
                        COMPRESSION SNAPPY,
                        OVERWRITE_OR_IGNORE
                    )
                    """
                )
        finally:
            con.close()
    except Exception as exc:
        print(f"DuckDB partition unavailable ({exc}); using PyArrow partition fallback ...")
        _partition_by_user_pyarrow(unsorted_path, work_dir)

    # Discover user partitions. DuckDB writes user=<id>/...parquet
    part_files: list[tuple[str, Path]] = []
    for path in sorted(work_dir.rglob("*.parquet")):
        user_id = path.parent.name
        if user_id.startswith("user="):
            user_id = user_id.split("=", 1)[1]
        part_files.append((user_id, path))

    # Deduplicate/group by user (in case of multiple files per user).
    by_user: dict[str, list[Path]] = {}
    for user_id, path in part_files:
        by_user.setdefault(user_id, []).append(path)
    users = sorted(by_user.keys())
    print(f"User partitions found: {len(users):,}")

    print("Sorting each user partition and writing unified stream ...")
    if output_path.exists():
        output_path.unlink()

    out_writer: pq.ParquetWriter | None = None
    written = 0
    try:
        for i, user_id in enumerate(users, start=1):
            tables = [pq.read_table(p) for p in by_user[user_id]]
            part = pa.concat_tables(tables, promote_options="default") if len(tables) > 1 else tables[0]
            # Hive partitions may omit the partition column from file bodies.
            if "user" not in part.column_names:
                part = part.append_column(
                    "user",
                    pa.array([user_id] * part.num_rows, type=pa.string()),
                )
            # Ensure stable column order.
            ordered = [
                c
                for c in (
                    "id",
                    "date",
                    "user",
                    "pc",
                    "event_type",
                    "is_malicious",
                    "activity",
                    "filename",
                )
                if c in part.column_names
            ]
            part = part.select(ordered)
            part = part.sort_by([("date", "ascending"), ("event_type", "ascending")])
            if out_writer is None:
                out_writer = pq.ParquetWriter(
                    where=str(output_path),
                    schema=part.schema,
                    compression="snappy",
                )
            out_writer.write_table(part)
            written += part.num_rows
            for p in by_user[user_id]:
                p.unlink(missing_ok=True)
            if i % 100 == 0 or i == len(users):
                print(f"  merged users {i}/{len(users)}; rows={written:,}")
    finally:
        if out_writer is not None:
            out_writer.close()

    shutil.rmtree(work_dir, ignore_errors=True)


def _partition_by_user_pyarrow(unsorted_path: Path, work_dir: Path) -> None:
    """Fallback partitioner using open-per-user writers."""
    writers: dict[str, pq.ParquetWriter] = {}
    schema: pa.Schema | None = None
    rows_seen = 0
    pf = pq.ParquetFile(unsorted_path)
    try:
        for batch in pf.iter_batches(batch_size=BATCH_SIZE):
            table = pa.Table.from_batches([batch])
            if schema is None:
                schema = table.schema
            rows_seen += table.num_rows
            user_col = table["user"].to_pylist()
            indexes: dict[str, list[int]] = {}
            for i, u in enumerate(user_col):
                key = str(u) if u is not None else ""
                if key:
                    indexes.setdefault(key, []).append(i)
            for user_id, idxs in indexes.items():
                subset = table.take(pa.array(idxs, type=pa.int64()))
                part_path = work_dir / f"user={user_id}" / "part.parquet"
                part_path.parent.mkdir(parents=True, exist_ok=True)
                writer = writers.get(user_id)
                if writer is None:
                    # Use a unique filename if rewriting.
                    writer = pq.ParquetWriter(
                        where=str(part_path),
                        schema=schema,
                        compression="snappy",
                    )
                    writers[user_id] = writer
                writer.write_table(subset)
            if rows_seen % 2_000_000 < BATCH_SIZE:
                print(f"  partitioned rows: {rows_seen:,}; open writers: {len(writers):,}")
    finally:
        for writer in writers.values():
            writer.close()


def summarize_stream(path: Path) -> dict:
    print(f"Summarising {path.name} ...")
    table = pq.read_table(path, columns=["event_type", "is_malicious", "user", "date"])

    total_events = table.num_rows
    mal = int(pc.sum(pc.cast(table["is_malicious"], pa.int64())).as_py() or 0)
    benign = total_events - mal
    pct = (100.0 * mal / total_events) if total_events else 0.0
    n_users = int(pc.count_distinct(table["user"]).as_py())
    min_ts = pc.min(table["date"]).as_py()
    max_ts = pc.max(table["date"]).as_py()

    pdf = table.select(["event_type", "is_malicious"]).to_pandas()
    event_counts: dict[str, int] = {}
    mal_counts: dict[str, int] = {}
    for et, group in pdf.groupby("event_type", sort=False):
        event_counts[str(et)] = int(len(group))
        mal_counts[str(et)] = int(
            pd.to_numeric(group["is_malicious"], errors="coerce").fillna(0).sum()
        )

    return {
        "total_events": total_events,
        "total_malicious_events": mal,
        "total_benign_events": benign,
        "malicious_percentage": round(pct, 6),
        "number_of_users": n_users,
        "earliest_timestamp": str(min_ts) if min_ts is not None else "",
        "latest_timestamp": str(max_ts) if max_ts is not None else "",
        "event_count_by_event_type": event_counts,
        "malicious_count_by_event_type": mal_counts,
    }


def write_summary_csv(path: Path, summary: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {"metric": "total_events", "event_type": "", "value": summary["total_events"]},
        {
            "metric": "total_malicious_events",
            "event_type": "",
            "value": summary["total_malicious_events"],
        },
        {
            "metric": "total_benign_events",
            "event_type": "",
            "value": summary["total_benign_events"],
        },
        {
            "metric": "malicious_percentage",
            "event_type": "",
            "value": summary["malicious_percentage"],
        },
        {
            "metric": "number_of_users",
            "event_type": "",
            "value": summary["number_of_users"],
        },
        {
            "metric": "earliest_timestamp",
            "event_type": "",
            "value": summary["earliest_timestamp"],
        },
        {
            "metric": "latest_timestamp",
            "event_type": "",
            "value": summary["latest_timestamp"],
        },
    ]
    for et in EVENT_TYPES:
        rows.append(
            {
                "metric": "event_count_by_event_type",
                "event_type": et,
                "value": summary["event_count_by_event_type"].get(et, 0),
            }
        )
    for et in EVENT_TYPES:
        rows.append(
            {
                "metric": "malicious_count_by_event_type",
                "event_type": et,
                "value": summary["malicious_count_by_event_type"].get(et, 0),
            }
        )

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["metric", "event_type", "value"])
        writer.writeheader()
        writer.writerows(rows)


def append_notes(
    notes_path: Path,
    summary: dict,
    stream_path: Path,
    summary_path: Path,
    matches: dict[str, bool],
) -> None:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with notes_path.open("a", encoding="utf-8") as f:
        f.write(f"\n\n## CERT r4.2 unified chronological event stream ({stamp})\n\n")
        f.write(
            "Built a unified chronological event stream from labelled event-level Parquet logs. "
            "Raw files were not modified. No model training was performed.\n\n"
        )
        f.write(f"Output stream: `{stream_path}`\n\n")
        f.write("Sort order: `user` → `date` → `event_type`.\n\n")
        f.write(
            "Unified schema: `id`, `date` (datetime), `user`, `pc`, `event_type`, "
            "`is_malicious`, plus nullable source fields `activity` (logon/device) and "
            "`filename` (file). Heavy free-text fields (http url/content, email bodies) "
            "were omitted to keep the chronological stream tractable.\n\n"
        )
        f.write(
            "Construction method: stream lean columns to an unsorted parquet, partition "
            "by user, sort each user partition by `date`/`event_type`, then concatenate "
            "users in sorted order.\n\n"
        )

        f.write("### Stream totals\n\n")
        f.write("| Metric | Value | Expected | Status |\n")
        f.write("|--------|-------|----------|--------|\n")
        f.write(
            f"| Total events | {summary['total_events']:,} | {EXPECTED['total_events']:,} | "
            f"{'MATCH' if matches['total'] else 'MISMATCH'} |\n"
        )
        f.write(
            f"| Malicious events | {summary['total_malicious_events']:,} | "
            f"{EXPECTED['malicious_events']:,} | "
            f"{'MATCH' if matches['malicious'] else 'MISMATCH'} |\n"
        )
        f.write(
            f"| Benign events | {summary['total_benign_events']:,} | "
            f"{EXPECTED['benign_events']:,} | "
            f"{'MATCH' if matches['benign'] else 'MISMATCH'} |\n"
        )
        f.write(f"| Malicious % | {summary['malicious_percentage']:.6f}% | — | — |\n")
        f.write(f"| Users | {summary['number_of_users']:,} | — | — |\n")
        f.write(f"| Earliest | {summary['earliest_timestamp']} | — | — |\n")
        f.write(f"| Latest | {summary['latest_timestamp']} | — | — |\n\n")

        f.write("### Counts by event type\n\n")
        f.write("| Event type | Events | Malicious |\n")
        f.write("|------------|--------|----------|\n")
        for et in EVENT_TYPES:
            f.write(
                f"| {et} | {summary['event_count_by_event_type'].get(et, 0):,} | "
                f"{summary['malicious_count_by_event_type'].get(et, 0):,} |\n"
            )
        f.write("\n")

        f.write("### Generated output files\n\n")
        f.write(f"- `{stream_path}`\n")
        f.write(f"- `{summary_path}`\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create unified chronological CERT r4.2 event stream."
    )
    parser.add_argument(
        "--input-dir",
        default="data/processed/event_level",
        help="Directory with *_labelled.parquet files",
    )
    parser.add_argument(
        "--output",
        default="data/processed/event_stream/r42_unified_event_stream.parquet",
        help="Unified event stream parquet path",
    )
    parser.add_argument(
        "--summary",
        default="outputs/eda/r42_unified_event_stream_summary.csv",
        help="Summary CSV path",
    )
    args = parser.parse_args()

    root = repo_root()
    input_dir = Path(args.input_dir)
    if not input_dir.is_absolute():
        input_dir = (root / input_dir).resolve()
    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = (root / output_path).resolve()
    summary_path = Path(args.summary)
    if not summary_path.is_absolute():
        summary_path = (root / summary_path).resolve()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    notes_path = root / "docs" / "cert_r42_notes.md"

    unsorted_path = output_path.parent / "_r42_unified_unsorted.parquet"
    work_dir = output_path.parent / "_user_parts"

    print("=" * 90)
    print("CERT r4.2 unified chronological event stream")
    print("=" * 90)
    print(f"Input:   {input_dir}")
    print(f"Output:  {output_path}")
    print(f"Summary: {summary_path}")
    print()

    for event_type in EVENT_TYPES:
        src = input_dir / f"{event_type}_labelled.parquet"
        if not src.exists():
            raise FileNotFoundError(f"Missing labelled parquet: {src}")

    # Clean leftovers from prior attempts.
    for p in (output_path, unsorted_path):
        if p.exists():
            p.unlink()
    if work_dir.exists():
        shutil.rmtree(work_dir, ignore_errors=True)
    duck_tmp = output_path.parent / "_duckdb_tmp"
    if duck_tmp.exists():
        shutil.rmtree(duck_tmp, ignore_errors=True)

    total_unsorted = write_unsorted_lean_stream(input_dir, unsorted_path)
    print(f"Unsorted lean stream rows: {total_unsorted:,}")
    print(f"Unsorted size: {unsorted_path.stat().st_size / (1024 ** 2):.1f} MiB")

    build_sorted_stream_by_user(unsorted_path, output_path, work_dir)

    if unsorted_path.exists():
        unsorted_path.unlink()

    print(f"Wrote unified stream: {output_path}")
    print(f"Size: {output_path.stat().st_size / (1024 ** 3):.2f} GiB")

    summary = summarize_stream(output_path)
    write_summary_csv(summary_path, summary)

    matches = {
        "total": summary["total_events"] == EXPECTED["total_events"],
        "malicious": summary["total_malicious_events"] == EXPECTED["malicious_events"],
        "benign": summary["total_benign_events"] == EXPECTED["benign_events"],
    }

    print()
    print("Unified event stream summary")
    print("-" * 60)
    print(
        f"total_events:            {summary['total_events']:,}  "
        f"[{'MATCH' if matches['total'] else 'MISMATCH'} vs {EXPECTED['total_events']:,}]"
    )
    print(
        f"total_malicious_events:  {summary['total_malicious_events']:,}  "
        f"[{'MATCH' if matches['malicious'] else 'MISMATCH'} vs {EXPECTED['malicious_events']:,}]"
    )
    print(
        f"total_benign_events:     {summary['total_benign_events']:,}  "
        f"[{'MATCH' if matches['benign'] else 'MISMATCH'} vs {EXPECTED['benign_events']:,}]"
    )
    print(f"malicious_percentage:    {summary['malicious_percentage']:.6f}%")
    print(f"number_of_users:         {summary['number_of_users']:,}")
    print(f"earliest_timestamp:      {summary['earliest_timestamp']}")
    print(f"latest_timestamp:        {summary['latest_timestamp']}")
    print()
    print("event_count_by_event_type:")
    for et in EVENT_TYPES:
        print(f"  {et}: {summary['event_count_by_event_type'].get(et, 0):,}")
    print("malicious_count_by_event_type:")
    for et in EVENT_TYPES:
        print(f"  {et}: {summary['malicious_count_by_event_type'].get(et, 0):,}")
    print()

    try:
        stream_rel = output_path.relative_to(root)
    except ValueError:
        stream_rel = output_path
    try:
        summary_rel = summary_path.relative_to(root)
    except ValueError:
        summary_rel = summary_path

    append_notes(notes_path, summary, stream_rel, summary_rel, matches)
    print(f"Wrote summary: {summary_path}")
    print(f"Appended notes: {notes_path}")

    if not all(matches.values()):
        raise SystemExit("Unified stream totals did not match expected values.")


if __name__ == "__main__":
    main()
