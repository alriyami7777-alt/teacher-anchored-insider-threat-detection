"""Byte hashes used by EDITOR-010 (authorised paths only)."""

from __future__ import annotations

import hashlib
from pathlib import Path

from .safety import assert_path_allowed_for_read, assert_output_namespace


def sha256_file(path: Path | str, *, write: bool = False) -> str:
    p = Path(path)
    if write:
        assert_output_namespace(p)
    else:
        assert_path_allowed_for_read(p, context="hash")
    digest = hashlib.sha256()
    with p.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()
