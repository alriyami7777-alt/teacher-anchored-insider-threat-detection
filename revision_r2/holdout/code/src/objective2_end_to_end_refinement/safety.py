"""Safety for Objective 2 end-to-end refinement study."""

from __future__ import annotations

from pathlib import Path

from prototype_v2.safety import (  # noqa: F401
    R42TestAccessError,
    assert_no_r42_test_access,
    default_v1_encoder_checkpoint,
    path_looks_like_r42_test,
    refuse_if_test_requested,
    repo_root,
    sha256_file,
)

ALLOWED_OUTPUT_NAMESPACE = "outputs/objective2/end_to_end_refinement"

PROTECTED_WRITE_PREFIXES = (
    "outputs/objective3/",
    "outputs/v3_node/",
    "outputs/baselines/",
    "outputs/objective2/r52_odst_confirmation/",
    "outputs/objective2/r52_locked_baselines/",
    "outputs/chapter4/",
    "docs/cert_r42_notes.md",
)

FORBIDDEN_PARTITION_MARKERS = (
    "later-development",
    "later_development",
    "r42_later",
    "r4.2 later",
    "r42_T20_s1_test",
    "r5.2_test",
    "r52_test",
    "r5.2/test",
    "r6.2",
    "r62_external",
    "cert_r6.2",
)


class ProtectedPartitionError(RuntimeError):
    """Raised when a protected CERT partition is requested."""


class Objective3WriteProtectionError(RuntimeError):
    """Raised when a write targets Objective 3 outputs."""


def assert_partition_role_permitted(role: str) -> None:
    text = (role or "").strip().lower().replace("\\", "/")
    if not text:
        raise ProtectedPartitionError("Empty partition role is refused")
    for marker in FORBIDDEN_PARTITION_MARKERS:
        if marker.lower() in text:
            raise ProtectedPartitionError(
                f"Partition role {role!r} is protected ({marker})"
            )
    if text in {"test", "r52_test", "r5.2_test", "r6.2", "r62"}:
        raise ProtectedPartitionError(f"Partition role {role!r} is protected")


def assert_path_not_protected_partition(path: str | Path) -> Path:
    p = Path(path)
    low = str(p).replace("\\", "/").lower()
    for marker in FORBIDDEN_PARTITION_MARKERS:
        if marker.lower() in low:
            raise ProtectedPartitionError(
                f"Refused protected partition path containing {marker!r}: {p}"
            )
    if path_looks_like_r42_test(p):
        raise R42TestAccessError(f"REFUSED r4.2 test path: {p}")
    return p


def assert_output_namespace(output_dir: str | Path, root: Path | None = None) -> Path:
    """Allow writes only under outputs/objective2/end_to_end_refinement/."""
    root = root or repo_root()
    out = Path(output_dir)
    if not out.is_absolute():
        out = (root / out).resolve()
    else:
        out = out.resolve()
    try:
        rel = out.relative_to(root.resolve()).as_posix() + "/"
    except ValueError:
        rel = out.as_posix().replace("\\", "/").lower() + "/"
    for prefix in PROTECTED_WRITE_PREFIXES:
        if rel.startswith(prefix) or f"/{prefix}" in f"/{rel}":
            if prefix == "outputs/objective3/":
                raise Objective3WriteProtectionError(
                    f"Refusing write into Objective 3 outputs: {out}"
                )
            raise RuntimeError(f"Refusing write into protected path prefix {prefix}")
    allowed = (root / ALLOWED_OUTPUT_NAMESPACE).resolve()
    try:
        out.relative_to(allowed)
    except ValueError as exc:
        raise RuntimeError(
            f"Refinement outputs must live under {allowed}; refused {out}"
        ) from exc
    return out


def assert_no_objective3_modification(paths: list[str | Path]) -> None:
    for path in paths:
        low = str(path).replace("\\", "/").lower()
        if "outputs/objective3/" in low:
            raise Objective3WriteProtectionError(
                f"Objective 3 output modification refused: {path}"
            )
