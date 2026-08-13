from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from editor006b_harness.contracts import load_freeze_bundle, validate_contracts
from editor006b_harness.hash_gate import gate_one, preflight_all_eighteen
from editor006b_harness.safety import HarnessProtocolError, sha256_file


def _ctx():
    bundle = load_freeze_bundle()
    validated = validate_contracts(bundle)
    deny = set(validated["deny_hashes"])
    allow = {str(a["expected_sha256"]) for a in validated["artefacts"]}
    return validated, deny, allow, bundle


def test_t05_all_eighteen_hashes_match():
    validated, deny, _allow, _bundle = _ctx()
    rows = preflight_all_eighteen(validated["artefacts"], deny)
    assert len(rows) == 18
    assert all(r["status"] == "MATCH" for r in rows)


def test_t06_denied_c5_blocked_before_deserialisation():
    validated, deny, allow, bundle = _ctx()
    art = bundle["EDITOR006A_C5_DENYLIST.json"]["artefacts"][0]
    with pytest.raises(HarnessProtocolError, match="deny-listed"):
        gate_one(
            family="C5_original_paper",
            seed=42,
            path=art["path"],
            expected_sha256=validated["artefacts"][6]["expected_sha256"],
            deny_hashes=deny,
            allow_hashes=allow,
        )


def test_t07_unknown_hash_blocked():
    validated, deny, allow, _bundle = _ctx()
    with tempfile.NamedTemporaryFile(delete=False) as handle:
        handle.write(b"editor006b-unknown")
        path = Path(handle.name)
    try:
        sha = sha256_file(path)
        with pytest.raises(HarnessProtocolError, match="unknown"):
            gate_one(
                family="C2",
                seed=42,
                path=path,
                expected_sha256=sha,
                deny_hashes=deny,
                allow_hashes=allow,
            )
    finally:
        path.unlink(missing_ok=True)


def test_t08_tampered_blocked():
    validated, deny, allow, _bundle = _ctx()
    src = Path(validated["artefacts"][0]["path"])
    with tempfile.NamedTemporaryFile(delete=False) as handle:
        data = src.read_bytes()
        handle.write(bytes([data[0] ^ 0xFF]) + data[1:])
        path = Path(handle.name)
    try:
        with pytest.raises(HarnessProtocolError, match="mismatch"):
            gate_one(
                family=validated["artefacts"][0]["family"],
                seed=int(validated["artefacts"][0]["seed"]),
                path=path,
                expected_sha256=validated["artefacts"][0]["expected_sha256"],
                deny_hashes=deny,
                allow_hashes=allow,
            )
    finally:
        path.unlink(missing_ok=True)
