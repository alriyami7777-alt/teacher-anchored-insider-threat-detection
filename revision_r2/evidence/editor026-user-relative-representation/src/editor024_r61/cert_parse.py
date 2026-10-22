"""Frozen CERT event/window/label parsers reused from the r5.1/r6.2 external harness.

Source (EDITOR023_RESULTS_COMMIT):
- scripts/run_editor007b_r51_bundle.py
- review/editor006c_r62_input_bundle/run_editor006c_r62_input_bundle.py
- src/editor006b_harness/input_bundle.py

These functions operate on caller-supplied paths. They do not know about CERT r6.1.
"""

from __future__ import annotations

import csv
import re
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path
from typing import Any, TextIO

import numpy as np

from .constants import FEATURE_ORDER, SEQUENCE_LENGTH, SOURCE_TYPES

EVENT_ID_RE = re.compile(r"^\{[A-Z0-9]+-[A-Z0-9]+-[A-Z0-9]+\}$", re.IGNORECASE)
CSV_FIELD_LIMIT = 64 * 1024 * 1024
T_WINDOW = SEQUENCE_LENGTH


def looks_like_event_id(value: str) -> bool:
    return bool(EVENT_ID_RE.match((value or "").strip().strip('"')))


def normalize_event_id(value: str) -> str:
    return (value or "").strip().strip('"')


def parse_cert_ts(text: str) -> tuple[int, int, int, int, int, int] | None:
    s = (text or "").strip().strip('"')
    if len(s) < 16 or s[2] != "/" or s[5] != "/":
        return None
    try:
        month = int(s[0:2])
        day = int(s[3:5])
        year = int(s[6:10])
        hour = int(s[11:13])
        minute = int(s[14:16])
        second = int(s[17:19]) if len(s) >= 19 and s[16] == ":" else 0
        if not (1 <= month <= 12 and 1 <= day <= 31):
            return None
        return (year, month, day, hour, minute, second)
    except ValueError:
        return None


def ts_to_minutes(a: tuple[int, int, int, int, int, int], b: tuple[int, int, int, int, int, int]) -> int:
    return max(int((datetime(*b) - datetime(*a)).total_seconds() // 60), 0)


def pack_ts(ts: tuple[int, int, int, int, int, int]) -> int:
    y, mo, d, h, mi, s = ts
    return (((((y * 100 + mo) * 100 + d) * 100 + h) * 100 + mi) * 100 + s)


def unpack_ts(packed: int) -> tuple[int, int, int, int, int, int]:
    s = packed % 100
    packed //= 100
    mi = packed % 100
    packed //= 100
    h = packed % 100
    packed //= 100
    d = packed % 100
    packed //= 100
    mo = packed % 100
    y = packed // 100
    return (y, mo, d, h, mi, s)


def parse_answer_file(handle: TextIO, scenario_key: str) -> list[dict[str, Any]]:
    """Frozen generic CERT answer parser. Caller supplies an already-opened handle."""
    records: list[dict[str, Any]] = []
    reader = csv.reader(handle)
    for row in reader:
        if not row or all(not (c or "").strip() for c in row):
            continue
        cells = [(c or "").strip().strip('"') for c in row]
        if len(cells) < 2:
            continue
        event_type = cells[0].strip().lower()
        event_id = normalize_event_id(cells[1])
        if not looks_like_event_id(event_id):
            continue
        records.append(
            {
                "scenario_key": scenario_key,
                "event_type": event_type,
                "event_id": event_id,
                "timestamp": cells[2] if len(cells) > 2 else "",
                "user": cells[3] if len(cells) > 3 else "",
            }
        )
    return records


def header_prefix_ok(header: list[str], required: tuple[str, ...] = ("id", "date", "user")) -> bool:
    got = [(c or "").strip().lower() for c in header[: len(required)]]
    return got == list(required)


def scan_source(
    source: str,
    handle: TextIO,
    *,
    source_answer_ids: set[str],
    id_to_bit: dict[str, int],
    match_counts: dict[str, int],
    active: dict[tuple[int, int], list[int]],
    user_index: dict[str, int],
    user_list: list[str],
    progress: Callable[[str], None] | None = None,
    progress_every: int = 2_000_000,
) -> dict[str, Any]:
    """Stream one CERT log. Columns 0/1/2 are id/date/user (frozen harness convention)."""
    src_idx = {name: i for i, name in enumerate(SOURCE_TYPES)}[source]
    header: list[str] | None = None
    n_rows = 0
    malformed = 0
    n_parsed_ts = 0
    reader = csv.reader(handle)
    for row in reader:
        if header is None:
            header = [(c or "").strip() for c in row]
            continue
        n_rows += 1
        if progress and n_rows % progress_every == 0:
            progress(f"  {source}: {n_rows:,}")
        if len(row) < 3:
            malformed += 1
            continue
        event_id = normalize_event_id(row[0])
        ts_raw = (row[1] or "").strip()
        user = (row[2] or "").strip()
        ts = parse_cert_ts(ts_raw)
        if ts is None or not event_id or not user:
            malformed += 1
            continue
        n_parsed_ts += 1
        matched = event_id in source_answer_ids
        if matched:
            match_counts[event_id] = match_counts.get(event_id, 0) + 1
        uid = user_index.get(user)
        if uid is None:
            uid = len(user_list)
            user_index[user] = uid
            user_list.append(user)
        ordinal = date(ts[0], ts[1], ts[2]).toordinal()
        key = (uid, ordinal)
        rec = active.get(key)
        packed = pack_ts(ts)
        if rec is None:
            rec = [0, 0, 0, 0, 0, 0, packed, packed, 0]
            active[key] = rec
        rec[src_idx] += 1
        if packed < rec[6]:
            rec[6] = packed
        if packed > rec[7]:
            rec[7] = packed
        if matched:
            rec[5] = 1
            rec[8] |= int(id_to_bit.get(event_id, 0))
    return {
        "source": source,
        "n_data_rows": n_rows,
        "header": header or [],
        "header_ok": header_prefix_ok(header or []),
        "malformed": malformed,
        "n_parsed_timestamps": n_parsed_ts,
    }


def build_dense_daily(
    *,
    user_list: list[str],
    active: dict[tuple[int, int], list[int]],
) -> dict[str, Any]:
    """Construct the frozen 13-feature dense user-day grid and completed-window labels."""
    if not user_list or not active:
        raise ValueError("empty CERT daily representation")
    ordinals = [k[1] for k in active]
    min_ord = min(ordinals)
    max_ord = max(ordinals)
    calendar = [date.fromordinal(o) for o in range(min_ord, max_ord + 1)]
    n_days = len(calendar)
    user_ids_sorted = sorted(user_list)
    discovery_index = {u: i for i, u in enumerate(user_list)}
    uid_rank = {discovery_index[u]: i for i, u in enumerate(user_ids_sorted)}

    n_users = len(user_ids_sorted)
    raw = np.zeros((n_users, n_days, 13), dtype=np.float64)
    mal = np.zeros((n_users, n_days), dtype=np.uint8)
    day_bits = np.zeros((n_users, n_days), dtype=np.uint32)
    for (uid, ordinal), rec in active.items():
        u = uid_rank[uid]
        d = ordinal - min_ord
        logon_c, device_c, file_c, email_c, http_c, is_mal, tmin_p, tmax_p, bits = rec
        total = logon_c + device_c + file_c + email_c + http_c
        duration = ts_to_minutes(unpack_ts(tmin_p), unpack_ts(tmax_p))
        raw[u, d, 0] = total
        raw[u, d, 1] = logon_c
        raw[u, d, 2] = device_c
        raw[u, d, 3] = file_c
        raw[u, d, 4] = email_c
        raw[u, d, 5] = http_c
        raw[u, d, 6] = duration
        raw[u, d, 7] = 1.0 if logon_c else 0.0
        raw[u, d, 8] = 1.0 if device_c else 0.0
        raw[u, d, 9] = 1.0 if file_c else 0.0
        raw[u, d, 10] = 1.0 if email_c else 0.0
        raw[u, d, 11] = 1.0 if http_c else 0.0
        raw[u, d, 12] = 1.0
        mal[u, d] = 1 if is_mal else 0
        day_bits[u, d] = np.uint32(bits)

    if n_days < T_WINDOW:
        raise ValueError(f"calendar days {n_days} < sequence length {T_WINDOW}")
    n_starts = n_days - T_WINDOW + 1
    ui = np.repeat(np.arange(n_users, dtype=np.int32), n_starts)
    si = np.tile(np.arange(n_starts, dtype=np.int32), n_users)
    window_index = np.stack([ui, si], axis=1)
    cs = np.pad(mal.cumsum(axis=1, dtype=np.int32), ((0, 0), (1, 0)))
    completed_2d = ((cs[:, T_WINDOW:] - cs[:, :n_starts]) > 0).astype(np.uint8)
    completed = completed_2d.reshape(-1)
    deov_starts = (np.arange(n_starts) % T_WINDOW == 0)
    deov = np.tile(deov_starts.astype(np.uint8), n_users)
    cal_iso = [d.isoformat() for d in calendar]
    seq_ids = np.array(
        [f"{user_ids_sorted[int(u)]}|{cal_iso[int(s)]}|{cal_iso[int(s) + T_WINDOW - 1]}" for u, s in window_index],
        dtype=object,
    )
    user_ids_windows = np.array([user_ids_sorted[int(u)] for u in ui], dtype=object)
    return {
        "raw": raw,
        "malicious_day_labels": mal,
        "day_bits": day_bits,
        "user_ids_sorted": user_ids_sorted,
        "calendar_iso": cal_iso,
        "window_index": window_index,
        "user_index": ui,
        "start_index": si,
        "completed_window_labels": completed,
        "deoverlap_offset0_mask": deov,
        "sequence_ids": seq_ids,
        "user_ids_windows": user_ids_windows,
        "n_users": n_users,
        "n_days": n_days,
        "n_starts": n_starts,
        "n_windows": int(n_users * n_starts),
        "n_completed_positives": int(completed.sum()),
        "n_deoverlap": int(deov.sum()),
        "n_deoverlap_positives": int((completed * deov).sum()),
        "feature_order": list(FEATURE_ORDER),
        "sequence_length": T_WINDOW,
        "stride": 1,
        "deoverlap_rule": "start_day_index % 20 == 0",
        "label_semantics": "COMPLETED_WINDOW",
    }


def gather_windows(dense: np.ndarray, user_idx: np.ndarray, start_idx: np.ndarray) -> np.ndarray:
    """Frozen T=20 gather used by editor006b DenseDailyWindowProvider."""
    offs = np.arange(T_WINDOW, dtype=np.int32)
    return np.asarray(dense)[user_idx[:, None], start_idx[:, None] + offs]
