"""Post-freeze CERT r6.1 bundle construction using the frozen external harness logic."""

from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

from .cert_parse import (
    CSV_FIELD_LIMIT,
    build_dense_daily,
    header_prefix_ok,
    parse_answer_file,
    scan_source,
)
from .constants import (
    ANSWER_BUNDLE_CANDIDATES,
    FEATURE_ORDER,
    LABEL_RULE,
    RAW_R61_ROOT,
    SEQUENCE_LENGTH,
    SOURCE_TYPES,
    STRIDE_PRIMARY,
)
from .io_util import write_json, write_npy
from .safety import (
    OUTPUT_ROOT,
    REVIEW_ROOT,
    Editor024Blocked,
    require_protocol_frozen,
    sha256_file,
    utc_now,
)
from .scaler import load_r52_train_scaler, transform_only

SCENARIO_FILE_RE = re.compile(r"^r6\.1-(\d+)\.csv$", re.IGNORECASE)


def _log(msg: str) -> None:
    print(f"[{utc_now()}] {msg}", flush=True)


def resolve_answer_bundle() -> dict[str, Any]:
    require_protocol_frozen(action="resolve r6.1 answer files")
    for root in ANSWER_BUNDLE_CANDIDATES:
        if not root.is_dir():
            continue
        scenario_files = sorted(
            p for p in root.iterdir() if p.is_file() and SCENARIO_FILE_RE.match(p.name)
        )
        insiders = root / "insiders.csv"
        if scenario_files:
            return {
                "root": root,
                "scenario_files": scenario_files,
                "insiders_csv": insiders if insiders.is_file() else None,
            }
    raise Editor024Blocked("EDITOR024_R61_COMPATIBILITY_GATE = FAIL: no r6.1-*.csv answer files found")


def load_official_insiders(path: Path) -> list[dict[str, str]]:
    require_protocol_frozen(action="read insiders.csv")
    rows: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        for row in csv.DictReader(handle):
            ds = str(row.get("dataset", "")).strip().lower().replace("r", "")
            if ds in {"6.1", "61"}:
                rows.append({k: (v or "").strip() for k, v in row.items()})
    return rows


def peek_header(path: Path, n_rows: int = 32) -> dict[str, Any]:
    require_protocol_frozen(action=f"peek {path.name}")
    csv.field_size_limit(CSV_FIELD_LIMIT)
    header: list[str] = []
    parsed = 0
    users = 0
    from .cert_parse import parse_cert_ts

    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        reader = csv.reader(handle)
        for i, row in enumerate(reader):
            if i == 0:
                header = [(c or "").strip() for c in row]
                continue
            if len(row) < 3:
                continue
            ts = parse_cert_ts((row[1] or "").strip())
            user = (row[2] or "").strip()
            if ts is not None and user:
                parsed += 1
                users += 1
            if i >= n_rows:
                break
    return {
        "path": str(path),
        "header": header,
        "header_ok": header_prefix_ok(header),
        "n_peeked_parsed": parsed,
        "readable": True,
    }


def hash_required_raw_files() -> dict[str, Any]:
    require_protocol_frozen(action="hash r6.1 raw files")
    rows = []
    for source in SOURCE_TYPES:
        path = RAW_R61_ROOT / f"{source}.csv"
        if not path.is_file():
            raise Editor024Blocked(f"EDITOR024_R61_COMPATIBILITY_GATE = FAIL: missing {path}")
        _log(f"Streaming SHA256 {path} ({path.stat().st_size:,} bytes)")
        rows.append(
            {
                "relative_path": f"{source}.csv",
                "path": str(path),
                "byte_size": int(path.stat().st_size),
                "sha256": sha256_file(path),
            }
        )
    payload = {"files": rows, "written_at": utc_now()}
    write_json(REVIEW_ROOT / "EDITOR024_R61_RAW_SHA256.json", payload)
    return payload


def compatibility_gate(raw_hashes: dict[str, Any], answers: dict[str, Any]) -> dict[str, Any]:
    require_protocol_frozen(action="r6.1 compatibility gate")
    peeks = []
    ok = True
    reasons: list[str] = []
    for source in SOURCE_TYPES:
        path = RAW_R61_ROOT / f"{source}.csv"
        rec = peek_header(path)
        peeks.append(rec)
        if not rec["header_ok"]:
            ok = False
            reasons.append(f"{source} header {rec['header'][:4]} incompatible")
        if rec["n_peeked_parsed"] == 0:
            ok = False
            reasons.append(f"{source} timestamps/users not parseable by frozen logic")
    if not answers["scenario_files"]:
        ok = False
        reasons.append("no official r6.1 answer scenario files")
    status = "PASS" if ok else "FAIL"
    payload = {
        "EDITOR024_R61_COMPATIBILITY_GATE": status,
        "required_source_files_readable": ok,
        "peeks": peeks,
        "answer_files": [str(p) for p in answers["scenario_files"]],
        "reasons": reasons,
        "predictive_outcomes_inspected": False,
        "written_at": utc_now(),
    }
    write_json(REVIEW_ROOT / "EDITOR024_COMPATIBILITY_GATE.json", payload)
    if not ok:
        raise Editor024Blocked(
            f"EDITOR024_R61_COMPATIBILITY_GATE = FAIL; EDITOR024_PREDICTIVE_INFERENCE_EXECUTED = NO; {reasons}"
        )
    return payload


def construct_r61_bundle() -> dict[str, Any]:
    require_protocol_frozen(action="construct r6.1 representation")
    csv.field_size_limit(CSV_FIELD_LIMIT)
    scaler = load_r52_train_scaler()
    answers = resolve_answer_bundle()
    official_rows = []
    if answers["insiders_csv"] is not None:
        official_rows = load_official_insiders(answers["insiders_csv"])
    official_insiders = [r.get("user", "") for r in official_rows if r.get("user")]
    official_set = set(official_insiders)
    user_to_incident = {
        r["user"]: f"r6.1-{r.get('scenario', '')}" for r in official_rows if r.get("user")
    }

    all_records: list[dict[str, Any]] = []
    answer_hashes = []
    for path in answers["scenario_files"]:
        m = SCENARIO_FILE_RE.match(path.name)
        assert m is not None
        key = f"r6.1-{int(m.group(1))}"
        rec_hash = {
            "relative_path": path.name,
            "path": str(path),
            "byte_size": int(path.stat().st_size),
            "sha256": sha256_file(path),
            "scenario_key": key,
        }
        answer_hashes.append(rec_hash)
        with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
            all_records.extend(parse_answer_file(handle, key))
    if answers["insiders_csv"] is not None:
        answer_hashes.append(
            {
                "relative_path": answers["insiders_csv"].name,
                "path": str(answers["insiders_csv"]),
                "byte_size": int(answers["insiders_csv"].stat().st_size),
                "sha256": sha256_file(answers["insiders_csv"]),
                "scenario_key": "insiders",
            }
        )
    if not all_records:
        raise Editor024Blocked("EDITOR024_R61_COMPATIBILITY_GATE = FAIL: answer parser produced zero records")

    id_to_bit: dict[str, int] = {}
    answer_ids_by_source: dict[str, set[str]] = {s: set() for s in SOURCE_TYPES}
    unknown_types: set[str] = set()
    for rec in all_records:
        n = int(rec["scenario_key"].split("-")[-1])
        id_to_bit[rec["event_id"]] = 1 << (n - 1)
        if rec["event_type"] in SOURCE_TYPES:
            answer_ids_by_source[rec["event_type"]].add(rec["event_id"])
        else:
            unknown_types.add(rec["event_type"])
    unique_ids = set(id_to_bit)
    match_counts = {eid: 0 for eid in unique_ids}

    user_index: dict[str, int] = {}
    user_list: list[str] = []
    active: dict[tuple[int, int], list[int]] = {}
    source_scan = []
    for source in SOURCE_TYPES:
        path = RAW_R61_ROOT / f"{source}.csv"
        _log(f"Streaming {source}: {path}")
        with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
            rec = scan_source(
                source,
                handle,
                source_answer_ids=answer_ids_by_source[source],
                id_to_bit=id_to_bit,
                match_counts=match_counts,
                active=active,
                user_index=user_index,
                user_list=user_list,
                progress=_log,
            )
        if not rec["header_ok"]:
            raise Editor024Blocked(f"EDITOR024_R61_COMPATIBILITY_GATE = FAIL: {source} schema incompatible")
        source_scan.append(rec)

    built = build_dense_daily(user_list=user_list, active=active)
    del active
    _log("Applying frozen r5.2 scaler (transform only)")
    scaled = transform_only(built["raw"], scaler)
    del built["raw"]
    if int(np.isnan(scaled).sum()) or int(np.isinf(scaled).sum()):
        raise Editor024Blocked("non-finite scaled r6.1 features")

    out_dir = OUTPUT_ROOT / "bundle"
    out_dir.mkdir(parents=True, exist_ok=True)
    write_npy(out_dir / "scaled_dense_daily.npy", scaled)
    write_npy(out_dir / "completed_window_labels.npy", built["completed_window_labels"])
    write_npy(out_dir / "deoverlap_offset0_mask.npy", built["deoverlap_offset0_mask"])
    write_npy(out_dir / "window_user_index.npy", built["user_index"])
    write_npy(out_dir / "window_start_index.npy", built["start_index"])
    np.save(out_dir / "user_ids_sorted.npy", np.array(built["user_ids_sorted"], dtype=object))
    np.save(out_dir / "calendar_dates.npy", np.array(built["calendar_iso"], dtype=object))
    np.save(out_dir / "sequence_ids.npy", built["sequence_ids"])
    np.save(out_dir / "user_ids_windows.npy", built["user_ids_windows"])

    n_windows = int(built["n_windows"])
    n_pos = int(built["n_completed_positives"])
    prevalence = float(n_pos / n_windows) if n_windows else float("nan")
    n_pos_users = int(
        len(
            {
                str(u)
                for u, lab in zip(built["user_ids_windows"], built["completed_window_labels"])
                if int(lab) > 0
            }
        )
    )
    manifest = {
        "dataset_id": "CERT r6.1",
        "role": "FINAL_PROSPECTIVELY_RESERVED_CONFIRMATION_TARGET",
        "raw_file_hashes_ref": "EDITOR024_R61_RAW_SHA256.json",
        "answer_file_hashes": answer_hashes,
        "scaler_hash": scaler["sha256"],
        "scaler_source": "R52_TRAIN",
        "TARGET_SCALER_FIT": "NO",
        "feature_order": list(FEATURE_ORDER),
        "sequence_length": SEQUENCE_LENGTH,
        "stride": STRIDE_PRIMARY,
        "label_semantics": "COMPLETED_WINDOW",
        "label_rule": LABEL_RULE,
        "number_of_users": int(built["n_users"]),
        "number_of_daily_records": int(built["n_users"] * built["n_days"]),
        "number_of_completed_windows": n_windows,
        "number_of_positive_windows": n_pos,
        "prevalence": prevalence,
        "deoverlap_retained": int(built["n_deoverlap"]),
        "deoverlap_positives": int(built["n_deoverlap_positives"]),
        "n_positive_label_users": n_pos_users,
        "official_insiders": official_insiders,
        "calendar_start": built["calendar_iso"][0],
        "calendar_end": built["calendar_iso"][-1],
        "n_days": int(built["n_days"]),
        "n_starts": int(built["n_starts"]),
        "answer_ids": len(unique_ids),
        "matched_once": int(sum(1 for n in match_counts.values() if n == 1)),
        "unmatched": int(sum(1 for n in match_counts.values() if n == 0)),
        "multiple": int(sum(1 for n in match_counts.values() if n > 1)),
        "unknown_answer_event_types": sorted(unknown_types),
        "source_scan": source_scan,
        "user_to_incident": user_to_incident,
        "official_insider_set_size": len(official_set),
        "bundle_dir": str(out_dir),
        "test_set_descriptor_only": True,
        "not_used_to_alter_model": True,
        "written_at": utc_now(),
    }
    write_json(REVIEW_ROOT / "EDITOR024_R61_INPUT_MANIFEST.json", manifest)
    built["scaled"] = scaled
    built["prevalence"] = prevalence
    built["n_positive_label_users"] = n_pos_users
    built["bundle_dir"] = out_dir
    built["manifest"] = manifest
    built["scaler"] = scaler
    return built
