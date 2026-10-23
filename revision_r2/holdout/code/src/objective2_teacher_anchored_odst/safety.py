"""Safety guards for teacher-anchored ODST outputs and partitions."""

from __future__ import annotations

from pathlib import Path

from prototype_v2.safety import (  # noqa: F401
    R42TestAccessError,
    assert_no_r42_test_access,
    path_looks_like_r42_test,
    refuse_if_test_requested,
    repo_root,
    sha256_file,
)

ALLOWED_OUTPUT_NAMESPACE = "outputs/objective2/teacher_anchored_odst"

PROTECTED_WRITE_PREFIXES = (
    "outputs/objective3/",
    "outputs/v3_node/",
    "outputs/baselines/",
    "outputs/objective2/r52_odst_confirmation/",
    "outputs/objective2/r52_locked_baselines/",
    "outputs/objective2/end_to_end_refinement/",
    "outputs/objective2/end_to_end_full_confirmation/",
    "outputs/objective2/residual_odst_refinement/",
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
    pass


class Objective3WriteProtectionError(RuntimeError):
    pass


class LockedArtefactWriteError(RuntimeError):
    pass


class OutputCollisionError(RuntimeError):
    pass


def assert_partition_role_permitted(role: str) -> None:
    text = (role or "").strip().lower().replace("\\", "/")
    if not text:
        raise ProtectedPartitionError("Empty partition role refused")
    for marker in FORBIDDEN_PARTITION_MARKERS:
        if marker.lower() in text:
            raise ProtectedPartitionError(f"Partition role {role!r} protected ({marker})")
    if text in {"test", "r52_test", "r5.2_test", "r6.2", "r62"}:
        raise ProtectedPartitionError(f"Partition role {role!r} protected")


def assert_path_not_protected_partition(path: str | Path) -> Path:
    p = Path(path)
    low = str(p).replace("\\", "/").lower()
    for marker in FORBIDDEN_PARTITION_MARKERS:
        if marker.lower() in low:
            raise ProtectedPartitionError(f"Refused protected path containing {marker!r}: {p}")
    if path_looks_like_r42_test(p):
        raise R42TestAccessError(f"REFUSED r4.2 test path: {p}")
    return p


def assert_output_namespace(output_dir: str | Path, root: Path | None = None) -> Path:
    root = root or repo_root()
    out = Path(output_dir)
    out = out.resolve() if out.is_absolute() else (root / out).resolve()
    try:
        rel = out.relative_to(root.resolve()).as_posix() + "/"
    except ValueError:
        rel = out.as_posix().replace("\\", "/").lower() + "/"
    for prefix in PROTECTED_WRITE_PREFIXES:
        if rel.startswith(prefix) or f"/{prefix}" in f"/{rel}":
            if prefix == "outputs/objective3/":
                raise Objective3WriteProtectionError(f"Refusing Objective 3 write: {out}")
            raise LockedArtefactWriteError(f"Refusing locked/protected write {prefix}: {out}")
    allowed = (root / ALLOWED_OUTPUT_NAMESPACE).resolve()
    try:
        out.relative_to(allowed)
    except ValueError as exc:
        raise RuntimeError(f"Teacher-anchored outputs must live under {allowed}; refused {out}") from exc
    return out


def assert_frozen_checkpoint_unchanged(path: Path, expected_sha256: str) -> str:
    digest = sha256_file(path)
    if digest.lower() != expected_sha256.lower():
        raise LockedArtefactWriteError(
            f"Frozen checkpoint hash mismatch for {path}: got {digest}, expected {expected_sha256}"
        )
    return digest


def assert_no_output_collision(out_dir: Path, run_id: str, resume_manifest: dict | None = None) -> None:
    marker = out_dir / "teacher_anchored_manifest.json"
    if not marker.exists():
        return
    import json

    existing = json.loads(marker.read_text(encoding="utf-8"))
    if existing.get("status") and existing.get("training_executed"):
        if resume_manifest and resume_manifest.get("run_id") == existing.get("run_id") == run_id:
            return
        raise OutputCollisionError(
            f"Completed teacher-anchored run already present at {marker}; refuse collision "
            f"(existing status={existing.get('status')!r})"
        )
