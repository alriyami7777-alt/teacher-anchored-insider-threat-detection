from pathlib import Path
from datetime import datetime
from collections import Counter
import argparse
import csv
import re

import pandas as pd


EVENT_ID_RE = re.compile(r"^\{[A-Z0-9]+-[A-Z0-9]+-[A-Z0-9]+\}$")
USER_FROM_FILENAME_RE = re.compile(r"r4\.2-[123]-([A-Z0-9]+)\.csv$", re.IGNORECASE)
TIMESTAMP_FORMATS = (
    "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y %H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
)


def parse_timestamp(value: str):
    text = (value or "").strip()
    if not text:
        return None
    for fmt in TIMESTAMP_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def looks_like_event_id(value: str) -> bool:
    return bool(EVENT_ID_RE.match((value or "").strip()))


def is_r42_insider_row(row: pd.Series) -> bool:
    dataset = str(row.get("dataset", "")).strip()
    details = str(row.get("details", "")).lower()
    return dataset == "4.2" or "r4.2" in details


def find_insiders_csv(answers_dir: Path) -> Path | None:
    direct = answers_dir / "insiders.csv"
    if direct.exists():
        return direct
    matches = list(answers_dir.rglob("insiders.csv"))
    return matches[0] if matches else None


def find_r42_per_user_files(answers_dir: Path) -> list[Path]:
    files = []
    for scenario in ("r4.2-1", "r4.2-2", "r4.2-3"):
        folder = answers_dir / scenario
        if not folder.is_dir():
            continue
        files.extend(sorted(folder.glob("*.csv")))
    return files


def user_id_from_filename(path: Path) -> str:
    match = USER_FROM_FILENAME_RE.search(path.name)
    if match:
        return match.group(1)
    # Fallback: last hyphen-separated token before .csv
    stem = path.stem
    return stem.split("-")[-1] if "-" in stem else stem


def summarize_per_user_file(path: Path, answers_dir: Path) -> dict:
    rel = path.relative_to(answers_dir)
    scenario_group = path.parent.name
    user_id = user_id_from_filename(path)

    event_types = Counter()
    timestamps = []
    event_ids_found = False
    row_count = 0

    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        for row in reader:
            if not row or all(not (cell or "").strip() for cell in row):
                continue
            row_count += 1
            event_type = (row[0] or "").strip()
            if event_type:
                event_types[event_type] += 1

            for cell in row:
                cell = (cell or "").strip()
                if not cell:
                    continue
                if looks_like_event_id(cell):
                    event_ids_found = True
                parsed = parse_timestamp(cell)
                if parsed is not None:
                    timestamps.append(parsed)

    earliest = min(timestamps).strftime("%Y-%m-%d %H:%M:%S") if timestamps else ""
    latest = max(timestamps).strftime("%Y-%m-%d %H:%M:%S") if timestamps else ""
    event_type_list = "; ".join(sorted(event_types.keys()))

    return {
        "relative_path": str(rel),
        "scenario_group": scenario_group,
        "user_id": user_id,
        "num_rows": row_count,
        "event_types": event_type_list,
        "event_type_counts": "; ".join(f"{k}:{v}" for k, v in sorted(event_types.items())),
        "earliest_timestamp": earliest,
        "latest_timestamp": latest,
        "has_event_ids": event_ids_found,
        "num_parseable_timestamps": len(timestamps),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Summarise CERT r4.2 ground-truth answer files (variable-length per-user CSVs)."
    )
    parser.add_argument(
        "--answers",
        required=True,
        help="Path to CERT answers folder, for example answers\\answers",
    )
    args = parser.parse_args()

    answers_dir = Path(args.answers)
    if not answers_dir.exists():
        raise FileNotFoundError(f"Answers folder not found: {answers_dir}")

    docs_dir = Path("docs")
    outputs_dir = Path("outputs") / "ground_truth"
    docs_dir.mkdir(exist_ok=True)
    outputs_dir.mkdir(parents=True, exist_ok=True)

    notes_path = docs_dir / "cert_r42_notes.md"
    per_user_summary_path = outputs_dir / "r42_per_user_answer_summary.csv"
    insiders_only_path = outputs_dir / "r42_insiders_only.csv"

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    print("=" * 90)
    print("CERT r4.2 Ground Truth Inspection (corrected CSV reader)")
    print("=" * 90)
    print(f"Answers folder: {answers_dir}")
    print()

    # --- insiders.csv via pandas ---
    insiders_path = find_insiders_csv(answers_dir)
    insiders_r42 = pd.DataFrame()
    insider_users = []
    scenario_counts = Counter()

    if insiders_path is None:
        print("WARNING: insiders.csv not found.")
    else:
        insiders_df = pd.read_csv(insiders_path, dtype=str, low_memory=False)
        mask = insiders_df.apply(is_r42_insider_row, axis=1)
        insiders_r42 = insiders_df.loc[mask].copy()
        insiders_r42.to_csv(insiders_only_path, index=False)

        if "user" in insiders_r42.columns:
            insider_users = sorted(
                {
                    str(u).strip()
                    for u in insiders_r42["user"].dropna()
                    if str(u).strip()
                }
            )
        if "scenario" in insiders_r42.columns:
            scenario_counts = Counter(
                str(s).strip() for s in insiders_r42["scenario"].dropna() if str(s).strip()
            )

        print(f"insiders.csv: {insiders_path}")
        print(f"r4.2 insider rows: {len(insiders_r42)}")
        print(f"r4.2 insider users: {len(insider_users)}")
        print()

    # --- r4.2 per-user files via csv.reader ---
    per_user_files = find_r42_per_user_files(answers_dir)
    print(f"r4.2 per-user answer files: {len(per_user_files)}")

    summary_rows = []
    for path in per_user_files:
        row = summarize_per_user_file(path, answers_dir)
        summary_rows.append(row)
        print(
            f"  {row['scenario_group']}/{row['user_id']}: "
            f"{row['num_rows']} events; types=[{row['event_types']}]; "
            f"event_ids={row['has_event_ids']}"
        )

    summary_df = pd.DataFrame(summary_rows)
    summary_df.to_csv(per_user_summary_path, index=False)

    # Aggregate stats for notes
    users_from_files = sorted({r["user_id"] for r in summary_rows if r["user_id"]})
    files_with_event_ids = sum(1 for r in summary_rows if r["has_event_ids"])
    total_events = sum(r["num_rows"] for r in summary_rows)
    all_event_types = Counter()
    for r in summary_rows:
        for part in (r["event_type_counts"] or "").split("; "):
            if not part or ":" not in part:
                continue
            etype, count = part.rsplit(":", 1)
            try:
                all_event_types[etype] += int(count)
            except ValueError:
                continue

    by_scenario = Counter(r["scenario_group"] for r in summary_rows)
    earliest_all = [r["earliest_timestamp"] for r in summary_rows if r["earliest_timestamp"]]
    latest_all = [r["latest_timestamp"] for r in summary_rows if r["latest_timestamp"]]

    with notes_path.open("a", encoding="utf-8") as f:
        f.write(f"\n\n## CERT r4.2 Ground Truth Inspection — corrected reader ({timestamp})\n\n")
        f.write(
            "Previous pandas `read_csv` failed on many r4.2 per-user answer files because "
            "rows are **variable-length** (different event types have different field counts) "
            "and files have **no header row**. This pass uses `csv.reader` for those files "
            "and keeps pandas only for `insiders.csv`.\n\n"
        )
        f.write(f"Answers folder inspected: `{answers_dir}`\n\n")

        f.write("### Method\n\n")
        f.write("- `insiders.csv`: pandas, filtered to r4.2 via `dataset == \"4.2\"` or `details` containing `r4.2`.\n")
        f.write("- Per-user files under `r4.2-1/`, `r4.2-2/`, `r4.2-3/`: Python `csv.reader` (no fixed schema).\n")
        f.write("- Column 0 treated as event type; timestamps scanned across all cells; event IDs matched as `{...-...-...}`.\n")
        f.write("- No model training was performed.\n\n")

        f.write("### r4.2 insiders.csv filter\n\n")
        if insiders_path is None:
            f.write("`insiders.csv` was not found.\n\n")
        else:
            f.write(f"Source: `{insiders_path}`\n\n")
            f.write(f"r4.2 rows retained: **{len(insiders_r42)}**\n\n")
            f.write(f"Unique r4.2 insider users (from `user` column): **{len(insider_users)}**\n\n")
            if scenario_counts:
                f.write("Scenario counts (from filtered `insiders.csv`):\n\n```text\n")
                for k, v in sorted(scenario_counts.items(), key=lambda x: (str(x[0]), -x[1])):
                    f.write(f"{k}: {v}\n")
                f.write("```\n\n")
            if insider_users:
                f.write(f"Insider users: {insider_users}\n\n")

        f.write("### r4.2 per-user answer files\n\n")
        f.write(f"Files summarised: **{len(summary_rows)}**\n\n")
        f.write(f"Files per scenario group: {dict(sorted(by_scenario.items()))}\n\n")
        f.write(f"Unique users from filenames: **{len(users_from_files)}**\n\n")
        f.write(f"Total malicious event rows: **{total_events}**\n\n")
        f.write(f"Files containing event IDs: **{files_with_event_ids} / {len(summary_rows)}**\n\n")

        if all_event_types:
            f.write("Event types across all per-user files (column 0):\n\n```text\n")
            for k, v in all_event_types.most_common():
                f.write(f"{k}: {v}\n")
            f.write("```\n\n")

        if earliest_all and latest_all:
            f.write(
                f"Earliest parseable timestamp across files: **{min(earliest_all)}**\n\n"
            )
            f.write(
                f"Latest parseable timestamp across files: **{max(latest_all)}**\n\n"
            )

        f.write("### Corrected findings\n\n")
        f.write(
            "- Per-user answer CSVs are **not tabular with a shared schema**; each row starts with "
            "an event type (`logon`, `device`, `http`, `email`, `file`, …) and then type-specific fields.\n"
        )
        f.write(
            "- Event IDs appear as brace-wrapped tokens (e.g. `{K3V4-Y4OK65SI-1583GEOQ}`), typically in column 1.\n"
        )
        f.write(
            "- Timestamps appear as `MM/DD/YYYY HH:MM:SS` (usually column 2).\n"
        )
        f.write(
            "- User ID is recoverable from the filename pattern `r4.2-{scenario}-{USERID}.csv` "
            "and also appears in the event rows.\n"
        )
        if insider_users and users_from_files:
            only_insiders = sorted(set(insider_users) - set(users_from_files))
            only_files = sorted(set(users_from_files) - set(insider_users))
            f.write(
                f"- Overlap check: insiders.csv users vs per-user files — "
                f"shared **{len(set(insider_users) & set(users_from_files))}**, "
                f"insiders-only **{len(only_insiders)}**, files-only **{len(only_files)}**.\n"
            )
        f.write("\n")

        f.write("### Generated output files\n\n")
        f.write(f"- `{per_user_summary_path}`\n")
        f.write(f"- `{insiders_only_path}`\n")

    print("\nSaved outputs:")
    print(per_user_summary_path)
    print(insiders_only_path)
    print(f"\nAppended notes to: {notes_path}")
    print(f"\nr4.2 insider users (insiders.csv): {len(insider_users)}")
    print(f"r4.2 per-user files: {len(summary_rows)}")
    print(f"Total malicious event rows: {total_events}")


if __name__ == "__main__":
    main()
