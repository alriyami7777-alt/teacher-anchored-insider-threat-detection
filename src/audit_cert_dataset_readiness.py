#!/usr/bin/env python3
"""CERT dataset readiness audit for releases 4.2, 5.2, and 6.2.

Preparation only:
  - no model training
  - no test-set evaluation
  - no writes into raw activity or answer folders
  - does not modify V1 / Objective 2 / Objective 3 artefacts

Examples:
  python scripts/audit_cert_dataset_readiness.py --dataset-version 5.2 --smoke
  python scripts/audit_cert_dataset_readiness.py --dataset-version 6.2 --smoke
  python scripts/audit_cert_dataset_readiness.py --dataset-version 5.2
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from cert_data_quality import (  # noqa: E402
    detect_aux_files,
    inventory_release_files,
    ldap_coverage,
    scan_log_quality,
)
from cert_ground_truth import (  # noqa: E402
    build_duplicate_event_id_detail_rows,
    load_answer_events,
    load_existing_match_summary,
    match_answer_ids_against_raw,
    resolve_matched_ids_from_summary,
    summarize_ground_truth,
)
from cert_schema_audit import (  # noqa: E402
    COMMON_13_FEATURES,
    assess_feature_compatibility,
    collect_release_schemas,
    compare_schemas,
    flatten_schema_comparison_rows,
)
from dataset_registry import (  # noqa: E402
    DatasetVersionError,
    add_dataset_path_arguments,
    assert_raw_is_readonly_target,
    check_optional_logs,
    check_required_logs,
    get_dataset_spec,
    normalize_dataset_version,
    print_resolved_paths,
    refuse_mixed_versions,
    resolve_dataset_paths,
    resolve_raw_dir_for_version,
    resolve_answers_dir,
)


AUDIT_ACTIONS_FORBIDDEN = (
    "train",
    "fit",
    "evaluate_test",
    "evaluate-test",
    "retrain",
)


def _refuse_training_flags(args: argparse.Namespace) -> None:
    for name in AUDIT_ACTIONS_FORBIDDEN:
        if getattr(args, name.replace("-", "_"), False):
            raise SystemExit(
                f"REFUSED: audit command must not perform '{name}'. "
                "This script is readiness-only (training_started=false, test_evaluated=false)."
            )


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        pd.DataFrame().to_csv(path, index=False)
        return
    pd.DataFrame(rows).to_csv(path, index=False)


def estimate_sequence_readiness(
    *,
    version: str,
    logon_report: dict[str, Any],
    gt_summary: dict[str, Any],
    window: int = 20,
) -> dict[str, Any]:
    """Estimate 20-day chronological sequence feasibility without building tensors."""
    n_users = logon_report.get("unique_users")
    min_ts = logon_report.get("min_timestamp")
    max_ts = logon_report.get("max_timestamp")
    if not min_ts or not max_ts or not n_users:
        return {
            "status": "insufficient_timestamp_or_user_stats",
            "unique_users": n_users,
            "date_range": [min_ts, max_ts],
            "notes": [
                "Need logon unique users and timestamp range. "
                "Re-run without --smoke or ensure logon scan completed."
            ],
        }

    start = datetime.strptime(min_ts[:19], "%Y-%m-%d %H:%M:%S")
    end = datetime.strptime(max_ts[:19], "%Y-%m-%d %H:%M:%S")
    n_calendar_days = (end.date() - start.date()).days + 1
    # Dense coverage assumption used by r4.2 densify step: every user × every day.
    estimated_user_days_dense = int(n_users) * int(n_calendar_days)
    # Active user-days unknown without full interval build; approximate from logon rows
    # as a lower bound proxy (one row ≠ one user-day, but order-of-magnitude).
    logon_rows = int(logon_report.get("row_count") or 0)
    approx_active_user_days = min(estimated_user_days_dense, logon_rows)

    users_lt_20 = None  # unknown without per-user day histogram
    # Under dense calendar construction (r4.2 style), each user contributes
    # max(n_calendar_days - window + 1, 0) sequences.
    seq_per_user = max(n_calendar_days - window + 1, 0)
    estimated_sequences = int(n_users) * seq_per_user

    insider_users = list(gt_summary.get("insider_users") or [])
    n_insiders = len(insider_users)
    # Positive sequences: without day-level labels we estimate a conservative band
    # using insider count × sequences-per-user as an upper-ish structural proxy,
    # and note that true positives are malicious-day windows only.
    estimated_positive_upper = n_insiders * seq_per_user
    estimated_class_imbalance = (
        None
        if estimated_sequences == 0 or n_insiders == 0
        else round(estimated_sequences / max(estimated_positive_upper, 1), 1)
    )

    # Chronological boundaries (80/10/10 by calendar), matching r4.2 practice.
    span = n_calendar_days
    train_days = int(span * 0.8)
    val_days = int(span * 0.1)
    test_days = span - train_days - val_days
    train_end = start.date() + timedelta(days=max(train_days - 1, 0))
    val_end = train_end + timedelta(days=max(val_days, 0))
    test_end = end.date()

    split_proposal: dict[str, Any] = {
        "method": "chronological_80_10_10_calendar",
        "train": {"start": str(start.date()), "end": str(train_end)},
        "validation": {
            "start": str(train_end + timedelta(days=1)),
            "end": str(val_end),
        },
        "test": {
            "start": str(val_end + timedelta(days=1)),
            "end": str(test_end),
        },
    }

    notes: list[str] = [
        "Estimates assume densified user-day calendars similar to r4.2.",
        "Positive counts are structural upper bounds (insider × sequences/user), "
        "not verified malicious-window counts.",
        "Do not use future confirmatory/test outcomes for architecture search.",
    ]

    if version == "5.2":
        notes.append(
            "r5.2 is the primary untouched confirmatory dataset; keep test sealed."
        )
        notes.append(
            "Proposed chronological split should be checked to ensure validation/test "
            "contain malicious sequences and distinct insiders before any V2 training."
        )
    elif version == "6.2":
        notes.append(
            "r6.2 has only five insiders; a conventional chronological split may leave "
            "validation/test without meaningful positive coverage."
        )
        split_proposal = {
            "method": "do_not_force_chronological_if_positives_missing",
            "chronological_80_10_10_calendar": {
                "train": {"start": str(start.date()), "end": str(train_end)},
                "validation": {
                    "start": str(train_end + timedelta(days=1)),
                    "end": str(val_end),
                },
                "test": {
                    "start": str(val_end + timedelta(days=1)),
                    "end": str(test_end),
                },
                "defensible": False,
                "reason": "Only five insiders; chronological folds risk empty positives.",
            },
            "recommended_alternatives": [
                "leave_one_insider_out",
                "grouped_cross_validation_by_insider",
                "scenario_based_evaluation",
                "external_stress_testing_without_tuning_on_r6.2",
            ],
        }

    return {
        "status": "estimated",
        "window_days": window,
        "unique_users": n_users,
        "date_range": [min_ts, max_ts],
        "n_calendar_days": n_calendar_days,
        "estimated_user_days_dense": estimated_user_days_dense,
        "approx_active_user_days_from_logon_rows": approx_active_user_days,
        "dense_calendar_coverage_assumed": True,
        "users_with_fewer_than_20_days": users_lt_20,
        "estimated_20day_sequence_count": estimated_sequences,
        "estimated_positive_sequence_count_upper": estimated_positive_upper,
        "positive_users_insiders": n_insiders,
        "insider_users": insider_users,
        "estimated_class_imbalance_sequences_per_positive_upper": estimated_class_imbalance,
        "insiders_in_proposed_splits": "unknown_until_day_level_labels",
        "split_proposal": split_proposal,
        "notes": notes,
    }


def export_gt_duplicates_only(args: argparse.Namespace) -> int:
    """Write duplicate GT ID CSV from answer records + existing match summary."""
    _refuse_training_flags(args)
    version = normalize_dataset_version(args.dataset_version)
    paths = resolve_dataset_paths(
        version,
        raw_dir=args.raw_dir,
        answers_dir=args.answers_dir,
        processed_dir=args.processed_dir,
        output_dir=args.output_dir,
    )
    print_resolved_paths(paths)
    out_dir = paths.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    print("Loading answer-package records (no raw activity rescan)...")
    records, diagnostics = load_answer_events(paths.answers_dir, version)
    match_summary = load_existing_match_summary(out_dir) or {
        "skipped": True,
        "reason": "no existing matching summary",
    }
    matched_ids, matching_known = resolve_matched_ids_from_summary(
        match_summary, records
    )
    duplicate_rows = build_duplicate_event_id_detail_rows(
        records,
        version,
        matched_event_ids=matched_ids,
        matching_status_known=matching_known,
    )
    out_path = out_dir / "ground_truth_duplicate_event_ids.csv"
    _write_csv(out_path, duplicate_rows)

    # Preserve existing manifest / summary; only append artifact name when present.
    manifest_path = out_dir / "readiness_manifest.json"
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            artifacts = list(manifest.get("artifacts") or [])
            if "ground_truth_duplicate_event_ids.csv" not in artifacts:
                artifacts.append("ground_truth_duplicate_event_ids.csv")
            manifest["artifacts"] = artifacts
            manifest["training_started"] = False
            manifest["test_evaluated"] = False
            manifest["gt_duplicate_export_at"] = datetime.now().isoformat(
                timespec="seconds"
            )
            manifest["n_duplicate_event_ids"] = len(
                {r["event_id"] for r in duplicate_rows}
            )
            manifest["n_duplicate_event_id_rows"] = len(duplicate_rows)
            manifest["gt_duplicate_matching_status_known"] = matching_known
            _write_json(manifest_path, manifest)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"WARNING: could not update readiness_manifest.json: {exc}")

    print()
    print("=" * 72)
    print(f"GT DUPLICATE EXPORT — CERT {version}")
    print("=" * 72)
    print(f"Answers            : {paths.answers_dir}")
    print(f"Output             : {out_path}")
    print(f"Answer records     : {len(records):,}")
    print(f"Malformed rows     : {diagnostics.get('malformed_rows')}")
    print(f"Duplicate ID rows  : {len(duplicate_rows):,}")
    print(f"Distinct dup IDs   : {len({r['event_id'] for r in duplicate_rows}):,}")
    print(f"Matching known     : {matching_known}")
    print(f"Match summary src  : {'existing' if match_summary else 'none'}")
    print("training_started   : false")
    print("test_evaluated     : false")
    print("=" * 72)
    return 0


def run_audit(args: argparse.Namespace) -> int:
    if getattr(args, "export_gt_duplicates_only", False):
        return export_gt_duplicates_only(args)

    _refuse_training_flags(args)
    version = normalize_dataset_version(args.dataset_version)
    spec = get_dataset_spec(version)

    paths = resolve_dataset_paths(
        version,
        raw_dir=args.raw_dir,
        answers_dir=args.answers_dir,
        processed_dir=args.processed_dir,
        output_dir=args.output_dir,
    )
    print_resolved_paths(paths)
    assert_raw_is_readonly_target(paths.raw_dir)
    refuse_mixed_versions(version, paths.raw_dir)

    out_dir = paths.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = out_dir / "_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    warnings: list[str] = []
    blocking: list[str] = []

    # --- File inventory ---
    inventory = inventory_release_files(paths.raw_dir)
    _write_csv(out_dir / "dataset_file_inventory.csv", inventory)

    present, missing = check_required_logs(paths.raw_dir, spec)
    optional = check_optional_logs(paths.raw_dir, spec)
    if missing:
        blocking.append(f"missing required logs: {', '.join(missing)}")
    for opt_name, opt_present in optional.items():
        if not opt_present:
            warnings.append(
                f"optional release-specific log absent: {opt_name}.csv "
                "(non-blocking for core-schema audit)"
            )

    ldap = ldap_coverage(paths.raw_dir)
    aux = detect_aux_files(paths.raw_dir)
    if spec.expects_ldap and not ldap["present"]:
        warnings.append("LDAP directory missing")
    if not aux["readme_present"]:
        warnings.append("readme.txt missing")

    # --- Per-log quality (chunked) ---
    max_rows = args.max_rows_per_file
    if args.smoke and max_rows is None:
        max_rows = 50_000

    quality_rows: list[dict[str, Any]] = []
    quality_by_log: dict[str, dict[str, Any]] = {}
    logs_to_scan = list(spec.required_logs) + list(spec.optional_logs)
    # In smoke mode, skip full scans of huge http/email — header + limited rows only.
    for log_name in logs_to_scan:
        path = paths.raw_dir / f"{log_name}.csv"
        if log_name in spec.optional_logs and not path.is_file():
            quality_by_log[log_name] = {
                "log_name": log_name,
                "exists": False,
                "optional": True,
                "status": "optional_absent",
            }
            quality_rows.append(quality_by_log[log_name])
            continue
        log_max = max_rows
        if args.smoke and log_name in {"http", "email"} and path.is_file():
            # Keep smoke audits short on 10–90 GB files.
            log_max = min(log_max or 50_000, 20_000)
        elif args.smoke and log_name == "logon":
            # logon is small enough to fully scan for user/date coverage estimates.
            log_max = None
        elif args.smoke and log_name in {"psychometric", "decoy_file"}:
            log_max = None
        report = scan_log_quality(
            path,
            log_name,
            max_rows=log_max,
            track_duplicate_ids=not args.smoke or log_name in {"logon", "device", "file"},
            track_duplicate_rows=log_name in {"psychometric", "decoy_file"},
        )
        payload = report.as_dict()
        payload["optional"] = log_name in spec.optional_logs
        quality_by_log[log_name] = payload
        # Flatten missingness for CSV
        flat = {
            k: v
            for k, v in payload.items()
            if k not in {"header", "missing_by_column", "notes"}
        }
        flat["header"] = ";".join(payload.get("header") or [])
        flat["notes"] = " | ".join(payload.get("notes") or [])
        miss = payload.get("missing_by_column") or {}
        flat["missing_values_json"] = json.dumps(miss)
        quality_rows.append(flat)
        if payload.get("status", "").startswith("scan_error"):
            blocking.append(f"{log_name}: {payload['status']}")

    _write_csv(out_dir / "dataset_data_quality.csv", quality_rows)

    # --- Schema comparison (this release + others if resolvable) ---
    version_to_raw: dict[str, Path] = {version: paths.raw_dir}
    for other in ("4.2", "5.2", "6.2"):
        if other == version:
            continue
        try:
            other_raw, _ = resolve_raw_dir_for_version(other)
            version_to_raw[other] = other_raw
        except Exception as exc:
            warnings.append(f"schema comparison: could not resolve {other}: {exc}")

    schemas = collect_release_schemas(version_to_raw)
    schema_rows = compare_schemas(schemas)
    _write_csv(
        out_dir / "dataset_schema_comparison.csv",
        flatten_schema_comparison_rows(schema_rows),
    )
    feature_rows = assess_feature_compatibility(schemas)
    _write_csv(out_dir / "feature_compatibility.csv", feature_rows)

    incompatible_features = [
        r["feature_name"]
        for r in feature_rows
        if r.get("exclude_from_common_space") != "yes"
        and (
            (
                version == "5.2"
                and (not r.get("available_r5.2") or r.get("mapping_r5.2") == "incompatible")
            )
            or (
                version == "6.2"
                and (not r.get("available_r6.2") or r.get("mapping_r6.2") == "incompatible")
            )
        )
    ]
    if incompatible_features:
        blocking.append(
            "common-13 feature incompatibilities: " + ", ".join(incompatible_features)
        )

    # --- Ground truth ---
    gt_summary = summarize_ground_truth(paths.answers_dir, version)
    gt_csv_row = {
        "dataset_version": version,
        "insiders_csv": gt_summary.get("insiders_csv"),
        "n_insider_rows": gt_summary.get("n_insider_rows"),
        "n_insider_users": gt_summary.get("n_insider_users"),
        "insider_counts_by_scenario": json.dumps(gt_summary.get("insider_counts_by_scenario")),
        "n_answer_records": gt_summary.get("n_answer_records"),
        "n_unique_event_ids": gt_summary.get("n_unique_event_ids"),
        "n_duplicate_event_ids": gt_summary.get("n_duplicate_event_ids"),
        "malformed_rows": gt_summary.get("malformed_rows"),
        "missing_scenario_sources": ";".join(gt_summary.get("missing_scenario_sources") or []),
        "event_type_counts": json.dumps(gt_summary.get("event_type_counts")),
        "scenario_event_counts": json.dumps(gt_summary.get("scenario_event_counts")),
        "answer_format": gt_summary.get("answer_format"),
    }
    _write_csv(out_dir / "ground_truth_summary.csv", [gt_csv_row])

    if gt_summary.get("n_insider_users", 0) == 0:
        blocking.append("no insiders resolved for this dataset version")
    if gt_summary.get("missing_scenario_sources"):
        blocking.append(
            "missing answer scenario sources: "
            + ", ".join(gt_summary["missing_scenario_sources"])
        )
    if gt_summary.get("n_answer_records", 0) == 0:
        blocking.append("no answer event records parsed")

    # Matching: smoke = limited scan; full = complete stream (long on http).
    # Prefer reusing records already parsed for the GT summary when possible.
    records, _ = load_answer_events(paths.answers_dir, version)
    match_max = args.match_max_rows_per_file
    if args.smoke and match_max is None:
        match_max = 100_000
    existing_match = load_existing_match_summary(out_dir)
    if args.skip_id_matching:
        match_summary = existing_match or {
            "skipped": True,
            "reason": "--skip-id-matching",
            "n_target_ids": len({r.event_id for r in records}),
            "n_matched_ids": None,
            "n_unmatched_ids": None,
        }
        if existing_match and not existing_match.get("skipped"):
            warnings.append(
                "ground-truth ID matching reused from existing readiness summary "
                "(no raw rescan)"
            )
        else:
            warnings.append("ground-truth ID matching skipped by flag")
    else:
        print("Matching answer event IDs against raw logs (streaming)...")
        match_summary = match_answer_ids_against_raw(
            records,
            paths.raw_dir,
            max_scan_rows_per_file=match_max,
        )
        if match_summary.get("partial_scan"):
            warnings.append(
                "ground-truth matching used a row cap (partial); "
                "unmatched counts may include not-yet-scanned IDs"
            )
        elif match_summary.get("n_unmatched_ids", 0) > 0:
            warnings.append(
                f"unmatched ground-truth IDs: {match_summary['n_unmatched_ids']}"
            )

    matched_ids, matching_known = resolve_matched_ids_from_summary(
        match_summary, records
    )
    duplicate_rows = build_duplicate_event_id_detail_rows(
        records,
        version,
        matched_event_ids=matched_ids,
        matching_status_known=matching_known,
    )
    _write_csv(out_dir / "ground_truth_duplicate_event_ids.csv", duplicate_rows)
    if duplicate_rows:
        n_dup_ids = len({r["event_id"] for r in duplicate_rows})
        warnings.append(
            f"duplicate ground-truth event IDs: {n_dup_ids} IDs across "
            f"{len(duplicate_rows)} answer rows "
            f"(see ground_truth_duplicate_event_ids.csv)"
        )

    _write_csv(
        out_dir / "ground_truth_matching_summary.csv",
        [
            {
                "dataset_version": version,
                "n_target_ids": match_summary.get("n_target_ids"),
                "n_matched_ids": match_summary.get("n_matched_ids"),
                "n_unmatched_ids": match_summary.get("n_unmatched_ids"),
                "matched_by_type": json.dumps(match_summary.get("matched_by_type")),
                "rows_scanned_by_type": json.dumps(
                    match_summary.get("rows_scanned_by_type")
                ),
                "partial_scan": match_summary.get("partial_scan"),
                "skipped": match_summary.get("skipped", False),
                "missing_or_invalid_raw_files": ";".join(
                    match_summary.get("missing_or_invalid_raw_files") or []
                ),
                "n_duplicate_event_id_rows": len(duplicate_rows),
                "n_duplicate_event_ids": len({r["event_id"] for r in duplicate_rows}),
            }
        ],
    )

    # --- Sequence readiness ---
    logon_q = quality_by_log.get("logon") or {}
    sequence_est = estimate_sequence_readiness(
        version=version,
        logon_report=logon_q,
        gt_summary=gt_summary,
        window=20,
    )

    # --- Readiness verdict ---
    ready_for_preprocessing = len(blocking) == 0
    ready_for_stress_prep = version == "6.2" and ready_for_preprocessing
    ready_for_confirmatory_prep = version == "5.2" and ready_for_preprocessing

    summary = {
        "dataset_version": version,
        "release_tag": spec.release_tag,
        "resolved_paths": paths.as_dict(),
        "answers_resolved": True,
        "required_logs_present": present,
        "required_logs_missing": missing,
        "optional_logs": optional,
        "ldap": ldap,
        "aux_files": aux,
        "file_inventory_count": len(inventory),
        "ground_truth": {
            "n_insiders": gt_summary.get("n_insider_users"),
            "n_answer_records": gt_summary.get("n_answer_records"),
            "n_duplicate_event_ids": gt_summary.get("n_duplicate_event_ids"),
            "n_duplicate_event_id_rows": len(duplicate_rows),
            "scenario_distribution": gt_summary.get("insider_counts_by_scenario"),
            "event_type_counts": gt_summary.get("event_type_counts"),
        },
        "ground_truth_matching": {
            k: v
            for k, v in match_summary.items()
            if k not in {"matched_event_ids", "unmatched_event_ids"}
        },
        "feature_schema_compatibility": {
            "common_13_features": list(COMMON_13_FEATURES),
            "incompatible_features": incompatible_features,
            "all_common_13_ok": len(incompatible_features) == 0,
        },
        "sequence_readiness": sequence_est,
        "warnings": warnings,
        "blocking_issues": blocking,
        "ready_for_preprocessing": ready_for_preprocessing,
        "ready_for_confirmatory_prep_r5_2": ready_for_confirmatory_prep,
        "ready_for_stress_test_prep_r6_2": ready_for_stress_prep,
        "mode": "smoke" if args.smoke else "full",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "training_started": False,
        "test_evaluated": False,
    }
    _write_json(out_dir / "dataset_readiness_summary.json", summary)

    manifest = {
        "dataset_version": version,
        "raw_dir": str(paths.raw_dir),
        "answers_dir": str(paths.answers_dir),
        "output_dir": str(out_dir),
        "processed_dir": str(paths.processed_dir),
        "artifacts": [
            "dataset_readiness_summary.json",
            "dataset_file_inventory.csv",
            "dataset_schema_comparison.csv",
            "dataset_data_quality.csv",
            "ground_truth_summary.csv",
            "ground_truth_matching_summary.csv",
            "ground_truth_duplicate_event_ids.csv",
            "feature_compatibility.csv",
            "readiness_manifest.json",
        ],
        "training_started": False,
        "test_evaluated": False,
        "chapters_3_4_modified": False,
        "v1_outputs_modified": False,
        "objective2_outputs_modified": False,
        "objective3_outputs_modified": False,
        "smoke": bool(args.smoke),
        "generated_at": summary["generated_at"],
        "ready_for_preprocessing": ready_for_preprocessing,
        "blocking_issues": blocking,
        "warnings": warnings,
    }
    _write_json(out_dir / "readiness_manifest.json", manifest)

    # Cache non-sensitive summary for resume/reuse.
    _write_json(cache_dir / "last_summary.json", summary)

    # --- Terminal summary ---
    print()
    print("=" * 72)
    print(f"READINESS SUMMARY — CERT {version}")
    print("=" * 72)
    print(f"Raw                : {paths.raw_dir}")
    print(f"Answers            : {paths.answers_dir}")
    print(f"Output             : {out_dir}")
    print(f"Required logs OK   : {not missing} ({', '.join(present) or 'none'})")
    print(f"Optional logs      : {optional}")
    print(f"LDAP files         : {ldap.get('n_files')}")
    print(f"Insiders           : {gt_summary.get('n_insider_users')}")
    print(f"Answer events      : {gt_summary.get('n_answer_records')}")
    print(
        f"Duplicate GT IDs   : {len({r['event_id'] for r in duplicate_rows})} "
        f"({len(duplicate_rows)} rows)"
    )
    print(
        f"GT matched/unmatched: {match_summary.get('n_matched_ids')}/"
        f"{match_summary.get('n_unmatched_ids')} "
        f"(partial={match_summary.get('partial_scan')})"
    )
    print(f"Common-13 OK       : {len(incompatible_features) == 0}")
    if sequence_est.get("status") == "estimated":
        print(
            f"Est. sequences     : {sequence_est.get('estimated_20day_sequence_count'):,}"
        )
        print(
            f"Est. pos. upper    : "
            f"{sequence_est.get('estimated_positive_sequence_count_upper'):,}"
        )
    print(f"Warnings ({len(warnings)}):")
    for w in warnings[:12]:
        print(f"  - {w}")
    print(f"Blocking ({len(blocking)}):")
    for b in blocking[:12]:
        print(f"  - {b}")
    print(f"Ready preprocessing: {ready_for_preprocessing}")
    print("training_started   : false")
    print("test_evaluated     : false")
    print("=" * 72)
    return 0 if ready_for_preprocessing else 2


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    add_dataset_path_arguments(p, default_version="5.2")
    p.add_argument(
        "--smoke",
        action="store_true",
        help="Fast partial scan (row caps on large CSVs). Use before full audits.",
    )
    p.add_argument(
        "--max-rows-per-file",
        type=int,
        default=None,
        help="Optional hard cap on rows scanned per activity log.",
    )
    p.add_argument(
        "--match-max-rows-per-file",
        type=int,
        default=None,
        help="Optional cap when matching answer IDs to raw logs.",
    )
    p.add_argument(
        "--skip-id-matching",
        action="store_true",
        help="Skip streaming ID matching (inventory/schema/GT parse only).",
    )
    p.add_argument(
        "--export-gt-duplicates-only",
        action="store_true",
        help=(
            "Only load answer-package records and write "
            "ground_truth_duplicate_event_ids.csv using any existing matching "
            "summary. Does not scan raw activity logs or rewrite other audits."
        ),
    )
    # Trap accidental training/eval flags.
    p.add_argument("--train", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--fit", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--evaluate-test", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--retrain", action="store_true", help=argparse.SUPPRESS)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return run_audit(args)
    except (DatasetVersionError, FileNotFoundError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
