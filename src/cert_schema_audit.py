#!/usr/bin/env python3
"""Schema comparison and common 13-feature compatibility across CERT releases."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dataset_registry import (
    CORE_EVENT_LOGS,
    REQUIRED_ACTIVITY_LOGS,
    DatasetSpec,
    get_dataset_spec,
    iter_known_versions,
)

# Canonical r4.2 13-feature behavioural representation (tensor inputs).
COMMON_13_FEATURES: tuple[str, ...] = (
    "total_events",
    "logon_count",
    "device_count",
    "file_count",
    "email_count",
    "http_count",
    "active_duration_minutes",
    "has_logon_activity",
    "has_device_activity",
    "has_file_activity",
    "has_email_activity",
    "has_http_activity",
    "is_active_day",
)

FEATURE_DEFINITIONS: dict[str, dict[str, str]] = {
    "total_events": {
        "source_logs": "logon,device,file,email,http",
        "r42_definition": "Count of all activity events for a user-day",
    },
    "logon_count": {
        "source_logs": "logon",
        "r42_definition": "Count of logon.csv rows for a user-day",
    },
    "device_count": {
        "source_logs": "device",
        "r42_definition": "Count of device.csv rows for a user-day",
    },
    "file_count": {
        "source_logs": "file",
        "r42_definition": "Count of file.csv rows for a user-day",
    },
    "email_count": {
        "source_logs": "email",
        "r42_definition": "Count of email.csv rows for a user-day",
    },
    "http_count": {
        "source_logs": "http",
        "r42_definition": "Count of http.csv rows for a user-day",
    },
    "active_duration_minutes": {
        "source_logs": "logon,device,file,email,http",
        "r42_definition": "Minutes between first and last event timestamps on a user-day",
    },
    "has_logon_activity": {
        "source_logs": "logon",
        "r42_definition": "1 if logon_count > 0 else 0",
    },
    "has_device_activity": {
        "source_logs": "device",
        "r42_definition": "1 if device_count > 0 else 0",
    },
    "has_file_activity": {
        "source_logs": "file",
        "r42_definition": "1 if file_count > 0 else 0",
    },
    "has_email_activity": {
        "source_logs": "email",
        "r42_definition": "1 if email_count > 0 else 0",
    },
    "has_http_activity": {
        "source_logs": "http",
        "r42_definition": "1 if http_count > 0 else 0",
    },
    "is_active_day": {
        "source_logs": "logon,device,file,email,http",
        "r42_definition": "1 if the user had any activity that calendar day (densified)",
    },
}

# Columns required to construct count / duration features from a log.
MIN_EVENT_COLUMNS = ("id", "date", "user")

# Documented semantic drift — flagged, never silently remapped as equivalent content fields.
KNOWN_SEMANTIC_NOTES: dict[str, list[str]] = {
    "device": [
        "r5.2/r6.2 add file_tree; unused by the common 13-feature schema.",
    ],
    "file": [
        "r5.2/r6.2 add activity (copy/delete/open/write) and removable-media flags; "
        "row counts remain exact for file_count if every file action is one row.",
        "Do not treat r4.2 content-only rows as semantically identical to r6.2 action taxonomy "
        "for action-specific features; count-based features are still exact.",
    ],
    "email": [
        "r5.2/r6.2 add activity; attachment/recipient fields may differ in density. "
        "email_count uses row counts and remains exact.",
    ],
    "http": [
        "r6.2 adds activity and denser sentence-level content; http_count uses row counts "
        "and remains exact. Do not add sentence features to the common schema.",
    ],
    "decoy_file": [
        "Optional r5.2/r6.2-only log. Exclude from the primary common 13-feature space.",
    ],
}


@dataclass(frozen=True)
class LogSchemaSnapshot:
    log_name: str
    version: str
    path: str
    exists: bool
    columns: tuple[str, ...]
    sample_values: dict[str, str]


def sniff_header(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
        first = handle.readline()
    if not first:
        return []
    return next(csv.reader([first]))


def sample_non_null_values(path: Path, columns: list[str], n: int = 1) -> dict[str, str]:
    """Return one sample non-null string per column (streaming, early stop)."""
    needed = set(columns)
    found: dict[str, str] = {}
    try:
        with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                for col in list(needed):
                    val = (row.get(col) or "").strip()
                    if val:
                        found[col] = val[:120]
                        needed.discard(col)
                if not needed:
                    break
                if len(found) >= len(columns):
                    break
    except OSError:
        return found
    return found


def snapshot_log_schema(raw_dir: Path, log_name: str, version: str) -> LogSchemaSnapshot:
    path = raw_dir / f"{log_name}.csv"
    if not path.is_file():
        return LogSchemaSnapshot(log_name, version, str(path), False, (), {})
    columns = tuple(sniff_header(path))
    samples = sample_non_null_values(path, list(columns[:12]))
    return LogSchemaSnapshot(log_name, version, str(path), True, columns, samples)


def collect_release_schemas(
    version_to_raw: dict[str, Path],
    log_names: tuple[str, ...] | None = None,
) -> dict[str, dict[str, LogSchemaSnapshot]]:
    logs = log_names or tuple(list(REQUIRED_ACTIVITY_LOGS) + ["decoy_file"])
    out: dict[str, dict[str, LogSchemaSnapshot]] = {}
    for version, raw_dir in version_to_raw.items():
        out[version] = {
            log: snapshot_log_schema(raw_dir, log, version) for log in logs
        }
    return out


def compare_schemas(
    schemas: dict[str, dict[str, LogSchemaSnapshot]],
) -> list[dict[str, Any]]:
    """Produce per-log comparison rows across releases present in ``schemas``."""
    versions = sorted(schemas.keys())
    log_names = sorted({log for v in schemas.values() for log in v.keys()})
    rows: list[dict[str, Any]] = []

    for log in log_names:
        col_sets = {
            ver: set(schemas[ver][log].columns)
            for ver in versions
            if log in schemas[ver] and schemas[ver][log].exists
        }
        present_versions = sorted(col_sets.keys())
        all_cols = set().union(*col_sets.values()) if col_sets else set()
        shared_all = (
            set.intersection(*col_sets.values()) if len(col_sets) >= 2 else set(all_cols)
        )
        # Shared by exactly two releases (when 3 present).
        shared_pairs: list[str] = []
        if len(present_versions) == 3:
            a, b, c = present_versions
            for x, y, z in ((a, b, c), (a, c, b), (b, c, a)):
                only_xy = (col_sets[x] & col_sets[y]) - col_sets[z]
                if only_xy:
                    shared_pairs.append(
                        f"{x}+{y}:{','.join(sorted(only_xy))}"
                    )
        release_specific = {
            ver: sorted(col_sets[ver] - shared_all) for ver in present_versions
        }
        missing = {
            ver: (log not in schemas[ver] or not schemas[ver][log].exists)
            for ver in versions
        }
        notes = list(KNOWN_SEMANTIC_NOTES.get(log, []))
        # Uncertain renames: none detected by exact name; flag content-bearing extras.
        uncertain = []
        for ver, extras in release_specific.items():
            for col in extras:
                if col.lower() in {
                    "content",
                    "file_tree",
                    "activity",
                    "to_removable_media",
                    "from_removable_media",
                    "attachments",
                }:
                    uncertain.append(
                        f"{ver}.{col}: present/extra — do not silently equate semantics "
                        f"with absences in other releases"
                    )

        # Compatibility with r4.2 preprocessing (needs id/date/user on event logs).
        r42_ok = True
        compat_notes = []
        if log in CORE_EVENT_LOGS:
            for ver in present_versions:
                cols = {c.lower() for c in col_sets[ver]}
                missing_min = [c for c in MIN_EVENT_COLUMNS if c not in cols]
                if missing_min:
                    r42_ok = False
                    compat_notes.append(f"{ver} missing {missing_min}")
            if log == "psychometric":
                pass
        if log == "psychometric":
            for ver in present_versions:
                cols = {c.lower() for c in col_sets[ver]}
                if "user_id" not in cols:
                    r42_ok = False
                    compat_notes.append(f"{ver} missing user_id")

        rows.append(
            {
                "log_name": log,
                "versions_present": ",".join(present_versions),
                "columns_by_version": {
                    ver: list(schemas[ver][log].columns)
                    for ver in versions
                    if log in schemas[ver]
                },
                "shared_by_all_present": sorted(shared_all),
                "shared_by_exactly_two": shared_pairs,
                "release_specific_columns": release_specific,
                "missing_in_version": {ver: missing[ver] for ver in versions},
                "sample_values_by_version": {
                    ver: schemas[ver][log].sample_values
                    for ver in present_versions
                },
                "semantic_notes": notes,
                "uncertain_semantic_mappings": uncertain,
                "compatible_with_r42_count_preprocessing": r42_ok and not any(
                    missing[v] for v in present_versions if v in col_sets
                ),
                "compatibility_notes": compat_notes,
            }
        )
    return rows


def flatten_schema_comparison_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flatten nested comparison dicts into CSV-friendly rows (one per log)."""
    flat: list[dict[str, Any]] = []
    for row in rows:
        flat.append(
            {
                "log_name": row["log_name"],
                "versions_present": row["versions_present"],
                "shared_by_all_present": ";".join(row["shared_by_all_present"]),
                "shared_by_exactly_two": " | ".join(row["shared_by_exactly_two"]),
                "release_specific_4.2": ";".join(
                    row["release_specific_columns"].get("4.2", [])
                ),
                "release_specific_5.2": ";".join(
                    row["release_specific_columns"].get("5.2", [])
                ),
                "release_specific_6.2": ";".join(
                    row["release_specific_columns"].get("6.2", [])
                ),
                "columns_4.2": ";".join(
                    row["columns_by_version"].get("4.2", [])
                ),
                "columns_5.2": ";".join(
                    row["columns_by_version"].get("5.2", [])
                ),
                "columns_6.2": ";".join(
                    row["columns_by_version"].get("6.2", [])
                ),
                "semantic_notes": " | ".join(row["semantic_notes"]),
                "uncertain_semantic_mappings": " | ".join(
                    row["uncertain_semantic_mappings"]
                ),
                "compatible_with_r42_count_preprocessing": row[
                    "compatible_with_r42_count_preprocessing"
                ],
                "compatibility_notes": " | ".join(row["compatibility_notes"]),
            }
        )
    return flat


def assess_feature_compatibility(
    schemas: dict[str, dict[str, LogSchemaSnapshot]],
) -> list[dict[str, Any]]:
    """Assess whether each of the common 13 features can be built for 5.2 / 6.2."""
    rows: list[dict[str, Any]] = []
    for feature in COMMON_13_FEATURES:
        meta = FEATURE_DEFINITIONS[feature]
        source_logs = [s.strip() for s in meta["source_logs"].split(",")]

        def _available(version: str) -> tuple[bool, str, str]:
            if version not in schemas:
                return False, "incompatible", "release schema not provided"
            for log in source_logs:
                snap = schemas[version].get(log)
                if snap is None or not snap.exists:
                    return False, "incompatible", f"missing log {log}.csv"
                cols = {c.lower() for c in snap.columns}
                if log in CORE_EVENT_LOGS:
                    missing = [c for c in MIN_EVENT_COLUMNS if c not in cols]
                    if missing:
                        return (
                            False,
                            "incompatible",
                            f"{log}.csv missing columns {missing}",
                        )
            # Count features are exact when id/date/user exist; we do not use
            # release-specific action/content columns.
            return True, "exact", "row-count / timestamp definition unchanged"

        avail_52, map_52, note_52 = _available("5.2") if "5.2" in schemas else (
            False,
            "incompatible",
            "5.2 not audited",
        )
        avail_62, map_62, note_62 = _available("6.2") if "6.2" in schemas else (
            False,
            "incompatible",
            "6.2 not audited",
        )
        avail_42, map_42, note_42 = _available("4.2") if "4.2" in schemas else (
            True,
            "exact",
            "reference definition",
        )

        recommended = "preserve_common_13_definition"
        if not avail_52 or not avail_62:
            recommended = "block_until_required_logs_present"
        elif map_52 != "exact" or map_62 != "exact":
            recommended = "review_uncertain_mapping_before_v2"

        rows.append(
            {
                "feature_name": feature,
                "source_logs": meta["source_logs"],
                "r42_definition": meta["r42_definition"],
                "available_r4.2": avail_42,
                "mapping_r4.2": map_42,
                "notes_r4.2": note_42,
                "available_r5.2": avail_52,
                "mapping_r5.2": map_52,
                "notes_r5.2": note_52,
                "available_r6.2": avail_62,
                "mapping_r6.2": map_62,
                "notes_r6.2": note_62,
                "required_column_mapping": "id,date,user (event logs); no content/action fields",
                "recommended_action": recommended,
                "exclude_from_common_space": "",
            }
        )

    # Explicitly record deferred release-specific candidates (not in common 13).
    for name, reason in (
        ("decoy_file_features", "optional r5.2/r6.2-only; ablation later"),
        ("sentence_level_content_features", "r6.2 content density; ablation later"),
        ("file_tree_features", "r5.2/r6.2 device.file_tree; ablation later"),
        ("file_action_taxonomy_features", "r5.2/r6.2 file.activity; ablation later"),
    ):
        rows.append(
            {
                "feature_name": name,
                "source_logs": "release-specific",
                "r42_definition": "not part of r4.2 common 13",
                "available_r4.2": False,
                "mapping_r4.2": "incompatible",
                "notes_r4.2": "absent by design",
                "available_r5.2": name != "sentence_level_content_features",
                "mapping_r5.2": "approximate",
                "notes_r5.2": reason,
                "available_r6.2": True,
                "mapping_r6.2": "approximate",
                "notes_r6.2": reason,
                "required_column_mapping": "n/a — excluded from primary cross-release space",
                "recommended_action": "defer_to_dataset_specific_ablation",
                "exclude_from_common_space": "yes",
            }
        )
    return rows


def infer_dtype_label(sample: str) -> str:
    if not sample:
        return "unknown"
    if looks_like_event_id_local(sample):
        return "event_id"
    if "/" in sample and ":" in sample:
        return "timestamp_like"
    if sample.replace(".", "", 1).isdigit():
        return "numeric_like"
    return "string"


def looks_like_event_id_local(value: str) -> bool:
    v = value.strip()
    return v.startswith("{") and v.endswith("}") and "-" in v


__all__ = [
    "COMMON_13_FEATURES",
    "FEATURE_DEFINITIONS",
    "KNOWN_SEMANTIC_NOTES",
    "LogSchemaSnapshot",
    "assess_feature_compatibility",
    "collect_release_schemas",
    "compare_schemas",
    "flatten_schema_comparison_rows",
    "infer_dtype_label",
    "sample_non_null_values",
    "sniff_header",
    "snapshot_log_schema",
]
