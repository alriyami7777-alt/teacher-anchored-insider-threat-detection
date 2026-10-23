#!/usr/bin/env python3
"""Common-13 CERT preparation stages (event labels → daily behaviour → T=20 tensors).

Preparation only:
  - no model training
  - no test-set evaluation / threshold selection
  - never writes inside raw activity or answer folders
  - never overwrites locked r4.2 / Objective 2 / Objective 3 artefacts

Uses the verified ``COMMON_13_FEATURES`` schema from ``cert_schema_audit``.
"""

from __future__ import annotations

import csv
import json
import re
import shutil
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from cert_ground_truth import AnswerEventRecord, load_answer_events
from cert_schema_audit import COMMON_13_FEATURES
from dataset_registry import (
    CORE_EVENT_LOGS,
    DatasetVersionError,
    ResolvedDatasetPaths,
    assert_output_outside_raw,
    get_dataset_spec,
    normalize_dataset_version,
)

DATE_FORMAT = "%m/%d/%Y %H:%M:%S"
BATCH_SIZE = 500_000
DEFAULT_CHUNK = 250_000
HTTP_CHUNK = 500_000
WINDOW_LENGTH = 20
STRIDE = 1
TRAIN_FRAC = 0.80
VAL_FRAC = 0.10

FORBIDDEN_FEATURE_RE = re.compile(
    r"(is_malicious|malicious|label|insider|scenario|answer)",
    re.IGNORECASE,
)

# Columns optionally retained when matching malicious IDs (present subset only).
MATCH_KEEP_COLUMNS: dict[str, tuple[str, ...]] = {
    "logon": ("id", "date", "user", "pc", "activity"),
    "device": ("id", "date", "user", "pc", "activity"),
    "file": ("id", "date", "user", "pc", "filename", "activity"),
    "email": (
        "id",
        "date",
        "user",
        "pc",
        "to",
        "cc",
        "bcc",
        "from",
        "size",
        "attachments",
        "activity",
    ),
    "http": ("id", "date", "user", "pc", "url", "activity"),
}

LOCKED_OUTPUT_MARKERS = (
    "objective2",
    "objective3",
    "baselines",
    "sequence_ensemble",
    "chapter4",
    "v2",
    "v3_fusion",
    "v3_node",
)


def posix(path: Path) -> str:
    return str(path).replace("\\", "/")


def chunk_size_for(event_type: str) -> int:
    return HTTP_CHUNK if event_type == "http" else DEFAULT_CHUNK


def refuse_locked_output_path(path: Path) -> None:
    """Refuse writes that would clobber locked research artefacts."""
    text = str(path).replace("\\", "/").lower()
    for marker in LOCKED_OUTPUT_MARKERS:
        if f"/{marker}/" in f"/{text}/" or text.rstrip("/").endswith(f"/{marker}"):
            raise DatasetVersionError(
                f"refusing to write into locked artefact path containing '{marker}': {path}"
            )


def assert_versioned_processed_tree(processed_dir: Path, version: str) -> None:
    """Require derived data under data/processed/{rX.Y}/ for confirmatory releases."""
    ver = normalize_dataset_version(version)
    if ver == "4.2":
        return
    tag = get_dataset_spec(ver).release_tag  # r5.2 / r6.2
    resolved = processed_dir.resolve()
    if tag.lower() not in str(resolved).replace("\\", "/").lower():
        raise DatasetVersionError(
            f"processed_dir for CERT {ver} must be under a '{tag}' folder; got {resolved}"
        )


@dataclass
class PipelinePaths:
    """Resolved artefact locations for one release preparation run."""

    version: str
    raw_dir: Path
    answers_dir: Path
    processed_dir: Path
    output_dir: Path
    prefix: str

    matched_csv: Path = field(init=False)
    match_summary_csv: Path = field(init=False)
    event_level_dir: Path = field(init=False)
    label_summary_csv: Path = field(init=False)
    event_stream_path: Path = field(init=False)
    intervals_path: Path = field(init=False)
    dense_path: Path = field(init=False)
    density_summary_csv: Path = field(init=False)
    sequence_meta_path: Path = field(init=False)
    sequence_summary_csv: Path = field(init=False)
    tensor_dir: Path = field(init=False)
    tensor_feature_list_csv: Path = field(init=False)
    tensor_summary_csv: Path = field(init=False)
    manifest_json: Path = field(init=False)
    notes_path: Path = field(init=False)

    def __post_init__(self) -> None:
        gt = self.output_dir / "ground_truth"
        seq = self.output_dir / "sequences"
        tensors_out = self.output_dir / "tensors"
        prep = self.output_dir / "dataset_preparation"
        self.matched_csv = gt / f"{self.prefix}_matched_malicious_events.csv"
        self.match_summary_csv = gt / f"{self.prefix}_malicious_id_match_summary.csv"
        self.event_level_dir = self.processed_dir / "event_level"
        self.label_summary_csv = gt / f"{self.prefix}_event_level_label_summary.csv"
        self.event_stream_path = (
            self.processed_dir / "event_stream" / f"{self.prefix}_unified_event_stream.parquet"
        )
        self.intervals_path = (
            self.processed_dir / "interval_level" / f"{self.prefix}_user_day_intervals.parquet"
        )
        self.dense_path = (
            self.processed_dir
            / "interval_level"
            / f"{self.prefix}_user_day_intervals_dense.parquet"
        )
        self.density_summary_csv = (
            self.output_dir / "interval_level" / f"{self.prefix}_density_summary.csv"
        )
        self.sequence_meta_path = seq / f"{self.prefix}_sliding_window_T20_s1_metadata.parquet"
        self.sequence_summary_csv = seq / f"{self.prefix}_sliding_window_T20_s1_summary.csv"
        self.tensor_dir = self.processed_dir / "tensors"
        self.tensor_feature_list_csv = tensors_out / f"{self.prefix}_T20_s1_tensor_feature_list.csv"
        self.tensor_summary_csv = tensors_out / f"{self.prefix}_T20_s1_tensor_summary.csv"
        self.manifest_json = prep / "pipeline_manifest.json"
        # Run notes stay under the versioned outputs tree (never locked chapter dirs).
        self.notes_path = self.output_dir / "pipeline_run_notes.md"

    def ensure_parents(self) -> None:
        for path in (
            self.matched_csv,
            self.match_summary_csv,
            self.label_summary_csv,
            self.event_stream_path,
            self.intervals_path,
            self.dense_path,
            self.density_summary_csv,
            self.sequence_meta_path,
            self.sequence_summary_csv,
            self.tensor_feature_list_csv,
            self.tensor_summary_csv,
            self.manifest_json,
        ):
            path.parent.mkdir(parents=True, exist_ok=True)
        self.event_level_dir.mkdir(parents=True, exist_ok=True)
        self.tensor_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_resolved(
        cls,
        paths: ResolvedDatasetPaths,
        *,
        output_dir: Path | None = None,
    ) -> "PipelinePaths":
        spec = paths.spec
        # Report artefacts live under outputs/{rX.Y}/ (ground_truth, sequences, …).
        report_root = (
            output_dir
            if output_dir is not None
            else Path(__file__).resolve().parents[1] / "outputs" / spec.release_tag
        )
        refuse_locked_output_path(report_root)
        refuse_locked_output_path(paths.processed_dir)
        pipe = cls(
            version=paths.version,
            raw_dir=paths.raw_dir,
            answers_dir=paths.answers_dir,
            processed_dir=paths.processed_dir,
            output_dir=report_root,
            prefix=spec.processed_prefix,
        )
        assert_output_outside_raw(pipe.processed_dir, pipe.raw_dir)
        assert_output_outside_raw(pipe.output_dir, pipe.raw_dir)
        assert_versioned_processed_tree(pipe.processed_dir, paths.version)
        return pipe


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        pd.DataFrame().to_csv(path, index=False)
        return
    pd.DataFrame(rows).to_csv(path, index=False)


# ---------------------------------------------------------------------------
# Stage 1: match malicious event IDs
# ---------------------------------------------------------------------------


def match_malicious_ids(
    records: list[AnswerEventRecord],
    raw_dir: Path,
    *,
    max_scan_rows_per_file: int | None = None,
    event_types: Iterable[str] = CORE_EVENT_LOGS,
) -> tuple[dict[str, dict[str, dict[str, str]]], dict[str, Any]]:
    """Return matches_by_type[event_type][event_id] = raw_fields, plus summary."""
    by_type: dict[str, set[str]] = defaultdict(set)
    answer_meta: dict[str, AnswerEventRecord] = {}
    for rec in records:
        if rec.event_type in event_types:
            by_type[rec.event_type].add(rec.event_id)
            answer_meta[rec.event_id] = rec

    matches_by_type: dict[str, dict[str, dict[str, str]]] = {t: {} for t in event_types}
    scanned: dict[str, int] = {}
    unmatched: dict[str, list[str]] = {}
    missing_files: list[str] = []
    partial = False

    for event_type in event_types:
        targets = by_type.get(event_type, set())
        path = raw_dir / f"{event_type}.csv"
        if not path.is_file():
            missing_files.append(f"{event_type}.csv")
            scanned[event_type] = 0
            unmatched[event_type] = sorted(targets)
            continue
        remaining = set(targets)
        keep = MATCH_KEEP_COLUMNS.get(event_type, ("id", "date", "user", "pc"))
        rows = 0
        with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames or "id" not in reader.fieldnames:
                raise ValueError(f"{path} missing id column; fields={reader.fieldnames}")
            available = set(reader.fieldnames)
            keep_cols = [c for c in keep if c in available]
            for row in reader:
                rows += 1
                if max_scan_rows_per_file is not None and rows > max_scan_rows_per_file:
                    partial = True
                    break
                event_id = (row.get("id") or "").strip()
                if event_id not in remaining:
                    continue
                matches_by_type[event_type][event_id] = {
                    col: (row.get(col) or "") for col in keep_cols
                }
                remaining.remove(event_id)
                if not remaining:
                    break
        scanned[event_type] = rows
        unmatched[event_type] = sorted(remaining)
        print(
            f"  {event_type}.csv: scanned={rows:,}; "
            f"matched={len(matches_by_type[event_type]):,}; "
            f"unmatched={len(remaining):,}"
        )

    answer_counts = Counter(r.event_type for r in records if r.event_type in event_types)
    matched_counts = {t: len(matches_by_type[t]) for t in event_types}
    summary = {
        "answer_counts": dict(answer_counts),
        "matched_counts": matched_counts,
        "unmatched_counts": {t: len(unmatched[t]) for t in event_types},
        "unmatched_ids": unmatched,
        "rows_scanned": scanned,
        "missing_files": missing_files,
        "partial_scan": partial,
        "n_answer_records": len(records),
        "n_matched_total": sum(matched_counts.values()),
        "answer_meta_keys": len(answer_meta),
    }
    return matches_by_type, summary


def write_matched_events_csv(
    path: Path,
    records: list[AnswerEventRecord],
    matches_by_type: dict[str, dict[str, dict[str, str]]],
) -> int:
    fieldnames = [
        "event_id",
        "event_type",
        "answer_scenario_group",
        "answer_user",
        "answer_file",
        "answer_row",
        "raw_date",
        "raw_user",
        "raw_pc",
        "raw_activity",
        "raw_filename",
        "raw_url",
        "match_status",
    ]
    written = 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for rec in sorted(
            records,
            key=lambda r: (r.event_type, r.scenario_key, r.answer_user, r.answer_row),
        ):
            raw = matches_by_type.get(rec.event_type, {}).get(rec.event_id)
            if raw is None:
                continue
            writer.writerow(
                {
                    "event_id": rec.event_id,
                    "event_type": rec.event_type,
                    "answer_scenario_group": rec.scenario_key,
                    "answer_user": rec.answer_user,
                    "answer_file": rec.answer_file,
                    "answer_row": rec.answer_row,
                    "raw_date": raw.get("date", ""),
                    "raw_user": raw.get("user", ""),
                    "raw_pc": raw.get("pc", ""),
                    "raw_activity": raw.get("activity", ""),
                    "raw_filename": raw.get("filename", ""),
                    "raw_url": raw.get("url", ""),
                    "match_status": "matched",
                }
            )
            written += 1
    return written


def stage_match(pipe: PipelinePaths, *, max_scan_rows_per_file: int | None = None) -> dict[str, Any]:
    print("\n=== Stage: match malicious event IDs ===")
    records, diagnostics = load_answer_events(pipe.answers_dir, pipe.version)
    print(
        f"Loaded {len(records):,} answer events "
        f"(unique diagnostics ids={diagnostics.get('event_ids_seen')})"
    )
    matches, summary = match_malicious_ids(
        records,
        pipe.raw_dir,
        max_scan_rows_per_file=max_scan_rows_per_file,
    )
    n_written = write_matched_events_csv(pipe.matched_csv, records, matches)
    rows = []
    for et in CORE_EVENT_LOGS:
        total = summary["answer_counts"].get(et, 0)
        matched = summary["matched_counts"].get(et, 0)
        rows.append(
            {
                "event_type": et,
                "malicious_event_ids": total,
                "matched": matched,
                "unmatched": total - matched,
                "match_rate": round(matched / total, 6) if total else "",
                "rows_scanned": summary["rows_scanned"].get(et, 0),
            }
        )
    _write_csv(pipe.match_summary_csv, rows)
    result = {
        "stage": "match",
        "matched_csv": str(pipe.matched_csv),
        "n_matched_rows_written": n_written,
        "partial_scan": summary["partial_scan"],
        "summary": {
            k: v
            for k, v in summary.items()
            if k != "unmatched_ids"  # potentially large
        },
        "unmatched_counts": summary["unmatched_counts"],
    }
    print(f"Wrote {n_written:,} matched rows -> {pipe.matched_csv}")
    return result


# ---------------------------------------------------------------------------
# Stage 2: event-level labels
# ---------------------------------------------------------------------------


def load_malicious_ids_by_type(matched_path: Path) -> dict[str, set[str]]:
    df = pd.read_csv(matched_path, dtype=str, usecols=["event_id", "event_type"])
    by_type: dict[str, set[str]] = {et: set() for et in CORE_EVENT_LOGS}
    for event_type, group in df.groupby("event_type"):
        et = str(event_type).strip().lower()
        by_type.setdefault(et, set())
        by_type[et].update(group["event_id"].dropna().astype(str).str.strip().tolist())
    return by_type


def label_activity_log(
    event_type: str,
    raw_path: Path,
    malicious_ids: set[str],
    output_path: Path,
    *,
    max_rows: int | None = None,
) -> dict[str, Any]:
    if not raw_path.exists():
        raise FileNotFoundError(f"Raw log not found: {raw_path}")
    if output_path.exists():
        output_path.unlink()

    total_events = 0
    malicious_events = 0
    parquet_writer = None
    chunksize = chunk_size_for(event_type)
    print(f"Labelling {raw_path.name} -> {output_path.name} ...")

    try:
        for chunk in pd.read_csv(
            raw_path,
            dtype=str,
            chunksize=chunksize,
            low_memory=False,
        ):
            if max_rows is not None and total_events >= max_rows:
                break
            if max_rows is not None and total_events + len(chunk) > max_rows:
                chunk = chunk.iloc[: max_rows - total_events].copy()

            ids = chunk["id"].astype(str).str.strip()
            is_mal = ids.isin(malicious_ids).astype("int8")
            chunk = chunk.copy()
            chunk["event_type"] = event_type
            chunk["is_malicious"] = is_mal
            total_events += len(chunk)
            malicious_events += int(is_mal.sum())

            table = pa.Table.from_pandas(chunk, preserve_index=False)
            if parquet_writer is None:
                parquet_writer = pq.ParquetWriter(
                    where=str(output_path),
                    schema=table.schema,
                    compression="snappy",
                )
            parquet_writer.write_table(table)
    finally:
        if parquet_writer is not None:
            parquet_writer.close()

    benign = total_events - malicious_events
    pct = (100.0 * malicious_events / total_events) if total_events else 0.0
    expected = len(malicious_ids)
    return {
        "event_type": event_type,
        "total_raw_events": total_events,
        "malicious_events": malicious_events,
        "benign_events": benign,
        "malicious_percentage": round(pct, 6),
        "expected_malicious_count": expected,
        "count_match_status": "MATCH" if malicious_events == expected else "MISMATCH",
        "output_file": str(output_path),
        "row_capped": max_rows is not None,
    }


def stage_label_events(
    pipe: PipelinePaths,
    *,
    max_rows_per_log: int | None = None,
) -> dict[str, Any]:
    print("\n=== Stage: event-level labelling ===")
    if not pipe.matched_csv.is_file():
        raise FileNotFoundError(f"Matched CSV required: {pipe.matched_csv}")
    malicious_by_type = load_malicious_ids_by_type(pipe.matched_csv)
    summary_rows: list[dict[str, Any]] = []
    for event_type in CORE_EVENT_LOGS:
        raw_path = pipe.raw_dir / f"{event_type}.csv"
        out_path = pipe.event_level_dir / f"{event_type}_labelled.parquet"
        row = label_activity_log(
            event_type,
            raw_path,
            malicious_by_type.get(event_type, set()),
            out_path,
            max_rows=max_rows_per_log,
        )
        summary_rows.append(row)
        print(
            f"  {event_type}: total={row['total_raw_events']:,} "
            f"malicious={row['malicious_events']:,} ({row['count_match_status']})"
        )
    _write_csv(
        pipe.label_summary_csv,
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
        ],
    )
    return {
        "stage": "label_events",
        "event_level_dir": str(pipe.event_level_dir),
        "summary_rows": summary_rows,
        "total_malicious": sum(r["malicious_events"] for r in summary_rows),
        "total_events": sum(r["total_raw_events"] for r in summary_rows),
    }


# ---------------------------------------------------------------------------
# Stage 3: unified chronological event stream
# ---------------------------------------------------------------------------


def _empty_string_array(n: int) -> pa.Array:
    return pa.nulls(n, type=pa.string())


def _normalize_batch(event_type: str, batch: pa.RecordBatch) -> pa.Table:
    table = pa.Table.from_batches([batch])
    n = table.num_rows
    date_arr = table["date"].combine_chunks()
    if pa.types.is_timestamp(date_arr.type):
        parsed = date_arr
    else:
        parsed = pc.strptime(date_arr.cast(pa.string()), format=DATE_FORMAT, unit="s")
    is_mal = pc.cast(table["is_malicious"].combine_chunks(), pa.int8())
    names = set(table.column_names)

    def get_str(name: str) -> pa.Array:
        if name in names:
            return table[name].combine_chunks().cast(pa.string())
        return _empty_string_array(n)

    activity = get_str("activity") if event_type in {"logon", "device"} else _empty_string_array(n)
    filename = get_str("filename") if event_type == "file" else _empty_string_array(n)
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


def _columns_for_event_type(event_type: str, available: list[str]) -> list[str]:
    wanted = ["id", "date", "user", "is_malicious"]
    if "pc" in available:
        wanted.append("pc")
    if event_type in {"logon", "device"} and "activity" in available:
        wanted.append("activity")
    if event_type == "file" and "filename" in available:
        wanted.append("filename")
    return wanted


def stage_unified_stream(pipe: PipelinePaths) -> dict[str, Any]:
    print("\n=== Stage: unified chronological event stream ===")
    work_dir = pipe.processed_dir / "event_stream" / "_work_partitions"
    unsorted_path = pipe.processed_dir / "event_stream" / f"{pipe.prefix}_unsorted_tmp.parquet"
    unsorted_path.parent.mkdir(parents=True, exist_ok=True)
    if unsorted_path.exists():
        unsorted_path.unlink()
    if pipe.event_stream_path.exists():
        pipe.event_stream_path.unlink()

    writer: pq.ParquetWriter | None = None
    total = 0
    try:
        for event_type in CORE_EVENT_LOGS:
            src = pipe.event_level_dir / f"{event_type}_labelled.parquet"
            if not src.is_file():
                raise FileNotFoundError(f"Missing labelled log: {src}")
            print(f"Reading {src.name} ...")
            pf = pq.ParquetFile(src)
            cols = _columns_for_event_type(event_type, list(pf.schema_arrow.names))
            for batch in pf.iter_batches(batch_size=BATCH_SIZE, columns=cols):
                table = _normalize_batch(event_type, batch)
                if writer is None:
                    writer = pq.ParquetWriter(
                        where=str(unsorted_path),
                        schema=table.schema,
                        compression="snappy",
                    )
                writer.write_table(table)
                total += table.num_rows
            print(f"  finished {event_type}; cumulative={total:,}")
    finally:
        if writer is not None:
            writer.close()

    import duckdb

    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    print("Partitioning by user with DuckDB ...")
    con = duckdb.connect()
    try:
        con.execute("SET preserve_insertion_order=false")
        con.execute("SET memory_limit='8GB'")
        con.execute("PRAGMA threads=2")
        src = posix(unsorted_path)
        dst = posix(work_dir)
        try:
            con.execute(
                f"""
                COPY (SELECT * FROM read_parquet('{src}'))
                TO '{dst}'
                (FORMAT PARQUET, PARTITION_BY ("user"), COMPRESSION SNAPPY,
                 OVERWRITE_OR_IGNORE, WRITE_PARTITION_COLUMNS true)
                """
            )
        except Exception:
            con.execute(
                f"""
                COPY (SELECT * FROM read_parquet('{src}'))
                TO '{dst}'
                (FORMAT PARQUET, PARTITION_BY ("user"), COMPRESSION SNAPPY,
                 OVERWRITE_OR_IGNORE)
                """
            )
    finally:
        con.close()

    by_user: dict[str, list[Path]] = {}
    for path in sorted(work_dir.rglob("*.parquet")):
        user_id = path.parent.name
        if user_id.startswith("user="):
            user_id = user_id.split("=", 1)[1]
        by_user.setdefault(user_id, []).append(path)
    users = sorted(by_user.keys())
    print(f"User partitions: {len(users):,}")

    out_writer: pq.ParquetWriter | None = None
    written = 0
    try:
        for i, user_id in enumerate(users, start=1):
            tables = [pq.read_table(p) for p in by_user[user_id]]
            part = (
                pa.concat_tables(tables, promote_options="default")
                if len(tables) > 1
                else tables[0]
            )
            if "user" not in part.column_names:
                part = part.append_column(
                    "user", pa.array([user_id] * part.num_rows, type=pa.string())
                )
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
            part = part.select(ordered).sort_by(
                [("date", "ascending"), ("event_type", "ascending")]
            )
            if out_writer is None:
                out_writer = pq.ParquetWriter(
                    where=str(pipe.event_stream_path),
                    schema=part.schema,
                    compression="snappy",
                )
            out_writer.write_table(part)
            written += part.num_rows
            if i % 200 == 0 or i == len(users):
                print(f"  merged users {i}/{len(users)}; rows={written:,}")
    finally:
        if out_writer is not None:
            out_writer.close()

    shutil.rmtree(work_dir, ignore_errors=True)
    unsorted_path.unlink(missing_ok=True)

    # Quick malicious total
    con = duckdb.connect()
    try:
        mal = con.execute(
            f"SELECT SUM(is_malicious)::BIGINT FROM read_parquet('{posix(pipe.event_stream_path)}')"
        ).fetchone()[0]
    finally:
        con.close()

    print(f"Wrote unified stream: {pipe.event_stream_path} ({written:,} rows)")
    return {
        "stage": "unified_stream",
        "path": str(pipe.event_stream_path),
        "n_events": written,
        "n_users": len(users),
        "malicious_events": int(mal or 0),
    }


# ---------------------------------------------------------------------------
# Stage 4–5: daily intervals + densify (common-13 behavioural features)
# ---------------------------------------------------------------------------


def stage_daily_intervals(pipe: PipelinePaths) -> dict[str, Any]:
    print("\n=== Stage: daily behavioural intervals (common-13 sources) ===")
    import duckdb

    if not pipe.event_stream_path.is_file():
        raise FileNotFoundError(pipe.event_stream_path)
    pipe.intervals_path.parent.mkdir(parents=True, exist_ok=True)
    if pipe.intervals_path.exists():
        pipe.intervals_path.unlink()

    src = posix(pipe.event_stream_path)
    out = posix(pipe.intervals_path)
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
                        CASE WHEN SUM(CASE WHEN is_malicious = 1 THEN 1 ELSE 0 END) > 0
                             THEN 1 ELSE 0 END AS TINYINT
                    ) AS is_malicious_interval,
                    MIN(date) AS first_event_time,
                    MAX(date) AS last_event_time,
                    CAST(
                        GREATEST(date_diff('minute', MIN(date), MAX(date)), 0) AS BIGINT
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
        stats = con.execute(
            f"""
            SELECT COUNT(*), COUNT(DISTINCT "user"),
                   SUM(is_malicious_interval), SUM(malicious_event_count),
                   MIN(interval_date), MAX(interval_date)
            FROM read_parquet('{out}')
            """
        ).fetchone()
    finally:
        con.close()

    n_rows, n_users, mal_iv, mal_ev, earliest, latest = stats
    print(
        f"Wrote intervals: {pipe.intervals_path} "
        f"(rows={n_rows:,}, users={n_users:,}, malicious_intervals={int(mal_iv or 0):,})"
    )
    return {
        "stage": "daily_intervals",
        "path": str(pipe.intervals_path),
        "n_intervals": int(n_rows),
        "n_users": int(n_users),
        "malicious_intervals": int(mal_iv or 0),
        "malicious_events": int(mal_ev or 0),
        "date_range": [str(earliest), str(latest)],
    }


def stage_densify(pipe: PipelinePaths) -> dict[str, Any]:
    print("\n=== Stage: densify user-day calendar + is_active_day ===")
    import duckdb

    if not pipe.intervals_path.is_file():
        raise FileNotFoundError(pipe.intervals_path)
    if pipe.dense_path.exists():
        pipe.dense_path.unlink()

    src = posix(pipe.intervals_path)
    out = posix(pipe.dense_path)
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
                    SELECT MIN(interval_date) AS start_date, MAX(interval_date) AS end_date
                    FROM active
                ),
                users AS (
                    SELECT DISTINCT "user" AS user FROM active
                ),
                calendar AS (
                    SELECT UNNEST(
                        generate_series(
                            (SELECT start_date FROM bounds),
                            (SELECT end_date FROM bounds),
                            INTERVAL 1 DAY
                        )
                    )::DATE AS interval_date
                ),
                grid AS (
                    SELECT u.user, c.interval_date FROM users u CROSS JOIN calendar c
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
                  ON g.user = a.user AND g.interval_date = a.interval_date
                ORDER BY g.user, g.interval_date
            ) TO '{out}' (FORMAT PARQUET, COMPRESSION SNAPPY)
            """
        )
        stats = con.execute(
            f"""
            SELECT COUNT(*), COUNT(DISTINCT "user"),
                   SUM(CASE WHEN is_active_day = 0 THEN 1 ELSE 0 END),
                   SUM(CASE WHEN is_active_day = 1 THEN 1 ELSE 0 END),
                   SUM(malicious_event_count), SUM(is_malicious_interval),
                   MIN(interval_date), MAX(interval_date)
            FROM read_parquet('{out}')
            """
        ).fetchone()
    finally:
        con.close()

    dense_rows, n_users, inactive, active, mal_ev, mal_iv, earliest, latest = stats
    # Verify common-13 columns present.
    schema_names = set(pq.read_schema(pipe.dense_path).names)
    missing = [f for f in COMMON_13_FEATURES if f not in schema_names]
    if missing:
        raise RuntimeError(f"Dense intervals missing common-13 features: {missing}")

    summary = {
        "dense_rows": int(dense_rows),
        "n_users": int(n_users),
        "inactive_rows": int(inactive),
        "active_rows": int(active),
        "malicious_events": int(mal_ev or 0),
        "malicious_intervals": int(mal_iv or 0),
        "earliest": str(earliest),
        "latest": str(latest),
        "common_13_features": list(COMMON_13_FEATURES),
        "common_13_present": True,
    }
    _write_csv(
        pipe.density_summary_csv,
        [{"metric": k, "value": v} for k, v in summary.items() if k != "common_13_features"]
        + [{"metric": "common_13_features", "value": ";".join(COMMON_13_FEATURES)}],
    )
    print(
        f"Wrote dense intervals: {pipe.dense_path} "
        f"(rows={dense_rows:,}, active={active:,}, inactive={inactive:,})"
    )
    return {"stage": "densify", "path": str(pipe.dense_path), **summary}


# ---------------------------------------------------------------------------
# Stage 6: T=20 sliding-window sequence metadata
# ---------------------------------------------------------------------------


def _split_day_counts(n_days: int) -> tuple[int, int, int]:
    n_train = int(n_days * TRAIN_FRAC)
    n_val = int(n_days * VAL_FRAC)
    n_test = n_days - n_train - n_val
    if n_train < WINDOW_LENGTH or n_val < WINDOW_LENGTH or n_test < WINDOW_LENGTH:
        raise ValueError(
            f"Split sizes too small for T={WINDOW_LENGTH}: "
            f"train={n_train}, val={n_val}, test={n_test}, n_days={n_days}"
        )
    return n_train, n_val, n_test


def stage_sliding_windows(pipe: PipelinePaths) -> dict[str, Any]:
    print("\n=== Stage: T=20 stride=1 sliding-window sequences ===")
    if not pipe.dense_path.is_file():
        raise FileNotFoundError(pipe.dense_path)

    table = pq.read_table(
        pipe.dense_path,
        columns=["user", "interval_date", "is_malicious_interval", "is_active_day"],
    )
    df = table.to_pandas()
    df["interval_date"] = pd.to_datetime(df["interval_date"]).dt.normalize()
    df = df.sort_values(["user", "interval_date"], kind="mergesort").reset_index(drop=True)

    users = sorted(df["user"].astype(str).unique().tolist())
    calendar = sorted(df["interval_date"].unique().tolist())
    n_days = len(calendar)
    n_train, n_val, n_test = _split_day_counts(n_days)
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
        f"Calendar days={n_days}, users={len(users)}; "
        f"split days train/val/test={n_train}/{n_val}/{n_test}"
    )

    grouped = {
        str(user): grp for user, grp in df.groupby(df["user"].astype(str), sort=False)
    }
    records: list[dict[str, Any]] = []
    seq_counter = 0
    window_crosses_boundary = False

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
            max_start = hi - WINDOW_LENGTH
            start_idx = lo
            while start_idx <= max_start:
                end_idx = start_idx + WINDOW_LENGTH
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
        if user_i % 200 == 0 or user_i == len(users):
            print(f"  users {user_i}/{len(users)}; sequences={seq_counter:,}")

    meta = pd.DataFrame.from_records(records)
    pipe.sequence_meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta.to_parquet(pipe.sequence_meta_path, index=False)

    # Sanity: no forbidden feature columns in metadata; y is label only.
    safe_note = list(COMMON_13_FEATURES)
    summary_rows: list[dict[str, Any]] = [
        {"metric": "n_users", "split": "", "value": len(users)},
        {"metric": "n_calendar_days", "split": "", "value": n_days},
        {"metric": "window_length_T", "split": "", "value": WINDOW_LENGTH},
        {"metric": "stride", "split": "", "value": STRIDE},
        {"metric": "total_sequences", "split": "", "value": len(meta)},
        {
            "metric": "window_crosses_split_boundaries",
            "split": "",
            "value": window_crosses_boundary,
        },
        {
            "metric": "common_13_features",
            "split": "",
            "value": ";".join(safe_note),
        },
    ]
    split_stats: dict[str, dict[str, Any]] = {}
    for split_name in ("train", "validation", "test"):
        part = meta.loc[meta["split"] == split_name]
        n_seq = int(len(part))
        n_mal = int((part["y"] == 1).sum())
        split_start, split_end = split_ranges[split_name]
        split_stats[split_name] = {
            "sequences": n_seq,
            "malicious_sequences": n_mal,
            "benign_sequences": n_seq - n_mal,
            "date_range": [
                split_start.date().isoformat(),
                split_end.date().isoformat(),
            ],
            "n_users": int(part["user"].nunique()),
        }
        summary_rows.extend(
            [
                {"metric": "sequences", "split": split_name, "value": n_seq},
                {"metric": "malicious_sequences", "split": split_name, "value": n_mal},
                {
                    "metric": "benign_sequences",
                    "split": split_name,
                    "value": n_seq - n_mal,
                },
                {
                    "metric": "split_start",
                    "split": split_name,
                    "value": split_start.date().isoformat(),
                },
                {
                    "metric": "split_end",
                    "split": split_name,
                    "value": split_end.date().isoformat(),
                },
            ]
        )
    _write_csv(pipe.sequence_summary_csv, summary_rows)
    print(f"Wrote sequence metadata: {pipe.sequence_meta_path} ({len(meta):,} sequences)")
    if window_crosses_boundary:
        raise RuntimeError("BUG: sliding windows crossed chronological split boundaries")
    return {
        "stage": "sliding_windows",
        "metadata_path": str(pipe.sequence_meta_path),
        "total_sequences": len(meta),
        "split_stats": split_stats,
        "n_users": len(users),
        "n_calendar_days": n_days,
    }


# ---------------------------------------------------------------------------
# Stage 7: sequence tensors (common-13 only, train-only scaling)
# ---------------------------------------------------------------------------


class TrainOnlyStandardScaler:
    def __init__(self) -> None:
        self.mean_: np.ndarray | None = None
        self.scale_: np.ndarray | None = None

    def fit(self, x: np.ndarray) -> None:
        self.mean_ = x.mean(axis=0)
        scale = x.std(axis=0, ddof=0)
        scale[scale == 0] = 1.0
        self.scale_ = scale

    def transform(self, x: np.ndarray) -> np.ndarray:
        if self.mean_ is None or self.scale_ is None:
            raise RuntimeError("Scaler has not been fitted.")
        return ((x - self.mean_) / self.scale_).astype(np.float32)


def stage_sequence_tensors(pipe: PipelinePaths) -> dict[str, Any]:
    print("\n=== Stage: T=20 common-13 sequence tensors ===")
    if not pipe.dense_path.is_file():
        raise FileNotFoundError(pipe.dense_path)
    if not pipe.sequence_meta_path.is_file():
        raise FileNotFoundError(pipe.sequence_meta_path)

    meta = pq.read_table(pipe.sequence_meta_path).to_pandas()
    meta["user"] = meta["user"].astype(str)
    meta["start_date"] = pd.to_datetime(meta["start_date"]).dt.normalize()
    meta["end_date"] = pd.to_datetime(meta["end_date"]).dt.normalize()
    meta["split"] = meta["split"].astype(str)

    schema_cols = list(pq.read_schema(pipe.dense_path).names)
    feature_cols = [c for c in COMMON_13_FEATURES if c in schema_cols]
    missing = [c for c in COMMON_13_FEATURES if c not in schema_cols]
    if missing:
        raise RuntimeError(f"Missing common-13 features in dense table: {missing}")
    forbidden = [c for c in feature_cols if FORBIDDEN_FEATURE_RE.search(c)]
    if forbidden:
        raise RuntimeError(f"Forbidden label-derived features selected: {forbidden}")

    print(f"Using F={len(feature_cols)} common-13 features")
    dense = pq.read_table(
        pipe.dense_path,
        columns=["user", "interval_date", *feature_cols],
    ).to_pandas()
    dense["user"] = dense["user"].astype(str)
    dense["interval_date"] = pd.to_datetime(dense["interval_date"]).dt.normalize()
    dense = dense.sort_values(["user", "interval_date"], kind="mergesort").reset_index(
        drop=True
    )

    train_start = meta.loc[meta["split"] == "train", "start_date"].min()
    train_end = meta.loc[meta["split"] == "train", "end_date"].max()
    train_mask = (dense["interval_date"] >= train_start) & (
        dense["interval_date"] <= train_end
    )
    train_daily = dense.loc[train_mask, feature_cols].to_numpy(dtype=np.float64)
    print(
        f"Fitting scaler on train daily rows: {train_daily.shape[0]:,} "
        f"({train_start.date()} -> {train_end.date()})"
    )
    scaler = TrainOnlyStandardScaler()
    scaler.fit(train_daily)

    dense_by_user: dict[str, pd.DataFrame] = {
        str(u): g.reset_index(drop=True)
        for u, g in dense.groupby("user", sort=False)
    }
    scaled_by_user: dict[str, np.ndarray] = {}
    for u, g in dense_by_user.items():
        raw = g[feature_cols].to_numpy(dtype=np.float64)
        scaled_by_user[u] = scaler.transform(raw)

    summary_rows: list[dict[str, Any]] = []
    tensor_paths: dict[str, str] = {}
    for split_name in ("train", "validation", "test"):
        meta_split = meta.loc[meta["split"] == split_name].reset_index(drop=True)
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
            time_offsets = np.arange(WINDOW_LENGTH, dtype=np.int64)
            gather_idx = start_idxs[:, None] + time_offsets[None, :]
            x[positions] = feats[gather_idx]

        out_path = pipe.tensor_dir / f"{pipe.prefix}_T20_s1_{split_name}.npz"
        np.savez_compressed(
            out_path,
            X=x,
            y=y,
            sequence_id=sequence_id,
            user=user,
            start_date=start_date,
            end_date=end_date,
            feature_names=np.array(feature_cols, dtype=object),
        )
        tensor_paths[split_name] = str(out_path)
        n_mal = int((y == 1).sum())
        summary_rows.append(
            {
                "split": split_name,
                "X_shape": str(tuple(x.shape)),
                "y_shape": str(tuple(y.shape)),
                "n_features_F": f,
                "malicious_sequences": n_mal,
                "benign_sequences": int(len(y) - n_mal),
                "malicious_percentage": round(100.0 * n_mal / len(y), 6) if len(y) else 0.0,
                "missing_values_in_X": int(np.isnan(x).sum()),
                "infinite_values_in_X": int(np.isinf(x).sum()),
                "scaling_fitted_only_on_train": True,
                "common_13_features_only": True,
            }
        )
        print(f"  {split_name}: X={x.shape}, malicious={n_mal:,}")

    _write_csv(
        pipe.tensor_feature_list_csv,
        [{"feature_index": i, "feature_name": name} for i, name in enumerate(feature_cols)],
    )
    _write_csv(pipe.tensor_summary_csv, summary_rows)
    return {
        "stage": "sequence_tensors",
        "tensor_paths": tensor_paths,
        "feature_cols": feature_cols,
        "summary_rows": summary_rows,
        "n_features": len(feature_cols),
    }


# ---------------------------------------------------------------------------
# Orchestration helpers
# ---------------------------------------------------------------------------

ALL_STAGES = (
    "match",
    "label_events",
    "unified_stream",
    "daily_intervals",
    "densify",
    "sliding_windows",
    "sequence_tensors",
)


def append_pipeline_notes(
    notes_path: Path,
    *,
    version: str,
    stage_results: dict[str, Any],
    pipe: PipelinePaths,
    smoke: bool,
) -> None:
    notes_path.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    mode = "smoke" if smoke else "full"
    with notes_path.open("a", encoding="utf-8") as handle:
        handle.write(
            f"\n\n## CERT {version} common-13 preparation pipeline ({stamp}, {mode})\n\n"
        )
        handle.write(
            "Built event-labelled logs, daily behavioural intervals, densified calendars, "
            f"and T={WINDOW_LENGTH} stride={STRIDE} sequence tensors using the verified "
            "common 13-feature schema. No model training. Raw files not modified. "
            "Locked r4.2 / Objective 2 / Objective 3 artefacts untouched.\n\n"
        )
        handle.write("### Common-13 features\n\n")
        for feat in COMMON_13_FEATURES:
            handle.write(f"- `{feat}`\n")
        handle.write("\n### Outputs\n\n")
        handle.write(f"- Matched IDs: `{pipe.matched_csv}`\n")
        handle.write(f"- Event-level dir: `{pipe.event_level_dir}`\n")
        handle.write(f"- Unified stream: `{pipe.event_stream_path}`\n")
        handle.write(f"- Active intervals: `{pipe.intervals_path}`\n")
        handle.write(f"- Dense intervals: `{pipe.dense_path}`\n")
        handle.write(f"- Sequence metadata: `{pipe.sequence_meta_path}`\n")
        handle.write(f"- Tensors: `{pipe.tensor_dir}`\n")
        handle.write(f"- Manifest: `{pipe.manifest_json}`\n\n")
        if "sliding_windows" in stage_results:
            stats = stage_results["sliding_windows"].get("split_stats", {})
            handle.write("### Sequence split summary\n\n")
            handle.write("| Split | Sequences | Malicious |\n")
            handle.write("|-------|-----------|----------|\n")
            for split_name in ("train", "validation", "test"):
                s = stats.get(split_name, {})
                handle.write(
                    f"| {split_name} | {s.get('sequences', 0):,} | "
                    f"{s.get('malicious_sequences', 0):,} |\n"
                )
            handle.write("\n")
        if smoke:
            handle.write(
                "> Smoke/partial run: do **not** use these artefacts for confirmatory "
                "evaluation or architecture search.\n"
            )


def run_pipeline(
    pipe: PipelinePaths,
    *,
    stages: Iterable[str] = ALL_STAGES,
    smoke: bool = False,
    max_scan_rows_per_file: int | None = None,
    max_rows_per_log: int | None = None,
) -> dict[str, Any]:
    """Run selected preparation stages. Never trains or evaluates models."""
    pipe.ensure_parents()
    selected = tuple(stages)
    unknown = [s for s in selected if s not in ALL_STAGES]
    if unknown:
        raise ValueError(f"Unknown stages: {unknown}; allowed={ALL_STAGES}")

    if smoke:
        if max_scan_rows_per_file is None:
            max_scan_rows_per_file = 100_000
        if max_rows_per_log is None:
            max_rows_per_log = 50_000

    results: dict[str, Any] = {}
    for stage in selected:
        if stage == "match":
            results[stage] = stage_match(
                pipe, max_scan_rows_per_file=max_scan_rows_per_file
            )
        elif stage == "label_events":
            results[stage] = stage_label_events(pipe, max_rows_per_log=max_rows_per_log)
        elif stage == "unified_stream":
            results[stage] = stage_unified_stream(pipe)
        elif stage == "daily_intervals":
            results[stage] = stage_daily_intervals(pipe)
        elif stage == "densify":
            results[stage] = stage_densify(pipe)
        elif stage == "sliding_windows":
            results[stage] = stage_sliding_windows(pipe)
        elif stage == "sequence_tensors":
            results[stage] = stage_sequence_tensors(pipe)

    manifest = {
        "dataset_version": pipe.version,
        "prefix": pipe.prefix,
        "raw_dir": str(pipe.raw_dir),
        "answers_dir": str(pipe.answers_dir),
        "processed_dir": str(pipe.processed_dir),
        "output_dir": str(pipe.output_dir),
        "stages_requested": list(selected),
        "stages_completed": list(results.keys()),
        "common_13_features": list(COMMON_13_FEATURES),
        "window_length": WINDOW_LENGTH,
        "stride": STRIDE,
        "smoke": smoke,
        "max_scan_rows_per_file": max_scan_rows_per_file,
        "max_rows_per_log": max_rows_per_log,
        "training_started": False,
        "test_evaluated": False,
        "locked_artefacts_modified": False,
        "stage_results": {
            k: {kk: vv for kk, vv in v.items() if kk != "summary_rows"}
            for k, v in results.items()
        },
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    # Keep compact stage summaries for label_events / tensors
    if "label_events" in results:
        manifest["stage_results"]["label_events"]["summary_rows"] = results[
            "label_events"
        ]["summary_rows"]
    if "sequence_tensors" in results:
        manifest["stage_results"]["sequence_tensors"]["summary_rows"] = results[
            "sequence_tensors"
        ]["summary_rows"]
        manifest["stage_results"]["sequence_tensors"]["feature_cols"] = results[
            "sequence_tensors"
        ]["feature_cols"]

    _write_json(pipe.manifest_json, manifest)
    append_pipeline_notes(
        pipe.notes_path,
        version=pipe.version,
        stage_results=results,
        pipe=pipe,
        smoke=smoke,
    )
    return manifest


__all__ = [
    "ALL_STAGES",
    "COMMON_13_FEATURES",
    "PipelinePaths",
    "WINDOW_LENGTH",
    "run_pipeline",
    "stage_daily_intervals",
    "stage_densify",
    "stage_label_events",
    "stage_match",
    "stage_sequence_tensors",
    "stage_sliding_windows",
    "stage_unified_stream",
]
