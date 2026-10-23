#!/usr/bin/env python3
"""Generalized CERT ground-truth loading for releases 4.2, 5.2, and 6.2.

Answer layouts:
- r4.2 / r5.2: per-user CSVs under scenario directories (variable-length rows)
- r6.2: flat scenario CSV files (all users interleaved; may be quoted)

Does not write into raw answer or activity directories.
"""

from __future__ import annotations

import csv
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

import pandas as pd

from dataset_registry import DatasetSpec, get_dataset_spec, normalize_dataset_version

EVENT_ID_RE = re.compile(r"^\{[A-Z0-9]+-[A-Z0-9]+-[A-Z0-9]+\}$", re.IGNORECASE)
TIMESTAMP_FORMATS = (
    "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y %H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
)


def parse_timestamp(value: str) -> datetime | None:
    text = (value or "").strip().strip('"')
    if not text:
        return None
    for fmt in TIMESTAMP_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def looks_like_event_id(value: str) -> bool:
    return bool(EVENT_ID_RE.match((value or "").strip().strip('"')))


def normalize_event_id(value: str) -> str:
    return (value or "").strip().strip('"')


def find_insiders_csv(answers_dir: Path) -> Path | None:
    direct = answers_dir / "insiders.csv"
    if direct.is_file():
        return direct
    matches = list(answers_dir.rglob("insiders.csv"))
    return matches[0] if matches else None


def is_insider_row_for_version(row: pd.Series, spec: DatasetSpec) -> bool:
    dataset = str(row.get("dataset", "")).strip().lower()
    details = str(row.get("details", "")).lower()
    accepted = {v.lower() for v in spec.insiders_dataset_values}
    if dataset in accepted:
        return True
    # details often contain "r5.2-1-USER.csv"
    for key in spec.scenario_keys:
        if key.lower() in details:
            return True
    tag = spec.release_tag.lower()
    return tag in details or tag.replace(".", "") in dataset.replace(".", "")


def load_insiders_for_version(answers_dir: Path, version: str) -> pd.DataFrame:
    spec = get_dataset_spec(version)
    path = find_insiders_csv(answers_dir)
    if path is None:
        return pd.DataFrame()
    df = pd.read_csv(path, dtype=str, low_memory=False)
    if df.empty:
        return df
    mask = df.apply(lambda row: is_insider_row_for_version(row, spec), axis=1)
    out = df.loc[mask].copy()
    out["_dataset_version"] = spec.version
    return out


def user_id_from_per_user_filename(path: Path, spec: DatasetSpec) -> str:
    # e.g. r5.2-1-<USERID>.csv
    pattern = re.compile(
        rf"{re.escape(spec.release_tag)}-\d+-([A-Z0-9]+)\.csv$",
        re.IGNORECASE,
    )
    match = pattern.search(path.name)
    if match:
        return match.group(1)
    stem = path.stem
    return stem.split("-")[-1] if "-" in stem else stem


def discover_answer_sources(answers_dir: Path, version: str) -> dict[str, Any]:
    """Discover answer files/dirs for a release without fully parsing them."""
    spec = get_dataset_spec(version)
    result: dict[str, Any] = {
        "dataset_version": spec.version,
        "answer_format": spec.answer_format,
        "expected_scenarios": list(spec.scenario_keys),
        "missing_scenario_sources": [],
        "sources": [],
    }
    if spec.answer_format == "per_user_directories":
        for key in spec.scenario_keys:
            folder = answers_dir / key
            if not folder.is_dir():
                result["missing_scenario_sources"].append(key)
                continue
            files = sorted(folder.glob("*.csv"))
            result["sources"].append(
                {
                    "scenario_key": key,
                    "kind": "directory",
                    "path": str(folder),
                    "n_files": len(files),
                }
            )
    else:
        for key in spec.scenario_keys:
            path = answers_dir / f"{key}.csv"
            if not path.is_file():
                result["missing_scenario_sources"].append(f"{key}.csv")
                continue
            result["sources"].append(
                {
                    "scenario_key": key,
                    "kind": "flat_csv",
                    "path": str(path),
                    "size_bytes": path.stat().st_size,
                }
            )
    return result


@dataclass
class AnswerEventRecord:
    event_id: str
    event_type: str
    scenario_key: str
    answer_user: str
    answer_file: str
    answer_row: int
    timestamp: str = ""
    extra: dict[str, str] = field(default_factory=dict)


def _iter_answer_rows(path: Path) -> Iterator[tuple[int, list[str]]]:
    with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
        reader = csv.reader(handle)
        for row_num, row in enumerate(reader, start=1):
            if not row or all(not (c or "").strip() for c in row):
                continue
            yield row_num, [(c or "").strip().strip('"') for c in row]


def parse_answer_row(row: list[str]) -> tuple[str, str, str, str] | None:
    """Extract (event_type, event_id, timestamp, user) when present.

    Layout observed across r4.2/r5.2/r6.2 answer rows:
    event_type, {EVENT-ID}, timestamp, user, pc, ...
    """
    if len(row) < 2:
        return None
    event_type = row[0].strip().lower()
    event_id = normalize_event_id(row[1])
    if not looks_like_event_id(event_id):
        # Some flat files may have a header-like first row; skip non-events.
        return None
    timestamp = row[2] if len(row) > 2 else ""
    user = row[3] if len(row) > 3 else ""
    return event_type, event_id, timestamp, user


def load_answer_events(
    answers_dir: Path,
    version: str,
    *,
    max_events: int | None = None,
) -> tuple[list[AnswerEventRecord], dict[str, Any]]:
    """Load malicious answer events for one release.

    Returns (records, diagnostics).
    """
    spec = get_dataset_spec(version)
    records: list[AnswerEventRecord] = []
    diagnostics: dict[str, Any] = {
        "dataset_version": spec.version,
        "answer_format": spec.answer_format,
        "files_read": 0,
        "rows_read": 0,
        "malformed_rows": 0,
        "duplicate_event_ids": 0,
        "event_ids_seen": 0,
        "missing_scenario_sources": [],
        "event_type_counts": Counter(),
        "scenario_counts": Counter(),
    }
    seen_ids: set[str] = set()

    def _ingest(path: Path, scenario_key: str, default_user: str = "") -> None:
        diagnostics["files_read"] += 1
        for row_num, row in _iter_answer_rows(path):
            diagnostics["rows_read"] += 1
            parsed = parse_answer_row(row)
            if parsed is None:
                diagnostics["malformed_rows"] += 1
                continue
            event_type, event_id, timestamp, user = parsed
            if event_id in seen_ids:
                diagnostics["duplicate_event_ids"] += 1
            else:
                seen_ids.add(event_id)
            try:
                rel = str(path.relative_to(answers_dir))
            except ValueError:
                rel = str(path)
            records.append(
                AnswerEventRecord(
                    event_id=event_id,
                    event_type=event_type,
                    scenario_key=scenario_key,
                    answer_user=user or default_user,
                    answer_file=rel,
                    answer_row=row_num,
                    timestamp=timestamp,
                )
            )
            diagnostics["event_type_counts"][event_type] += 1
            diagnostics["scenario_counts"][scenario_key] += 1
            if max_events is not None and len(records) >= max_events:
                return

    if spec.answer_format == "per_user_directories":
        for key in spec.scenario_keys:
            folder = answers_dir / key
            if not folder.is_dir():
                diagnostics["missing_scenario_sources"].append(key)
                continue
            for path in sorted(folder.glob("*.csv")):
                user = user_id_from_per_user_filename(path, spec)
                _ingest(path, key, default_user=user)
                if max_events is not None and len(records) >= max_events:
                    break
            if max_events is not None and len(records) >= max_events:
                break
    else:
        for key in spec.scenario_keys:
            path = answers_dir / f"{key}.csv"
            if not path.is_file():
                diagnostics["missing_scenario_sources"].append(f"{key}.csv")
                continue
            _ingest(path, key)
            if max_events is not None and len(records) >= max_events:
                break

    diagnostics["event_ids_seen"] = len(seen_ids)
    diagnostics["n_answer_records"] = len(records)
    diagnostics["event_type_counts"] = dict(diagnostics["event_type_counts"])
    diagnostics["scenario_counts"] = dict(diagnostics["scenario_counts"])
    return records, diagnostics


def summarize_ground_truth(answers_dir: Path, version: str) -> dict[str, Any]:
    """Full ground-truth summary for readiness reporting."""
    spec = get_dataset_spec(version)
    insiders = load_insiders_for_version(answers_dir, version)
    discovery = discover_answer_sources(answers_dir, version)
    records, diagnostics = load_answer_events(answers_dir, version)

    insider_users = []
    scenario_from_insiders: Counter[str] = Counter()
    if not insiders.empty and "user" in insiders.columns:
        insider_users = sorted(
            {str(u).strip() for u in insiders["user"].dropna() if str(u).strip()}
        )
    if not insiders.empty and "scenario" in insiders.columns:
        scenario_from_insiders = Counter(
            str(s).strip() for s in insiders["scenario"].dropna() if str(s).strip()
        )

    users_from_answers = sorted({r.answer_user for r in records if r.answer_user})
    event_ids = [r.event_id for r in records]
    id_counts = Counter(event_ids)

    return {
        "dataset_version": spec.version,
        "answer_format": spec.answer_format,
        "insiders_csv": str(find_insiders_csv(answers_dir) or ""),
        "n_insider_rows": int(len(insiders)),
        "n_insider_users": len(insider_users),
        "insider_users": insider_users,
        "insider_counts_by_scenario": dict(scenario_from_insiders),
        "answer_discovery": discovery,
        "n_answer_records": len(records),
        "n_unique_event_ids": len(id_counts),
        "n_duplicate_event_ids": sum(1 for _, c in id_counts.items() if c > 1),
        "event_types_available": sorted({r.event_type for r in records}),
        "malformed_rows": diagnostics["malformed_rows"],
        "missing_scenario_sources": diagnostics["missing_scenario_sources"],
        "event_type_counts": diagnostics["event_type_counts"],
        "scenario_event_counts": diagnostics["scenario_counts"],
        "answer_users": users_from_answers,
        "n_answer_users": len(users_from_answers),
        "diagnostics": diagnostics,
    }


def match_answer_ids_against_raw(
    records: list[AnswerEventRecord],
    raw_dir: Path,
    *,
    event_types: tuple[str, ...] = ("logon", "device", "file", "email", "http"),
    max_scan_rows_per_file: int | None = None,
) -> dict[str, Any]:
    """Stream raw logs and count matched / unmatched answer event IDs.

    For smoke audits, pass a small ``max_scan_rows_per_file``. Full audits
    should leave it ``None`` (scan until all IDs found or EOF).
    """
    by_type: dict[str, set[str]] = defaultdict(set)
    for rec in records:
        if rec.event_type in event_types:
            by_type[rec.event_type].add(rec.event_id)

    matched: dict[str, set[str]] = {t: set() for t in event_types}
    scanned: dict[str, int] = {}
    missing_files: list[str] = []

    for event_type in event_types:
        targets = by_type.get(event_type, set())
        path = raw_dir / f"{event_type}.csv"
        if not path.is_file():
            missing_files.append(f"{event_type}.csv")
            scanned[event_type] = 0
            continue
        remaining = set(targets)
        rows = 0
        with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames or "id" not in reader.fieldnames:
                missing_files.append(f"{event_type}.csv (no id column)")
                scanned[event_type] = 0
                continue
            for row in reader:
                rows += 1
                eid = normalize_event_id(row.get("id") or "")
                if eid in remaining:
                    matched[event_type].add(eid)
                    remaining.remove(eid)
                    if not remaining:
                        break
                if max_scan_rows_per_file is not None and rows >= max_scan_rows_per_file:
                    break
        scanned[event_type] = rows

    n_targets = sum(len(v) for v in by_type.values())
    n_matched = sum(len(v) for v in matched.values())
    unmatched_by_type = {
        t: sorted(by_type.get(t, set()) - matched.get(t, set())) for t in event_types
    }
    return {
        "n_target_ids": n_targets,
        "n_matched_ids": n_matched,
        "n_unmatched_ids": n_targets - n_matched,
        "matched_by_type": {t: len(matched[t]) for t in event_types},
        "targets_by_type": {t: len(by_type.get(t, set())) for t in event_types},
        "rows_scanned_by_type": scanned,
        "missing_or_invalid_raw_files": missing_files,
        "unmatched_sample_by_type": {
            t: ids[:20] for t, ids in unmatched_by_type.items() if ids
        },
        "partial_scan": max_scan_rows_per_file is not None,
    }


__all__ = [
    "AnswerEventRecord",
    "discover_answer_sources",
    "find_insiders_csv",
    "is_insider_row_for_version",
    "load_answer_events",
    "load_insiders_for_version",
    "looks_like_event_id",
    "match_answer_ids_against_raw",
    "normalize_dataset_version",
    "normalize_event_id",
    "parse_answer_row",
    "parse_timestamp",
    "summarize_ground_truth",
    "user_id_from_per_user_filename",
]
