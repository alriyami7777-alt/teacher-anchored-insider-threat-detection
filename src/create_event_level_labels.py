#!/usr/bin/env python3
"""Create event-level labelled CERT r4.2 activity logs (no modelling)."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime
from pathlib import Path

import pandas as pd

EVENT_TYPES = ("logon", "device", "file", "email", "http")

RAW_LOG_FILES = {
    "logon": "logon.csv",
    "device": "device.csv",
    "file": "file.csv",
    "email": "email.csv",
    "http": "http.csv",
}

EXPECTED_MALICIOUS = {
    "logon": 198,
    "device": 2785,
    "file": 10,
    "email": 470,
    "http": 3860,
}

DEFAULT_CHUNK_SIZE = 250_000
HTTP_CHUNK_SIZE = 500_000


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def resolve_raw_dir(raw_dir: Path) -> Path:
    """Prefer data/raw/r4.2 when present (legacy r4.2-compatible)."""
    try:
        from dataset_registry import resolve_raw_dir_legacy_r42

        return resolve_raw_dir_legacy_r42(raw_dir)
    except Exception:
        candidate = raw_dir / "r4.2"
        return candidate if candidate.is_dir() else raw_dir


def parquet_available() -> bool:
    try:
        import pyarrow  # noqa: F401

        return True
    except ImportError:
        try:
            import fastparquet  # noqa: F401

            return True
        except ImportError:
            return False


def load_malicious_ids_by_type(matched_path: Path) -> dict[str, set[str]]:
    df = pd.read_csv(matched_path, dtype=str, usecols=["event_id", "event_type"])
    by_type: dict[str, set[str]] = {et: set() for et in EVENT_TYPES}
    for event_type, group in df.groupby("event_type"):
        et = str(event_type).strip().lower()
        if et not in by_type:
            by_type[et] = set()
        by_type[et].update(group["event_id"].dropna().astype(str).str.strip().tolist())
    return by_type


def chunk_size_for(event_type: str) -> int:
    return HTTP_CHUNK_SIZE if event_type == "http" else DEFAULT_CHUNK_SIZE


def label_activity_log(
    event_type: str,
    raw_path: Path,
    malicious_ids: set[str],
    output_path: Path,
    use_parquet: bool,
) -> dict:
    if not raw_path.exists():
        raise FileNotFoundError(f"Raw log not found: {raw_path}")

    if output_path.exists():
        output_path.unlink()

    total_events = 0
    malicious_events = 0
    chunks_written = 0
    chunksize = chunk_size_for(event_type)
    parquet_writer = None

    print(f"Labelling {raw_path.name} -> {output_path.name} ...")

    try:
        reader = pd.read_csv(
            raw_path,
            dtype=str,
            chunksize=chunksize,
            low_memory=False,
        )

        for chunk in reader:
            # Preserve original columns; add labels.
            chunk = chunk.copy()
            chunk["event_type"] = event_type
            ids = chunk["id"].fillna("").astype(str).str.strip()
            chunk["is_malicious"] = ids.isin(malicious_ids).astype("int8")

            n = len(chunk)
            m = int(chunk["is_malicious"].sum())
            total_events += n
            malicious_events += m
            chunks_written += 1

            if use_parquet:
                import pyarrow as pa
                import pyarrow.parquet as pq

                table = pa.Table.from_pandas(chunk, preserve_index=False)
                if parquet_writer is None:
                    parquet_writer = pq.ParquetWriter(
                        where=str(output_path),
                        schema=table.schema,
                        compression="snappy",
                    )
                parquet_writer.write_table(table)
            else:
                header = not output_path.exists()
                chunk.to_csv(
                    output_path,
                    index=False,
                    mode="a",
                    header=header,
                    compression="gzip",
                    quoting=csv.QUOTE_MINIMAL,
                )

            if event_type == "http" or chunks_written % 10 == 0:
                print(
                    f"  {event_type}: chunks={chunks_written}, "
                    f"rows={total_events:,}, malicious_so_far={malicious_events:,}"
                )
    finally:
        if parquet_writer is not None:
            parquet_writer.close()

    benign_events = total_events - malicious_events
    expected = EXPECTED_MALICIOUS.get(event_type, 0)
    status = "MATCH" if malicious_events == expected else "MISMATCH"

    print(
        f"  done {event_type}: total={total_events:,}, "
        f"malicious={malicious_events:,}, expected={expected}, status={status}"
    )

    pct = (100.0 * malicious_events / total_events) if total_events else 0.0
    return {
        "event_type": event_type,
        "total_raw_events": total_events,
        "malicious_events": malicious_events,
        "benign_events": benign_events,
        "malicious_percentage": round(pct, 6),
        "expected_malicious_count": expected,
        "count_match_status": status,
        "output_file": str(output_path),
        "output_format": "parquet" if use_parquet else "csv.gz",
    }


def append_notes(
    notes_path: Path,
    summary_rows: list[dict],
    output_dir: Path,
    summary_path: Path,
    use_parquet: bool,
    matched_path: Path,
) -> None:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total_raw = sum(r["total_raw_events"] for r in summary_rows)
    total_mal = sum(r["malicious_events"] for r in summary_rows)
    total_benign = sum(r["benign_events"] for r in summary_rows)
    all_match = all(r["count_match_status"] == "MATCH" for r in summary_rows)
    expected_total = sum(EXPECTED_MALICIOUS.values())

    with notes_path.open("a", encoding="utf-8") as f:
        f.write(f"\n\n## CERT r4.2 event-level labelled logs ({stamp})\n\n")
        f.write(
            "Created event-level labelled copies of the raw r4.2 activity logs using the "
            "official matched malicious event IDs. Raw files were not modified. "
            "No model training was performed.\n\n"
        )
        f.write(f"Matched malicious source: `{matched_path}`\n\n")
        f.write(f"Output directory: `{output_dir}`\n\n")
        f.write(
            f"Output format: **{'parquet (snappy)' if use_parquet else 'gzip-compressed CSV'}**\n\n"
        )

        f.write("### Label schema\n\n")
        f.write("- Original raw columns preserved.\n")
        f.write("- `event_type`: activity modality (`logon`, `device`, `file`, `email`, `http`).\n")
        f.write(
            "- `is_malicious`: `1` if raw `id` is in the official matched malicious ID set "
            "for that event type; otherwise `0`.\n\n"
        )

        f.write("### Event-level label summary\n\n")
        f.write(
            "| Event type | Total raw | Malicious | Benign | Malicious % | Expected | Status |\n"
        )
        f.write(
            "|------------|-----------|-----------|--------|-------------|----------|--------|\n"
        )
        for r in summary_rows:
            f.write(
                f"| {r['event_type']} | {r['total_raw_events']:,} | "
                f"{r['malicious_events']:,} | {r['benign_events']:,} | "
                f"{r['malicious_percentage']:.4f}% | {r['expected_malicious_count']:,} | "
                f"{r['count_match_status']} |\n"
            )
        pct_all = (100.0 * total_mal / total_raw) if total_raw else 0.0
        f.write(
            f"| **ALL** | **{total_raw:,}** | **{total_mal:,}** | **{total_benign:,}** | "
            f"**{pct_all:.4f}%** | **{expected_total:,}** | "
            f"**{'MATCH' if all_match and total_mal == expected_total else 'MISMATCH'}** |\n\n"
        )

        f.write("### Verification\n\n")
        if all_match and total_mal == expected_total:
            f.write(
                "Malicious counts match the official matched ID totals exactly "
                "(logon 198, device 2,785, file 10, email 470, http 3,860; total 7,323).\n\n"
            )
        else:
            f.write(
                "WARNING: malicious counts do **not** all match the expected official totals.\n\n"
            )

        f.write("### Generated output files\n\n")
        for r in summary_rows:
            f.write(f"- `{r['output_file']}`\n")
        f.write(f"- `{summary_path}`\n")


def print_summary_table(summary_rows: list[dict]) -> None:
    headers = (
        "event_type",
        "total_raw_events",
        "malicious_events",
        "benign_events",
        "malicious_percentage",
        "expected_malicious_count",
        "count_match_status",
    )
    widths = {h: max(len(h), max(len(str(r[h])) for r in summary_rows)) for h in headers}
    # also account for ALL row later
    total_raw = sum(r["total_raw_events"] for r in summary_rows)
    total_mal = sum(r["malicious_events"] for r in summary_rows)
    total_benign = sum(r["benign_events"] for r in summary_rows)
    expected_total = sum(EXPECTED_MALICIOUS.values())
    pct_all = round((100.0 * total_mal / total_raw), 6) if total_raw else 0.0
    all_status = (
        "MATCH"
        if all(r["count_match_status"] == "MATCH" for r in summary_rows)
        and total_mal == expected_total
        else "MISMATCH"
    )
    all_row = {
        "event_type": "ALL",
        "total_raw_events": total_raw,
        "malicious_events": total_mal,
        "benign_events": total_benign,
        "malicious_percentage": pct_all,
        "expected_malicious_count": expected_total,
        "count_match_status": all_status,
    }
    for h in headers:
        widths[h] = max(widths[h], len(str(all_row[h])))

    line = "  ".join(h.ljust(widths[h]) for h in headers)
    print()
    print(line)
    print("  ".join("-" * widths[h] for h in headers))
    for r in summary_rows + [all_row]:
        print("  ".join(str(r[h]).ljust(widths[h]) for h in headers))
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create event-level labelled CERT r4.2 activity logs."
    )
    parser.add_argument(
        "--raw",
        default="data/raw",
        help="Path to raw data folder or r4.2 folder (default: data/raw)",
    )
    parser.add_argument(
        "--matched",
        default="outputs/ground_truth/r42_matched_malicious_events.csv",
        help="Path to matched malicious events CSV",
    )
    parser.add_argument(
        "--output-dir",
        default="data/processed/event_level",
        help="Directory for labelled event-level outputs",
    )
    args = parser.parse_args()

    root = repo_root()

    raw_dir = Path(args.raw)
    if not raw_dir.is_absolute():
        raw_dir = (root / raw_dir).resolve()
    raw_dir = resolve_raw_dir(raw_dir)

    matched_path = Path(args.matched)
    if not matched_path.is_absolute():
        matched_path = (root / matched_path).resolve()

    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = (root / output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    summary_path = root / "outputs" / "ground_truth" / "r42_event_level_label_summary.csv"
    notes_path = root / "docs" / "cert_r42_notes.md"
    summary_path.parent.mkdir(parents=True, exist_ok=True)

    if not raw_dir.exists():
        raise FileNotFoundError(f"Raw data folder not found: {raw_dir}")
    if not matched_path.exists():
        raise FileNotFoundError(f"Matched malicious events not found: {matched_path}")

    use_parquet = parquet_available()
    print("=" * 90)
    print("CERT r4.2 event-level labelling")
    print("=" * 90)
    print(f"Raw folder:     {raw_dir}")
    print(f"Matched IDs:    {matched_path}")
    print(f"Output folder:  {output_dir}")
    print(f"Output format:  {'parquet' if use_parquet else 'csv.gz (parquet unavailable)'}")
    print()

    malicious_by_type = load_malicious_ids_by_type(matched_path)
    for et in EVENT_TYPES:
        print(f"Malicious IDs loaded for {et}: {len(malicious_by_type.get(et, set())):,}")
    print()

    summary_rows: list[dict] = []
    for event_type in EVENT_TYPES:
        raw_path = raw_dir / RAW_LOG_FILES[event_type]
        suffix = ".parquet" if use_parquet else ".csv.gz"
        out_path = output_dir / f"{event_type}_labelled{suffix}"
        row = label_activity_log(
            event_type=event_type,
            raw_path=raw_path,
            malicious_ids=malicious_by_type.get(event_type, set()),
            output_path=out_path,
            use_parquet=use_parquet,
        )
        # Store relative-ish path for notes when under repo
        try:
            row["output_file"] = str(out_path.relative_to(root))
        except ValueError:
            row["output_file"] = str(out_path)
        summary_rows.append(row)

    summary_df = pd.DataFrame(
        [
            {
                "event_type": r["event_type"],
                "total_raw_events": r["total_raw_events"],
                "malicious_events": r["malicious_events"],
                "benign_events": r["benign_events"],
                "malicious_percentage": r["malicious_percentage"],
                "expected_malicious_count": r["expected_malicious_count"],
                "count_match_status": r["count_match_status"],
            }
            for r in summary_rows
        ]
    )
    summary_df.to_csv(summary_path, index=False)

    print_summary_table(summary_rows)

    total_mal = sum(r["malicious_events"] for r in summary_rows)
    expected_total = sum(EXPECTED_MALICIOUS.values())
    if total_mal != expected_total:
        print(
            f"WARNING: total malicious {total_mal} != expected {expected_total}"
        )
    else:
        print(f"Confirmed total malicious events: {total_mal:,} == {expected_total:,}")

    try:
        summary_rel = summary_path.relative_to(root)
    except ValueError:
        summary_rel = summary_path

    append_notes(
        notes_path=notes_path,
        summary_rows=summary_rows,
        output_dir=output_dir,
        summary_path=summary_rel,
        use_parquet=use_parquet,
        matched_path=matched_path,
    )

    print(f"Wrote summary: {summary_path}")
    print(f"Appended notes: {notes_path}")


if __name__ == "__main__":
    main()
