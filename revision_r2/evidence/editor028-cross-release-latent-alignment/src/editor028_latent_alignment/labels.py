"""r6.1 label views. Import only after the r5.2 model-freeze commit."""

from __future__ import annotations

import csv
from typing import Any

import numpy as np

from editor024_r61.cert_parse import CSV_FIELD_LIMIT, build_dense_daily, scan_source
from editor024_r61.constants import RAW_R61_ROOT, SOURCE_TYPES
from editor024_r61.bundle import SCENARIO_FILE_RE, resolve_answer_bundle
from editor026_user_relative.labels import freeze_label_views

from .constants import R61_LABEL_VIEW_A, R61_LABEL_VIEW_B
from .safety import Editor028Blocked, require_r52_model_frozen


def construct_r61_editor024_labels() -> dict[str, Any]:
    """Answer-matched completed-window labels. Forbidden before model freeze."""
    require_r52_model_frozen(action="construct r6.1 diagnostic labels")
    csv.field_size_limit(CSV_FIELD_LIMIT)
    answers = resolve_answer_bundle()
    all_records: list[dict[str, Any]] = []
    from editor024_r61.cert_parse import parse_answer_file

    for path in answers["scenario_files"]:
        m = SCENARIO_FILE_RE.match(path.name)
        if m is None:
            continue
        key = f"r6.1-{int(m.group(1))}"
        with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
            all_records.extend(parse_answer_file(handle, key))
    if not all_records:
        raise Editor028Blocked("r6.1 answer parser produced zero records")
    id_to_bit: dict[str, int] = {}
    answer_ids_by_source: dict[str, set[str]] = {s: set() for s in SOURCE_TYPES}
    for rec in all_records:
        n = int(rec["scenario_key"].split("-")[-1])
        id_to_bit[rec["event_id"]] = 1 << (n - 1)
        if rec["event_type"] in SOURCE_TYPES:
            answer_ids_by_source[rec["event_type"]].add(rec["event_id"])
    user_index: dict[str, int] = {}
    user_list: list[str] = []
    active: dict[tuple[int, int], list[int]] = {}
    match_counts = {eid: 0 for eid in id_to_bit}
    for source in SOURCE_TYPES:
        path = RAW_R61_ROOT / f"{source}.csv"
        with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
            scan_source(
                source,
                handle,
                source_answer_ids=answer_ids_by_source[source],
                id_to_bit=id_to_bit,
                match_counts=match_counts,
                active=active,
                user_index=user_index,
                user_list=user_list,
            )
    built = build_dense_daily(user_list=user_list, active=active)
    y_a = np.asarray(built["completed_window_labels"]).astype(np.int8).ravel()
    views = freeze_label_views(
        bundle_y_editor024=y_a,
        user_ids_windows=np.asarray(built["user_ids_windows"]).astype(str),
        start_index=np.asarray(built["start_index"]),
        calendar_dates=np.asarray(built["calendar_iso"]).astype(str),
    )
    y_b = views["views"][R61_LABEL_VIEW_B]["y"]
    if y_b is None:
        raise Editor028Blocked("insider-consistent view unavailable; scenario 4 remains not invented")
    return {
        "y_editor024": y_a,
        "y_insider": np.asarray(y_b).astype(np.int8).ravel(),
        "user_ids_windows": np.asarray(built["user_ids_windows"]).astype(str),
        "sequence_ids": np.asarray(built["sequence_ids"]).astype(str),
        "views": views,
        "R61_EDITOR024_LABEL_VIEW": R61_LABEL_VIEW_A,
        "R61_INSIDER_CONSISTENT_VIEW": R61_LABEL_VIEW_B,
        "scenario4": "NOT_EVALUABLE",
    }
