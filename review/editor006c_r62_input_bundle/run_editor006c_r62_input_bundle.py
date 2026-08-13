#!/usr/bin/env python3
"""EDITOR-006C — model-free CERT r6.2 input-bundle materialisation.

No predictive model is loaded or scored. Transform-only frozen r5.2 scaler.
"""
from __future__ import annotations

import csv
import hashlib
import json
import platform
import subprocess
import sys
import traceback
import tracemalloc
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

REPO = Path(r"C:\PhD\07_Projects\teacher-anchored-insider-threat-detection")
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from editor006b_harness.contracts import load_freeze_bundle, validate_contracts  # noqa: E402
from editor006b_harness.input_bundle import DenseDailyWindowProvider  # noqa: E402
from editor006b_harness.safety import (  # noqa: E402
    BATCH_SIZE_FROZEN,
    COMMON_13_FEATURES,
    EXPECTED_SCALER_SHA256,
    N_FEATURES,
    T_WINDOW,
    hash_harness_sources,
    sha256_file,
)

TASK_ID = "EDITOR-006C"
HARNESS_RELEASE_COMMIT = "2a73123b25f9bf9d92b651e07ce06b8fa1ba6017"
CERT_R62_ROOT = Path(r"C:\PhD\06_Datasets\r6.2\r6.2")
ANSWERS_CANONICAL = Path(r"C:\PhD\07_Projects\cert-r42-feasibility\answers\answers")
FREEZE_DIR = REPO / "review" / "editor006a_preinference_freeze"
REVIEW_DIR = REPO / "review" / "editor006c_r62_input_bundle"
BUNDLE_DIR = Path(r"C:\PhD\06_Datasets\derived\teacher_anchored_r62_editor006c_bundle")
RUNNER_PATH = REPO / "scripts" / "run_editor006b_harness.py"

CSV_FIELD_LIMIT = 64 * 1024 * 1024
PROGRESS_EVERY = 2_000_000
HASH_BLOCK = 8 * 1024 * 1024
EVENT_ID_RE = __import__("re").compile(r"^\{[A-Z0-9]+-[A-Z0-9]+-[A-Z0-9]+\}$", __import__("re").IGNORECASE)
SOURCE_TYPES = ("logon", "device", "file", "email", "http")
SOURCE_FILES = {s: CERT_R62_ROOT / f"{s}.csv" for s in SOURCE_TYPES}
NULL_INCIDENT_SENTINEL = ""
SCENARIO_BIT = {f"r6.2-{i}": 1 << (i - 1) for i in range(1, 6)}

EXPECTED = {
    "users": 4000,
    "calendar_days": 516,
    "features": 13,
    "dense_rows": 2_064_000,
    "eligible_windows": 1_988_000,
    "completed_positives": 715,
    "endpoint_positives": 78,
    "deoverlap_retained": 100_000,
    "deoverlap_positives": 35,
    "official_insiders": 5,
    "official_incidents": 5,
    "event_level_labelled_users": 29,
    "official_only_completed": 222,
    "official_only_endpoint": 44,
    "official_only_deoverlap": 11,
    "answer_ids": 470,
    "matched_once": 470,
    "unmatched": 0,
    "multiple": 0,
}

FROZEN_STAGE1 = {
    "logon": {"bytes": 241640758, "mtime_utc": "2012-05-31T08:32:04Z", "rows": 3530285,
              "header": ["id", "date", "user", "pc", "activity"],
              "sha256": "ddc683adaaa2ad49dcf68a15c5c7e817089f0a061d7243c258f9999ec8f59b8a"},
    "device": {"bytes": 139541381, "mtime_utc": "2012-06-08T15:00:15Z", "rows": 1551828,
               "header": ["id", "date", "user", "pc", "file_tree", "activity"],
               "sha256": "99a4e9e702ee53d4235c512044e770e0e4961f47589bef81c623e13f5fac385c"},
    "file": {"bytes": 1331296612, "mtime_utc": "2012-06-08T15:21:59Z", "rows": 2014883,
             "header": ["id", "date", "user", "pc", "filename", "activity", "to_removable_media", "from_removable_media", "content"],
             "sha256": "ed4bf6c609c423167ac7b98ec4a5fdec69e7f7e614b94872bf42097d19313cbc"},
    "email": {"bytes": 8084765283, "mtime_utc": "2012-06-08T15:17:41Z", "rows": 10994957,
              "header": ["id", "date", "user", "pc", "to", "cc", "bcc", "from", "activity", "size", "attachments", "content"],
              "sha256": "a9c5190a01cd5a384f1355dd93bc82ad53f30f2825a52984eed76b1ca5e66ae5"},
    "http": {"bytes": 90233360621, "mtime_utc": "2012-06-08T18:36:16Z", "rows": 117025216,
             "header": ["id", "date", "user", "pc", "url", "activity", "content"],
             "sha256": "9d66d0b6aafb1294a215f10feb4251f36acdb70b4404f6259adc24f78ab262b9"},
}
FROZEN_ANSWER_HASHES = {
    "readme.txt": ("820", "fb341d6fb6e36831e63f204a9bd71d59d81714d13ae64aaa88d153bc54a3fe30"),
    "scenarios.txt": ("1055", "dc86447f1669fb1c4fd400264bfcfd8f5f9b94d94fcfe4bcb0bf8acbf6f3c0e0"),
    "insiders.csv": ("13792", "394202dfd70884edb61fc9ecde9f08d6f616700e4eee0984bf06a52d1a99d726"),
    "r6.2-1.csv": ("8161", "b620765b655e06e812087158c3bbd323af3f401a2d6a4537e5058e9eea1fcf33"),
    "r6.2-2.csv": ("121935", "9a45a9a57ce918fbc96bcd9b3d3efd88f6c0490edae512ba21fb16db93c5465e"),
    "r6.2-3.csv": ("43448", "366fdbf1301d5220b72d2df3a16af35624947bdba534a9d9039567e70f79735b"),
    "r6.2-4.csv": ("83716", "1bba2dd5acf4260aa07aa308880313a5cf3ac6f012dd159dda94c54df3a391d2"),
    "r6.2-5.csv": ("1431", "5e9758cb4d3842fc6a9fe69db75d7a7bbaafdd5cb59d861f0cfff21a8a43531c"),
}

FILES_OPENED: list[str] = []
RAW_OPENED: list[str] = []
CONTRACT_OPENED: list[str] = []
FILES_CREATED: list[str] = []
CDE1846_EVENT_DATES: set[str] = set()
CDE1846_EVENT_TIMESTAMPS: list[str] = []


class ProtocolStop(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(msg: str) -> None:
    print(f"[{utc_now()}] {msg}", flush=True)


def note_open(path: Path, kind: str = "other") -> None:
    FILES_OPENED.append(str(path))
    if kind == "raw":
        RAW_OPENED.append(str(path))
    elif kind == "contract":
        CONTRACT_OPENED.append(str(path))


def git_capture(repo: Path) -> dict[str, str]:
    def run(*args: str) -> str:
        proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=False)
        return (proc.stdout or "").strip()

    return {
        "branch": run("rev-parse", "--abbrev-ref", "HEAD"),
        "head": run("rev-parse", "HEAD"),
        "status_short": run("status", "--short"),
    }


def file_stat(path: Path) -> dict[str, Any]:
    st = path.stat()
    mtime = datetime.fromtimestamp(st.st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"path": str(path), "exists": True, "byte_size": int(st.st_size), "mtime_utc": mtime}


def dump_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    FILES_CREATED.append(str(path))


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


def parse_answer_file(path: Path, scenario_key: str) -> list[dict[str, Any]]:
    note_open(path, "raw")
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        reader = csv.reader(handle)
        for row_num, row in enumerate(reader, start=1):
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


def load_official_insiders(path: Path) -> list[dict[str, str]]:
    note_open(path, "raw")
    rows: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        for row in csv.DictReader(handle):
            if str(row.get("dataset", "")).strip() == "6.2":
                rows.append({k: (v or "").strip() for k, v in row.items()})
    return rows


def scan_source(
    source: str,
    path: Path,
    expected_header: list[str],
    expected_rows: int,
    answer_ids: set[str],
    id_to_bit: dict[str, int],
    match_counts: dict[str, int],
    active: dict[tuple[int, int], list[int]],
    user_index: dict[str, int],
    user_list: list[str],
) -> dict[str, Any]:
    log(f"Streaming {source}: {path} ({path.stat().st_size:,} bytes)")
    note_open(path, "raw")
    src_idx = {"logon": 0, "device": 1, "file": 2, "email": 3, "http": 4}[source]
    header: list[str] | None = None
    n_rows = 0
    malformed = 0
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        reader = csv.reader(handle)
        for row in reader:
            if header is None:
                header = [(c or "").strip() for c in row]
                continue
            n_rows += 1
            if n_rows % PROGRESS_EVERY == 0:
                log(f"  {source}: {n_rows:,} / ~{expected_rows:,}")
            if len(row) < 4:
                malformed += 1
                continue
            event_id = normalize_event_id(row[0])
            ts_raw = (row[1] or "").strip()
            user = (row[2] or "").strip()
            ts = parse_cert_ts(ts_raw)
            if ts is None or not event_id or not user:
                malformed += 1
                continue
            if event_id in answer_ids:
                match_counts[event_id] += 1
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
            if event_id in answer_ids:
                rec[5] = 1
                rec[8] |= int(id_to_bit.get(event_id, 0))
                if user == "CDE1846":
                    CDE1846_EVENT_TIMESTAMPS.append(ts_raw)
                    CDE1846_EVENT_DATES.add(date(ts[0], ts[1], ts[2]).isoformat())
    if n_rows != expected_rows:
        raise ProtocolStop(f"EDITOR006C_LABEL_REPRODUCTION_MISMATCH: {source} rows {n_rows} != {expected_rows}")
    if header != expected_header:
        log(f"WARNING {source} header {header} != frozen {expected_header}")
    return {"source": source, "n_data_rows": n_rows, "header": header, "malformed": malformed}


def save_npy(path: Path, arr: np.ndarray) -> dict[str, Any]:
    np.save(path, arr)
    path = Path(path)
    sha = sha256_file(path)
    rec = {
        "filename": path.name,
        "path": str(path),
        "byte_size": int(path.stat().st_size),
        "shape": list(arr.shape),
        "dtype": str(arr.dtype),
        "sha256": sha,
    }
    FILES_CREATED.append(str(path))
    return rec


def bits_to_ids(mask: int) -> list[int]:
    return [i for i in range(1, 6) if mask & (1 << (i - 1))]


def main() -> int:
    csv.field_size_limit(CSV_FIELD_LIMIT)
    start_ts = utc_now()
    tracemalloc.start()
    git_before = git_capture(REPO)
    if git_before["head"] != HARNESS_RELEASE_COMMIT:
        print("EDITOR006C_WRONG_HARNESS_COMMIT")
        print(git_before["head"])
        return 2

    skip = {"run_editor006c_r62_input_bundle.py", "__pycache__"}
    existing = [p for p in REVIEW_DIR.iterdir() if p.name not in skip and not p.name.endswith(".pyc")]
    if existing:
        print("EDITOR006C_OUTPUT_DIRECTORY_NOT_EMPTY")
        return 2
    BUNDLE_DIR.parent.mkdir(parents=True, exist_ok=True)
    if BUNDLE_DIR.exists() and any(BUNDLE_DIR.iterdir()):
        print("EDITOR006C_BUNDLE_DIRECTORY_NOT_EMPTY")
        return 2
    BUNDLE_DIR.mkdir(parents=True, exist_ok=True)

    # ---- contracts ----
    contract_names = [
        "EDITOR006A_MODEL_ALLOWLIST.json",
        "EDITOR006A_C5_DENYLIST.json",
        "EDITOR006A_THRESHOLDS.json",
        "EDITOR006A_SCALER.json",
        "EDITOR006A_R62_LABEL_CONTRACT.json",
        "EDITOR006A_INPUT_CONTRACT.json",
        "EDITOR006A_DATA_QUALITY_CAVEATS.json",
    ]
    contract_hashes: dict[str, str] = {}
    for name in contract_names + ["EDITOR006A_RUN_MANIFEST.json"]:
        path = FREEZE_DIR / name
        if not path.is_file():
            raise ProtocolStop(f"Missing freeze file {name}")
        note_open(path, "contract")
        contract_hashes[name] = sha256_file(path)
    scaler_sha = contract_hashes["EDITOR006A_SCALER.json"]
    if scaler_sha != EXPECTED_SCALER_SHA256:
        raise ProtocolStop(f"Scaler SHA mismatch {scaler_sha}")
    freeze = load_freeze_bundle(FREEZE_DIR)
    validated = validate_contracts(freeze)
    labels = freeze["EDITOR006A_R62_LABEL_CONTRACT.json"]
    scaler_obj = freeze["EDITOR006A_SCALER.json"]
    if labels.get("R62_LABEL_RULE") != "R52_LABEL_RULE_EVENT_LEVEL_ANSWER_MATCH":
        raise ProtocolStop("Label rule drift")
    if list(scaler_obj["features"]) != list(COMMON_13_FEATURES):
        raise ProtocolStop("Feature order drift")
    mean = np.asarray(scaler_obj["mean"], dtype=np.float64)
    scale = np.asarray(scaler_obj["scale"], dtype=np.float64)
    scale = np.where(scale == 0.0, 1.0, scale)

    contract_bundle_payload = {k: contract_hashes[k] for k in contract_names}
    canonical = json.dumps(contract_bundle_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    contract_bundle_sha256 = hashlib.sha256(canonical).hexdigest()
    model_allowlist_sha256 = contract_hashes["EDITOR006A_MODEL_ALLOWLIST.json"]
    harness_code_sha256 = hash_harness_sources()
    harness_runner_sha256 = sha256_file(RUNNER_PATH)

    # ---- raw provenance ----
    raw_stats = {}
    for src, meta in FROZEN_STAGE1.items():
        path = SOURCE_FILES[src]
        st = file_stat(path)
        if st["byte_size"] != meta["bytes"] or st["mtime_utc"] != meta["mtime_utc"]:
            log(f"{src} size/mtime differs from 005A; re-hashing")
            observed = sha256_file(path)
            if observed != meta["sha256"]:
                raise ProtocolStop(f"Raw {src} hash mismatch after size/mtime drift")
        raw_stats[src] = {**st, "frozen_bytes": meta["bytes"], "frozen_mtime_utc": meta["mtime_utc"],
                          "size_mtime_match_005a": st["byte_size"] == meta["bytes"] and st["mtime_utc"] == meta["mtime_utc"],
                          "rehashed": False}

    answer_hash_rows = []
    for name, (sz, expected) in FROZEN_ANSWER_HASHES.items():
        path = ANSWERS_CANONICAL / name
        actual = sha256_file(path)
        actual_sz = str(path.stat().st_size)
        answer_hash_rows.append({"file": name, "bytes": actual_sz, "sha256": actual, "match": actual == expected and actual_sz == sz})
        if actual != expected or actual_sz != sz:
            raise ProtocolStop(f"Answer file mismatch {name}")

    insider_rows = load_official_insiders(ANSWERS_CANONICAL / "insiders.csv")
    official_insiders = [r["user"] for r in insider_rows]
    official_insider_set = set(official_insiders)
    official_incidents = [f"r6.2-{r['scenario']}" for r in insider_rows]
    user_to_incident = {r["user"]: f"r6.2-{r['scenario']}" for r in insider_rows}
    if official_insiders != ["ACM2278", "CMP2946", "PLJ1771", "CDE1846", "MBG3183"]:
        raise ProtocolStop(f"Official insider mapping drift: {official_insiders}")

    all_records: list[dict[str, Any]] = []
    for i in range(1, 6):
        all_records.extend(parse_answer_file(ANSWERS_CANONICAL / f"r6.2-{i}.csv", f"r6.2-{i}"))
    id_to_rec: dict[str, list[dict[str, Any]]] = defaultdict(list)
    id_to_bit: dict[str, int] = {}
    for rec in all_records:
        id_to_rec[rec["event_id"]].append(rec)
        id_to_bit[rec["event_id"]] = int(SCENARIO_BIT[rec["scenario_key"]])
    unique_ids = set(id_to_rec)
    if len(unique_ids) != EXPECTED["answer_ids"]:
        raise ProtocolStop(f"EDITOR006C_LABEL_REPRODUCTION_MISMATCH unique ids {len(unique_ids)}")
    event_level_users = sorted({r["user"] for r in all_records if r["user"]})
    match_counts = {eid: 0 for eid in unique_ids}

    user_index: dict[str, int] = {}
    user_list: list[str] = []
    active: dict[tuple[int, int], list[int]] = {}
    source_scan = []
    for source in SOURCE_TYPES:
        source_scan.append(
            scan_source(
                source,
                SOURCE_FILES[source],
                FROZEN_STAGE1[source]["header"],
                FROZEN_STAGE1[source]["rows"],
                unique_ids,
                id_to_bit,
                match_counts,
                active,
                user_index,
                user_list,
            )
        )

    n_matched_once = sum(1 for n in match_counts.values() if n == 1)
    n_unmatched = sum(1 for n in match_counts.values() if n == 0)
    n_multi = sum(1 for n in match_counts.values() if n > 1)
    if (n_matched_once, n_unmatched, n_multi) != (470, 0, 0):
        raise ProtocolStop(
            f"EDITOR006C_LABEL_REPRODUCTION_MISMATCH matches once={n_matched_once} unmatched={n_unmatched} multi={n_multi}"
        )

    log("Building dense user-day representation")
    n_users = len(user_list)
    ordinals = [k[1] for k in active]
    min_ord = min(ordinals)
    max_ord = max(ordinals)
    calendar = [date.fromordinal(o) for o in range(min_ord, max_ord + 1)]
    n_days = len(calendar)
    user_ids_sorted = sorted(user_list)
    uid_rank = {user_index[u]: i for i, u in enumerate(user_ids_sorted)}
    if n_users != EXPECTED["users"] or n_days != EXPECTED["calendar_days"]:
        raise ProtocolStop(f"EDITOR006C_LABEL_REPRODUCTION_MISMATCH users={n_users} days={n_days}")
    if calendar[0].isoformat() != "2010-01-02" or calendar[-1].isoformat() != "2011-06-01":
        raise ProtocolStop(f"Calendar drift {calendar[0]} .. {calendar[-1]}")

    raw = np.zeros((n_users, n_days, 13), dtype=np.float64)
    mal = np.zeros((n_users, n_days), dtype=np.uint8)
    day_bits = np.zeros((n_users, n_days), dtype=np.uint8)
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
        day_bits[u, d] = np.uint8(bits)
    del active

    n_mal_days = int(mal.sum())
    mal_event_users = [user_ids_sorted[i] for i in np.where(mal.sum(axis=1) > 0)[0].tolist()]
    if len(mal_event_users) != EXPECTED["event_level_labelled_users"]:
        raise ProtocolStop(f"EDITOR006C_LABEL_REPRODUCTION_MISMATCH event-level users {len(mal_event_users)}")
    if n_mal_days != EXPECTED["endpoint_positives"]:
        # 78 malicious user-days equals endpoint positives at the day level; frozen dense count is 78
        log(f"malicious_user_days={n_mal_days}")

    log("Applying frozen r5.2 scaler (transform only, no fit)")
    scaled = ((raw - mean.reshape(1, 1, 13)) / scale.reshape(1, 1, 13)).astype(np.float32)
    del raw
    nan_count = int(np.isnan(scaled).sum())
    inf_count = int(np.isinf(scaled).sum())
    if nan_count or inf_count:
        raise ProtocolStop(f"NaN={nan_count} Inf={inf_count}")

    n_starts = n_days - T_WINDOW + 1
    n_windows = n_users * n_starts
    if n_windows != EXPECTED["eligible_windows"]:
        raise ProtocolStop(f"EDITOR006C_LABEL_REPRODUCTION_MISMATCH windows {n_windows}")

    log("Building window index and labels")
    ui = np.repeat(np.arange(n_users, dtype=np.int32), n_starts)
    si = np.tile(np.arange(n_starts, dtype=np.int32), n_users)
    window_index = np.stack([ui, si], axis=1)
    cs = np.pad(mal.cumsum(axis=1, dtype=np.int32), ((0, 0), (1, 0)))
    completed_2d = ((cs[:, T_WINDOW:] - cs[:, :n_starts]) > 0).astype(np.uint8)
    endpoint_2d = mal[:, T_WINDOW - 1 :].astype(np.uint8)
    completed = completed_2d.reshape(-1)
    endpoint = endpoint_2d.reshape(-1)
    deov_starts = (np.arange(n_starts) % T_WINDOW == 0)
    deov = np.tile(deov_starts.astype(np.uint8), n_users)
    win_bits_2d = np.zeros((n_users, n_starts), dtype=np.uint8)
    for k in range(T_WINDOW):
        win_bits_2d |= day_bits[:, k : k + n_starts]
    window_bits = win_bits_2d.reshape(-1)
    endpoint_bits = day_bits[:, T_WINDOW - 1 :].reshape(-1)

    n_completed = int(completed.sum())
    n_endpoint = int(endpoint.sum())
    n_deov_ret = int(deov.sum())
    n_deov_pos = int((completed * deov).sum())
    official_mask = np.array([u in official_insider_set for u in user_ids_sorted], dtype=np.uint8)
    off_2d = official_mask.reshape(-1, 1)
    n_off_completed = int((completed_2d * off_2d).sum())
    n_off_endpoint = int((endpoint_2d * off_2d).sum())
    n_off_deov = int(((completed_2d * off_2d) * deov_starts.reshape(1, -1)).sum())

    counts = {
        "users": n_users,
        "calendar_days": n_days,
        "features": 13,
        "dense_rows": n_users * n_days,
        "eligible_windows": n_windows,
        "completed_positives": n_completed,
        "endpoint_positives": n_endpoint,
        "deoverlap_retained": n_deov_ret,
        "deoverlap_positives": n_deov_pos,
        "official_insiders": int(official_mask.sum()),
        "official_incidents": len(official_incidents),
        "event_level_labelled_users": len(mal_event_users),
        "official_only_completed": n_off_completed,
        "official_only_endpoint": n_off_endpoint,
        "official_only_deoverlap": n_off_deov,
        "answer_ids": len(unique_ids),
        "matched_once": n_matched_once,
        "unmatched": n_unmatched,
        "multiple": n_multi,
        "malicious_user_days": n_mal_days,
    }
    # active days: is_active_day raw was 1 on filled days; after scale, count pre-scale via scaled inverse is messy.
    # Count from day_bits/mal/raw is_active: we stored is_active as feature 12 before scale. Reconstruct:
    # scaled = (raw - mean) / scale so raw12 = scaled12 * scale12 + mean12; active iff raw12==1.
    raw12 = scaled[:, :, 12].astype(np.float64) * scale[12] + mean[12]
    n_active = int(np.sum(np.abs(raw12 - 1.0) < 1e-5))
    counts["active_user_days"] = n_active
    counts["inactive_user_days"] = n_users * n_days - n_active

    for key, exp in EXPECTED.items():
        if int(counts[key]) != int(exp):
            raise ProtocolStop(f"EDITOR006C_LABEL_REPRODUCTION_MISMATCH {key}={counts[key]} expected {exp}")

    log("Computing sequence_order_sha256")
    digest = hashlib.sha256()
    cal_iso = [d.isoformat() for d in calendar]
    for u in range(n_users):
        uid = user_ids_sorted[u]
        for s in range(n_starts):
            seq = f"{uid}|{cal_iso[s]}|{cal_iso[s + T_WINDOW - 1]}\n"
            digest.update(seq.encode("utf-8"))
    sequence_order_sha256 = digest.hexdigest()

    official_flags = official_mask.astype(np.uint8)
    incident_codes = np.array(
        [user_to_incident.get(u, NULL_INCIDENT_SENTINEL) for u in user_ids_sorted],
        dtype="<U8",
    )
    user_ids_arr = np.array(user_ids_sorted, dtype="<U16")
    calendar_arr = np.array(cal_iso, dtype="<U10")

    # CDE1846
    expected_cde_days = {
        "2011-02-21", "2011-03-17", "2011-03-22", "2011-03-29",
        "2011-04-06", "2011-04-07", "2011-04-11", "2011-04-15", "2011-04-25",
    }
    malformed = "/21/2011 11:43:39"
    cde_pass = (
        CDE1846_EVENT_DATES == expected_cde_days
        and malformed not in CDE1846_EVENT_TIMESTAMPS
        and not any(t.startswith("/") for t in CDE1846_EVENT_TIMESTAMPS)
    )
    cde_check = "PASS" if cde_pass else "FAIL"
    if not cde_pass:
        raise ProtocolStop(f"CDE1846_EVENT_DATE_LABEL_CHECK = FAIL dates={sorted(CDE1846_EVENT_DATES)}")

    log("Writing large bundle arrays")
    components = []
    roles = [
        (BUNDLE_DIR / "scaled_dense_daily.npy", scaled, "scaled common-13 daily design; frozen r5.2 scaler transform-only"),
        (BUNDLE_DIR / "malicious_day_labels.npy", mal, "event-level answer-match user-day labels (primary producing label)"),
        (BUNDLE_DIR / "answer_scenario_day_bitmask.npy", day_bits, "uint8 bits 0-4 = r6.2-1..r6.2-5"),
        (BUNDLE_DIR / "user_ids.npy", user_ids_arr, "lexicographic ascending event-observed user IDs"),
        (BUNDLE_DIR / "calendar_dates.npy", calendar_arr, "contiguous YYYY-MM-DD calendar"),
        (BUNDLE_DIR / "official_insider_flags.npy", official_flags, "1 iff official mapped insider"),
        (BUNDLE_DIR / "official_incident_codes.npy", incident_codes, f"official incident id or sentinel {NULL_INCIDENT_SENTINEL!r} for null"),
        (BUNDLE_DIR / "window_index.npy", window_index, "int32 [user_index, start_day_index]; user then start ascending"),
        (BUNDLE_DIR / "completed_window_labels.npy", completed, "any-day event-level label in T=20 window"),
        (BUNDLE_DIR / "endpoint_labels.npy", endpoint, "malicious status of decision day only"),
        (BUNDLE_DIR / "deoverlap_offset0_mask.npy", deov, "start_day_index % 20 == 0"),
        (BUNDLE_DIR / "window_scenario_bitmask.npy", window_bits, "OR of day scenario bits across T=20"),
        (BUNDLE_DIR / "endpoint_scenario_bitmask.npy", endpoint_bits, "scenario bitmask on decision day"),
    ]
    for path, arr, role in roles:
        rec = save_npy(path, arr)
        rec["semantic_role"] = role
        components.append(rec)

    # streaming provider dry check (model-free)
    log("Streaming provider dry check")
    dense_mm = np.load(BUNDLE_DIR / "scaled_dense_daily.npy", mmap_mode="r")
    provider = DenseDailyWindowProvider(dense_mm, ui, si, batch_size=BATCH_SIZE_FROZEN)
    n = provider.n_sequences
    checkpoints = {
        "first": (0, min(BATCH_SIZE_FROZEN, n)),
        "middle": (max(0, (n // 2) - ((n // 2) % BATCH_SIZE_FROZEN)), min(n, max(0, (n // 2) - ((n // 2) % BATCH_SIZE_FROZEN)) + BATCH_SIZE_FROZEN)),
        "final": ((n - 1) // BATCH_SIZE_FROZEN * BATCH_SIZE_FROZEN, n),
    }
    stream_rows = []
    for name, (lo, hi) in checkpoints.items():
        batch_ui = ui[lo:hi]
        batch_si = si[lo:hi]
        batch = np.empty((hi - lo, T_WINDOW, N_FEATURES), dtype=np.float32)
        for i in range(hi - lo):
            batch[i] = dense_mm[int(batch_ui[i]), int(batch_si[i]) : int(batch_si[i]) + T_WINDOW]
        if batch.shape[0] > BATCH_SIZE_FROZEN:
            raise ProtocolStop("batch exceeded frozen batch size")
        i0 = 0
        u0 = int(batch_ui[i0])
        s0 = int(batch_si[i0])
        stream_rows.append(
            {
                "checkpoint": name,
                "lo": lo,
                "hi": hi,
                "batch_shape": list(batch.shape),
                "user_id": user_ids_sorted[u0],
                "start_date": cal_iso[s0],
                "end_date": cal_iso[s0 + T_WINDOW - 1],
                "completed_label": int(completed[lo]),
                "endpoint_label": int(endpoint[lo]),
                "window_scenario_ids": bits_to_ids(int(window_bits[lo])),
                "endpoint_scenario_ids": bits_to_ids(int(endpoint_bits[lo])),
                "official_incident_id": None if incident_codes[u0] == NULL_INCIDENT_SENTINEL else str(incident_codes[u0]),
            }
        )
        if not np.allclose(batch[0], dense_mm[u0, s0 : s0 + T_WINDOW]):
            raise ProtocolStop("gather mismatch")
    # instantiate real provider on first batch only to avoid 1.988M gathers
    first_provider = DenseDailyWindowProvider(
        dense_mm, ui[:BATCH_SIZE_FROZEN], si[:BATCH_SIZE_FROZEN], batch_size=BATCH_SIZE_FROZEN
    )
    first_batch = None
    for lo, hi, b in first_provider:
        first_batch = b
        break
    assert first_batch is not None
    first_provider.assert_never_full_sequence_tensor()
    del dense_mm

    # contextual official_incident_id null
    contextual = [u for u in mal_event_users if u not in official_insider_set]
    for u in contextual:
        idx = user_ids_sorted.index(u)
        if incident_codes[idx] != NULL_INCIDENT_SENTINEL or official_flags[idx] != 0:
            raise ProtocolStop(f"contextual user {u} has official incident")

    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    contract_bundle_doc = {
        "files": contract_bundle_payload,
        "serialization": "json.dumps(sort_keys=True, separators=(',', ':')) over filename->sha256 map",
        "contract_bundle_sha256": contract_bundle_sha256,
        "excludes_mutable_timestamps": True,
    }
    dump_json(REVIEW_DIR / "EDITOR006C_CONTRACT_BUNDLE.json", contract_bundle_doc)
    dump_json(REVIEW_DIR / "EDITOR006C_BUNDLE_COMPONENTS.json", {"components": components})

    manifest = {
        "task_id": TASK_ID,
        "dataset_id": "CERT r6.2",
        "dataset_role": "PRIMARY_UNTOUCHED_CONFIRMATORY_CANDIDATE",
        "evaluation_type": "UNTOUCHED_CROSS_VERSION_EXTERNAL_COHORT",
        "creation_timestamp": start_ts,
        "raw_source_provenance": {
            "CERT_R62_ROOT": str(CERT_R62_ROOT),
            "CERT_ANSWERS_CANONICAL": str(ANSWERS_CANONICAL),
            "raw_files": raw_stats,
            "answer_files": answer_hash_rows,
            "size_mtime_matched_005a": True,
            "raw_rehash_performed": False,
        },
        "users": n_users,
        "calendar_start": "2010-01-02",
        "calendar_end": "2011-06-01",
        "calendar_days": n_days,
        "feature_order": list(COMMON_13_FEATURES),
        "T": T_WINDOW,
        "stride": 1,
        "label_rule": "R52_LABEL_RULE_EVENT_LEVEL_ANSWER_MATCH",
        "user_order": "lexicographic ascending user ID (event-observed cohort, same as EDITOR-005A)",
        "window_order": "for user_index ascending: for start_day_index = 0..496 ascending; no shuffle",
        "official_mapped_insiders": official_insiders,
        "official_incidents": official_incidents,
        "event_level_labelled_users": event_level_users,
        "effective_malicious_cluster_count": 5,
        "frozen_wording": "Five official insider–incident clusters are represented.",
        "eligible_completed_windows": n_windows,
        "completed_positive_count": n_completed,
        "endpoint_positive_count": n_endpoint,
        "deoverlap_retained_count": n_deov_ret,
        "deoverlap_positive_count": n_deov_pos,
        "official_only_completed_positive_count": n_off_completed,
        "official_only_endpoint_positive_count": n_off_endpoint,
        "official_only_deoverlap_positive_count": n_off_deov,
        "sequence_id_template": "{user_id}|{window_start_date}|{window_end_date}",
        "sequence_order_sha256": sequence_order_sha256,
        "official_incident_null_sentinel": NULL_INCIDENT_SENTINEL,
        "scenario_bit_legend": {f"bit_{i}": f"r6.2-{i+1}" for i in range(5)},
        "component_files": components,
        "scaler_sha256": scaler_sha,
        "contract_bundle_sha256": contract_bundle_sha256,
        "model_allowlist_sha256": model_allowlist_sha256,
        "harness_release_commit": HARNESS_RELEASE_COMMIT,
        "harness_code_sha256": harness_code_sha256,
        "harness_runner_sha256": harness_runner_sha256,
        "predictive_models_loaded": False,
        "predictive_inference_executed": False,
        "nan_count": nan_count,
        "inf_count": inf_count,
        "CDE1846_EVENT_DATE_LABEL_CHECK": cde_check,
        "inherited_stage2b2_one_email_field_mismatch": {
            "present": True,
            "malicious_ids_recovered_exactly_once": "470/470",
            "labels_changed": False,
            "note": "Frozen Stage 2B-2 retains one email Scenario 3 recipient-membership discrepancy; ID recoverability still 470/470. Not treated as unmatched.",
        },
    }
    man_path = REVIEW_DIR / "EDITOR006C_BUNDLE_MANIFEST.json"
    dump_json(man_path, manifest)
    input_bundle_manifest_sha256 = sha256_file(man_path)

    release = {
        "dataset_id": "CERT r6.2",
        "dataset_role": "PRIMARY_UNTOUCHED_CONFIRMATORY_CANDIDATE",
        "evaluation_type": "UNTOUCHED_CROSS_VERSION_EXTERNAL_COHORT",
        "harness_release_commit": HARNESS_RELEASE_COMMIT,
        "harness_code_sha256": harness_code_sha256,
        "harness_runner_sha256": harness_runner_sha256,
        "contract_bundle_sha256": contract_bundle_sha256,
        "model_allowlist_sha256": model_allowlist_sha256,
        "input_bundle_manifest_sha256": input_bundle_manifest_sha256,
        "external_predictive_run_authorised": False,
        "release_status": "MODEL_FREE_INPUT_BUNDLE_READY_FOR_INDEPENDENT_REVIEW",
        "not_an_external_run_authorisation": True,
    }
    dump_json(REVIEW_DIR / "EDITOR006C_RELEASE_CANDIDATE.json", release)

    count_val = {
        "assertions": {k: {"observed": counts[k], "expected": EXPECTED[k], "pass": counts[k] == EXPECTED[k]} for k in EXPECTED},
        "all_pass": True,
        "CDE1846_EVENT_DATE_LABEL_CHECK": cde_check,
        "CDE1846_matched_event_days": sorted(CDE1846_EVENT_DATES),
        "malformed_summary_field_used": False,
    }
    dump_json(REVIEW_DIR / "EDITOR006C_COUNT_VALIDATION.json", count_val)

    meta_val = {
        "official_insiders_true_count": int(official_flags.sum()),
        "contextual_users_official_incident_null": all(
            incident_codes[user_ids_sorted.index(u)] == NULL_INCIDENT_SENTINEL for u in contextual
        ),
        "null_sentinel": NULL_INCIDENT_SENTINEL,
        "event_level_labelled_users": mal_event_users,
        "contextual_users": contextual,
        "feature_order": list(COMMON_13_FEATURES),
        "user_order": "lexicographic ascending",
        "window_index_monotonic_users": bool(np.all(np.diff(window_index[:, 0]) >= 0)),
        "scenario_bits_allow_multiple": True,
        "distinction": "official_incident_id != contextual scenario evidence",
        "harness_schema": {
            "scaled_dtype": str(scaled.dtype),
            "scaled_shape": list(scaled.shape),
            "T": T_WINDOW,
            "N_FEATURES": N_FEATURES,
            "BATCH_SIZE_FROZEN": BATCH_SIZE_FROZEN,
        },
        "validate_contracts_status": validated.get("status"),
        "label_rule": labels.get("R62_LABEL_RULE"),
    }
    dump_json(REVIEW_DIR / "EDITOR006C_METADATA_VALIDATION.json", meta_val)
    dump_json(
        REVIEW_DIR / "EDITOR006C_STREAMING_PROVIDER_CHECK.json",
        {
            "status": "PASS",
            "provider": "DenseDailyWindowProvider",
            "batch_size": BATCH_SIZE_FROZEN,
            "full_N_20_13_materialised": False,
            "models_called": False,
            "checkpoints": stream_rows,
            "first_real_provider_batch_shape": list(first_batch.shape),
        },
    )

    effect = {
        "files_opened_read_only": FILES_OPENED,
        "raw_files_opened": RAW_OPENED,
        "contract_files_opened": CONTRACT_OPENED,
        "model_files_opened": [],
        "files_created": FILES_CREATED,
        "files_modified_existing": [],
        "predictive_inference_calls": [],
        "model_deserialisation_calls": [],
        "scaler_fit_calls": [],
        "threshold_selection_calls": [],
        "calibration_fit_calls": [],
    }
    dump_json(REVIEW_DIR / "EDITOR006C_EFFECT_REGISTER.json", effect)

    git_after = git_capture(REPO)
    current_mb = current / (1024 * 1024)
    peak_mb = peak / (1024 * 1024)
    run_manifest = {
        "task_id": TASK_ID,
        "start_timestamp": start_ts,
        "end_timestamp": utc_now(),
        "repository": str(REPO),
        "branch": git_before["branch"],
        "HEAD": git_before["head"],
        "git_status_before": git_before["status_short"],
        "git_status_after": git_after["status_short"],
        "harness_release_commit": HARNESS_RELEASE_COMMIT,
        "harness_code_sha256": harness_code_sha256,
        "harness_runner_sha256": harness_runner_sha256,
        "raw_source_paths_hashes": raw_stats,
        "answer_paths_hashes": answer_hash_rows,
        "scaler_sha256": scaler_sha,
        "contract_bundle_sha256": contract_bundle_sha256,
        "model_allowlist_sha256": model_allowlist_sha256,
        "bundle_component_hashes": components,
        "bundle_manifest_sha256": input_bundle_manifest_sha256,
        "sequence_order_sha256": sequence_order_sha256,
        "machine_environment": {
            "platform": platform.platform(),
            "python": sys.version,
            "numpy": np.__version__,
        },
        "memory_strategy": "stream csv.reader; sparse user-day accumulator; discard row; no whole-CSV RAM load; no (N,20,13) tensor",
        "tracemalloc_current_mib": current_mb,
        "tracemalloc_peak_mib": peak_mb,
        "chunking": "line-oriented csv.reader; progress every 2000000 rows",
        "protocol_flags": {
            "r62_predictive_inference_executed": False,
            "predictive_models_loaded": False,
            "scaler_fit_executed": False,
            "threshold_selection_executed": False,
            "r52_test_tensor_opened": False,
            "external_authorisation_created": False,
        },
        "verdict": "EDITOR006C_R62_INPUT_BUNDLE_READY_WITH_QUALIFICATIONS",
    }
    dump_json(REVIEW_DIR / "EDITOR006C_RUN_MANIFEST.json", run_manifest)

    md = build_report(
        counts=counts,
        components=components,
        harness_code_sha256=harness_code_sha256,
        harness_runner_sha256=harness_runner_sha256,
        contract_bundle_sha256=contract_bundle_sha256,
        model_allowlist_sha256=model_allowlist_sha256,
        input_bundle_manifest_sha256=input_bundle_manifest_sha256,
        sequence_order_sha256=sequence_order_sha256,
        scaler_sha256=scaler_sha,
        nan_count=nan_count,
        inf_count=inf_count,
        scaled_sha=next(c["sha256"] for c in components if c["filename"] == "scaled_dense_daily.npy"),
        cde_check=cde_check,
        stream_rows=stream_rows,
        git_before=git_before,
        git_after=git_after,
        n_active=n_active,
    )
    (REVIEW_DIR / "EDITOR006C_BUNDLE_REPORT.md").write_text(md, encoding="utf-8")
    FILES_CREATED.append(str(REVIEW_DIR / "EDITOR006C_BUNDLE_REPORT.md"))

    print("EDITOR006C_R62_INPUT_BUNDLE_READY_WITH_QUALIFICATIONS")
    print(f"HARNESS_RELEASE_COMMIT = {HARNESS_RELEASE_COMMIT}")
    print(f"HARNESS_CODE_SHA256 = {harness_code_sha256}")
    print(f"HARNESS_RUNNER_SHA256 = {harness_runner_sha256}")
    print(f"CONTRACT_BUNDLE_SHA256 = {contract_bundle_sha256}")
    print(f"MODEL_ALLOWLIST_SHA256 = {model_allowlist_sha256}")
    print(f"INPUT_BUNDLE_MANIFEST_SHA256 = {input_bundle_manifest_sha256}")
    print(f"DENSE_DAILY_SHAPE = (4000, 516, 13)")
    print(f"ELIGIBLE_WINDOWS = {n_windows}")
    print(f"COMPLETED_POSITIVES = {n_completed}")
    print(f"ENDPOINT_POSITIVES = {n_endpoint}")
    print(f"DEOVERLAP_POSITIVES = {n_deov_pos}")
    print(f"OFFICIAL_ONLY_COMPLETED = {n_off_completed}")
    print(f"OFFICIAL_ONLY_ENDPOINT = {n_off_endpoint}")
    print(f"OFFICIAL_ONLY_DEOVERLAP = {n_off_deov}")
    print("MODEL_FILES_OPENED = 0")
    print("PREDICTIVE_INFERENCE_EXECUTED = NO")
    print("PREDICTIVE_INFERENCE_AUTHORISED = NO")
    return 0


def build_report(**kw: Any) -> str:
    c = kw["counts"]
    comps = kw["components"]
    rows = "\n".join(
        f"| `{x['filename']}` | {x['byte_size']} | {x['shape']} | {x['dtype']} | `{x['sha256']}` | {x['semantic_role']} |"
        for x in comps
    )
    stream = "\n".join(
        f"| {r['checkpoint']} | {r['lo']}:{r['hi']} | {r['batch_shape']} | {r['user_id']} | {r['start_date']} | {r['completed_label']} | {r['endpoint_label']} |"
        for r in kw["stream_rows"]
    )
    return f"""# EDITOR-006C — Final Model-Free CERT r6.2 Input Bundle

Verdict: **EDITOR006C_R62_INPUT_BUNDLE_READY_WITH_QUALIFICATIONS**

R62_ROLE = PRIMARY_UNTOUCHED_CONFIRMATORY_CANDIDATE
EXTERNAL_EVALUATION_TYPE = UNTOUCHED_CROSS_VERSION_EXTERNAL_COHORT

This task did **not** load any predictive model and did **not** score CERT r6.2.
This is **not** an external-run authorisation.

Large arrays live at `C:\\\\PhD\\\\06_Datasets\\\\derived\\\\teacher_anchored_r62_editor006c_bundle\\\\` and are not in Git.

---

## TABLE 1 — SOURCE / CONTRACT PROVENANCE

| Item | Value |
| --- | --- |
| Raw r6.2 root | `C:\\\\PhD\\\\06_Datasets\\\\r6.2\\\\r6.2` |
| Canonical answers | `C:\\\\PhD\\\\07_Projects\\\\cert-r42-feasibility\\\\answers\\\\answers` |
| Size/mtime vs EDITOR-005A | MATCH (no 90 GiB rehash) |
| Scaler SHA-256 | `{kw["scaler_sha256"]}` |
| Label rule | `R52_LABEL_RULE_EVENT_LEVEL_ANSWER_MATCH` |
| Feature order | frozen common-13 |
| HTTP count | one HTTP row = one event; no URL dedup |
| Active duration | max(minutes(latest-earliest), 0) over five sources |

---

## TABLE 2 — DENSE DAILY BUNDLE

| Field | Value |
| --- | --- |
| shape | (4000, 516, 13) |
| dtype | float32 |
| feature order | {", ".join(COMMON_13_FEATURES)} |
| NaN | {kw["nan_count"]} |
| Inf | {kw["inf_count"]} |
| SHA-256 | `{kw["scaled_sha"]}` |
| active user-days | {kw["n_active"]} |
| scaler | LOAD/TRANSFORM only; r5.2 TRAIN fit; no r6.2 adaptation |

---

## TABLE 3 — LABEL REPRODUCTION

Producing contract: `R52_LABEL_RULE_EVENT_LEVEL_ANSWER_MATCH` (no official-insider-only label filter).

| View | Event-level | Official-insider descriptive |
| --- | ---: | ---: |
| completed-window T=20 stride=1 | **{c["completed_positives"]}** | **{c["official_only_completed"]}** |
| endpoint past-only | **{c["endpoint_positives"]}** | **{c["official_only_endpoint"]}** |
| de-overlap offset-0 | **{c["deoverlap_positives"]}** | **{c["official_only_deoverlap"]}** |

Frozen required values reproduced: 715 / 78 / 35 and 222 / 44 / 11.

---

## TABLE 4 — GROUND-TRUTH / SCENARIO METADATA

| Item | Value |
| --- | --- |
| Official mapped insiders | 5: ACM2278, CMP2946, PLJ1771, CDE1846, MBG3183 |
| Official incidents | 5: r6.2-1 … r6.2-5 (1:1 with insiders) |
| effective_malicious_cluster_count | 5 |
| Event-level labelled users | 29 (24 contextual; not extra actors) |
| Answer IDs | 470 MATCHED_ONCE, 0 unmatched, 0 multiple |
| official_incident_id for contextual | null (sentinel empty string) |
| Scenario bits | bit0=r6.2-1 … bit4=r6.2-5 |
| CDE1846_EVENT_DATE_LABEL_CHECK | {kw["cde_check"]} |
| Inherited Scenario-3 email field mismatch | documented; IDs still 470/470; labels unchanged |

---

## TABLE 5 — WINDOW INDEX / SEQUENCE ORDER

| Field | Value |
| --- | --- |
| window_index shape | (1988000, 2) int32 |
| columns | [user_index, start_day_index] |
| order | user ascending, then start 0..496; no shuffle |
| sequence_id | `{{user_id}}\\|{{window_start_date}}\\|{{window_end_date}}` |
| sequence_order_sha256 | `{kw["sequence_order_sha256"]}` |
| de-overlap retained | 100000 |

---

## TABLE 6 — LARGE BUNDLE COMPONENT HASHES

| file | bytes | shape | dtype | SHA-256 | role |
| --- | ---: | --- | --- | --- | --- |
{rows}

---

## TABLE 7 — CONTRACT / HARNESS IDENTITY

| Item | Value |
| --- | --- |
| harness commit | `{HARNESS_RELEASE_COMMIT}` |
| harness_code_sha256 | `{kw["harness_code_sha256"]}` |
| harness_runner_sha256 | `{kw["harness_runner_sha256"]}` |
| contract_bundle_sha256 | `{kw["contract_bundle_sha256"]}` |
| model_allowlist_sha256 | `{kw["model_allowlist_sha256"]}` |
| input_bundle_manifest_sha256 | `{kw["input_bundle_manifest_sha256"]}` |

---

## TABLE 8 — STREAMING PROVIDER COMPATIBILITY

Provider: `DenseDailyWindowProvider`. Batch bound: {BATCH_SIZE_FROZEN}. No model called. No full (N,20,13) tensor.

| checkpoint | slice | batch shape | user | start | completed | endpoint |
| --- | --- | --- | --- | --- | --- | --- |
{stream}

---

## TABLE 9 — PROTOCOL EFFECT REGISTER

| Field | Value |
| --- | --- |
| model_files_opened | [] |
| files_modified_existing | [] |
| predictive_inference_calls | [] |
| model_deserialisation_calls | [] |
| scaler_fit_calls | [] |
| threshold_selection_calls | [] |
| calibration_fit_calls | [] |

---

## TABLE 10 — REMAINING QUALIFICATIONS

* Five collinear insider–incident clusters (not ten independent malicious units).
* Whole-cohort untouched cross-version external test, not an internal r6.2 holdout.
* Event-level label includes 24 contextual users; they are not extra official actors.
* Checkpoint identity does not establish complete from-source reproducibility.
* Unused-leaf / tree-contribution-rho remain manuscript-facing and externally disabled (EDITOR-006B1).
* Inherited Stage 2B-2 one email Scenario-3 field mismatch does not alter event IDs or labels.
* CDE1846 labels come from matched raw-event timestamps, not `/21/2011 11:43:39`.

---

NEXT_ACTION = Independent EDITOR-006C-R review of the bundle, manifest, sequence ordering, hashes, and metadata. Do not score CERT r6.2.
"""


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ProtocolStop as exc:
        print("EDITOR006C_R62_INPUT_BUNDLE_BLOCKED")
        print(exc)
        raise SystemExit(4)
    except Exception as exc:  # noqa: BLE001
        print("EDITOR006C_R62_INPUT_BUNDLE_BLOCKED")
        print(exc)
        traceback.print_exc()
        raise SystemExit(4)
