from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from editor006b_harness.cli import (
    gated_external_execution,
    open_external_input_bundle,
    prepare_mode,
    validate_external_authorization,
)
from editor006b_harness.safety import FUTURE_EXTERNAL_DATASET_ID, HarnessProtocolError, hash_harness_sources

EXPECTED_TASK = "EDITOR-006D"
BUNDLE = "b" * 64
CONTRACT = "c" * 64
ALLOW = "a" * 64


def _harness() -> str:
    return hash_harness_sources()


def _write_auth(tmp_path: Path, **kwargs):
    payload = {
        "task_id": EXPECTED_TASK,
        "dataset_id": FUTURE_EXTERNAL_DATASET_ID,
        "input_bundle_manifest_sha256": BUNDLE,
        "contract_bundle_sha256": CONTRACT,
        "harness_code_sha256": _harness(),
        "model_allowlist_sha256": ALLOW,
        "authorised_timestamp": "2026-08-13T00:00:00Z",
        "predictive_external_run_authorised": True,
    }
    payload.update(kwargs)
    path = tmp_path / "auth.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _kwargs(overrides: dict | None = None) -> dict:
    kw = {
        "expected_task_id": EXPECTED_TASK,
        "expected_dataset_id": FUTURE_EXTERNAL_DATASET_ID,
        "expected_input_bundle_manifest_sha256": BUNDLE,
        "expected_contract_bundle_sha256": CONTRACT,
        "expected_harness_code_sha256": _harness(),
        "expected_model_allowlist_sha256": ALLOW,
    }
    if overrides:
        kw.update(overrides)
    return kw


def _gated(tmp_path: Path, auth_path, spy, **auth_overrides):
    path = auth_path if auth_path is None else _write_auth(tmp_path, **auth_overrides) if auth_path == "write" else auth_path
    return gated_external_execution(
        auth_path=path,
        bundle_path=tmp_path / "bundle.json",
        open_bundle_fn=spy,
        **_kwargs(),
    )


def test_t35_t37_external_gate(tmp_path: Path):
    harness = _harness()
    with pytest.raises(HarnessProtocolError, match="absent authorisation|missing"):
        validate_external_authorization(None, **_kwargs())
    bad = tmp_path / "malformed.json"
    bad.write_text("{nope", encoding="utf-8")
    with pytest.raises(HarnessProtocolError, match="malformed"):
        validate_external_authorization(bad, **_kwargs())

    with pytest.raises(HarnessProtocolError, match="wrong dataset"):
        validate_external_authorization(
            _write_auth(tmp_path, dataset_id="CERT r4.2"), **_kwargs()
        )
    with pytest.raises(HarnessProtocolError, match="wrong contract"):
        validate_external_authorization(
            _write_auth(tmp_path, contract_bundle_sha256="deadbeef"), **_kwargs()
        )
    with pytest.raises(HarnessProtocolError, match="wrong harness"):
        validate_external_authorization(
            _write_auth(tmp_path, harness_code_sha256="deadbeef"), **_kwargs()
        )
    with pytest.raises(HarnessProtocolError, match="not true"):
        validate_external_authorization(
            _write_auth(tmp_path, predictive_external_run_authorised=False), **_kwargs()
        )

    fake = tmp_path / "r6.2" / "manifest.json"
    fake.parent.mkdir()
    fake.write_text(json.dumps({"dataset_id": "CERT r6.2"}), encoding="utf-8")

    class Args:
        mode = "synthetic"
        authorization = None
        input_bundle = fake
        expected_input_bundle_manifest_sha256 = None
        expected_task_id = None

    with pytest.raises(HarnessProtocolError):
        prepare_mode(Args(), contract_hash=CONTRACT, allowlist_hash=ALLOW)


def test_h01_external_auth_binds_actual_bundle_hash(tmp_path: Path):
    spy = MagicMock()
    with pytest.raises(HarnessProtocolError, match="wrong input_bundle_manifest"):
        gated_external_execution(
            auth_path=_write_auth(tmp_path, input_bundle_manifest_sha256="d" * 64),
            bundle_path=tmp_path / "never_open.json",
            open_bundle_fn=spy,
            **_kwargs(),
        )
    spy.assert_not_called()
    with pytest.raises(HarnessProtocolError, match="missing"):
        validate_external_authorization(
            _write_auth(tmp_path),
            **_kwargs({"expected_input_bundle_manifest_sha256": ""}),
        )
    spy.assert_not_called()


def test_h02_wrong_bundle_hash_blocks_before_open(tmp_path: Path):
    spy = MagicMock()
    with pytest.raises(HarnessProtocolError, match="wrong input_bundle_manifest"):
        gated_external_execution(
            auth_path=_write_auth(tmp_path, input_bundle_manifest_sha256="e" * 64),
            bundle_path=tmp_path / "bundle.json",
            open_bundle_fn=spy,
            **_kwargs(),
        )
    spy.assert_not_called()


def test_h03_wrong_task_id_blocks_before_open(tmp_path: Path):
    spy = MagicMock()
    with pytest.raises(HarnessProtocolError, match="wrong task_id"):
        gated_external_execution(
            auth_path=_write_auth(tmp_path, task_id="EDITOR-006B1"),
            bundle_path=tmp_path / "bundle.json",
            open_bundle_fn=spy,
            **_kwargs(),
        )
    spy.assert_not_called()


def test_h04_malformed_authorised_timestamp_blocks(tmp_path: Path):
    spy = MagicMock()
    with pytest.raises(HarnessProtocolError, match="malformed authorised_timestamp"):
        gated_external_execution(
            auth_path=_write_auth(tmp_path, authorised_timestamp="not-a-timestamp"),
            bundle_path=tmp_path / "bundle.json",
            open_bundle_fn=spy,
            **_kwargs(),
        )
    spy.assert_not_called()
    with pytest.raises(HarnessProtocolError, match="missing or empty"):
        gated_external_execution(
            auth_path=_write_auth(tmp_path, authorised_timestamp=""),
            bundle_path=tmp_path / "bundle.json",
            open_bundle_fn=spy,
            **_kwargs(),
        )
    spy.assert_not_called()


def test_h01_companion_auth_failures_never_open_bundle(tmp_path: Path):
    spy = MagicMock()
    cases = [
        ({}, {"expected_task_id": "WRONG-TASK"}, "wrong task_id"),
        ({"dataset_id": "CERT r5.2"}, {}, "wrong dataset"),
        ({"contract_bundle_sha256": "f" * 64}, {}, "wrong contract"),
        ({"harness_code_sha256": "f" * 64}, {}, "wrong harness"),
        ({"model_allowlist_sha256": "f" * 64}, {}, "wrong model_allowlist"),
        ({"predictive_external_run_authorised": False}, {}, "not true"),
        ({"authorised_timestamp": "13/08/2026"}, {}, "malformed"),
    ]
    for auth_over, kw_over, _match in cases:
        spy.reset_mock()
        with pytest.raises(HarnessProtocolError):
            gated_external_execution(
                auth_path=_write_auth(tmp_path, **auth_over),
                bundle_path=tmp_path / "bundle.json",
                open_bundle_fn=spy,
                **_kwargs(kw_over),
            )
        spy.assert_not_called()

    spy.reset_mock()
    with pytest.raises(HarnessProtocolError, match="absent authorisation|missing"):
        gated_external_execution(
            auth_path=None,
            bundle_path=tmp_path / "bundle.json",
            open_bundle_fn=spy,
            **_kwargs(),
        )
    spy.assert_not_called()

    spy.reset_mock()
    missing_bundle = {
        "task_id": EXPECTED_TASK,
        "dataset_id": FUTURE_EXTERNAL_DATASET_ID,
        "contract_bundle_sha256": CONTRACT,
        "harness_code_sha256": _harness(),
        "model_allowlist_sha256": ALLOW,
        "authorised_timestamp": "2026-08-13T00:00:00Z",
        "predictive_external_run_authorised": True,
    }
    p = tmp_path / "no_bundle_hash.json"
    p.write_text(json.dumps(missing_bundle), encoding="utf-8")
    with pytest.raises(HarnessProtocolError, match="missing"):
        gated_external_execution(
            auth_path=p,
            bundle_path=tmp_path / "bundle.json",
            open_bundle_fn=spy,
            **_kwargs(),
        )
    spy.assert_not_called()


def test_open_external_bundle_refused_in_006b1(tmp_path: Path):
    with pytest.raises(HarnessProtocolError, match="refuses to open"):
        open_external_input_bundle(tmp_path / "anything.json")
