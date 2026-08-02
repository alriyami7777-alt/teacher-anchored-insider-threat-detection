#!/usr/bin/env python3
"""CERT dataset registry and path resolution for releases 4.2, 5.2, and 6.2.

Read-only raw data; derived outputs never written inside raw folders.
Defaults preserve existing r4.2 behaviour.
"""

from __future__ import annotations


import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Literal, Sequence

AnswerFormat = Literal["per_user_directories", "flat_scenario_csv"]
DatasetVersion = Literal["4.2", "5.2", "6.2"]

REQUIRED_ACTIVITY_LOGS: tuple[str, ...] = (
    "logon",
    "device",
    "file",
    "email",
    "http",
    "psychometric",
)

CORE_EVENT_LOGS: tuple[str, ...] = ("logon", "device", "file", "email", "http")

# Known non-canonical or incomplete trees are supplied explicitly.
FORBIDDEN_RAW_SOURCES: tuple[Path, ...] = tuple(
    Path(p)
    for p in os.environ.get("CERT_FORBIDDEN_RAW", "").split(os.pathsep)
    if p
)

# Optional external raw roots. No machine-specific path is committed.
CANONICAL_EXTERNAL_RAW: dict[str, Path] = {
    version: Path(os.environ[env_name])
    for version, env_name in (
        ("5.2", "CERT_R52_ROOT"),
        ("6.2", "CERT_R62_ROOT"),
    )
    if os.environ.get(env_name)
}


@dataclass(frozen=True)
class DatasetSpec:
    """Release-specific CERT metadata."""

    version: DatasetVersion
    folder_name: str
    n_scenarios: int
    answer_format: AnswerFormat
    required_logs: tuple[str, ...] = REQUIRED_ACTIVITY_LOGS
    optional_logs: tuple[str, ...] = ()
    expects_ldap: bool = True
    processed_prefix: str = "r42"
    insiders_dataset_values: tuple[str, ...] = ()
    scenario_keys: tuple[str, ...] = ()
    metadata: dict[str, str] = field(default_factory=dict)

    @property
    def release_tag(self) -> str:
        return f"r{self.version}"

    def scenario_dirs(self) -> tuple[str, ...]:
        if self.answer_format == "per_user_directories":
            return self.scenario_keys
        return ()

    def scenario_flat_files(self) -> tuple[str, ...]:
        if self.answer_format == "flat_scenario_csv":
            return tuple(f"{key}.csv" for key in self.scenario_keys)
        return ()


DATASETS: dict[str, DatasetSpec] = {
    "4.2": DatasetSpec(
        version="4.2",
        folder_name="r4.2",
        n_scenarios=3,
        answer_format="per_user_directories",
        optional_logs=(),
        processed_prefix="r42",
        insiders_dataset_values=("4.2", "r4.2"),
        scenario_keys=("r4.2-1", "r4.2-2", "r4.2-3"),
        metadata={
            "role": "primary_development_dataset",
            "notes": "Per-user scenario directories; no decoy_file log.",
        },
    ),
    "5.2": DatasetSpec(
        version="5.2",
        folder_name="r5.2",
        n_scenarios=4,
        answer_format="per_user_directories",
        optional_logs=("decoy_file",),
        processed_prefix="r52",
        insiders_dataset_values=("5.2", "r5.2"),
        scenario_keys=("r5.2-1", "r5.2-2", "r5.2-3", "r5.2-4"),
        metadata={
            "role": "primary_untouched_confirmatory_dataset",
            "notes": "Per-user scenario directories; optional decoy_file.csv.",
        },
    ),
    "6.2": DatasetSpec(
        version="6.2",
        folder_name="r6.2",
        n_scenarios=5,
        answer_format="flat_scenario_csv",
        optional_logs=("decoy_file",),
        processed_prefix="r62",
        insiders_dataset_values=("6.2", "r6.2"),
        scenario_keys=("r6.2-1", "r6.2-2", "r6.2-3", "r6.2-4", "r6.2-5"),
        metadata={
            "role": "external_severe_imbalance_stress_test",
            "notes": "Flat scenario CSVs; only five insiders; optional decoy_file.csv.",
        },
    ),
}


_VERSION_RE = re.compile(
    r"(?:cert[\s_\-]*)?r?(?P<major>[456])\.(?P<minor>\d+)",
    re.IGNORECASE,
)


class DatasetVersionError(ValueError):
    """Raised when a dataset version string cannot be resolved or is mixed."""


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def normalize_dataset_version(value: str | None) -> DatasetVersion:
    """Normalize version tokens such as ``5.2``, ``r5.2``, ``CERT r5.2``."""
    if value is None or not str(value).strip():
        raise DatasetVersionError("dataset version is required")
    text = str(value).strip()
    match = _VERSION_RE.search(text)
    if not match:
        raise DatasetVersionError(f"unrecognised dataset version: {value!r}")
    version = f"{match.group('major')}.{match.group('minor')}"
    if version not in DATASETS:
        raise DatasetVersionError(
            f"unsupported dataset version {version!r}; "
            f"supported: {', '.join(sorted(DATASETS))}"
        )
    return version  # type: ignore[return-value]


def get_dataset_spec(version: str | DatasetVersion) -> DatasetSpec:
    return DATASETS[normalize_dataset_version(str(version))]


def list_dataset_versions() -> list[str]:
    return sorted(DATASETS.keys())


def resolve_path(root: Path, path: str | Path) -> Path:
    p = Path(path)
    return p if p.is_absolute() else (root / p).resolve()


def _is_forbidden_raw(path: Path) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path
    for forbidden in FORBIDDEN_RAW_SOURCES:
        try:
            if resolved == forbidden.resolve():
                return True
        except OSError:
            if str(resolved).lower() == str(forbidden).lower():
                return True
    return False


def _looks_like_release_root(path: Path) -> bool:
    """Heuristic: directory containing at least one required activity CSV."""
    if not path.is_dir():
        return False
    for log in CORE_EVENT_LOGS:
        if (path / f"{log}.csv").is_file():
            return True
    return False


@dataclass(frozen=True)
class ResolvedDatasetPaths:
    version: DatasetVersion
    spec: DatasetSpec
    raw_dir: Path
    answers_dir: Path
    processed_dir: Path
    output_dir: Path
    raw_source: str  # how raw_dir was chosen

    def as_dict(self) -> dict[str, str]:
        return {
            "dataset_version": self.version,
            "raw_dir": str(self.raw_dir),
            "answers_dir": str(self.answers_dir),
            "processed_dir": str(self.processed_dir),
            "output_dir": str(self.output_dir),
            "raw_source": self.raw_source,
            "folder_name": self.spec.folder_name,
            "answer_format": self.spec.answer_format,
            "n_scenarios": str(self.spec.n_scenarios),
        }


def resolve_raw_dir_for_version(
    version: str | DatasetVersion,
    *,
    raw_dir: str | Path | None = None,
    repo: Path | None = None,
) -> tuple[Path, str]:
    """Resolve the activity-data root for one CERT release.

    Precedence:
    1. Explicit ``--raw-dir`` (must not be a forbidden duplicate/placeholder).
    2. Junction/local ``data/raw/{rX.Y}`` when it exists and looks valid.
    3. Confirmed external canonical path for 5.2 / 6.2.
    4. For 4.2 only: ``data/raw`` itself if it already contains the CSVs
       (legacy layout used by older scripts).

    Never silently falls back to a different dataset version.
    """
    root = repo or repo_root()
    spec = get_dataset_spec(version)

    if raw_dir is not None:
        path = resolve_path(root, raw_dir)
        if not path.exists():
            raise FileNotFoundError(f"--raw-dir does not exist: {path}")
        if _is_forbidden_raw(path):
            raise DatasetVersionError(
                f"refusing non-canonical / incomplete raw source: {path}"
            )
        # Explicit override already pointing at the release root.
        if path.name.lower() == spec.folder_name.lower() and _looks_like_release_root(path):
            return path.resolve(), "explicit_raw_dir"
        # If caller passed data/raw (parent), descend into version folder when present.
        versioned = path / spec.folder_name
        if versioned.is_dir() and _looks_like_release_root(versioned):
            return versioned.resolve(), "explicit_raw_dir_version_subdir"
        if _looks_like_release_root(path):
            # Explicit override pointing at a release root with atypical folder name.
            return path.resolve(), "explicit_raw_dir"
        raise DatasetVersionError(
            f"--raw-dir {path} does not contain {spec.folder_name} activity data "
            f"for dataset version {spec.version}"
        )

    junction = (root / "data" / "raw" / spec.folder_name).resolve()
    if junction.is_dir() and _looks_like_release_root(junction):
        if _is_forbidden_raw(junction):
            raise DatasetVersionError(
                f"junction path resolves to a forbidden source: {junction}"
            )
        return junction, "data_raw_junction_or_local"

    external = CANONICAL_EXTERNAL_RAW.get(spec.version)
    if external is not None and external.is_dir() and _looks_like_release_root(external):
        if _is_forbidden_raw(external):
            raise DatasetVersionError(
                f"canonical external path marked forbidden: {external}"
            )
        return external.resolve(), "canonical_external"

    # Legacy r4.2: activity CSVs may sit directly under data/raw.
    if spec.version == "4.2":
        legacy = (root / "data" / "raw").resolve()
        if _looks_like_release_root(legacy):
            return legacy, "legacy_data_raw_flat"

    raise FileNotFoundError(
        f"could not resolve raw directory for CERT {spec.version}; "
        f"expected {junction} or pass --raw-dir"
    )


def resolve_answers_dir(
    *,
    answers_dir: str | Path | None = None,
    repo: Path | None = None,
) -> Path:
    """Resolve the shared CERT answers package."""
    root = repo or repo_root()
    candidates: list[Path] = []
    if answers_dir is not None:
        candidates.append(resolve_path(root, answers_dir))
    else:
        candidates.extend(
            [
                root / "data" / "raw" / "answers",
                root / "answers" / "answers",
            ]
        )
    for cand in candidates:
        if cand.is_dir() and (cand / "insiders.csv").is_file():
            return cand.resolve()
    if answers_dir is not None:
        raise FileNotFoundError(f"--answers-dir not found or missing insiders.csv: {candidates[0]}")
    raise FileNotFoundError(
        "shared answers package not found; tried: "
        + ", ".join(str(c) for c in candidates)
    )


def default_processed_dir(version: str | DatasetVersion, repo: Path | None = None) -> Path:
    root = repo or repo_root()
    spec = get_dataset_spec(version)
    return (root / "data" / "processed" / spec.release_tag).resolve()


def default_readiness_output_dir(
    version: str | DatasetVersion, repo: Path | None = None
) -> Path:
    root = repo or repo_root()
    spec = get_dataset_spec(version)
    return (root / "outputs" / "dataset_readiness" / spec.release_tag).resolve()


def resolve_dataset_paths(
    version: str | DatasetVersion = "4.2",
    *,
    raw_dir: str | Path | None = None,
    answers_dir: str | Path | None = None,
    processed_dir: str | Path | None = None,
    output_dir: str | Path | None = None,
    repo: Path | None = None,
) -> ResolvedDatasetPaths:
    """Resolve all paths for one dataset version (never mixes versions)."""
    root = repo or repo_root()
    ver = normalize_dataset_version(str(version))
    spec = get_dataset_spec(ver)
    raw, raw_source = resolve_raw_dir_for_version(ver, raw_dir=raw_dir, repo=root)
    answers = resolve_answers_dir(answers_dir=answers_dir, repo=root)
    processed = (
        resolve_path(root, processed_dir)
        if processed_dir is not None
        else default_processed_dir(ver, root)
    )
    output = (
        resolve_path(root, output_dir)
        if output_dir is not None
        else default_readiness_output_dir(ver, root)
    )
    assert_output_outside_raw(output, raw)
    assert_output_outside_raw(processed, raw)
    return ResolvedDatasetPaths(
        version=ver,
        spec=spec,
        raw_dir=raw,
        answers_dir=answers,
        processed_dir=processed,
        output_dir=output,
        raw_source=raw_source,
    )


def assert_output_outside_raw(output: Path, raw_dir: Path) -> None:
    """Refuse to write derived artefacts inside a raw dataset tree."""
    try:
        out_r = output.resolve()
        raw_r = raw_dir.resolve()
    except OSError as exc:
        raise DatasetVersionError(f"cannot resolve paths for isolation check: {exc}") from exc
    try:
        out_r.relative_to(raw_r)
    except ValueError:
        return
    raise DatasetVersionError(
        f"refusing to write derived outputs inside raw data folder: "
        f"output={out_r} raw={raw_r}"
    )


def assert_raw_is_readonly_target(path: Path) -> None:
    """Mark intent: callers must not write beside or into raw trees."""
    if not path.exists():
        raise FileNotFoundError(f"raw path does not exist: {path}")
    if not path.is_dir():
        raise DatasetVersionError(f"raw path is not a directory: {path}")


def required_log_paths(raw_dir: Path, spec: DatasetSpec | None = None) -> dict[str, Path]:
    logs = (spec.required_logs if spec else REQUIRED_ACTIVITY_LOGS)
    return {name: raw_dir / f"{name}.csv" for name in logs}


def optional_log_paths(raw_dir: Path, spec: DatasetSpec) -> dict[str, Path]:
    return {name: raw_dir / f"{name}.csv" for name in spec.optional_logs}


def check_required_logs(
    raw_dir: Path, spec: DatasetSpec
) -> tuple[list[str], list[str]]:
    """Return (present, missing) required log basenames (without .csv)."""
    present: list[str] = []
    missing: list[str] = []
    for name, path in required_log_paths(raw_dir, spec).items():
        if path.is_file():
            present.append(name)
        else:
            missing.append(name)
    return present, missing


def check_optional_logs(raw_dir: Path, spec: DatasetSpec) -> dict[str, bool]:
    return {name: path.is_file() for name, path in optional_log_paths(raw_dir, spec).items()}


def refuse_mixed_versions(
    declared_version: str | DatasetVersion,
    raw_dir: Path,
) -> None:
    """Ensure the raw folder name matches the declared dataset version."""
    ver = normalize_dataset_version(str(declared_version))
    spec = get_dataset_spec(ver)
    name = raw_dir.name.lower()
    expected = spec.folder_name.lower()
    # Allow legacy flat data/raw for r4.2 only.
    if ver == "4.2" and name == "raw":
        return
    if name != expected:
        # Also accept if parent folder carries the release tag (junction edge cases).
        parent = raw_dir.parent.name.lower()
        if parent != expected and expected not in name:
            raise DatasetVersionError(
                f"refusing to mix dataset versions: declared={ver} "
                f"but raw_dir name is {raw_dir.name!r} (expected {spec.folder_name})"
            )


def print_resolved_paths(paths: ResolvedDatasetPaths) -> None:
    print("=" * 72)
    print(f"CERT dataset version : {paths.version} ({paths.spec.folder_name})")
    print(f"Answer format        : {paths.spec.answer_format}")
    print(f"Scenarios            : {paths.spec.n_scenarios}")
    print(f"Raw dir              : {paths.raw_dir}")
    print(f"Raw source           : {paths.raw_source}")
    print(f"Answers dir          : {paths.answers_dir}")
    print(f"Processed dir        : {paths.processed_dir}")
    print(f"Output dir           : {paths.output_dir}")
    print("=" * 72)


def add_dataset_path_arguments(parser, *, default_version: str = "4.2") -> None:
    """Attach shared CLI flags to an argparse parser."""
    parser.add_argument(
        "--dataset-version",
        default=default_version,
        help="CERT release version: 4.2, 5.2, or 6.2 (also accepts r5.2 / 'CERT r5.2')",
    )
    parser.add_argument(
        "--raw-dir",
        default=None,
        help="Explicit raw activity root (or parent data/raw). Overrides auto-resolution.",
    )
    parser.add_argument(
        "--answers-dir",
        default=None,
        help="Shared answers package (default: data/raw/answers or answers/answers).",
    )
    parser.add_argument(
        "--processed-dir",
        default=None,
        help="Derived processed-data root (never inside raw).",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Audit/report output root (never inside raw).",
    )


# Backward-compatible helper used by legacy r4.2 scripts.
def resolve_raw_dir_legacy_r42(raw_dir: Path, repo: Path | None = None) -> Path:
    """Preserve historical behaviour: prefer ``raw_dir/r4.2`` when present."""
    root = repo or repo_root()
    path = raw_dir if raw_dir.is_absolute() else (root / raw_dir)
    path = path.resolve()
    candidate = path / "r4.2"
    if candidate.is_dir() and _looks_like_release_root(candidate):
        return candidate
    if _looks_like_release_root(path):
        return path
    if candidate.is_dir():
        return candidate
    return path


def iter_known_versions() -> Iterable[DatasetSpec]:
    for key in sorted(DATASETS):
        yield DATASETS[key]


__all__ = [
    "AnswerFormat",
    "CANONICAL_EXTERNAL_RAW",
    "CORE_EVENT_LOGS",
    "DATASETS",
    "DatasetSpec",
    "DatasetVersion",
    "DatasetVersionError",
    "FORBIDDEN_RAW_SOURCES",
    "REQUIRED_ACTIVITY_LOGS",
    "ResolvedDatasetPaths",
    "add_dataset_path_arguments",
    "assert_output_outside_raw",
    "assert_raw_is_readonly_target",
    "check_optional_logs",
    "check_required_logs",
    "default_processed_dir",
    "default_readiness_output_dir",
    "get_dataset_spec",
    "iter_known_versions",
    "list_dataset_versions",
    "normalize_dataset_version",
    "optional_log_paths",
    "print_resolved_paths",
    "refuse_mixed_versions",
    "repo_root",
    "required_log_paths",
    "resolve_answers_dir",
    "resolve_dataset_paths",
    "resolve_path",
    "resolve_raw_dir_for_version",
    "resolve_raw_dir_legacy_r42",
]
