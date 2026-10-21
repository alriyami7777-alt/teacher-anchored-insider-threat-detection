#!/usr/bin/env python3
"""Check and densify CERT r4.2 user-day intervals (no modelling)."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime
from pathlib import Path

import duckdb
import pyarrow.parquet as pq


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def posix(path: Path) -> str:
    return str(path).replace("\\", "/")


def density_check(active_path: Path) -> dict:
    src = posix(active_path)
    con = duckdb.connect()
    try:
        row = con.execute(
            f"""
            WITH base AS (
                SELECT * FROM read_parquet('{src}')
            ),
            bounds AS (
                SELECT
                    MIN(interval_date) AS earliest,
                    MAX(interval_date) AS latest,
                    date_diff('day', MIN(interval_date), MAX(interval_date)) + 1 AS global_days,
                    COUNT(DISTINCT "user") AS n_users,
                    COUNT(*) AS actual_rows
                FROM base
            ),
            per_user AS (
                SELECT "user", COUNT(*) AS cnt
                FROM base
                GROUP BY "user"
            )
            SELECT
                b.n_users,
                b.global_days,
                b.n_users * b.global_days AS expected_dense_rows,
                b.actual_rows,
                b.n_users * b.global_days - b.actual_rows AS missing_inactive_rows,
                b.earliest,
                b.latest,
                MIN(p.cnt) AS min_intervals_per_user,
                MAX(p.cnt) AS max_intervals_per_user,
                AVG(p.cnt) AS avg_intervals_per_user,
                SUM(CASE WHEN p.cnt = b.global_days THEN 1 ELSE 0 END) AS users_with_full_calendar
            FROM bounds b, per_user p
            GROUP BY
                b.n_users, b.global_days, b.actual_rows, b.earliest, b.latest
            """
        ).fetchone()
    finally:
        con.close()

    (
        n_users,
        global_days,
        expected_dense,
        actual_rows,
        missing_rows,
        earliest,
        latest,
        min_ipu,
        max_ipu,
        avg_ipu,
        users_full,
    ) = row

    representation = (
        "dense_full_calendar"
        if missing_rows == 0
        else "active_days_only"
    )

    return {
        "representation_type": representation,
        "number_of_users": int(n_users),
        "global_days_in_date_range": int(global_days),
        "expected_dense_user_day_rows": int(expected_dense),
        "actual_interval_rows": int(actual_rows),
        "missing_inactive_user_day_rows": int(missing_rows),
        "earliest_interval_date": str(earliest),
        "latest_interval_date": str(latest),
        "min_intervals_per_user": int(min_ipu),
        "max_intervals_per_user": int(max_ipu),
        "avg_intervals_per_user": round(float(avg_ipu), 6),
        "users_with_full_calendar": int(users_full),
    }


def create_dense_intervals(active_path: Path, dense_path: Path) -> dict:
    dense_path.parent.mkdir(parents=True, exist_ok=True)
    if dense_path.exists():
        dense_path.unlink()

    src = posix(active_path)
    out = posix(dense_path)
    print(f"Building dense user-day grid from {active_path.name} ...")

    con = duckdb.connect()
    try:
        con.execute("SET preserve_insertion_order=false")
        con.execute("SET memory_limit='8GB'")
        con.execute("PRAGMA threads=4")
        con.execute(
            f"""
            COPY (
                WITH active AS (
                    SELECT * FROM read_parquet('{src}')
                ),
                bounds AS (
                    SELECT
                        MIN(interval_date) AS start_date,
                        MAX(interval_date) AS end_date
                    FROM active
                ),
                users AS (
                    SELECT DISTINCT "user" AS user FROM active
                ),
                calendar AS (
                    SELECT
                        UNNEST(
                            generate_series(
                                (SELECT start_date FROM bounds),
                                (SELECT end_date FROM bounds),
                                INTERVAL 1 DAY
                            )
                        )::DATE AS interval_date
                ),
                grid AS (
                    SELECT u.user, c.interval_date
                    FROM users u
                    CROSS JOIN calendar c
                )
                SELECT
                    g.user,
                    g.interval_date,
                    COALESCE(a.total_events, 0)::BIGINT AS total_events,
                    COALESCE(a.logon_count, 0)::BIGINT AS logon_count,
                    COALESCE(a.device_count, 0)::BIGINT AS device_count,
                    COALESCE(a.file_count, 0)::BIGINT AS file_count,
                    COALESCE(a.email_count, 0)::BIGINT AS email_count,
                    COALESCE(a.http_count, 0)::BIGINT AS http_count,
                    COALESCE(a.malicious_event_count, 0)::BIGINT AS malicious_event_count,
                    COALESCE(a.is_malicious_interval, 0)::TINYINT AS is_malicious_interval,
                    a.first_event_time,
                    a.last_event_time,
                    COALESCE(a.active_duration_minutes, 0)::BIGINT AS active_duration_minutes,
                    COALESCE(a.has_device_activity, 0)::TINYINT AS has_device_activity,
                    COALESCE(a.has_file_activity, 0)::TINYINT AS has_file_activity,
                    COALESCE(a.has_email_activity, 0)::TINYINT AS has_email_activity,
                    COALESCE(a.has_http_activity, 0)::TINYINT AS has_http_activity,
                    COALESCE(a.has_logon_activity, 0)::TINYINT AS has_logon_activity,
                    CASE WHEN a.user IS NULL THEN 0 ELSE 1 END::TINYINT AS is_active_day
                FROM grid g
                LEFT JOIN active a
                  ON g.user = a.user
                 AND g.interval_date = a.interval_date
                ORDER BY g.user, g.interval_date
            ) TO '{out}' (FORMAT PARQUET, COMPRESSION SNAPPY)
            """
        )

        stats = con.execute(
            f"""
            SELECT
                COUNT(*) AS dense_rows,
                COUNT(DISTINCT "user") AS n_users,
                SUM(CASE WHEN is_active_day = 0 THEN 1 ELSE 0 END) AS inactive_rows,
                SUM(CASE WHEN is_active_day = 1 THEN 1 ELSE 0 END) AS active_rows,
                SUM(malicious_event_count) AS malicious_events,
                SUM(is_malicious_interval) AS malicious_intervals
            FROM read_parquet('{out}')
            """
        ).fetchone()
    finally:
        con.close()

    dense_rows, n_users, inactive_rows, active_rows, mal_events, mal_intervals = stats
    print(f"Wrote dense intervals: {dense_path}")
    print(f"  dense_rows={dense_rows:,}, active={active_rows:,}, inactive={inactive_rows:,}")

    return {
        "dense_rows": int(dense_rows),
        "dense_users": int(n_users),
        "dense_active_rows": int(active_rows),
        "dense_inactive_rows": int(inactive_rows),
        "dense_malicious_events": int(mal_events),
        "dense_malicious_intervals": int(mal_intervals),
    }


def write_summary_csv(path: Path, check: dict, dense: dict | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = list(check.items())
    if dense:
        rows.extend(dense.items())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["metric", "value"])
        writer.writeheader()
        for key, value in rows:
            writer.writerow({"metric": key, "value": value})


def append_notes(
    notes_path: Path,
    check: dict,
    dense: dict | None,
    active_rel: Path,
    dense_rel: Path | None,
    summary_rel: Path,
) -> None:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with notes_path.open("a", encoding="utf-8") as f:
        f.write(f"\n\n## CERT r4.2 user-day interval density check ({stamp})\n\n")
        f.write(
            "Inspected whether `r42_user_day_intervals.parquet` is active-day only or a "
            "dense full calendar. Raw files were not modified. No model training.\n\n"
        )
        f.write(f"Source intervals: `{active_rel}`\n\n")

        f.write("### Density findings\n\n")
        f.write(
            f"- Representation type: **{check['representation_type']}**\n"
        )
        f.write(
            f"- Global days in range ({check['earliest_interval_date']} to "
            f"{check['latest_interval_date']}): **{check['global_days_in_date_range']:,}**\n"
        )
        f.write(f"- Users: **{check['number_of_users']:,}**\n")
        f.write(
            f"- Expected dense user-day rows (users × days): "
            f"**{check['expected_dense_user_day_rows']:,}**\n"
        )
        f.write(f"- Actual interval rows: **{check['actual_interval_rows']:,}**\n")
        f.write(
            f"- Missing inactive user-day rows: "
            f"**{check['missing_inactive_user_day_rows']:,}**\n"
        )
        f.write(
            f"- Intervals per user: min **{check['min_intervals_per_user']}**, "
            f"max **{check['max_intervals_per_user']}**, "
            f"avg **{check['avg_intervals_per_user']:.6f}**\n"
        )
        f.write(
            f"- Users with a full dense calendar in the active file: "
            f"**{check['users_with_full_calendar']}**\n\n"
        )

        if check["representation_type"] == "active_days_only":
            f.write(
                "Conclusion: the current interval table contains **only days with at least "
                "one event** for each user (active-day sparse representation), not a dense "
                "daily timeline.\n\n"
            )
        else:
            f.write(
                "Conclusion: the current interval table already covers every user-day in "
                "the global date range.\n\n"
            )

        if dense and dense_rel is not None:
            f.write("### Dense zero-filled version\n\n")
            f.write(f"Created: `{dense_rel}`\n\n")
            f.write(
                "- Inactive days are zero-filled for event counts / flags; "
                "`first_event_time` / `last_event_time` are null on inactive days.\n"
            )
            f.write(
                "- Added `is_active_day` (1 = original active interval, 0 = imputed inactive day).\n"
            )
            f.write(f"- Dense rows: **{dense['dense_rows']:,}**\n")
            f.write(f"- Active rows: **{dense['dense_active_rows']:,}**\n")
            f.write(f"- Inactive rows: **{dense['dense_inactive_rows']:,}**\n")
            f.write(
                f"- Malicious events preserved: **{dense['dense_malicious_events']:,}**\n\n"
            )

        f.write("### Generated output files\n\n")
        f.write(f"- `{summary_rel}`\n")
        if dense_rel is not None:
            f.write(f"- `{dense_rel}`\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check and densify CERT r4.2 user-day intervals."
    )
    parser.add_argument(
        "--active",
        default="data/processed/interval_level/r42_user_day_intervals.parquet",
    )
    parser.add_argument(
        "--dense-output",
        default="data/processed/interval_level/r42_user_day_intervals_dense.parquet",
    )
    parser.add_argument(
        "--summary",
        default="outputs/eda/r42_user_day_interval_density_check.csv",
    )
    args = parser.parse_args()

    root = repo_root()
    active_path = Path(args.active)
    if not active_path.is_absolute():
        active_path = (root / active_path).resolve()
    dense_path = Path(args.dense_output)
    if not dense_path.is_absolute():
        dense_path = (root / dense_path).resolve()
    summary_path = Path(args.summary)
    if not summary_path.is_absolute():
        summary_path = (root / summary_path).resolve()
    notes_path = root / "docs" / "cert_r42_notes.md"

    print("=" * 90)
    print("CERT r4.2 user-day interval density check")
    print("=" * 90)
    print(f"Active intervals: {active_path}")

    if not active_path.exists():
        raise FileNotFoundError(active_path)

    check = density_check(active_path)
    print()
    print("Density check")
    print("-" * 60)
    for k, v in check.items():
        print(f"{k}: {v}")
    print()

    dense_stats = None
    dense_rel = None
    if check["representation_type"] == "active_days_only":
        dense_stats = create_dense_intervals(active_path, dense_path)
        # Verify dense row count matches expectation.
        if dense_stats["dense_rows"] != check["expected_dense_user_day_rows"]:
            raise SystemExit(
                f"Dense rows {dense_stats['dense_rows']} != expected "
                f"{check['expected_dense_user_day_rows']}"
            )
        if dense_stats["dense_malicious_events"] != 7323:
            raise SystemExit(
                f"Dense malicious events {dense_stats['dense_malicious_events']} != 7323"
            )
        try:
            dense_rel = dense_path.relative_to(root)
        except ValueError:
            dense_rel = dense_path
        print("Dense schema:", pq.read_schema(dense_path))
    else:
        print("Already dense; no zero-filled file created.")

    write_summary_csv(summary_path, check, dense_stats)

    try:
        active_rel = active_path.relative_to(root)
    except ValueError:
        active_rel = active_path
    try:
        summary_rel = summary_path.relative_to(root)
    except ValueError:
        summary_rel = summary_path

    append_notes(notes_path, check, dense_stats, active_rel, dense_rel, summary_rel)
    print(f"Wrote summary: {summary_path}")
    print(f"Appended notes: {notes_path}")


if __name__ == "__main__":
    main()
