#!/usr/bin/env python3
"""Create CERT r4.2 user-day interval behavioural representations (no modelling)."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime
from pathlib import Path

import duckdb
import pyarrow.parquet as pq

EXPECTED_MALICIOUS_EVENTS = 7_323


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def posix(path: Path) -> str:
    return str(path).replace("\\", "/")


def build_intervals(stream_path: Path, output_path: Path) -> None:
    """Aggregate the unified event stream into user-day intervals via DuckDB."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()

    src = posix(stream_path)
    out = posix(output_path)

    print(f"Reading event stream: {stream_path}")
    print("Aggregating to user-day intervals ...")

    con = duckdb.connect()
    try:
        con.execute("SET preserve_insertion_order=false")
        con.execute("SET memory_limit='8GB'")
        con.execute("PRAGMA threads=4")
        con.execute(
            f"""
            COPY (
                SELECT
                    "user" AS user,
                    CAST(date AS DATE) AS interval_date,
                    CAST(COUNT(*) AS BIGINT) AS total_events,
                    CAST(SUM(CASE WHEN event_type = 'logon' THEN 1 ELSE 0 END) AS BIGINT) AS logon_count,
                    CAST(SUM(CASE WHEN event_type = 'device' THEN 1 ELSE 0 END) AS BIGINT) AS device_count,
                    CAST(SUM(CASE WHEN event_type = 'file' THEN 1 ELSE 0 END) AS BIGINT) AS file_count,
                    CAST(SUM(CASE WHEN event_type = 'email' THEN 1 ELSE 0 END) AS BIGINT) AS email_count,
                    CAST(SUM(CASE WHEN event_type = 'http' THEN 1 ELSE 0 END) AS BIGINT) AS http_count,
                    CAST(SUM(CASE WHEN is_malicious = 1 THEN 1 ELSE 0 END) AS BIGINT) AS malicious_event_count,
                    CAST(
                        CASE
                            WHEN SUM(CASE WHEN is_malicious = 1 THEN 1 ELSE 0 END) > 0 THEN 1
                            ELSE 0
                        END AS TINYINT
                    ) AS is_malicious_interval,
                    MIN(date) AS first_event_time,
                    MAX(date) AS last_event_time,
                    CAST(
                        GREATEST(
                            date_diff('minute', MIN(date), MAX(date)),
                            0
                        ) AS BIGINT
                    ) AS active_duration_minutes,
                    CAST(CASE WHEN SUM(CASE WHEN event_type = 'device' THEN 1 ELSE 0 END) > 0
                         THEN 1 ELSE 0 END AS TINYINT) AS has_device_activity,
                    CAST(CASE WHEN SUM(CASE WHEN event_type = 'file' THEN 1 ELSE 0 END) > 0
                         THEN 1 ELSE 0 END AS TINYINT) AS has_file_activity,
                    CAST(CASE WHEN SUM(CASE WHEN event_type = 'email' THEN 1 ELSE 0 END) > 0
                         THEN 1 ELSE 0 END AS TINYINT) AS has_email_activity,
                    CAST(CASE WHEN SUM(CASE WHEN event_type = 'http' THEN 1 ELSE 0 END) > 0
                         THEN 1 ELSE 0 END AS TINYINT) AS has_http_activity,
                    CAST(CASE WHEN SUM(CASE WHEN event_type = 'logon' THEN 1 ELSE 0 END) > 0
                         THEN 1 ELSE 0 END AS TINYINT) AS has_logon_activity
                FROM read_parquet('{src}')
                GROUP BY "user", CAST(date AS DATE)
                ORDER BY "user", interval_date
            ) TO '{out}' (FORMAT PARQUET, COMPRESSION SNAPPY)
            """
        )
    finally:
        con.close()

    print(f"Wrote intervals: {output_path}")


def summarize_intervals(interval_path: Path) -> dict:
    print(f"Summarising {interval_path.name} ...")
    con = duckdb.connect()
    try:
        src = posix(interval_path)
        row = con.execute(
            f"""
            SELECT
                COUNT(DISTINCT "user") AS n_users,
                COUNT(*) AS n_intervals,
                SUM(CASE WHEN is_malicious_interval = 1 THEN 1 ELSE 0 END) AS malicious_intervals,
                SUM(CASE WHEN is_malicious_interval = 0 THEN 1 ELSE 0 END) AS benign_intervals,
                MIN(interval_date) AS earliest_interval_date,
                MAX(interval_date) AS latest_interval_date,
                AVG(total_events) AS avg_events_per_interval,
                MAX(total_events) AS max_events_in_one_interval,
                SUM(malicious_event_count) AS total_malicious_events,
                SUM(total_events) AS total_events
            FROM read_parquet('{src}')
            """
        ).fetchone()

        (
            n_users,
            n_intervals,
            malicious_intervals,
            benign_intervals,
            earliest,
            latest,
            avg_events,
            max_events,
            total_malicious_events,
            total_events,
        ) = row

        avg_intervals_per_user = (
            float(n_intervals) / float(n_users) if n_users else 0.0
        )
        mal_pct = (
            100.0 * float(malicious_intervals) / float(n_intervals)
            if n_intervals
            else 0.0
        )

        return {
            "number_of_users": int(n_users),
            "number_of_user_day_intervals": int(n_intervals),
            "malicious_intervals": int(malicious_intervals),
            "benign_intervals": int(benign_intervals),
            "malicious_interval_percentage": round(mal_pct, 6),
            "earliest_interval_date": str(earliest),
            "latest_interval_date": str(latest),
            "average_intervals_per_user": round(avg_intervals_per_user, 6),
            "average_events_per_interval": round(float(avg_events or 0.0), 6),
            "maximum_events_in_one_interval": int(max_events or 0),
            "total_malicious_events_across_intervals": int(total_malicious_events or 0),
            "total_events_across_intervals": int(total_events or 0),
        }
    finally:
        con.close()


def write_summary_csv(path: Path, summary: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["metric", "value"])
        writer.writeheader()
        for key, value in summary.items():
            writer.writerow({"metric": key, "value": value})


def append_notes(
    notes_path: Path,
    summary: dict,
    interval_rel: Path,
    summary_rel: Path,
    malicious_match: bool,
) -> None:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with notes_path.open("a", encoding="utf-8") as f:
        f.write(f"\n\n## CERT r4.2 user-day interval representation ({stamp})\n\n")
        f.write(
            "Created initial daily user-level behavioural intervals from the unified "
            "chronological event stream. Raw files were not modified. No model training "
            "was performed.\n\n"
        )
        f.write(f"Interval table: `{interval_rel}`\n\n")
        f.write(
            "Interval definition: one row per (`user`, calendar day of event `date`).\n\n"
        )
        f.write(
            "Features include event-type counts, malicious event count / interval label, "
            "first/last event times, active duration (minutes), and modality activity flags.\n\n"
        )

        f.write("### Interval summary\n\n")
        f.write("| Metric | Value |\n")
        f.write("|--------|-------|\n")
        f.write(f"| Users | {summary['number_of_users']:,} |\n")
        f.write(
            f"| User-day intervals | {summary['number_of_user_day_intervals']:,} |\n"
        )
        f.write(f"| Malicious intervals | {summary['malicious_intervals']:,} |\n")
        f.write(f"| Benign intervals | {summary['benign_intervals']:,} |\n")
        f.write(
            f"| Malicious interval % | {summary['malicious_interval_percentage']:.6f}% |\n"
        )
        f.write(f"| Earliest interval date | {summary['earliest_interval_date']} |\n")
        f.write(f"| Latest interval date | {summary['latest_interval_date']} |\n")
        f.write(
            f"| Avg intervals / user | {summary['average_intervals_per_user']:.6f} |\n"
        )
        f.write(
            f"| Avg events / interval | {summary['average_events_per_interval']:.6f} |\n"
        )
        f.write(
            f"| Max events in one interval | {summary['maximum_events_in_one_interval']:,} |\n"
        )
        f.write(
            f"| Sum of malicious_event_count | "
            f"{summary['total_malicious_events_across_intervals']:,} |\n\n"
        )

        f.write("### Verification\n\n")
        if malicious_match:
            f.write(
                f"Total malicious events across intervals equals the official total "
                f"(**{EXPECTED_MALICIOUS_EVENTS:,}**).\n\n"
            )
        else:
            f.write(
                f"WARNING: malicious event sum across intervals "
                f"({summary['total_malicious_events_across_intervals']:,}) "
                f"does not equal {EXPECTED_MALICIOUS_EVENTS:,}.\n\n"
            )

        f.write("### Generated output files\n\n")
        f.write(f"- `{interval_rel}`\n")
        f.write(f"- `{summary_rel}`\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create CERT r4.2 user-day interval behavioural representations."
    )
    parser.add_argument(
        "--stream",
        default="data/processed/event_stream/r42_unified_event_stream.parquet",
        help="Unified event stream parquet path",
    )
    parser.add_argument(
        "--output",
        default="data/processed/interval_level/r42_user_day_intervals.parquet",
        help="User-day interval parquet path",
    )
    parser.add_argument(
        "--summary",
        default="outputs/eda/r42_user_day_interval_summary.csv",
        help="Summary CSV path",
    )
    args = parser.parse_args()

    root = repo_root()
    stream_path = Path(args.stream)
    if not stream_path.is_absolute():
        stream_path = (root / stream_path).resolve()
    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = (root / output_path).resolve()
    summary_path = Path(args.summary)
    if not summary_path.is_absolute():
        summary_path = (root / summary_path).resolve()
    notes_path = root / "docs" / "cert_r42_notes.md"

    print("=" * 90)
    print("CERT r4.2 user-day interval representation")
    print("=" * 90)
    print(f"Stream:  {stream_path}")
    print(f"Output:  {output_path}")
    print(f"Summary: {summary_path}")
    print()

    if not stream_path.exists():
        raise FileNotFoundError(f"Unified event stream not found: {stream_path}")

    n_stream = pq.ParquetFile(stream_path).metadata.num_rows
    print(f"Stream rows: {n_stream:,}")

    build_intervals(stream_path, output_path)
    summary = summarize_intervals(output_path)
    write_summary_csv(summary_path, summary)

    malicious_match = (
        summary["total_malicious_events_across_intervals"] == EXPECTED_MALICIOUS_EVENTS
    )

    print()
    print("User-day interval summary")
    print("-" * 60)
    for key, value in summary.items():
        print(f"{key}: {value}")
    print()
    print(
        "malicious_event_count sum check: "
        f"{summary['total_malicious_events_across_intervals']:,} "
        f"[{'MATCH' if malicious_match else 'MISMATCH'} vs {EXPECTED_MALICIOUS_EVENTS:,}]"
    )
    print()

    try:
        interval_rel = output_path.relative_to(root)
    except ValueError:
        interval_rel = output_path
    try:
        summary_rel = summary_path.relative_to(root)
    except ValueError:
        summary_rel = summary_path

    append_notes(notes_path, summary, interval_rel, summary_rel, malicious_match)
    print(f"Wrote summary: {summary_path}")
    print(f"Appended notes: {notes_path}")

    # Quick schema print
    schema = pq.read_schema(output_path)
    print(f"Interval schema: {schema}")
    print(f"Interval rows: {pq.ParquetFile(output_path).metadata.num_rows:,}")

    if not malicious_match:
        raise SystemExit("Malicious event total across intervals did not match 7,323.")


if __name__ == "__main__":
    main()
