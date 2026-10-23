"""Safety guards for Prototype V3 NODE (outputs/v3_node/ only)."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from prototype_v2.safety import (  # noqa: F401
    R42TestAccessError,
    assert_no_r42_test_access,
    default_v1_encoder_checkpoint,
    default_v1_protected_paths,
    path_looks_like_r42_test,
    refuse_if_test_requested,
    repo_root,
    sha256_file,
    snapshot_v1_artefact_hashes,
    verify_v1_artefacts_unchanged,
    write_hash_snapshot,
)

PROTECTED_OUTPUT_PREFIXES = (
    "outputs/objective2/",
    "outputs/objective3/",
    "outputs/baselines/",
    "outputs/dataset_readiness/",
    "outputs/chapter4/",
    "outputs/v2/",
    "outputs/v2_1/",
    "docs/cert_r42_notes.md",
)

V3_OUTPUT_NAMESPACE = "outputs/v3_node"


def assert_output_namespace_is_v3(output_dir: str | Path, root: Path | None = None) -> Path:
    """Ensure writes stay under outputs/v3_node/."""
    root = root or repo_root()
    out = Path(output_dir)
    if not out.is_absolute():
        out = (root / out).resolve()
    else:
        out = out.resolve()
    allowed = (root / "outputs" / "v3_node").resolve()
    try:
        out.relative_to(allowed)
    except ValueError as exc:
        raise RuntimeError(
            f"V3 NODE outputs must live under {allowed}; refused path {out}"
        ) from exc
    try:
        rel = out.relative_to(root).as_posix() + "/"
    except ValueError:
        rel = out.as_posix()
    for prefix in PROTECTED_OUTPUT_PREFIXES:
        if rel.startswith(prefix) or f"/{prefix}" in f"/{rel}":
            raise RuntimeError(f"Refusing write into protected path prefix {prefix}")
    return out


def verify_checkpoint_hash_stable(
    checkpoint_path: Path,
    *,
    before_hash: str | None = None,
) -> dict[str, str | bool]:
    """Hash a pretrained checkpoint before/after load; refuse mutation."""
    path = Path(checkpoint_path)
    if not path.exists():
        raise FileNotFoundError(path)
    after = sha256_file(path)
    before = before_hash if before_hash is not None else after
    return {
        "checkpoint": str(path),
        "sha256_before": before,
        "sha256_after": after,
        "unchanged": before == after,
    }
