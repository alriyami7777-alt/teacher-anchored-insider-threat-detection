from __future__ import annotations

from pathlib import Path

import pytest

from editor006b_harness.model_loaders import (
    construct_if_source_hash_ok,
    producing_source_preflight,
    require_source_hash,
)
from editor006b_harness.safety import HarnessProtocolError, sha256_file


def test_h08_source_hash_gate_before_architecture_construction(tmp_path: Path):
    src = tmp_path / "architecture.py"
    src.write_text("# synthetic producing-source fixture\nclass AttentionNodeEnsemble:\n    pass\n", encoding="utf-8")
    expected = sha256_file(src)
    constructed: list[str] = []

    def construct() -> str:
        constructed.append("constructed")
        return "model"

    out = construct_if_source_hash_ok(
        component="teacher_c2_c5_architecture",
        path=src,
        expected_sha256=expected,
        construct=construct,
    )
    assert out == "model"
    assert constructed == ["constructed"]

    real = producing_source_preflight()
    assert real["status"] == "PASS"
    assert all(row["status"] == "MATCH" for row in real["components"])
    names = {row["component"] for row in real["components"]}
    assert names == {
        "teacher_c2_c5_architecture",
        "odst_implementation",
        "attention_linear",
        "rf_xgb_aggregator",
    }


def test_h09_tampered_architecture_source_blocked(tmp_path: Path):
    src = tmp_path / "architecture.py"
    src.write_text("# authentic copy\n", encoding="utf-8")
    expected = sha256_file(src)
    tampered = tmp_path / "architecture_tampered.py"
    tampered.write_text("# authentic copy\n# tampered\n", encoding="utf-8")
    constructed: list[str] = []

    def construct() -> str:
        constructed.append("constructed")
        return "model"

    with pytest.raises(HarnessProtocolError, match="SOURCE HASH GATE ABORT BEFORE ARCHITECTURE CONSTRUCTION"):
        construct_if_source_hash_ok(
            component="teacher_c2_c5_architecture",
            path=tampered,
            expected_sha256=expected,
            construct=construct,
        )
    assert constructed == []

    with pytest.raises(HarnessProtocolError, match="SOURCE HASH GATE ABORT BEFORE ARCHITECTURE CONSTRUCTION"):
        require_source_hash(
            component="teacher_c2_c5_architecture",
            path=tampered,
            expected_sha256=expected,
        )
    assert constructed == []
