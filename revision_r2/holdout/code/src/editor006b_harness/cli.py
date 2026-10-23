"""CLI and external-run authorisation gate.

EDITOR-006B1 binds authorisation to the actual input-bundle manifest hash.
A failed authorisation aborts before any external input file is opened.
This module never writes a valid r6.2 authorisation file and never opens
an r6.2 bundle.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .safety import (
    FUTURE_EXTERNAL_DATASET_ID,
    HarnessProtocolError,
    hash_harness_sources,
    refuse_dataset_id_r62,
    refuse_r62_without_auth,
)

REQUIRED_AUTH_FIELDS = (
    "task_id",
    "dataset_id",
    "input_bundle_manifest_sha256",
    "contract_bundle_sha256",
    "harness_code_sha256",
    "model_allowlist_sha256",
    "authorised_timestamp",
    "predictive_external_run_authorised",
)

_EXACT_HASH_FIELDS = (
    "input_bundle_manifest_sha256",
    "contract_bundle_sha256",
    "harness_code_sha256",
    "model_allowlist_sha256",
)


def contract_bundle_hash(file_hashes: dict[str, str]) -> str:
    import hashlib

    blob = json.dumps(file_hashes, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def parse_authorised_timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise HarnessProtocolError("EXTERNAL GATE: authorised_timestamp missing or empty")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise HarnessProtocolError("EXTERNAL GATE: malformed authorised_timestamp") from exc
    return parsed


def open_external_input_bundle(path: Path | str) -> dict[str, Any]:
    """Future bundle opener. EDITOR-006B1 always refuses r6.2 / external open."""
    raise HarnessProtocolError(
        "EXTERNAL GATE: EDITOR-006B1 refuses to open an external input bundle; "
        f"path={path}"
    )


def validate_external_authorization(
    auth_path: Path | None,
    *,
    expected_task_id: str,
    expected_dataset_id: str,
    expected_input_bundle_manifest_sha256: str,
    expected_contract_bundle_sha256: str,
    expected_harness_code_sha256: str,
    expected_model_allowlist_sha256: str,
) -> dict[str, Any]:
    """Fail-closed schema + exact-value checks. Does not open the input bundle."""
    if not expected_input_bundle_manifest_sha256:
        raise HarnessProtocolError(
            "EXTERNAL GATE: missing expected input_bundle_manifest_sha256"
        )
    if not expected_task_id:
        raise HarnessProtocolError("EXTERNAL GATE: missing expected task_id")
    if auth_path is None:
        raise HarnessProtocolError("EXTERNAL GATE: missing --authorization / absent authorisation")
    path = Path(auth_path)
    if not path.is_file():
        raise HarnessProtocolError("EXTERNAL GATE: authorisation file not found")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HarnessProtocolError("EXTERNAL GATE: malformed authorisation JSON") from exc
    if not isinstance(raw, dict):
        raise HarnessProtocolError("EXTERNAL GATE: malformed authorisation (not an object)")
    missing = [k for k in REQUIRED_AUTH_FIELDS if k not in raw]
    if missing:
        raise HarnessProtocolError(f"EXTERNAL GATE: malformed authorisation, missing {missing}")
    if raw.get("task_id") != expected_task_id:
        raise HarnessProtocolError(
            f"EXTERNAL GATE: wrong task_id {raw.get('task_id')!r} expected {expected_task_id!r}"
        )
    if raw.get("dataset_id") != expected_dataset_id:
        raise HarnessProtocolError(
            f"EXTERNAL GATE: wrong dataset_id {raw.get('dataset_id')!r} expected {expected_dataset_id!r}"
        )
    observed_bundle = raw.get("input_bundle_manifest_sha256")
    if not observed_bundle:
        raise HarnessProtocolError("EXTERNAL GATE: missing input_bundle_manifest_sha256")
    if observed_bundle != expected_input_bundle_manifest_sha256:
        raise HarnessProtocolError("EXTERNAL GATE: wrong input_bundle_manifest_sha256")
    if raw.get("contract_bundle_sha256") != expected_contract_bundle_sha256:
        raise HarnessProtocolError("EXTERNAL GATE: wrong contract_bundle_sha256")
    if raw.get("harness_code_sha256") != expected_harness_code_sha256:
        raise HarnessProtocolError("EXTERNAL GATE: wrong harness_code_sha256")
    if raw.get("model_allowlist_sha256") != expected_model_allowlist_sha256:
        raise HarnessProtocolError("EXTERNAL GATE: wrong model_allowlist_sha256")
    for field in _EXACT_HASH_FIELDS:
        val = raw.get(field)
        if not isinstance(val, str) or not val:
            raise HarnessProtocolError(f"EXTERNAL GATE: empty {field}")
    parse_authorised_timestamp(raw.get("authorised_timestamp"))
    if raw.get("predictive_external_run_authorised") is not True:
        raise HarnessProtocolError("EXTERNAL GATE: predictive_external_run_authorised is not true")
    if expected_dataset_id == FUTURE_EXTERNAL_DATASET_ID and raw.get("dataset_id") != FUTURE_EXTERNAL_DATASET_ID:
        raise HarnessProtocolError("EXTERNAL GATE: future r6.2 dataset_id mismatch")
    return {"status": "PASS", "auth_path": str(path), "bundle_opened": False}


def gated_external_execution(
    *,
    auth_path: Path | None,
    expected_task_id: str,
    expected_dataset_id: str,
    expected_input_bundle_manifest_sha256: str,
    expected_contract_bundle_sha256: str,
    expected_harness_code_sha256: str,
    expected_model_allowlist_sha256: str,
    bundle_path: Path | str | None,
    open_bundle_fn: Callable[[Path], Any] | None = None,
) -> Any:
    """read auth → validate schema → validate hashes/ids → only then open bundle."""
    validate_external_authorization(
        auth_path,
        expected_task_id=expected_task_id,
        expected_dataset_id=expected_dataset_id,
        expected_input_bundle_manifest_sha256=expected_input_bundle_manifest_sha256,
        expected_contract_bundle_sha256=expected_contract_bundle_sha256,
        expected_harness_code_sha256=expected_harness_code_sha256,
        expected_model_allowlist_sha256=expected_model_allowlist_sha256,
    )
    fn = open_bundle_fn if open_bundle_fn is not None else open_external_input_bundle
    if bundle_path is None:
        raise HarnessProtocolError("EXTERNAL GATE: missing input bundle path after authorisation")
    return fn(Path(bundle_path))


def assert_fixture_path_allowed(path: str | Path, *, authorised: bool) -> None:
    refuse_r62_without_auth(path, authorised=authorised)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="editor006b_harness")
    parser.add_argument(
        "--mode",
        choices=("synthetic", "development", "all-fixtures", "external"),
        default="all-fixtures",
    )
    parser.add_argument("--authorization", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--freeze-dir", type=Path, default=None)
    parser.add_argument("--batch-size", type=int, default=1024)
    parser.add_argument(
        "--input-bundle",
        type=Path,
        default=None,
        help="Forbidden for r6.2 in EDITOR-006B1",
    )
    parser.add_argument(
        "--expected-input-bundle-manifest-sha256",
        type=str,
        default=None,
        help="Required for external mode; binds authorisation to the actual bundle hash",
    )
    parser.add_argument(
        "--expected-task-id",
        type=str,
        default=None,
        help="Required for external mode; exact task_id match",
    )
    return parser.parse_args(argv)


def prepare_mode(args: argparse.Namespace, *, contract_hash: str, allowlist_hash: str) -> str:
    """External mode: authorise first, never open the bundle on failure. 006B1 never opens r6.2."""
    if args.mode == "external":
        expected_bundle = getattr(args, "expected_input_bundle_manifest_sha256", None)
        expected_task = getattr(args, "expected_task_id", None)
        if not expected_bundle:
            raise HarnessProtocolError(
                "EXTERNAL GATE: missing expected input_bundle_manifest_sha256"
            )
        if not expected_task:
            raise HarnessProtocolError("EXTERNAL GATE: missing expected task_id")
        gated_external_execution(
            auth_path=args.authorization,
            expected_task_id=str(expected_task),
            expected_dataset_id=FUTURE_EXTERNAL_DATASET_ID,
            expected_input_bundle_manifest_sha256=str(expected_bundle),
            expected_contract_bundle_sha256=contract_hash,
            expected_harness_code_sha256=hash_harness_sources(),
            expected_model_allowlist_sha256=allowlist_hash,
            bundle_path=args.input_bundle,
            open_bundle_fn=open_external_input_bundle,
        )
        raise HarnessProtocolError("EXTERNAL GATE: unreachable after refused bundle open")
    if args.input_bundle is not None:
        refuse_r62_without_auth(args.input_bundle, authorised=False)
        refuse_dataset_id_r62(str(args.input_bundle), authorised=False)
    return args.mode
