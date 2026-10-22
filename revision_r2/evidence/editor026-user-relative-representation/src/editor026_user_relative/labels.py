"""Frozen r6.1 label views. Scenario 4 remains not evaluable. No invented labels."""

from __future__ import annotations

from typing import Any

import numpy as np

from editor025_r61_autopsy.labels import (
    attribution_counts,
    diagnostic_view_available,
    discover_answer_files,
    enrich_crosswalk,
    inventory_row,
    load_r61_insiders,
    official_insider_map,
    parse_all_answers,
    scenario_insider_consistent_day_keys,
    window_labels_from_day_keys,
)

from .constants import (
    R61_LABEL_VIEW_A,
    R61_LABEL_VIEW_B,
    R61_SCENARIO4_ANSWER_AVAILABLE,
    SCENARIO4_STATUS,
)


def freeze_label_views(
    *,
    bundle_y_editor024: np.ndarray,
    user_ids_windows: np.ndarray,
    start_index: np.ndarray,
    calendar_dates: np.ndarray,
) -> dict[str, Any]:
    discovered = discover_answer_files()
    chosen: dict[str, Any] = {}
    inventory = []
    for name in ("r6.1-1.csv", "r6.1-2.csv", "r6.1-3.csv", "r6.1-4.csv", "r6.1-5.csv", "insiders.csv"):
        paths = discovered.get(name) or []
        path = paths[0] if paths else None
        chosen[name] = path
        rec = inventory_row(name, path)
        rec["n_locations_found"] = len(paths)
        inventory.append(rec)
    s4_available = bool(chosen.get("r6.1-4.csv"))
    insiders_path = chosen.get("insiders.csv")
    insider_map: dict[str, str] = {}
    if insiders_path is not None:
        insider_map = official_insider_map(load_r61_insiders(insiders_path))
    files = {k: v for k, v in chosen.items() if k.startswith("r6.1-") and v is not None}
    records = parse_all_answers(files)
    crosswalk = enrich_crosswalk(records, insider_map)
    attr = attribution_counts(crosswalk)
    diag_ok = diagnostic_view_available(crosswalk, insider_map)
    y_a = np.asarray(bundle_y_editor024).astype(np.int8).ravel()
    y_b = None
    if diag_ok:
        keys = scenario_insider_consistent_day_keys(crosswalk)
        y_b = window_labels_from_day_keys(
            user_ids_windows=user_ids_windows,
            start_index=start_index,
            calendar_dates=calendar_dates,
            positive_days=keys,
        ).astype(np.int8)
    return {
        "inventory": inventory,
        "insider_map": insider_map,
        "attribution_by_scenario": attr,
        "R61_SCENARIO4_ANSWER_AVAILABLE": "YES" if s4_available else "NO",
        "SCENARIO4_STATUS": "EVALUABLE" if s4_available else SCENARIO4_STATUS,
        "R61_EDITOR024_LABEL_VIEW": R61_LABEL_VIEW_A,
        "R61_INSIDER_CONSISTENT_VIEW": R61_LABEL_VIEW_B,
        "NOT_EVALUABLE": SCENARIO4_STATUS,
        "views": {
            R61_LABEL_VIEW_A: {
                "source": "EDITOR-024 completed-window event-ID labels",
                "y": y_a,
                "prevalence": float(y_a.mean()) if y_a.size else float("nan"),
                "n_pos": int(y_a.sum()),
            },
            R61_LABEL_VIEW_B: {
                "source": "official scenario insider + answer-file actor/user",
                "available": bool(diag_ok and y_b is not None),
                "y": y_b,
                "prevalence": float(y_b.mean()) if y_b is not None and y_b.size else float("nan"),
                "n_pos": int(y_b.sum()) if y_b is not None else 0,
            },
        },
        "scenario4_not_invented": True,
        "frozen_view_names": [R61_LABEL_VIEW_A, R61_LABEL_VIEW_B],
        "R61_SCENARIO4_ANSWER_AVAILABLE_PROTOCOL": R61_SCENARIO4_ANSWER_AVAILABLE,
    }
