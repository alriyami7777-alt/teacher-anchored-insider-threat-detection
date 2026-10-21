"""EDITOR-006D1 H1 component-byte identity tests.

Synthetic / copied fixtures only. Never tampers with the derived r6.2 bundle.
Never scores CERT r6.2. Never writes a committed true authorisation.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from editor006b_harness.safety import HarnessProtocolError, sha256_file

RUNNER_PATH = ROOT / "scripts" / "run_editor006e_r62_one_pass.py"


def _load_runner():
    spec = importlib.util.spec_from_file_location("run_editor006e_r62_one_pass_d1", RUNNER_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


R = _load_runner()
REAL_BUNDLE = Path(r"C:\PhD\06_Datasets\derived\teacher_anchored_r62_editor006c_bundle")


def _component_names() -> list[str]:
    man = json.loads(R.FINAL_MANIFEST_DEFAULT.read_text(encoding="utf-8"))
    names = [row["filename"] for row in man["component_files"]]
    assert len(names) == 13
    return names


def _write_synthetic_components(bundle_dir: Path, *, tamper: str | None = None, skip: str | None = None):
    bundle_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for i, name in enumerate(_component_names()):
        if name == skip:
            continue
        payload = f"synthetic-component-{i}-{name}\n".encode("utf-8")
        path = bundle_dir / name
        path.write_bytes(payload)
        rows.append(
            {
                "filename": name,
                "sha256": sha256_file(path),
                "byte_size": path.stat().st_size,
            }
        )
    if tamper is not None:
        target = bundle_dir / tamper
        target.write_bytes(target.read_bytes() + b"TAMPER")
    return {"component_files": rows}


def _d1_auth(tmp_path: Path, **overrides) -> Path:
    payload = {
        "task_id": R.TASK_ID_FUTURE,
        "dataset_id": R.DATASET_ID,
        "input_bundle_manifest_sha256": R.FINAL_RELEASE_MANIFEST_SHA256,
        "contract_bundle_sha256": R.CONTRACT_BUNDLE_SHA256,
        "harness_code_sha256": R.HARNESS_CODE_SHA256,
        "model_allowlist_sha256": R.MODEL_ALLOWLIST_SHA256,
        "authorised_timestamp": "2026-08-13T00:00:00Z",
        "predictive_external_run_authorised": True,
        "external_runner_sha256": R.compute_external_runner_sha256(),
        "harness_runner_sha256": R.HARNESS_RUNNER_SHA256,
        "editor006c_release_commit": R.EDITOR006C_RELEASE_COMMIT,
        "sequence_order_sha256": R.SEQUENCE_ORDER_SHA256,
        "scaler_sha256": R.SCALER_SHA256,
        "editor006d_runner_release_commit": R.EDITOR006D_REVIEWED_BASE_COMMIT,
    }
    payload.update(overrides)
    path = tmp_path / "auth.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_d2_all_thirteen_component_identities_validated(tmp_path: Path):
    bundle = tmp_path / "syn_bundle"
    man = _write_synthetic_components(bundle)
    table = R.verify_bundle_component_identity(bundle, man)
    assert table["status"] == "PASS"
    assert table["n_components"] == 13
    assert len(table["components"]) == 13
    assert all(row["match"] is True for row in table["components"])
    names = {row["filename"] for row in table["components"]}
    assert names == set(_component_names())


def test_d2_tampered_copied_fixture_aborts(tmp_path: Path):
    bundle = tmp_path / "syn_bundle"
    man = _write_synthetic_components(bundle)
    tamper_name = _component_names()[0]
    (bundle / tamper_name).write_bytes((bundle / tamper_name).read_bytes() + b"X")
    with pytest.raises(HarnessProtocolError, match="BUNDLE_COMPONENT_IDENTITY_MISMATCH"):
        R.verify_bundle_component_identity(bundle, man)


def test_d2_missing_component_aborts(tmp_path: Path):
    bundle = tmp_path / "syn_bundle"
    skip = _component_names()[1]
    man = _write_synthetic_components(bundle, skip=skip)
    man["component_files"].insert(
        1,
        {"filename": skip, "sha256": "ab" * 32, "byte_size": 1},
    )
    with pytest.raises(HarnessProtocolError, match="BUNDLE_COMPONENT_IDENTITY_MISMATCH"):
        R.verify_bundle_component_identity(bundle, man)


def test_d2_byte_size_mismatch_aborts(tmp_path: Path):
    bundle = tmp_path / "syn_bundle"
    man = _write_synthetic_components(bundle)
    man["component_files"][0]["byte_size"] = int(man["component_files"][0]["byte_size"]) + 1
    with pytest.raises(HarnessProtocolError, match="BUNDLE_COMPONENT_IDENTITY_MISMATCH"):
        R.verify_bundle_component_identity(bundle, man)


def test_d1_tamper_blocks_before_execution_started(tmp_path: Path):
    bundle = tmp_path / "copied_bundle"
    _write_synthetic_components(bundle)
    out = tmp_path / "out"
    spy = MagicMock()
    state = R.ExecutionAuditState()
    with pytest.raises(HarnessProtocolError, match="BUNDLE_COMPONENT_IDENTITY_MISMATCH"):
        R.execute_external_one_pass(
            auth_path=_d1_auth(tmp_path),
            output_dir=out,
            bundle_dir=bundle,
            final_manifest_path=R.FINAL_MANIFEST_DEFAULT,
            open_bundle_fn=spy,
            audit=state,
        )
    spy.assert_not_called()
    assert not (out / "EXECUTION_STARTED.json").exists()
    assert state.bundle_opened is False
    assert state.execution_started is False
    assert state.predictive_execution_report() == "NO"
    assert bundle.resolve() != REAL_BUNDLE.resolve()


def test_d1_identity_runs_before_model_deserialisation():
    import inspect

    src = inspect.getsource(R.execute_external_one_pass)
    ident = src.index("verify_bundle_component_identity")
    started = src.index("write_execution_started")
    scoring = src.index("write_scores_phase_streaming")
    assert ident < started < scoring


def test_d11_no_true_authorisation_created_by_runner():
    src = RUNNER_PATH.read_text(encoding="utf-8")
    assert "predictive_external_run_authorised\": true" not in src
    assert "TRUE_AUTH" not in src
    review = ROOT / "review" / "editor006d1_external_runner_hardening"
    if review.is_dir():
        for path in review.rglob("*"):
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            assert '"predictive_external_run_authorised": true' not in text
            assert '"predictive_external_run_authorised": True' not in text


def test_d12_tests_do_not_score_r62_or_open_real_bundle():
    here = Path(__file__).read_text(encoding="utf-8")
    forbidden = (
        "R.open_external_bundle(" + "REAL_BUNDLE",
        "--" + "execute-external",
        "bundle_dir=" + "REAL_BUNDLE",
        "bundle_dir=" + "R.BUNDLE_DIR_DEFAULT",
    )
    for token in forbidden:
        assert token not in here
    assert R.BUNDLE_DIR_DEFAULT == REAL_BUNDLE
