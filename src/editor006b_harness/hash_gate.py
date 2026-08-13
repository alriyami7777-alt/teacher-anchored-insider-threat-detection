"""SHA-256 hash gate. Must run before any model deserialisation."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .safety import HarnessProtocolError, sha256_file


def hash_artefact(path: Path) -> str:
    if not Path(path).is_file():
        raise HarnessProtocolError(f"HASH GATE: missing artefact: {path}")
    return sha256_file(Path(path))


def gate_one(
    *,
    family: str,
    seed: int,
    path: str | Path,
    expected_sha256: str,
    deny_hashes: set[str],
    allow_hashes: set[str],
) -> dict[str, Any]:
    """Abort before deserialisation on deny / unknown / mismatch."""
    observed = hash_artefact(Path(path))
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    row = {
        "family": family,
        "seed": int(seed),
        "path": str(path),
        "expected_sha256": expected_sha256,
        "observed_sha256": observed,
        "hash_timestamp_utc": ts,
        "status": "MATCH",
    }
    if observed in deny_hashes:
        raise HarnessProtocolError(
            f"HASH GATE ABORT BEFORE DESERIALISATION: deny-listed SHA-256 "
            f"family={family} seed={seed} sha={observed}"
        )
    if expected_sha256 != observed:
        raise HarnessProtocolError(
            f"HASH GATE ABORT BEFORE DESERIALISATION: expected/observed mismatch "
            f"family={family} seed={seed} expected={expected_sha256} observed={observed}"
        )
    if observed not in allow_hashes:
        raise HarnessProtocolError(
            f"HASH GATE ABORT BEFORE DESERIALISATION: unknown SHA-256 "
            f"family={family} seed={seed} sha={observed}"
        )
    return row


def preflight_all_eighteen(
    artefacts: list[dict[str, Any]],
    deny_hashes: set[str],
) -> list[dict[str, Any]]:
    if len(artefacts) != 18:
        raise HarnessProtocolError(f"HASH GATE: expected 18 artefacts, got {len(artefacts)}")
    allow_hashes = {str(a["expected_sha256"]) for a in artefacts}
    if allow_hashes & deny_hashes:
        raise HarnessProtocolError("HASH GATE: allow-list intersects deny-list")
    rows: list[dict[str, Any]] = []
    for art in artefacts:
        rows.append(
            gate_one(
                family=str(art["family"]),
                seed=int(art["seed"]),
                path=art["path"],
                expected_sha256=str(art["expected_sha256"]),
                deny_hashes=deny_hashes,
                allow_hashes=allow_hashes,
            )
        )
    if len(rows) != 18:
        raise HarnessProtocolError("HASH GATE: partial preflight is forbidden")
    if any(r["status"] != "MATCH" for r in rows):
        raise HarnessProtocolError("HASH GATE: non-MATCH row")
    return rows
