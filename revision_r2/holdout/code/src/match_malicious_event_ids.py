#!/usr/bin/env python3
"""Match CERT r4.2 answer-file event IDs to raw activity logs (no modelling)."""

from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

EVENT_TYPES = ("logon", "device", "file", "email", "http")

RAW_LOG_FILES = {
    "logon": "logon.csv",
    "device": "device.csv",
    "file": "file.csv",
    "email": "email.csv",
    "http": "http.csv",
}

# Columns to keep from raw logs (exclude large free-text content where possible).
RAW_KEEP_COLUMNS = {
    "logon": ["id", "date", "user", "pc", "activity"],
    "device": ["id", "date", "user", "pc", "activity"],
    "file": ["id", "date", "user", "pc", "filename"],
    "email": ["id", "date", "user", "pc", "to", "cc", "bcc", "from", "size", "attachments"],
    "http": ["id", "date", "user", "pc", "url"],
}


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def resolve_raw_dir(raw_dir: Path) -> Path:
    """Prefer data/raw/r4.2 when present (legacy r4.2-compatible)."""
    try:
        from dataset_registry import resolve_raw_dir_legacy_r42

        return resolve_raw_dir_legacy_r42(raw_dir)
    except Exception:
        candidate = raw_dir / "r4.2"
        return candidate if candidate.is_dir() else raw_dir


def user_id_from_filename(path: Path) -> str:
    stem = path.stem
    return stem.split("-")[-1] if "-" in stem else stem


def collect_answer_event_ids(answers_dir: Path) -> dict[str, dict]:
    """Return mapping event_id -> answer-side metadata."""
    events: dict[str, dict] = {}
    duplicates = 0

    for scenario in ("r4.2-1", "r4.2-2", "r4.2-3"):
        folder = answers_dir / scenario
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.csv")):
            user_id = user_id_from_filename(path)
            with path.open("r", encoding="utf-8", newline="") as handle:
                for row_num, row in enumerate(csv.reader(handle), start=1):
                    if not row or all(not (c or "").strip() for c in row):
                        continue
                    event_type = (row[0] or "").strip().lower()
                    event_id = (row[1] or "").strip() if len(row) > 1 else ""
                    if not event_id.startswith("{") or not event_id.endswith("}"):
                        continue
                    record = {
                        "event_id": event_id,
                        "event_type": event_type,
                        "answer_scenario_group": scenario,
                        "answer_user": user_id,
                        "answer_file": str(path.relative_to(answers_dir)),
                        "answer_row": row_num,
                    }
                    if event_id in events:
                        duplicates += 1
                    events[event_id] = record

    return events


def match_event_type(
    event_type: str,
    target_ids: set[str],
    raw_path: Path,
) -> dict[str, dict]:
    """Stream one raw log and return matched rows keyed by event id."""
    if not target_ids:
        return {}
    if not raw_path.exists():
        raise FileNotFoundError(f"Raw log not found: {raw_path}")

    keep = RAW_KEEP_COLUMNS[event_type]
    matched: dict[str, dict] = {}
    remaining = set(target_ids)
    rows_scanned = 0

    print(f"Scanning {raw_path.name} for {len(target_ids):,} {event_type} IDs...")

    with raw_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or "id" not in reader.fieldnames:
            raise ValueError(f"{raw_path} has no 'id' column; fields={reader.fieldnames}")

        for row in reader:
            rows_scanned += 1
            if rows_scanned % 2_000_000 == 0:
                print(
                    f"  {raw_path.name}: scanned {rows_scanned:,} rows; "
                    f"matched {len(matched):,}; remaining {len(remaining):,}"
                )

            event_id = (row.get("id") or "").strip()
            if event_id not in remaining:
                continue

            matched[event_id] = {col: (row.get(col) or "") for col in keep if col in row}
            remaining.remove(event_id)
            if not remaining:
                break

    print(
        f"  {raw_path.name}: done. scanned {rows_scanned:,}; "
        f"matched {len(matched):,}; unmatched {len(remaining):,}"
    )
    return matched


def write_matched_csv(
    path: Path,
    answer_events: dict[str, dict],
    matches_by_type: dict[str, dict[str, dict]],
) -> int:
    fieldnames = [
        "event_id",
        "event_type",
        "answer_scenario_group",
        "answer_user",
        "answer_file",
        "answer_row",
        "raw_date",
        "raw_user",
        "raw_pc",
        "raw_activity",
        "raw_filename",
        "raw_url",
        "raw_to",
        "raw_cc",
        "raw_bcc",
        "raw_from",
        "raw_size",
        "raw_attachments",
        "match_status",
    ]

    written = 0
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()

        for event_id, answer in sorted(
            answer_events.items(),
            key=lambda item: (
                item[1]["event_type"],
                item[1]["answer_scenario_group"],
                item[1]["answer_user"],
                item[1]["answer_row"],
            ),
        ):
            event_type = answer["event_type"]
            raw = matches_by_type.get(event_type, {}).get(event_id)
            if raw is None:
                continue

            writer.writerow(
                {
                    "event_id": event_id,
                    "event_type": event_type,
                    "answer_scenario_group": answer["answer_scenario_group"],
                    "answer_user": answer["answer_user"],
                    "answer_file": answer["answer_file"],
                    "answer_row": answer["answer_row"],
                    "raw_date": raw.get("date", ""),
                    "raw_user": raw.get("user", ""),
                    "raw_pc": raw.get("pc", ""),
                    "raw_activity": raw.get("activity", ""),
                    "raw_filename": raw.get("filename", ""),
                    "raw_url": raw.get("url", ""),
                    "raw_to": raw.get("to", ""),
                    "raw_cc": raw.get("cc", ""),
                    "raw_bcc": raw.get("bcc", ""),
                    "raw_from": raw.get("from", ""),
                    "raw_size": raw.get("size", ""),
                    "raw_attachments": raw.get("attachments", ""),
                    "match_status": "matched",
                }
            )
            written += 1

    return written


def write_summary_csv(
    path: Path,
    answer_counts: Counter,
    matched_counts: Counter,
    unmatched_by_type: dict[str, list[str]],
) -> None:
    fieldnames = [
        "event_type",
        "malicious_event_ids",
        "matched",
        "unmatched",
        "match_rate",
        "raw_log_file",
        "raw_id_column",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for event_type in EVENT_TYPES:
            total = answer_counts.get(event_type, 0)
            matched = matched_counts.get(event_type, 0)
            unmatched = total - matched
            rate = f"{(matched / total):.4f}" if total else ""
            writer.writerow(
                {
                    "event_type": event_type,
                    "malicious_event_ids": total,
                    "matched": matched,
                    "unmatched": unmatched,
                    "match_rate": rate,
                    "raw_log_file": RAW_LOG_FILES[event_type],
                    "raw_id_column": "id",
                }
            )

        total_all = sum(answer_counts.values())
        matched_all = sum(matched_counts.values())
        writer.writerow(
            {
                "event_type": "ALL",
                "malicious_event_ids": total_all,
                "matched": matched_all,
                "unmatched": total_all - matched_all,
                "match_rate": f"{(matched_all / total_all):.4f}" if total_all else "",
                "raw_log_file": "",
                "raw_id_column": "id",
            }
        )


def append_notes(
    notes_path: Path,
    answers_dir: Path,
    raw_dir: Path,
    answer_counts: Counter,
    matched_counts: Counter,
    unmatched_by_type: dict[str, list[str]],
    summary_path: Path,
    matched_path: Path,
    id_column_notes: list[str],
) -> None:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total = sum(answer_counts.values())
    matched_total = sum(matched_counts.values())
    unmatched_total = total - matched_total

    with notes_path.open("a", encoding="utf-8") as f:
        f.write(f"\n\n## CERT r4.2 malicious event ID mapping ({stamp})\n\n")
        f.write("Mapped answer-file malicious event IDs onto raw r4.2 activity logs. No model training.\n\n")
        f.write(f"Answers folder: `{answers_dir}`\n\n")
        f.write(f"Raw data folder: `{raw_dir}`\n\n")

        f.write("### Raw log event ID columns\n\n")
        for line in id_column_notes:
            f.write(f"- {line}\n")
        f.write("\n")

        f.write("### Match results by event type\n\n")
        f.write("| Event type | Malicious IDs | Matched | Unmatched | Match rate |\n")
        f.write("|------------|---------------|---------|-----------|------------|\n")
        for event_type in EVENT_TYPES:
            total_t = answer_counts.get(event_type, 0)
            matched_t = matched_counts.get(event_type, 0)
            unmatched_t = total_t - matched_t
            rate = f"{(matched_t / total_t * 100):.1f}%" if total_t else "n/a"
            f.write(
                f"| {event_type} | {total_t} | {matched_t} | {unmatched_t} | {rate} |\n"
            )
        rate_all = f"{(matched_total / total * 100):.1f}%" if total else "n/a"
        f.write(
            f"| **ALL** | **{total}** | **{matched_total}** | **{unmatched_total}** | **{rate_all}** |\n\n"
        )

        f.write("### Unmatched event IDs\n\n")
        if unmatched_total == 0:
            f.write("None — every malicious event ID from the r4.2 answer files was found in the corresponding raw log.\n\n")
        else:
            for event_type in EVENT_TYPES:
                ids = unmatched_by_type.get(event_type, [])
                if not ids:
                    continue
                f.write(f"- `{event_type}`: **{len(ids)}** unmatched\n")
                preview = ids[:20]
                f.write(f"  - Sample: {preview}\n")
            f.write("\n")

        f.write("### Findings\n\n")
        f.write(
            "- All inspected raw activity logs expose a primary key column named `id` "
            "with the same brace-wrapped CERT event-ID format used in answer files.\n"
        )
        f.write(
            "- Answer-file column 1 (after event type) is the join key to raw `id`.\n"
        )
        f.write(
            f"- Overall match rate: **{matched_total}/{total}** ({rate_all}).\n"
        )
        f.write("\n### Generated output files\n\n")
        f.write(f"- `{summary_path}`\n")
        f.write(f"- `{matched_path}`\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Match r4.2 answer malicious event IDs to raw CERT logs."
    )
    parser.add_argument(
        "--answers",
        default="answers/answers",
        help="Path to CERT answers folder (default: answers/answers)",
    )
    parser.add_argument(
        "--raw",
        default="data/raw",
        help="Path to raw data folder or r4.2 folder (default: data/raw)",
    )
    args = parser.parse_args()

    root = repo_root()
    answers_dir = Path(args.answers)
    if not answers_dir.is_absolute():
        answers_dir = (root / answers_dir).resolve()
    raw_dir = Path(args.raw)
    if not raw_dir.is_absolute():
        raw_dir = (root / raw_dir).resolve()
    raw_dir = resolve_raw_dir(raw_dir)

    if not answers_dir.exists():
        raise FileNotFoundError(f"Answers folder not found: {answers_dir}")
    if not raw_dir.exists():
        raise FileNotFoundError(f"Raw data folder not found: {raw_dir}")

    outputs_dir = root / "outputs" / "ground_truth"
    docs_dir = root / "docs"
    outputs_dir.mkdir(parents=True, exist_ok=True)
    docs_dir.mkdir(exist_ok=True)

    summary_path = outputs_dir / "r42_malicious_event_id_mapping_summary.csv"
    matched_path = outputs_dir / "r42_matched_malicious_events.csv"
    notes_path = docs_dir / "cert_r42_notes.md"

    print("=" * 90)
    print("CERT r4.2 malicious event ID mapping")
    print("=" * 90)
    print(f"Answers: {answers_dir}")
    print(f"Raw:     {raw_dir}")
    print()

    # Inspect raw ID columns
    id_column_notes: list[str] = []
    for event_type, filename in RAW_LOG_FILES.items():
        path = raw_dir / filename
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.reader(handle)
            header = next(reader)
            sample = next(reader, None)
        sample_id = sample[0] if sample else ""
        note = (
            f"`{filename}` columns include `{header}`; "
            f"event ID column is `id` (sample: `{sample_id}`)."
        )
        id_column_notes.append(note)
        print(note)

    print()
    answer_events = collect_answer_event_ids(answers_dir)
    answer_counts: Counter = Counter(e["event_type"] for e in answer_events.values())
    print(f"Collected {len(answer_events):,} unique malicious event IDs")
    for event_type in EVENT_TYPES:
        print(f"  {event_type}: {answer_counts.get(event_type, 0)}")
    print()

    ids_by_type: dict[str, set[str]] = defaultdict(set)
    for event_id, meta in answer_events.items():
        ids_by_type[meta["event_type"]].add(event_id)

    matches_by_type: dict[str, dict[str, dict]] = {}
    matched_counts: Counter = Counter()
    unmatched_by_type: dict[str, list[str]] = {}

    for event_type in EVENT_TYPES:
        targets = ids_by_type.get(event_type, set())
        raw_path = raw_dir / RAW_LOG_FILES[event_type]
        matched = match_event_type(event_type, targets, raw_path)
        matches_by_type[event_type] = matched
        matched_counts[event_type] = len(matched)
        unmatched = sorted(targets - set(matched.keys()))
        unmatched_by_type[event_type] = unmatched

    write_summary_csv(summary_path, answer_counts, matched_counts, unmatched_by_type)
    written = write_matched_csv(matched_path, answer_events, matches_by_type)
    append_notes(
        notes_path,
        answers_dir,
        raw_dir,
        answer_counts,
        matched_counts,
        unmatched_by_type,
        summary_path.relative_to(root),
        matched_path.relative_to(root),
        id_column_notes,
    )

    print()
    print("Summary by event type:")
    for event_type in EVENT_TYPES:
        total = answer_counts.get(event_type, 0)
        matched = matched_counts.get(event_type, 0)
        print(f"  {event_type}: matched {matched}/{total}; unmatched {total - matched}")
    total = sum(answer_counts.values())
    matched_total = sum(matched_counts.values())
    print(f"  ALL: matched {matched_total}/{total}; unmatched {total - matched_total}")
    print()
    print(f"Wrote {summary_path}")
    print(f"Wrote {matched_path} ({written:,} rows)")
    print(f"Appended notes to {notes_path}")


if __name__ == "__main__":
    main()
