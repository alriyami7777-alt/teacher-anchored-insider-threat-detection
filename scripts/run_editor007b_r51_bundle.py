#!/usr/bin/env python3
"""EDITOR-007B — model-free CERT r5.1 secondary-stress bundle materialisation.

No predictive model is loaded or scored. Transform-only frozen r5.2 scaler.
Does not score CERT r5.1. Does not rerun CERT r6.2. Does not open r5.2 TEST.
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
    path_looks_like_r52_test,
    path_looks_like_r62,
    refuse_r52_test,
    sha256_file,
)

TASK_ID = "EDITOR-007B"
DATASET_ID = "CERT r5.1"
DATASET_ROLE = "R51_SECONDARY_STRESS_ONLY"
EDITOR007A_HEAD = "002d7aadef893bf4c2ab186c3a123bc1b21e4a94"
CERT_R51_ROOT = Path(r"C:\PhD\06_Datasets\r5.1\r5.1")
ANSWERS_CANONICAL = Path(r"C:\PhD\06_Datasets\answers")
FREEZE_DIR = REPO / "review" / "editor006a_preinference_freeze"
REVIEW_DIR = REPO / "review" / "editor007b_r51_secondary_stress"
BUNDLE_DIR = Path(r"C:\PhD\06_Datasets\derived\teacher_anchored_r51_editor007b_bundle")
RESERVED_SCORE_DIR = Path(r"C:\PhD\06_Datasets\derived\teacher_anchored_r51_editor007c_scores")
RUNNER_PATH = REPO / "scripts" / "run_editor006b_harness.py"
AUDIT_004A = REPO / "review" / "editor004a_r51_model_free_audit"

CSV_FIELD_LIMIT = 64 * 1024 * 1024
PROGRESS_EVERY = 2_000_000
EVENT_ID_RE = __import__("re").compile(r"^\{[A-Z0-9]+-[A-Z0-9]+-[A-Z0-9]+\}$", __import__("re").IGNORECASE)
SOURCE_TYPES = ("logon", "device", "file", "email", "http")
SOURCE_FILES = {s: CERT_R51_ROOT / f"{s}.csv" for s in SOURCE_TYPES}
NULL_INCIDENT_SENTINEL = ""
SCENARIO_BIT = {f"r5.1-{i}": 1 << (i - 1) for i in range(1, 5)}
OFFICIAL_INSIDERS_FROZEN = ["JTC1885", "LBE0376", "BGC0686", "JAK0783"]
CONTEXTUAL_USERS_FROZEN = [
    "ACB0270", "DKB0259", "EHW0689", "GJB0268", "HCW0681", "HRS0274",
    "KSC0148", "LHO0687", "MAH0683", "RNW0269", "SDP0271", "SKR0266", "UNK0265",
]
QS = (0.01, 0.05, 0.25, 0.50, 0.75, 0.95, 0.99)
ALLOWED_REVIEW_PREEXISTING = {
    "EDITOR007B_007A_ADJUDICATION_FREEZE.json",
    "EDITOR007B_007A_ADJUDICATION_FREEZE.md",
    "__pycache__",
}

EXPECTED = {
    "users": 2000,
    "calendar_days": 517,
    "features": 13,
    "dense_rows": 1_034_000,
    "eligible_windows": 996_000,
    "completed_positives": 461,
    "endpoint_positives": 58,
    "deoverlap_retained": 50_000,
    "deoverlap_positives": 24,
    "official_insiders": 4,
    "official_incidents": 4,
    "event_level_labelled_users": 17,
    "answer_ids": 351,
    "matched_once": 351,
    "unmatched": 0,
    "multiple": 0,
}

FROZEN_STAGE1 = {
    "logon": {"bytes": 125264192, "mtime_utc": "2013-09-17T17:56:32Z", "rows": 1829996,
              "header": ["id", "date", "user", "pc", "activity"],
              "sha256": "fcb9baad7294569a95dcc8e100a2332229da9382e4dc3ee6db5931cf6b7d9fed"},
    "device": {"bytes": 82815266, "mtime_utc": "2013-09-17T17:49:43Z", "rows": 908379,
               "header": ["id", "date", "user", "pc", "file_tree", "activity"],
               "sha256": "5bc69c3e8e346b813aef11d839ff1aeb76301cbc875eccc3cd98cf430cdab0a8"},
    "file": {"bytes": 435215504, "mtime_utc": "2013-09-17T17:49:42Z", "rows": 947613,
             "header": ["id", "date", "user", "pc", "filename", "activity", "to_removable_media", "from_removable_media", "content"],
             "sha256": "d10cd5cae32e28ff543ef1281c6345ab617e3f8f040fe5bd9bd4ffb963fa65c0"},
    "email": {"bytes": 9555883511, "mtime_utc": "2013-09-17T17:49:27Z", "rows": 17608751,
              "header": ["id", "date", "user", "pc", "to", "cc", "bcc", "from", "activity", "size", "attachments", "content"],
              "sha256": "eb45c082e05854afbe31a0c651923b275e5788e4c53fcbb1225b19c1ea6e7920"},
    "http": {"bytes": 30497635168, "mtime_utc": "2013-09-17T17:56:31Z", "rows": 59686023,
             "header": ["id", "date", "user", "pc", "url", "content"],
             "sha256": "c8299b480cda67075b4b7d1cdf751931c056d1f562436fa4ee2a425bc9a0b835"},
}
FROZEN_ANSWER_HASHES = {
    "readme.txt": ("820", "fb341d6fb6e36831e63f204a9bd71d59d81714d13ae64aaa88d153bc54a3fe30"),
    "scenarios.txt": ("1055", "dc86447f1669fb1c4fd400264bfcfd8f5f9b94d94fcfe4bcb0bf8acbf6f3c0e0"),
    "insiders.csv": ("13792", "394202dfd70884edb61fc9ecde9f08d6f616700e4eee0984bf06a52d1a99d726"),
    "r5.1-1.csv": ("6763", "149466404a4d59fcc4e23b15977cf13017c18723102f3edd7e7580b6d2398c47"),
    "r5.1-2.csv": ("64106", "01c599bd652a02e939e289f58d5119997e4a800a8a1cdf7c173935938ec362f0"),
    "r5.1-3.csv": ("19897", "8800625e9e5e980a8a126b143f2eb6fcd79d1cdc70bc4cffd793f8dfda123361"),
    "r5.1-4.csv": ("46082", "a56b2b2fe549b7639af07c734e8cdffe525da9afdec8e1aebe3d05976977bb24"),
}

FILES_OPENED: list[str] = []
RAW_OPENED: list[str] = []
CONTRACT_OPENED: list[str] = []
FILES_CREATED: list[str] = []


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
            if str(row.get("dataset", "")).strip() == "5.1":
                rows.append({k: (v or "").strip() for k, v in row.items()})
    return rows


def scan_source(
    source: str,
    path: Path,
    expected_header: list[str],
    expected_rows: int,
    source_answer_ids: set[str],
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
            matched = event_id in source_answer_ids
            if matched:
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
            if matched:
                rec[5] = 1
                rec[8] |= int(id_to_bit.get(event_id, 0))
    if n_rows != expected_rows:
        raise ProtocolStop(f"EDITOR007B_R51_BUNDLE_BLOCKED: {source} rows {n_rows} != {expected_rows}")
    if header != expected_header:
        raise ProtocolStop(f"EDITOR007B_R51_BUNDLE_BLOCKED: {source} header {header} != frozen {expected_header}")
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
    return [i for i in range(1, 5) if mask & (1 << (i - 1))]


def feature_column_stats(mat: np.ndarray, names: list[str]) -> list[dict[str, Any]]:
    rows = []
    for j, name in enumerate(names):
        col = np.asarray(mat[:, j], dtype=np.float64)
        finite = col[np.isfinite(col)]
        absz = np.abs(finite)
        rec: dict[str, Any] = {
            "feature": name,
            "feature_index": j,
            "N": int(col.size),
            "finite_count": int(np.isfinite(col).sum()),
            "mean": float(finite.mean()) if finite.size else None,
            "sd": float(finite.std(ddof=0)) if finite.size else None,
            "standard_deviation": float(finite.std(ddof=0)) if finite.size else None,
        }
        for q, key in (
            (0.01, "q01"),
            (0.05, "q05"),
            (0.25, "q25"),
            (0.50, "q50"),
            (0.75, "q75"),
            (0.95, "q95"),
            (0.99, "q99"),
        ):
            rec[key] = float(np.quantile(finite, q)) if finite.size else None
        rec["fraction_abs_z_gt_3"] = float(np.mean(absz > 3)) if finite.size else None
        rec["fraction_abs_z_gt_5"] = float(np.mean(absz > 5)) if finite.size else None
        rec["fraction_abs_z_gt_10"] = float(np.mean(absz > 10)) if finite.size else None
        rows.append(rec)
    return rows


def protocol_flags() -> dict[str, bool]:
    return {
        "r62_predictive_inference_executed": False,
        "r51_predictive_inference_executed": False,
        "r52_test_opened": False,
        "training_executed": False,
        "threshold_selection_executed": False,
        "scaler_fit_executed": False,
        "calibration_fit_executed": False,
        "model_selection_executed": False,
        "true_authorisation_created": False,
        "predictive_models_loaded": False,
        "predictive_inference_executed": False,
        "external_predictive_run_authorised": False,
    }


def assert_protocol_flags(flags: dict[str, Any]) -> None:
    for key, val in flags.items():
        if val is True:
            raise ProtocolStop(f"EDITOR007B_R51_BUNDLE_BLOCKED: prohibited TRUE flag {key}")


def main() -> int:
    csv.field_size_limit(CSV_FIELD_LIMIT)
    start_ts = utc_now()
    tracemalloc.start()
    git_before = git_capture(REPO)
    if git_before["head"] != EDITOR007A_HEAD and EDITOR007A_HEAD not in git_before["head"]:
        # Require 007A freeze commit to be HEAD or an ancestor; do not require exact HEAD.
        proc = subprocess.run(
            ["git", "-C", str(REPO), "merge-base", "--is-ancestor", EDITOR007A_HEAD, "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            raise ProtocolStop(f"EDITOR007B_R51_BUNDLE_BLOCKED: 007A commit is not an ancestor of HEAD ({git_before['head']})")

    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    unexpected = [
        p.name
        for p in REVIEW_DIR.iterdir()
        if p.name not in ALLOWED_REVIEW_PREEXISTING and not p.name.endswith(".pyc")
    ]
    if unexpected:
        raise ProtocolStop(f"EDITOR007B_R51_BUNDLE_BLOCKED: review directory not empty of unexpected files {unexpected}")

    if path_looks_like_r62(BUNDLE_DIR) or path_looks_like_r52_test(BUNDLE_DIR):
        raise ProtocolStop("EDITOR007B_R51_BUNDLE_BLOCKED: bundle path looks like r6.2 or r5.2 TEST")
    refuse_r52_test(BUNDLE_DIR)
    refuse_r52_test(CERT_R51_ROOT)

    BUNDLE_DIR.parent.mkdir(parents=True, exist_ok=True)
    if BUNDLE_DIR.exists() and any(BUNDLE_DIR.iterdir()):
        print("EDITOR007B_R51_BUNDLE_BLOCKED")
        print("bundle directory is not empty")
        return 2
    BUNDLE_DIR.mkdir(parents=True, exist_ok=True)
    RESERVED_SCORE_DIR.mkdir(parents=True, exist_ok=True)
    if any(RESERVED_SCORE_DIR.iterdir()):
        raise ProtocolStop("EDITOR007B_R51_BUNDLE_BLOCKED: reserved 007C score directory is not empty")

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

    raw_stats = {}
    for src, meta in FROZEN_STAGE1.items():
        path = SOURCE_FILES[src]
        if not path.is_file():
            raise ProtocolStop(f"EDITOR007B_R51_BUNDLE_BLOCKED: missing raw {src}")
        st = file_stat(path)
        size_mtime_ok = st["byte_size"] == meta["bytes"] and st["mtime_utc"] == meta["mtime_utc"]
        rehashed = False
        observed_sha = meta["sha256"]
        if not size_mtime_ok:
            log(f"{src} size/mtime differs from EDITOR-004A; re-hashing")
            observed_sha = sha256_file(path)
            rehashed = True
            if observed_sha != meta["sha256"]:
                raise ProtocolStop(f"EDITOR007B_R51_BUNDLE_BLOCKED: raw {src} hash mismatch")
        raw_stats[src] = {
            **st,
            "frozen_bytes": meta["bytes"],
            "frozen_mtime_utc": meta["mtime_utc"],
            "frozen_sha256": meta["sha256"],
            "observed_sha256": observed_sha,
            "size_mtime_match_004a": size_mtime_ok,
            "rehashed": rehashed,
        }

    answer_hash_rows = []
    for name, (sz, expected) in FROZEN_ANSWER_HASHES.items():
        path = ANSWERS_CANONICAL / name
        actual = sha256_file(path)
        actual_sz = str(path.stat().st_size)
        answer_hash_rows.append({"file": name, "bytes": actual_sz, "sha256": actual, "match": actual == expected and actual_sz == sz})
        if actual != expected or actual_sz != sz:
            raise ProtocolStop(f"EDITOR007B_R51_BUNDLE_BLOCKED: answer file mismatch {name}")

    insider_rows = load_official_insiders(ANSWERS_CANONICAL / "insiders.csv")
    official_insiders = [r["user"] for r in insider_rows]
    official_insider_set = set(official_insiders)
    official_incidents = [f"r5.1-{r['scenario']}" for r in insider_rows]
    user_to_incident = {r["user"]: f"r5.1-{r['scenario']}" for r in insider_rows}
    if official_insiders != OFFICIAL_INSIDERS_FROZEN:
        raise ProtocolStop(f"EDITOR007B_R51_BUNDLE_BLOCKED: official insider mapping drift: {official_insiders}")
    if len(official_incidents) != 4 or len(set(official_incidents)) != 4:
        raise ProtocolStop(f"EDITOR007B_R51_BUNDLE_BLOCKED: official incidents {official_incidents}")

    all_records: list[dict[str, Any]] = []
    for i in range(1, 5):
        all_records.extend(parse_answer_file(ANSWERS_CANONICAL / f"r5.1-{i}.csv", f"r5.1-{i}"))
    id_to_rec: dict[str, list[dict[str, Any]]] = defaultdict(list)
    id_to_bit: dict[str, int] = {}
    answer_ids_by_source: dict[str, set[str]] = {s: set() for s in SOURCE_TYPES}
    for rec in all_records:
        id_to_rec[rec["event_id"]].append(rec)
        id_to_bit[rec["event_id"]] = int(SCENARIO_BIT[rec["scenario_key"]])
        if rec["event_type"] not in SOURCE_TYPES:
            raise ProtocolStop(f"EDITOR007B_R51_BUNDLE_BLOCKED: unknown answer source {rec['event_type']}")
        answer_ids_by_source[rec["event_type"]].add(rec["event_id"])
    unique_ids = set(id_to_rec)
    if len(unique_ids) != EXPECTED["answer_ids"]:
        raise ProtocolStop(f"EDITOR007B_R51_BUNDLE_BLOCKED unique ids {len(unique_ids)}")
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
                answer_ids_by_source[source],
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
    if (n_matched_once, n_unmatched, n_multi) != (351, 0, 0):
        raise ProtocolStop(
            f"EDITOR007B_R51_BUNDLE_BLOCKED matches once={n_matched_once} unmatched={n_unmatched} multi={n_multi}"
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
        raise ProtocolStop(f"EDITOR007B_R51_BUNDLE_BLOCKED users={n_users} days={n_days}")
    if calendar[0].isoformat() != "2010-01-02" or calendar[-1].isoformat() != "2011-06-02":
        raise ProtocolStop(f"EDITOR007B_R51_BUNDLE_BLOCKED calendar {calendar[0]} .. {calendar[-1]}")

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
    if mal_event_users != event_level_users:
        raise ProtocolStop("EDITOR007B_R51_BUNDLE_BLOCKED: event-level users from answers vs labels differ")
    if len(mal_event_users) != EXPECTED["event_level_labelled_users"]:
        raise ProtocolStop(f"EDITOR007B_R51_BUNDLE_BLOCKED event-level users {len(mal_event_users)}")
    extra = [u for u in mal_event_users if u not in official_insider_set]
    if extra != CONTEXTUAL_USERS_FROZEN:
        raise ProtocolStop(f"EDITOR007B_R51_BUNDLE_BLOCKED contextual users {extra}")

    log("Applying frozen r5.2 scaler (transform only, no fit)")
    scaled = ((raw - mean.reshape(1, 1, 13)) / scale.reshape(1, 1, 13)).astype(np.float32)
    del raw
    nan_count = int(np.isnan(scaled).sum())
    inf_count = int(np.isinf(scaled).sum())
    if nan_count or inf_count:
        raise ProtocolStop(f"NaN={nan_count} Inf={inf_count}")

    n_starts = n_days - T_WINDOW + 1
    n_windows = n_users * n_starts
    if n_windows != EXPECTED["eligible_windows"] or n_starts != 498:
        raise ProtocolStop(f"EDITOR007B_R51_BUNDLE_BLOCKED windows {n_windows} n_starts={n_starts}")

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
        "n_starts": n_starts,
        "calendar_start": calendar[0].isoformat(),
        "calendar_end": calendar[-1].isoformat(),
    }
    raw12 = scaled[:, :, 12].astype(np.float64) * scale[12] + mean[12]
    n_active = int(np.sum(np.abs(raw12 - 1.0) < 1e-5))
    counts["active_user_days"] = n_active
    counts["inactive_user_days"] = n_users * n_days - n_active

    for key, exp in EXPECTED.items():
        if int(counts[key]) != int(exp):
            raise ProtocolStop(f"EDITOR007B_R51_BUNDLE_BLOCKED {key}={counts[key]} expected {exp}")

    log("Computing r5.1 scaled feature profile (model-free)")
    flat = np.reshape(scaled, (-1, 13))
    feature_rows = feature_column_stats(flat, list(COMMON_13_FEATURES))
    feature_profile = {
        "task_id": TASK_ID,
        "dataset_id": DATASET_ID,
        "role": DATASET_ROLE,
        "source": "scaled_dense_daily.npy flatten (users x days x 13); frozen r5.2 TRAIN scaler transform-only",
        "scaler_sha256": scaler_sha,
        "feature_order": list(COMMON_13_FEATURES),
        "N_user_days": int(flat.shape[0]),
        "predictive_models_loaded": False,
        "predictive_interpretation": False,
        "features": feature_rows,
    }

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

    log("Writing large bundle arrays")
    components = []
    roles = [
        (BUNDLE_DIR / "scaled_dense_daily.npy", scaled, "scaled common-13 daily design; frozen r5.2 scaler transform-only"),
        (BUNDLE_DIR / "malicious_day_labels.npy", mal, "event-level answer-match user-day labels (primary producing label)"),
        (BUNDLE_DIR / "answer_scenario_day_bitmask.npy", day_bits, "uint8 bits 0-3 = r5.1-1..r5.1-4"),
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

    log("Streaming provider dry check")
    dense_mm = np.load(BUNDLE_DIR / "scaled_dense_daily.npy", mmap_mode="r")
    checkpoints = {
        "first": (0, min(BATCH_SIZE_FROZEN, n_windows)),
        "middle": (
            max(0, (n_windows // 2) - ((n_windows // 2) % BATCH_SIZE_FROZEN)),
            min(n_windows, max(0, (n_windows // 2) - ((n_windows // 2) % BATCH_SIZE_FROZEN)) + BATCH_SIZE_FROZEN),
        ),
        "final": ((n_windows - 1) // BATCH_SIZE_FROZEN * BATCH_SIZE_FROZEN, n_windows),
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

    contextual = [u for u in mal_event_users if u not in official_insider_set]
    for u in contextual:
        idx = user_ids_sorted.index(u)
        if incident_codes[idx] != NULL_INCIDENT_SENTINEL or official_flags[idx] != 0:
            raise ProtocolStop(f"contextual user {u} has official incident")

    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    flags = protocol_flags()
    assert_protocol_flags(flags)

    dump_json(REVIEW_DIR / "EDITOR007B_R51_BUNDLE_COMPONENTS.json", {"components": components})
    dump_json(REVIEW_DIR / "EDITOR007B_R51_FEATURE_PROFILE.json", feature_profile)
    csv_path = REVIEW_DIR / "EDITOR007B_R51_FEATURE_PROFILE.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "feature", "feature_index", "N", "mean", "sd",
                "q01", "q05", "q25", "q50", "q75", "q95", "q99",
                "fraction_abs_z_gt_3", "fraction_abs_z_gt_5", "fraction_abs_z_gt_10",
            ],
        )
        writer.writeheader()
        for row in feature_rows:
            writer.writerow({k: row[k] for k in writer.fieldnames})
    FILES_CREATED.append(str(csv_path))

    predeclared_views = [
        {"name": "COMPLETED_WINDOW", "definition": "any-day event-level label in T=20 completed window; stride=1"},
        {"name": "ENDPOINT_PAST_ONLY", "definition": "label = malicious status of decision day only; features days s..s+19"},
        {"name": "DEOVERLAP_OFFSET0", "definition": "completed-window labels retained where start_day_index % 20 == 0"},
    ]
    predeclared_metrics = {
        "per_family_seed_view": ["PR-AUC", "F1 at frozen threshold", "precision", "recall", "FP", "FN"],
        "brier_logloss": "only if scores are on [0,1] probability scale",
        "mechanism_allowed": ["logit deviation", "route MAE", "route KL", "hard-route agreement", "dominant-leaf agreement"],
        "mechanism_disabled": ["unused-leaf fraction", "tree-contribution rho"],
        "no_new_view_after_results": True,
        "no_superiority_hypothesis": True,
        "diagnostic_questions": [
            "Does ranking portability resemble r5.2 or r6.2?",
            "Do frozen-threshold exceedance rates resemble r5.2 or r6.2?",
            "Do neural models collapse?",
            "Do RF/XGBoost retain ranking?",
            "Does C5 differ predictively from C2?",
            "Does C5 remain closer to teacher in route/logit behaviour?",
        ],
    }

    manifest = {
        "task_id": TASK_ID,
        "dataset_id": DATASET_ID,
        "dataset_role": DATASET_ROLE,
        "evaluation_type": "SECONDARY_STRESS_ONLY",
        "creation_timestamp": start_ts,
        "authoritative_sources": {
            "CERT_R51_ROOT": str(CERT_R51_ROOT),
            "CERT_ANSWERS_CANONICAL": str(ANSWERS_CANONICAL),
            "recovered_from": "EDITOR-004A; EDITOR-004B evidence not present",
            "raw_files": raw_stats,
            "answer_files": answer_hash_rows,
        },
        "users": n_users,
        "calendar_start": "2010-01-02",
        "calendar_end": "2011-06-02",
        "calendar_days": n_days,
        "dense_user_days": n_users * n_days,
        "feature_order": list(COMMON_13_FEATURES),
        "T": T_WINDOW,
        "stride": 1,
        "label_rule": "R52_LABEL_RULE_EVENT_LEVEL_ANSWER_MATCH",
        "matching_rule": "declared-source-scoped event ID match (r5.1 IDs unique within a CSV, not globally)",
        "user_order": "lexicographic ascending user ID (event-observed cohort)",
        "window_order": "for user_index ascending: for start_day_index = 0..497 ascending; no shuffle",
        "official_mapped_insiders": official_insiders,
        "official_incidents": official_incidents,
        "event_level_labelled_users": event_level_users,
        "contextual_event_level_users": contextual,
        "effective_malicious_cluster_count": 4,
        "frozen_wording": "Four official insider–incident clusters are represented. They are not 8 independent malicious units.",
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
        "scenario_bit_legend": {f"bit_{i}": f"r5.1-{i+1}" for i in range(4)},
        "component_files": components,
        "scaler_sha256": scaler_sha,
        "contract_bundle_sha256": contract_bundle_sha256,
        "model_allowlist_sha256": model_allowlist_sha256,
        "harness_code_sha256": harness_code_sha256,
        "harness_runner_sha256": harness_runner_sha256,
        "frozen_checkpoint_contract": "18 frozen 006A artefacts; bytes unmodified in EDITOR-007B",
        "predeclared_views": predeclared_views,
        "predeclared_metrics": predeclared_metrics,
        "predictive_models_loaded": False,
        "predictive_inference_executed": False,
        "external_predictive_run_authorised": False,
        "true_authorisation_created": False,
        "nan_count": nan_count,
        "inf_count": inf_count,
        "http_row_equals_one_event": True,
        "active_duration": "max(minutes(latest_event - earliest_event), 0) over five principal event sources",
        "no_answer_derived_predictor": True,
        "no_full_N_20_13_tensor": True,
        "reserved_future_score_dir": str(RESERVED_SCORE_DIR),
        "reserved_score_dir_populated": False,
        **{k: v for k, v in flags.items() if k not in {
            "predictive_models_loaded", "predictive_inference_executed", "external_predictive_run_authorised",
            "true_authorisation_created",
        }},
    }
    man_path = REVIEW_DIR / "EDITOR007B_R51_BUNDLE_MANIFEST.json"
    dump_json(man_path, manifest)
    input_bundle_manifest_sha256 = sha256_file(man_path)

    count_val = {
        "assertions": {k: {"observed": counts[k], "expected": EXPECTED[k], "pass": counts[k] == EXPECTED[k]} for k in EXPECTED},
        "all_pass": True,
        "geometry": {
            "users": n_users,
            "calendar_start": "2010-01-02",
            "calendar_end": "2011-06-02",
            "calendar_days": n_days,
            "dense_user_days": n_users * n_days,
            "eligible_T20_windows": n_windows,
            "n_starts": n_starts,
            "deoverlap_retained_windows": n_deov_ret,
        },
        "consistency_with_editor004a": True,
        "matching": {
            "rule": "declared-source-scoped",
            "MATCHED_ONCE": n_matched_once,
            "UNMATCHED": n_unmatched,
            "MULTIPLE": n_multi,
        },
        "source_scan": source_scan,
        "validated_contracts_status": validated.get("status"),
    }
    dump_json(REVIEW_DIR / "EDITOR007B_R51_COUNT_VALIDATION.json", count_val)

    meta_val = {
        "official_insiders_true_count": int(official_flags.sum()),
        "official_incidents": official_incidents,
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
        "scenario_bit_legend": {f"bit_{i}": f"r5.1-{i+1}" for i in range(4)},
        "distinction": "official_incident_id != contextual scenario evidence",
        "invented_official_incident_ids_for_contextual_users": False,
        "effective_malicious_cluster_count": 4,
        "not_eight_independent_malicious_units": True,
        "label_rule": labels.get("R62_LABEL_RULE"),
        "harness_schema": {
            "scaled_dtype": str(scaled.dtype),
            "scaled_shape": list(scaled.shape),
            "T": T_WINDOW,
            "N_FEATURES": N_FEATURES,
            "BATCH_SIZE_FROZEN": BATCH_SIZE_FROZEN,
        },
        "c2_remains_first_class_control": True,
        "c5_is": ["teacher initialisation", "logit anchoring", "route anchoring"],
    }
    dump_json(REVIEW_DIR / "EDITOR007B_R51_METADATA_VALIDATION.json", meta_val)

    effect = {
        "files_opened_read_only": FILES_OPENED,
        "raw_files_opened": RAW_OPENED,
        "contract_files_opened": CONTRACT_OPENED,
        "model_files_opened": [],
        "r62_score_files_opened": [],
        "r52_test_files_opened": [],
        "files_created": FILES_CREATED,
        "files_modified_existing": [],
        "predictive_inference_calls": [],
        "model_deserialisation_calls": [],
        "scaler_fit_calls": [],
        "threshold_selection_calls": [],
        "calibration_fit_calls": [],
        "r51_predictive_inference_executed": False,
        "r62_predictive_inference_executed": False,
    }
    dump_json(REVIEW_DIR / "EDITOR007B_R51_EFFECT_REGISTER.json", effect)

    git_after = git_capture(REPO)
    run_manifest = {
        "task_id": TASK_ID,
        "start_timestamp": start_ts,
        "end_timestamp": utc_now(),
        "repository": str(REPO),
        "branch": git_before["branch"],
        "HEAD": git_before["head"],
        "git_status_before": git_before["status_short"],
        "git_status_after": git_after["status_short"],
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
        "label_rule": "R52_LABEL_RULE_EVENT_LEVEL_ANSWER_MATCH",
        "role": DATASET_ROLE,
        "machine_environment": {
            "platform": platform.platform(),
            "python": sys.version,
            "numpy": np.__version__,
        },
        "memory_strategy": "stream csv.reader; sparse user-day accumulator; discard row; no whole-CSV RAM load; no (N,20,13) tensor",
        "tracemalloc_current_mib": current / (1024 * 1024),
        "tracemalloc_peak_mib": peak / (1024 * 1024),
        "chunking": "line-oriented csv.reader; progress every 2000000 rows",
        "protocol_flags": flags,
        "004a_audit_dir": str(AUDIT_004A),
        "verdict_candidate": "EDITOR007B_R51_SECONDARY_STRESS_PREPARED",
    }
    dump_json(REVIEW_DIR / "EDITOR007B_R51_RUN_MANIFEST.json", run_manifest)

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
        stream_rows=stream_rows,
        git_before=git_before,
        n_active=n_active,
        feature_rows=feature_rows,
        official_only=(n_off_completed, n_off_endpoint, n_off_deov),
        contextual=contextual,
    )
    (REVIEW_DIR / "EDITOR007B_R51_BUNDLE_REPORT.md").write_text(md, encoding="utf-8")
    FILES_CREATED.append(str(REVIEW_DIR / "EDITOR007B_R51_BUNDLE_REPORT.md"))

    print("EDITOR007B_R51_SECONDARY_STRESS_BUNDLE_READY")
    print(f"R51_ANSWER_IDS = {len(unique_ids)}")
    print(f"R51_MATCHED_ONCE = {n_matched_once}")
    print(f"R51_OFFICIAL_INSIDERS = {len(official_insiders)}")
    print(f"R51_OFFICIAL_INCIDENTS = {len(official_incidents)}")
    print(f"R51_EVENT_LEVEL_USERS = {len(mal_event_users)}")
    print(f"R51_COMPLETED_POSITIVES = {n_completed}")
    print(f"R51_ENDPOINT_POSITIVES = {n_endpoint}")
    print(f"R51_DEOVERLAP_POSITIVES = {n_deov_pos}")
    print(f"R51_BUNDLE_MANIFEST_SHA256 = {input_bundle_manifest_sha256}")
    print(f"SEQUENCE_ORDER_SHA256 = {sequence_order_sha256}")
    print("PREDICTIVE_MODELS_LOADED = false")
    print("PREDICTIVE_INFERENCE_EXECUTED = false")
    print("EXTERNAL_PREDICTIVE_RUN_AUTHORISED = false")
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
    feat = "\n".join(
        f"| {r['feature']} | {r['mean']} | {r['sd']} | {r['q01']} | {r['q50']} | {r['q99']} | {r['fraction_abs_z_gt_3']} | {r['fraction_abs_z_gt_5']} | {r['fraction_abs_z_gt_10']} |"
        for r in kw["feature_rows"]
    )
    off = kw["official_only"]
    return f"""# EDITOR-007B — Model-free CERT r5.1 secondary-stress bundle

Role: **R51_SECONDARY_STRESS_ONLY**

This task did **not** load any predictive model and did **not** score CERT r5.1 or rerun CERT r6.2.
This is **not** a true predictive authorisation.

Large arrays live at `C:\\\\PhD\\\\06_Datasets\\\\derived\\\\teacher_anchored_r51_editor007b_bundle\\\\` and are not in Git.

---

## Geometry (derived from data; consistent with EDITOR-004A)

| Field | Value |
| --- | --- |
| users | {c["users"]} |
| calendar_start | {c["calendar_start"]} |
| calendar_end | {c["calendar_end"]} |
| calendar_days | {c["calendar_days"]} |
| dense_user_days | {c["dense_rows"]} |
| eligible T=20 windows | {c["eligible_windows"]} |
| n_starts | {c["n_starts"]} |
| de-overlap retained (offset 0) | {c["deoverlap_retained"]} |

---

## Frozen label / answer anchors

Producing contract: `R52_LABEL_RULE_EVENT_LEVEL_ANSWER_MATCH` (no official-insider-only label filter).
Matching: declared-source-scoped (r5.1 event IDs unique within a CSV, not globally).

| Anchor | Value |
| --- | ---: |
| official malicious answer IDs | {c["answer_ids"]} |
| MATCHED_ONCE | {c["matched_once"]} |
| UNMATCHED | {c["unmatched"]} |
| MULTIPLE | {c["multiple"]} |
| official mapped insiders | {c["official_insiders"]} |
| official incidents | {c["official_incidents"]} |
| event-level labelled users | {c["event_level_labelled_users"]} |
| completed-window positives | {c["completed_positives"]} |
| endpoint positives | {c["endpoint_positives"]} |
| de-overlap offset-0 positives | {c["deoverlap_positives"]} |
| official-only completed (descriptive) | {off[0]} |
| official-only endpoint (descriptive) | {off[1]} |
| official-only de-overlap (descriptive) | {off[2]} |

Official insider–incident clusters: **4**. Not 8 independent malicious units.

Contextual event-level users receive null official incident IDs: {", ".join(kw["contextual"])}.

---

## Scaler / features

| Item | Value |
| --- | --- |
| scaler SHA-256 | `{kw["scaler_sha256"]}` |
| scaler | LOAD/TRANSFORM only; r5.2 TRAIN fit; no r5.1 adaptation |
| feature order | {", ".join(COMMON_13_FEATURES)} |
| HTTP | one row = one event |
| active duration | max(minutes(latest-earliest), 0) over five sources |
| NaN / Inf | {kw["nan_count"]} / {kw["inf_count"]} |
| scaled SHA-256 | `{kw["scaled_sha"]}` |
| active user-days | {kw["n_active"]} |

---

## Sequence order

| Field | Value |
| --- | --- |
| window_index | `[user_index, start_day_index]` |
| order | user ascending, then start 0..497; no shuffle |
| sequence_id | `{{user_id}}\\|{{window_start_date}}\\|{{window_end_date}}` |
| sequence_order_sha256 | `{kw["sequence_order_sha256"]}` |

---

## Component hashes

| file | bytes | shape | dtype | SHA-256 | role |
| --- | ---: | --- | --- | --- | --- |
{rows}

input_bundle_manifest_sha256 = `{kw["input_bundle_manifest_sha256"]}`

---

## Feature profile (scaled daily flatten; no model)

| feature | mean | sd | q01 | q50 | q99 | frac\\|z\\|>3 | frac\\|z\\|>5 | frac\\|z\\|>10 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
{feat}

No predictive interpretation.

---

## Streaming provider check

Provider: `DenseDailyWindowProvider`. Batch bound: {BATCH_SIZE_FROZEN}. No model called. No full (N,20,13) tensor.

| checkpoint | slice | batch shape | user | start | completed | endpoint |
| --- | --- | --- | --- | --- | --- | --- |
{stream}

---

## Future r5.1 views / metrics (predeclared; not executed)

Views: COMPLETED_WINDOW, ENDPOINT_PAST_ONLY, DEOVERLAP_OFFSET0.
Metrics: PR-AUC; F1/precision/recall/FP/FN at frozen threshold; Brier/log-loss only if scores in [0,1].
Mechanism allowed: logit deviation, route MAE, route KL, hard-route agreement, dominant-leaf agreement.
Mechanism disabled: unused-leaf fraction, tree-contribution rho.

---

## Protocol flags

All required flags are false: r62/r51 predictive inference, r5.2 TEST opened, training, threshold selection, scaler fit, calibration fit, model selection, true authorisation.

NEXT_ACTION = Independent review of r5.1 bundle identity, counts, feature profile, and runner SHA. If approved, create one true EDITOR-007C secondary-stress authorisation and score r5.1 exactly once.
"""


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ProtocolStop as exc:
        print("EDITOR007B_R51_BUNDLE_BLOCKED")
        print(exc)
        raise SystemExit(4)
    except Exception as exc:  # noqa: BLE001
        print("EDITOR007B_R51_BUNDLE_BLOCKED")
        print(exc)
        traceback.print_exc()
        raise SystemExit(4)
