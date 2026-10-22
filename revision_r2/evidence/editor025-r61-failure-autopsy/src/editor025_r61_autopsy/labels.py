"""Phase A — ground-truth / label autopsy. Does not invent missing answer files."""

from __future__ import annotations

import csv
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from sklearn.metrics import average_precision_score

from editor024_r61.cert_parse import looks_like_event_id, normalize_event_id, parse_answer_file, parse_cert_ts
from editor024_r61.constants import ANSWER_BUNDLE_CANDIDATES

from .constants import ANSWER_SEARCH_ROOTS, EXPECTED_ANSWER_FILES
from .safety import sha256_file, utc_now


def discover_answer_files(roots: Iterable[Path] | None = None) -> dict[str, list[Path]]:
    """Search known local CERT answer locations. Do not download. Do not synthesize."""
    found: dict[str, list[Path]] = {name: [] for name in EXPECTED_ANSWER_FILES}
    seen: set[str] = set()
    candidates = list(roots) if roots is not None else list(ANSWER_SEARCH_ROOTS) + list(ANSWER_BUNDLE_CANDIDATES)
    extra: list[Path] = []
    for root in candidates:
        if root is None:
            continue
        p = Path(root)
        if p.is_file():
            extra.append(p)
            continue
        if not p.is_dir():
            continue
        try:
            for child in p.iterdir():
                extra.append(child)
        except OSError:
            continue
        # Do not walk raw CERT log trees. Recurse only into answer-named folders.
        try:
            if "answer" in p.name.lower():
                for child in p.rglob("r6.1-*.csv"):
                    extra.append(child)
                for child in p.rglob("insiders.csv"):
                    extra.append(child)
            else:
                ins = p / "insiders.csv"
                if ins.is_file():
                    extra.append(ins)
                for name in EXPECTED_ANSWER_FILES:
                    hit = p / name
                    if hit.is_file():
                        extra.append(hit)
        except OSError:
            continue
    for path in extra:
        if not path.is_file():
            continue
        name = path.name
        if name not in found:
            continue
        key = str(path.resolve()).lower()
        if key in seen:
            continue
        seen.add(key)
        found[name].append(path.resolve())
    return found


def inventory_row(name: str, path: Path | None) -> dict[str, Any]:
    rec: dict[str, Any] = {
        "filename": name,
        "exists": False,
        "path": None,
        "sha256": None,
        "byte_size": None,
        "scenario": name.replace(".csv", "") if name.startswith("r6.1-") else name.replace(".csv", ""),
        "row_count": None,
        "parsed_answer_event_count": None,
    }
    if path is None or not path.is_file():
        return rec
    rec["exists"] = True
    rec["path"] = str(path)
    rec["byte_size"] = int(path.stat().st_size)
    rec["sha256"] = sha256_file(path)
    n_rows = 0
    parsed = 0
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        if name == "insiders.csv":
            reader = csv.reader(handle)
            for row in reader:
                if row and any((c or "").strip() for c in row):
                    n_rows += 1
            rec["row_count"] = n_rows
            rec["parsed_answer_event_count"] = 0
            return rec
        start = handle.tell()
        reader = csv.reader(handle)
        for row in reader:
            if row and any((c or "").strip() for c in row):
                n_rows += 1
        rec["row_count"] = n_rows
        handle.seek(start)
        records = parse_answer_file(handle, rec["scenario"])
        rec["parsed_answer_event_count"] = len(records)
    return rec


def load_r61_insiders(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        for row in csv.DictReader(handle):
            cleaned = {k: (v or "").strip() for k, v in row.items()}
            ds = cleaned.get("dataset", "").lower().replace("r", "")
            if ds in {"6.1", "61"}:
                rows.append(cleaned)
    return rows


def official_insider_map(rows: list[dict[str, str]]) -> dict[str, str]:
    """scenario_key -> official insider user. Requires authoritative insiders.csv fields."""
    out: dict[str, str] = {}
    for row in rows:
        user = (row.get("user") or row.get("username") or "").strip()
        scenario = (row.get("scenario") or "").strip()
        if not user:
            continue
        key = None
        if scenario.startswith("r6.1-"):
            key = scenario
        elif scenario.isdigit() and scenario in {"1", "2", "3", "4", "5"}:
            key = f"r6.1-{scenario}"
        if key:
            out[key] = user
    return out


def parse_all_answers(files: dict[str, Path | None]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for i in range(1, 6):
        name = f"r6.1-{i}.csv"
        path = files.get(name)
        if path is None or not Path(path).is_file():
            continue
        with Path(path).open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
            recs = parse_answer_file(handle, f"r6.1-{i}")
        records.extend(recs)
    return records


def enrich_crosswalk(
    records: list[dict[str, Any]],
    insider_by_scenario: dict[str, str],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for rec in records:
        scenario = rec["scenario_key"]
        official = insider_by_scenario.get(scenario, "")
        user = (rec.get("user") or "").strip()
        user_eq = bool(user) and bool(official) and user == official
        out.append(
            {
                "scenario": scenario,
                "official_insider": official,
                "event_type": rec.get("event_type", ""),
                "event_id": rec.get("event_id", ""),
                "answer_file_timestamp": rec.get("timestamp", ""),
                "answer_file_user": user,
                "answer_file_user_equals_official_insider": user_eq,
                "user_missing_or_ambiguous": not bool(user),
            }
        )
    return out


def attribution_counts(crosswalk: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    by: dict[str, dict[str, int]] = defaultdict(lambda: {"official": 0, "other": 0, "missing": 0, "n": 0})
    for rec in crosswalk:
        sc = rec["scenario"]
        by[sc]["n"] += 1
        if rec["user_missing_or_ambiguous"]:
            by[sc]["missing"] += 1
        elif rec["answer_file_user_equals_official_insider"]:
            by[sc]["official"] += 1
        else:
            by[sc]["other"] += 1
    return dict(by)


def timestamp_to_iso(ts_text: str) -> str | None:
    parsed = parse_cert_ts(ts_text)
    if parsed is None:
        return None
    try:
        return date(parsed[0], parsed[1], parsed[2]).isoformat()
    except ValueError:
        return None


def diagnostic_view_available(crosswalk: list[dict[str, Any]], insider_by_scenario: dict[str, str]) -> bool:
    if not insider_by_scenario:
        return False
    if not crosswalk:
        return False
    if any(rec["user_missing_or_ambiguous"] for rec in crosswalk):
        return False
    scenarios = {rec["scenario"] for rec in crosswalk}
    return all(sc in insider_by_scenario and insider_by_scenario[sc] for sc in scenarios)


def scenario_insider_consistent_day_keys(
    crosswalk: list[dict[str, Any]],
) -> set[tuple[str, str]]:
    """(user, iso_date) that are positive under the diagnostic view."""
    keys: set[tuple[str, str]] = set()
    for rec in crosswalk:
        if not rec["answer_file_user_equals_official_insider"]:
            continue
        iso = timestamp_to_iso(rec["answer_file_timestamp"])
        user = rec["answer_file_user"]
        if iso and user:
            keys.add((user, iso))
    return keys


def window_labels_from_day_keys(
    *,
    user_ids_windows: np.ndarray,
    start_index: np.ndarray,
    calendar_dates: np.ndarray,
    positive_days: set[tuple[str, str]],
    sequence_length: int = 20,
) -> np.ndarray:
    users = np.asarray(user_ids_windows).astype(str)
    starts = np.asarray(start_index).astype(int)
    cal = np.asarray(calendar_dates).astype(str)
    n = len(users)
    y = np.zeros(n, dtype=np.int8)
    cal_index = {d: i for i, d in enumerate(cal.tolist())}
    user_dates: dict[str, set[int]] = defaultdict(set)
    for user, iso in positive_days:
        if iso in cal_index:
            user_dates[user].add(cal_index[iso])
    if not user_dates:
        return y
    for i in range(n):
        u = users[i]
        if u not in user_dates:
            continue
        s = int(starts[i])
        days = user_dates[u]
        if any(s <= d < s + sequence_length for d in days):
            y[i] = 1
    return y


def pr_auc(y: np.ndarray, scores: np.ndarray) -> float:
    y = np.asarray(y).astype(int).ravel()
    p = np.asarray(scores, dtype=np.float64).ravel()
    if len(np.unique(y)) < 2:
        return float("nan")
    return float(average_precision_score(y, p))


def ranking_excess(pr: float, prevalence: float) -> float:
    return float(pr - prevalence)


def semantic_mismatch_from_crosswalk(
    *,
    attribution: dict[str, dict[str, int]],
    n_positive_bundle_users: int,
    n_official_insiders: int,
) -> bool:
    """Mismatch only if authoritative fields show systematic non-insider attribution."""
    other = sum(v.get("other", 0) for v in attribution.values())
    total = sum(v.get("n", 0) for v in attribution.values())
    if total <= 0:
        return False
    systematic = other > 0 and (other / total) >= 0.05
    extra_users = n_positive_bundle_users > n_official_insiders
    return bool(systematic and extra_users)
