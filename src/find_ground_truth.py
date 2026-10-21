#!/usr/bin/env python3
"""Locate CERT R4.2 ground-truth or answer-key files under data/raw (read-only)."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

SEARCH_KEYWORDS = (
    "answer",
    "ground",
    "truth",
    "malicious",
    "insider",
    "scenario",
    "readme",
    "ldap",
)

# Common answer-key names used in CERT releases (often outside the r4.2 folder).
ANSWER_KEY_NAMES = (
    "insiders.csv",
    "answers.tar.bz2",
    "answers.tar",
    "answers",
)

TEXT_EXTENSIONS = {".txt", ".csv", ".md", ".json", ".yaml", ".yml", ".log"}
PREVIEW_LINES = 8


@dataclass
class Match:
    path: Path
    rel_path: str
    kind: str
    size_bytes: int
    matched_keywords: list[str] = field(default_factory=list)
    preview: list[str] = field(default_factory=list)
    is_likely_label_file: bool = False
    notes: str = ""


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.2f} KB"
    if size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.2f} MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def matched_keywords(path: Path) -> list[str]:
    text = str(path).lower()
    hits = [kw for kw in SEARCH_KEYWORDS if kw in text]
    return hits


def is_answer_key_candidate(path: Path) -> bool:
    name = path.name.lower()
    if name in ANSWER_KEY_NAMES:
        return True
    if "insider" in name and path.suffix.lower() == ".csv":
        return True
    if name.startswith("answer"):
        return True
    return False


def classify_match(path: Path) -> tuple[bool, str]:
    name = path.name.lower()
    rel = path.as_posix().lower()

    if is_answer_key_candidate(path):
        return True, "Likely malicious-label / answer-key file."

    if "ldap" in rel:
        return False, "Organizational metadata (roles, departments); not a malicious label file."

    if name == "readme.txt":
        return False, "Dataset documentation; describes scenarios but does not list labels."

    if name == "license.txt":
        return False, "License text only."

    if "malicious" in rel or "insider" in rel or "scenario" in rel:
        return False, "Name matches search keyword; inspect content to confirm whether labels are present."

    return False, "Matched search keyword in path only."


def preview_text_file(path: Path, max_lines: int = PREVIEW_LINES) -> list[str]:
    if path.suffix.lower() not in TEXT_EXTENSIONS:
        return [f"(binary or unsupported extension: {path.suffix or 'none'})"]

    lines: list[str] = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for idx, line in enumerate(handle):
                if idx >= max_lines:
                    break
                lines.append(line.rstrip("\n\r"))
    except OSError as exc:
        lines.append(f"(could not read file: {exc})")
    return lines


def scan_raw_dir(raw_dir: Path) -> list[Match]:
    if not raw_dir.exists():
        raise FileNotFoundError(f"Raw directory not found: {raw_dir}")

    matches: list[Match] = []

    for path in sorted(raw_dir.rglob("*")):
        keywords = matched_keywords(path)
        answer_key = is_answer_key_candidate(path)
        if not keywords and not answer_key:
            continue

        if path.is_dir():
            matches.append(
                Match(
                    path=path,
                    rel_path=str(path.relative_to(raw_dir)).replace("\\", "/"),
                    kind="directory",
                    size_bytes=0,
                    matched_keywords=keywords,
                    notes="Directory matched search keywords.",
                )
            )
            continue

        likely_label, note = classify_match(path)
        matches.append(
            Match(
                path=path,
                rel_path=str(path.relative_to(raw_dir)).replace("\\", "/"),
                kind="file",
                size_bytes=path.stat().st_size,
                matched_keywords=keywords,
                preview=preview_text_file(path),
                is_likely_label_file=likely_label,
                notes=note,
            )
        )

    return matches


def safe_print(text: str) -> None:
    try:
        print(text)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        print(text.encode(encoding, errors="replace").decode(encoding))


def print_report(raw_dir: Path, matches: list[Match]) -> None:
    safe_print(f"Searching: {raw_dir.resolve()}")
    safe_print(f"Keywords: {', '.join(SEARCH_KEYWORDS)}")
    safe_print(f"Matches: {len(matches)}")
    safe_print("")

    label_files = [m for m in matches if m.is_likely_label_file]
    safe_print(f"Likely malicious-label files: {len(label_files)}")
    safe_print("")

    for match in matches:
        safe_print("=" * 72)
        safe_print(f"{match.kind.upper():10} {match.rel_path}")
        if match.kind == "file":
            safe_print(f"Size:       {format_size(match.size_bytes)} ({match.size_bytes:,} bytes)")
        if match.matched_keywords:
            safe_print(f"Keywords:   {', '.join(match.matched_keywords)}")
        if match.notes:
            safe_print(f"Notes:      {match.notes}")
        if match.is_likely_label_file:
            safe_print("Label file: YES")
        else:
            safe_print("Label file: NO")

        if match.preview:
            safe_print("Preview:")
            for line in match.preview:
                safe_print(f"  {line}")
        safe_print("")


def build_markdown(raw_dir: Path, matches: list[Match]) -> str:
    generated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    label_files = [m for m in matches if m.is_likely_label_file]
    docs_matches = [m for m in matches if not m.is_likely_label_file]

    lines = [
        "## Ground truth search",
        "",
        f"*Generated by `scripts/find_ground_truth.py` on {generated}.*",
        "",
        f"Searched: `{raw_dir}`",
        "",
        f"Keywords: `{', '.join(SEARCH_KEYWORDS)}`",
        "",
        "### Result",
        "",
    ]

    if label_files:
        lines.append(
            f"**Malicious-label files found:** {len(label_files)} "
            "(see table below)."
        )
    else:
        lines.append(
            "**No dedicated malicious-label / answer-key files were found** under "
            "`data/raw/` in this workspace."
        )
        lines.append("")
        lines.append(
            "The activity release (`r4.2/*.csv`) and `readme.txt` confirm that "
            "insider-threat scenarios exist, but labels are typically shipped "
            "separately in CMU's `answers.tar.bz2` archive (often extracted to "
            "`answers/insiders.csv`). Download that answer package from the "
            "[Insider Threat Test Dataset](https://www.sei.cmu.edu/library/insider-threat-test-dataset/) "
            "page and place it under `data/raw/` without modifying the existing logs."
        )

    lines.extend(["", "### Matching paths", ""])

    if not matches:
        lines.append("_No paths matched the search keywords._")
    else:
        lines.extend(
            [
                "| Path | Type | Size | Label file? | Notes |",
                "|------|------|------|-------------|-------|",
            ]
        )
        for match in matches:
            size = format_size(match.size_bytes) if match.kind == "file" else "-"
            label = "yes" if match.is_likely_label_file else "no"
            note = match.notes.replace("|", "/")
            lines.append(
                f"| `{match.rel_path}` | {match.kind} | {size} | {label} | {note} |"
            )

    if docs_matches:
        lines.extend(["", "### Readme excerpt (scenario documentation)", ""])
        readme = next((m for m in docs_matches if m.path.name.lower() == "readme.txt"), None)
        if readme and readme.preview:
            lines.append("From `r4.2/readme.txt`:")
            lines.append("")
            for line in readme.preview:
                lines.append(f"- {line}")
            lines.append("")
            lines.append(
                "- `readme.txt` states there are **two insider-threat instances** "
                "but does not list user IDs or event IDs."
            )

    ldap_files = [m for m in docs_matches if "ldap" in m.rel_path.lower() and m.kind == "file"]
    if ldap_files:
        sample = ldap_files[0]
        lines.extend(["", "### LDAP snapshots (not labels)", ""])
        lines.append(
            f"Found {len(ldap_files)} monthly LDAP CSV files under `r4.2/LDAP/`. "
            "These contain employee/org metadata, not malicious labels."
        )
        if sample.preview:
            lines.append("")
            lines.append(f"Example header from `{sample.rel_path}`:")
            lines.append("")
            lines.append("```")
            lines.extend(sample.preview[:3])
            lines.append("```")

    lines.extend(
        [
            "",
            "### Implication for feasibility",
            "",
            "- Supervised evaluation requires the separate CERT answer key (`insiders.csv`).",
            "- Until that file is present, only unsupervised / documentation-driven exploration is possible.",
            "- Do not infer malicious users from activity logs alone without the official labels.",
            "",
        ]
    )

    return "\n".join(lines)


def update_notes(notes_path: Path, section_md: str) -> None:
    marker = "## Ground truth search"
    existing = notes_path.read_text(encoding="utf-8") if notes_path.exists() else ""

    if marker in existing:
        prefix = existing.split(marker)[0].rstrip()
        suffix_parts = existing.split(marker)[1:]
        remainder = ""
        if len(suffix_parts) > 1:
            tail = suffix_parts[1]
            next_heading = tail.find("\n## ")
            if next_heading != -1:
                remainder = tail[next_heading:]
        content = prefix + "\n\n" + section_md.rstrip() + remainder
    else:
        content = existing.rstrip() + "\n\n" + section_md

    notes_path.write_text(content.rstrip() + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=repo_root() / "data" / "raw",
        help="Directory to search (default: data/raw)",
    )
    parser.add_argument(
        "--notes",
        type=Path,
        default=repo_root() / "docs" / "cert_r42_notes.md",
        help="Markdown notes file to update",
    )
    parser.add_argument(
        "--skip-notes",
        action="store_true",
        help="Print report only; do not update docs/cert_r42_notes.md",
    )
    args = parser.parse_args()

    raw_dir = args.raw_dir.resolve()
    try:
        matches = scan_raw_dir(raw_dir)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print_report(raw_dir, matches)

    if not args.skip_notes:
        section = build_markdown(raw_dir, matches)
        update_notes(args.notes.resolve(), section)
        print(f"Updated notes: {args.notes.resolve()}")

    label_count = sum(1 for m in matches if m.is_likely_label_file)
    return 0 if label_count or not matches else 0


if __name__ == "__main__":
    sys.exit(main())
