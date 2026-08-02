#!/usr/bin/env python3
"""Chunked CSV quality scanning helpers for CERT readiness audits."""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

DATE_FORMATS = (
    "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y %H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
)


def available_memory_bytes() -> int | None:
    """Best-effort available RAM estimate (Windows-friendly)."""
    try:
        import psutil  # type: ignore

        return int(psutil.virtual_memory().available)
    except Exception:
        pass
    try:
        import ctypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
            return int(stat.ullAvailPhys)
    except Exception:
        return None
    return None


def choose_chunk_size(
    file_size_bytes: int,
    *,
    default: int = 250_000,
    min_size: int = 50_000,
    max_size: int = 1_000_000,
) -> int:
    mem = available_memory_bytes()
    if mem is None:
        if file_size_bytes > 10 * 1024**3:
            return min_size
        if file_size_bytes > 2 * 1024**3:
            return 100_000
        return default
    # Aim for roughly <2% of available RAM per chunk (very conservative for wide rows).
    approx = max(min_size, min(max_size, int(mem / (50_000 * 40))))
    if file_size_bytes > 20 * 1024**3:
        return min(approx, 100_000)
    return approx


def parse_ts(value: Any) -> datetime | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    if not text:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    try:
        ts = pd.to_datetime(text, errors="coerce")
        if pd.isna(ts):
            return None
        return ts.to_pydatetime()
    except Exception:
        return None


@dataclass
class LogQualityReport:
    log_name: str
    path: str
    exists: bool
    size_bytes: int = 0
    header: list[str] = field(default_factory=list)
    row_count: int = 0
    unique_users: int | None = None
    user_column: str | None = None
    date_column: str | None = None
    min_timestamp: str | None = None
    max_timestamp: str | None = None
    invalid_timestamps: int = 0
    missing_by_column: dict[str, int] = field(default_factory=dict)
    duplicate_event_ids: int | None = None
    duplicate_complete_rows: int | None = None
    notes: list[str] = field(default_factory=list)
    status: str = "ok"

    def as_dict(self) -> dict[str, Any]:
        return {
            "log_name": self.log_name,
            "path": self.path,
            "exists": self.exists,
            "size_bytes": self.size_bytes,
            "size_gb": round(self.size_bytes / (1024**3), 4) if self.size_bytes else 0.0,
            "header": self.header,
            "row_count": self.row_count,
            "unique_users": self.unique_users,
            "user_column": self.user_column,
            "date_column": self.date_column,
            "min_timestamp": self.min_timestamp,
            "max_timestamp": self.max_timestamp,
            "invalid_timestamps": self.invalid_timestamps,
            "missing_by_column": self.missing_by_column,
            "duplicate_event_ids": self.duplicate_event_ids,
            "duplicate_complete_rows": self.duplicate_complete_rows,
            "notes": self.notes,
            "status": self.status,
        }


def _pick_column(header: list[str], candidates: tuple[str, ...]) -> str | None:
    lower = {c.lower(): c for c in header}
    for cand in candidates:
        if cand in lower:
            return lower[cand]
    return None


def scan_log_quality(
    path: Path,
    log_name: str,
    *,
    max_rows: int | None = None,
    track_duplicate_ids: bool = True,
    track_duplicate_rows: bool = False,
    progress_every: int = 1_000_000,
) -> LogQualityReport:
    """Chunked quality scan for one CSV log."""
    report = LogQualityReport(log_name=log_name, path=str(path), exists=path.is_file())
    if not report.exists:
        report.status = "missing"
        return report

    report.size_bytes = path.stat().st_size
    try:
        with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
            header_line = handle.readline()
        report.header = next(csv.reader([header_line])) if header_line else []
    except Exception as exc:
        report.status = f"header_error: {exc}"
        return report

    user_col = _pick_column(report.header, ("user", "user_id"))
    date_col = _pick_column(report.header, ("date", "timestamp", "time"))
    id_col = _pick_column(report.header, ("id",))
    report.user_column = user_col
    report.date_column = date_col

    # Psychometric is small and has no activity timestamps.
    if log_name == "psychometric" or report.size_bytes < 5_000_000:
        try:
            df = pd.read_csv(path, dtype=str, low_memory=False)
            report.row_count = len(df)
            if user_col and user_col in df.columns:
                report.unique_users = int(df[user_col].dropna().astype(str).nunique())
            for col in df.columns:
                report.missing_by_column[col] = int(df[col].isna().sum() + (df[col] == "").sum())
            if date_col and date_col in df.columns:
                parsed = [parse_ts(v) for v in df[date_col].tolist()]
                valid = [p for p in parsed if p is not None]
                report.invalid_timestamps = len(parsed) - len(valid)
                if valid:
                    report.min_timestamp = min(valid).strftime("%Y-%m-%d %H:%M:%S")
                    report.max_timestamp = max(valid).strftime("%Y-%m-%d %H:%M:%S")
            if id_col and id_col in df.columns and track_duplicate_ids:
                report.duplicate_event_ids = int(
                    df[id_col].duplicated().sum()
                )
            if track_duplicate_rows and len(df) <= 200_000:
                report.duplicate_complete_rows = int(df.duplicated().sum())
            elif track_duplicate_rows:
                report.notes.append("duplicate complete-row check skipped (file large)")
            return report
        except Exception as exc:
            report.notes.append(f"full-read failed, falling back to chunks: {exc}")

    chunk_size = choose_chunk_size(report.size_bytes)
    users: set[str] = set()
    min_ts: datetime | None = None
    max_ts: datetime | None = None
    invalid_ts = 0
    missing: dict[str, int] = {c: 0 for c in report.header}
    seen_ids: set[str] | None = set() if (track_duplicate_ids and id_col) else None
    dup_ids = 0
    rows = 0

    usecols = None
    # Prefer reading all columns for missingness on manageable files only.
    wide_and_huge = report.size_bytes > 2 * 1024**3
    if wide_and_huge:
        usecols = [c for c in (user_col, date_col, id_col) if c]
        report.notes.append(
            "huge file: missingness computed only for user/date/id columns"
        )

    print(
        f"  scanning {path.name} (size={report.size_bytes / (1024**3):.2f} GiB, "
        f"chunk={chunk_size:,}, max_rows={max_rows})"
    )
    try:
        reader = pd.read_csv(
            path,
            dtype=str,
            chunksize=chunk_size,
            usecols=usecols,
            low_memory=False,
        )
        for chunk in reader:
            n = len(chunk)
            rows += n
            for col in chunk.columns:
                if col in missing:
                    missing[col] += int(chunk[col].isna().sum() + (chunk[col] == "").sum())
                else:
                    missing[col] = int(chunk[col].isna().sum() + (chunk[col] == "").sum())
            if user_col and user_col in chunk.columns:
                users.update(chunk[user_col].dropna().astype(str).unique().tolist())
            if date_col and date_col in chunk.columns:
                for val in chunk[date_col].tolist():
                    ts = parse_ts(val)
                    if ts is None:
                        if str(val).strip():
                            invalid_ts += 1
                        continue
                    min_ts = ts if min_ts is None else min(min_ts, ts)
                    max_ts = ts if max_ts is None else max(max_ts, ts)
            if seen_ids is not None and id_col and id_col in chunk.columns:
                for eid in chunk[id_col].dropna().astype(str):
                    if eid in seen_ids:
                        dup_ids += 1
                    else:
                        seen_ids.add(eid)
            if rows % progress_every < chunk_size:
                print(f"    {path.name}: {rows:,} rows ...")
            if max_rows is not None and rows >= max_rows:
                report.notes.append(f"truncated after {rows:,} rows (smoke/partial mode)")
                report.status = "partial"
                break
    except Exception as exc:
        report.status = f"scan_error: {exc}"
        report.notes.append(str(exc))
        report.row_count = rows
        return report

    report.row_count = rows
    report.unique_users = len(users) if user_col else None
    report.invalid_timestamps = invalid_ts
    report.missing_by_column = missing
    if min_ts:
        report.min_timestamp = min_ts.strftime("%Y-%m-%d %H:%M:%S")
    if max_ts:
        report.max_timestamp = max_ts.strftime("%Y-%m-%d %H:%M:%S")
    if seen_ids is not None:
        report.duplicate_event_ids = dup_ids
    if track_duplicate_rows:
        report.notes.append("duplicate complete-row check skipped in chunked mode")
        report.duplicate_complete_rows = None
    return report


def inventory_release_files(raw_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not raw_dir.is_dir():
        return rows
    for path in sorted(raw_dir.rglob("*")):
        if not path.is_file():
            continue
        # Skip writing anything; inventory only.
        try:
            rel = str(path.relative_to(raw_dir))
        except ValueError:
            rel = str(path)
        size = path.stat().st_size
        rows.append(
            {
                "relative_path": rel,
                "size_bytes": size,
                "size_mb": round(size / (1024**2), 3),
                "suffix": path.suffix.lower(),
            }
        )
    return rows


def ldap_coverage(raw_dir: Path) -> dict[str, Any]:
    ldap = raw_dir / "LDAP"
    if not ldap.is_dir():
        return {"present": False, "n_files": 0, "files": [], "date_coverage": []}
    files = sorted(p for p in ldap.iterdir() if p.is_file())
    names = [p.name for p in files]
    # CERT LDAP files are typically YYYY-MM.csv or similar.
    dates = []
    for name in names:
        stem = Path(name).stem
        dates.append(stem)
    return {
        "present": True,
        "n_files": len(files),
        "files": names,
        "date_coverage": dates,
        "first": dates[0] if dates else None,
        "last": dates[-1] if dates else None,
    }


def detect_aux_files(raw_dir: Path) -> dict[str, Any]:
    readme = raw_dir / "readme.txt"
    licenses = sorted(
        p.name
        for p in raw_dir.iterdir()
        if p.is_file() and "license" in p.name.lower()
    ) if raw_dir.is_dir() else []
    return {
        "readme_present": readme.is_file(),
        "readme_path": str(readme) if readme.is_file() else None,
        "license_files": licenses,
    }


__all__ = [
    "LogQualityReport",
    "available_memory_bytes",
    "choose_chunk_size",
    "detect_aux_files",
    "inventory_release_files",
    "ldap_coverage",
    "scan_log_quality",
]
