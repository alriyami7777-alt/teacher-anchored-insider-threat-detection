"""Hash-gate the twelve frozen student checkpoints from EDITOR-023."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from editor012_rescue.evaluate import hash_gate_checkpoint

from .constants import SEEDS, STUDENT_MODELS, student_checkpoint_records, teacher_checkpoint_records
from .safety import Editor024Blocked, sha256_file


def gate_student_checkpoints() -> dict[str, Any]:
    recs = []
    all_pass = True
    rows = student_checkpoint_records()
    if len(rows) != 12:
        raise Editor024Blocked(f"expected 12 student checkpoints, found {len(rows)}")
    seen = {(row["model"], int(row["seed"])) for row in rows}
    required = {(m, s) for m in STUDENT_MODELS for s in SEEDS}
    if seen != required:
        raise Editor024Blocked(f"checkpoint identity drift: {sorted(seen)} != {sorted(required)}")
    for row in rows:
        path = Path(row["path"])
        expected = str(row["expected_sha256"])
        exists = path.is_file()
        observed = sha256_file(path) if exists else None
        ok = bool(exists and observed == expected)
        if exists:
            hash_gate_checkpoint(path, expected)
        all_pass = all_pass and ok
        recs.append(
            {
                "model": row["model"],
                "seed": int(row["seed"]),
                "path": str(path),
                "expected_sha256": expected,
                "observed_sha256": observed,
                "exists": exists,
                "PASS": ok,
            }
        )
    status = "PASS" if all_pass else "FAIL"
    if not all_pass:
        raise Editor024Blocked("EDITOR024_CHECKPOINT_GATE = FAIL")
    return {"CHECKPOINT_GATE": status, "n_student_checkpoints": len(recs), "records": recs}


def gate_teacher_checkpoints() -> dict[str, Any]:
    recs = []
    all_pass = True
    for row in teacher_checkpoint_records():
        path = Path(row["path"])
        expected = str(row["expected_sha256"])
        exists = path.is_file()
        observed = sha256_file(path) if exists else None
        ok = bool(exists and observed == expected)
        if exists:
            hash_gate_checkpoint(path, expected)
        all_pass = all_pass and ok
        recs.append(
            {
                "model": row["model"],
                "seed": int(row["seed"]),
                "path": str(path),
                "expected_sha256": expected,
                "observed_sha256": observed,
                "exists": exists,
                "PASS": ok,
            }
        )
    return {
        "TEACHER_CHECKPOINT_GATE": "PASS" if all_pass else "FAIL",
        "records": recs,
        "compatible": all_pass,
    }
