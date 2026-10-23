"""Safety guards for Prototype V2 development.

- Refuse CERT r4.2 test tensor / label access during V2 development commands.
- Snapshot and verify V1 / Objective 2 / Objective 3 artefacts remain unchanged.
- Support Git worktrees whose ``outputs`` directory is a Windows junction.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable


R42_TEST_BASENAMES = (
    "r42_T20_s1_test.npz",
    "r42_T20_s1_test.parquet",
)

R42_TEST_PATH_MARKERS = (
    "r42_T20_s1_test",
    "/test.npz",
    "\\test.npz",
    "tensors/test",
    "tensors\\test",
)

# Relative paths that V2 must never write to.
PROTECTED_OUTPUT_PREFIXES = (
    "outputs/objective2/",
    "outputs/objective3/",
    "outputs/baselines/",
    "outputs/dataset_readiness/",
    "outputs/chapter4/",
    "docs/cert_r42_notes.md",
)

# Canonical V2 write namespace.
V2_OUTPUT_NAMESPACE = "outputs/v2"

# Prefix used when an explicitly supplied protected file is genuinely outside
# the logical worktree root.
EXTERNAL_SNAPSHOT_PREFIX = "external::"


class R42TestAccessError(RuntimeError):
    """Raised when a V2 development command requests the r4.2 test set."""


def repo_root() -> Path:
    """Return the logical repository root containing this module."""
    return Path(__file__).absolute().parents[2]


def sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    """Calculate the SHA-256 hash of a file without loading it all into memory."""
    path = Path(path)

    hasher = hashlib.sha256()

    with path.open("rb") as file_handle:
        while True:
            chunk = file_handle.read(chunk_size)

            if not chunk:
                break

            hasher.update(chunk)

    return hasher.hexdigest()


def _norm(text: str) -> str:
    """Normalize path-like text for case-insensitive safety comparisons."""
    return text.replace("\\", "/").lower()


def path_looks_like_r42_test(path: str | Path) -> bool:
    """Return True when a path appears to reference the locked r4.2 test set."""
    path_text = _norm(str(path))
    filename = Path(path).name.lower()

    if filename in {basename.lower() for basename in R42_TEST_BASENAMES}:
        return True

    return any(
        marker in path_text
        for marker in (_norm(value) for value in R42_TEST_PATH_MARKERS)
    )


def refuse_if_test_requested(
    *,
    evaluate_test: bool = False,
    confirm_test_evaluation: bool = False,
    split: str | None = None,
    tensor_paths: Iterable[str | Path] | None = None,
    output_dir: str | Path | None = None,
    extra_flags: dict[str, Any] | None = None,
) -> None:
    """Refuse any Prototype V2 development request targeting r4.2 test data.

    Prototype V2 development is restricted to training and validation data.
    There is intentionally no confirmation flag that bypasses this restriction.
    """
    reasons: list[str] = []

    if evaluate_test:
        reasons.append("--evaluate-test / evaluate_test=True")

    if confirm_test_evaluation:
        reasons.append(
            "--confirm-test-evaluation "
            "(not permitted during Prototype V2 development)"
        )

    if split is not None and str(split).lower() in {
        "test",
        "heldout_test",
        "r42_test",
    }:
        reasons.append(f"split={split!r}")

    if tensor_paths:
        for tensor_path in tensor_paths:
            if path_looks_like_r42_test(tensor_path):
                reasons.append(f"tensor path {tensor_path}")

    if output_dir is not None and path_looks_like_r42_test(output_dir):
        reasons.append(f"output_dir {output_dir}")

    if extra_flags:
        for key, value in extra_flags.items():
            if not value:
                continue

            key_text = str(key).lower()
            value_text = str(value).lower()

            if "test" not in key_text:
                continue

            if value_text in {"false", "0", "none", "no"}:
                continue

            if value_text in {"true", "1", "yes"} or path_looks_like_r42_test(
                value
            ):
                reasons.append(f"{key}={value}")

    if reasons:
        raise R42TestAccessError(
            "REFUSED: Prototype V2 development commands must not access the "
            "CERT r4.2 test tensor or labels. "
            f"Blocked because: {'; '.join(reasons)}. "
            "Use training and validation data only "
            "(test_evaluated=false)."
        )


def assert_no_r42_test_access(paths: Iterable[str | Path]) -> None:
    """Raise an exception if any provided path references r4.2 test data."""
    refuse_if_test_requested(tensor_paths=paths)


def assert_output_namespace_is_v2(
    output_dir: str | Path,
    root: Path | None = None,
) -> Path:
    """Ensure that Prototype V2 writes remain under ``outputs/v2``.

    Resolving the output path is appropriate here because the objective is to
    verify the physical write destination, including when ``outputs`` is a
    Windows junction.
    """
    root = root or repo_root()
    output_path = Path(output_dir)

    if not output_path.is_absolute():
        output_path = (root / output_path).resolve()
    else:
        output_path = output_path.resolve()

    allowed_path = (root / "outputs" / "v2").resolve()

    try:
        output_path.relative_to(allowed_path)
    except ValueError as exc:
        raise RuntimeError(
            f"V2 outputs must live under {allowed_path}; "
            f"refused path {output_path}"
        ) from exc

    # Additional protection against explicitly prohibited output namespaces.
    try:
        relative_output = (
            output_path.relative_to(root.resolve()).as_posix() + "/"
        )
    except ValueError:
        relative_output = output_path.as_posix()

    for protected_prefix in PROTECTED_OUTPUT_PREFIXES:
        if (
            relative_output.startswith(protected_prefix)
            or f"/{protected_prefix}" in f"/{relative_output}"
        ):
            raise RuntimeError(
                "Refusing write into protected path prefix "
                f"{protected_prefix}"
            )

    return output_path


def default_v1_encoder_checkpoint(
    seed: int,
    root: Path | None = None,
) -> Path:
    """Return the validation-best attention-linear checkpoint for a seed."""
    root = root or repo_root()

    checkpoint_mapping = {
        42: (
            root
            / "outputs"
            / "baselines"
            / "sequence_ensemble"
            / "stage11_A_attn_linear"
            / "best.pt"
        ),
        52: (
            root
            / "outputs"
            / "baselines"
            / "sequence_ensemble"
            / "pretrain_attn_linear_seed52"
            / "best.pt"
        ),
        62: (
            root
            / "outputs"
            / "baselines"
            / "sequence_ensemble"
            / "pretrain_attn_linear_seed62"
            / "best.pt"
        ),
    }

    if seed not in checkpoint_mapping:
        raise ValueError(
            f"No default V1 attention-linear checkpoint for seed={seed}"
        )

    return checkpoint_mapping[seed]


def default_v1_protected_paths(
    root: Path | None = None,
) -> list[Path]:
    """Return representative locked artefacts for immutability checks."""
    root = root or repo_root()

    candidates = [
        (
            root
            / "outputs"
            / "objective2"
            / "objective2_final_locked_manifest.json"
        ),
        (
            root
            / "outputs"
            / "objective2"
            / "objective2_test_evaluation_manifest.json"
        ),
        (
            root
            / "outputs"
            / "objective2"
            / "objective2_validation_model_summary.csv"
        ),
        (
            root
            / "outputs"
            / "objective3"
            / "objective3_protocol_manifest.json"
        ),
        (
            root
            / "outputs"
            / "baselines"
            / "sequence_ensemble"
            / "stage11_A_attn_linear"
            / "best.pt"
        ),
        (
            root
            / "outputs"
            / "baselines"
            / "sequence_ensemble"
            / "stage11_A_attn_linear"
            / "threshold.json"
        ),
        (
            root
            / "outputs"
            / "baselines"
            / "sequence_ensemble"
            / "stage11_D_pretrained_seed42_best"
            / "best.pt"
        ),
        (
            root
            / "outputs"
            / "baselines"
            / "sequence_ensemble"
            / "stage11_D_pretrained_seed42_best"
            / "threshold.json"
        ),
        (
            root
            / "outputs"
            / "objective2"
            / "bilstm_seed42"
            / "best.pt"
        ),
        (
            root
            / "outputs"
            / "objective2"
            / "bilstm_seed42"
            / "threshold.json"
        ),
        (
            root
            / "outputs"
            / "objective2"
            / "fragmented_hybrid_seed42"
            / "xgboost"
            / "threshold.json"
        ),
        root / "docs" / "cert_r42_notes.md",
        (
            root
            / "outputs"
            / "chapter4"
            / "chapter4_results_manifest.csv"
        ),
    ]

    return [path for path in candidates if path.exists()]


def _logical_absolute(path: Path, root: Path) -> Path:
    """Return an absolute logical path without resolving junctions.

    ``Path.resolve()`` must not be used here because it follows Windows
    junctions. A path such as ``v2-worktree/outputs/...`` would then become a
    physical path inside the main worktree and could no longer be represented
    relative to the V2 worktree.
    """
    path = Path(path)

    if not path.is_absolute():
        path = root / path

    return path.absolute()


def _snapshot_key(path: Path, root: Path) -> str:
    """Create a stable logical snapshot key without following junctions."""
    logical_root = root.absolute()
    logical_path = _logical_absolute(path, logical_root)

    try:
        return logical_path.relative_to(logical_root).as_posix()
    except ValueError:
        # Explicitly supplied files may genuinely reside outside the worktree.
        # Retain their absolute logical paths using a deterministic prefix.
        return EXTERNAL_SNAPSHOT_PREFIX + logical_path.as_posix()


def _snapshot_key_to_path(key: str, root: Path) -> Path:
    """Convert a logical snapshot key back into a filesystem path."""
    if key.startswith(EXTERNAL_SNAPSHOT_PREFIX):
        external_value = key[len(EXTERNAL_SNAPSHOT_PREFIX) :]
        return Path(external_value)

    return root / Path(key)


def snapshot_v1_artefact_hashes(
    root: Path | None = None,
    paths: Iterable[Path] | None = None,
) -> dict[str, str]:
    """Hash protected artefacts using junction-safe logical path keys.

    Files are read normally, so paths reached through a junction still hash the
    real physical target. Only the dictionary key avoids resolving the
    junction.
    """
    logical_root = (root or repo_root()).absolute()

    protected_paths = (
        list(paths)
        if paths is not None
        else default_v1_protected_paths(logical_root)
    )

    snapshot: dict[str, str] = {}

    for protected_path in protected_paths:
        logical_path = _logical_absolute(
            Path(protected_path),
            logical_root,
        )

        if not logical_path.exists():
            continue

        key = _snapshot_key(logical_path, logical_root)
        snapshot[key] = sha256_file(logical_path)

    return snapshot


def verify_v1_artefacts_unchanged(
    expected: dict[str, str],
    root: Path | None = None,
) -> list[str]:
    """Return mismatch messages; an empty list means all hashes match."""
    logical_root = (root or repo_root()).absolute()
    mismatches: list[str] = []

    for key, expected_digest in expected.items():
        protected_path = _snapshot_key_to_path(key, logical_root)

        if not protected_path.exists():
            mismatches.append(f"MISSING: {key}")
            continue

        actual_digest = sha256_file(protected_path)

        if actual_digest != expected_digest:
            mismatches.append(
                f"CHANGED: {key} "
                f"(was {expected_digest[:12]}… "
                f"now {actual_digest[:12]}…)"
            )

    return mismatches


def write_hash_snapshot(
    path: Path,
    snapshot: dict[str, str],
) -> None:
    """Write a hash snapshot as deterministic UTF-8 JSON."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    path.write_text(
        json.dumps(snapshot, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def load_hash_snapshot(path: Path) -> dict[str, str]:
    """Load a previously written hash snapshot."""
    path = Path(path)

    loaded = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(loaded, dict):
        raise ValueError(
            f"Expected a JSON object in hash snapshot: {path}"
        )

    return {
        str(key): str(value)
        for key, value in loaded.items()
    }