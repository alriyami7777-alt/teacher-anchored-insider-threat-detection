from __future__ import annotations

from pathlib import Path

from editor006b_harness.input_bundle import FUTURE_METADATA_FIELDS, build_synthetic_bundle, metadata_schema
from editor006b_harness.scoring import load_sequence_metadata, persist_sequence_metadata


def _roles(syn):
    official_pos = []
    contextual_pos = []
    benign = []
    one_scenario = []
    multi_scenario = []
    for row in syn["identifiers"]:
        if row.official_insider_flag == 1 and row.completed_window_label == 1:
            official_pos.append(row)
        if row.official_insider_flag != 1 and row.completed_window_label == 1:
            contextual_pos.append(row)
        if row.completed_window_label == 0:
            benign.append(row)
        if len(row.answer_scenario_ids) == 1:
            one_scenario.append(row)
        if len(row.answer_scenario_ids) >= 2:
            multi_scenario.append(row)
    return official_pos, contextual_pos, benign, one_scenario, multi_scenario


def test_h13_h15_scenario_metadata_preserved_through_phases(tmp_path: Path):
    syn = build_synthetic_bundle()
    official_pos, contextual_pos, benign, one_scenario, multi_scenario = _roles(syn)
    assert official_pos, "need official insider positive"
    assert contextual_pos, "need contextual non-insider positive"
    assert benign, "need benign user"
    assert one_scenario, "need single-scenario window"
    assert multi_scenario, "need multi-scenario window"

    schema = metadata_schema()
    assert schema["distinction"] == "official_incident_id != contextual scenario evidence"
    for row in syn["identifiers"]:
        for field in FUTURE_METADATA_FIELDS:
            assert hasattr(row, field)

    input_records = persist_sequence_metadata(tmp_path, syn["identifiers"])
    after_scores = load_sequence_metadata(tmp_path)
    assert input_records["records"] == after_scores["records"]
    by_id = {r["sequence_id"]: r for r in after_scores["records"]}
    for row in syn["identifiers"]:
        rec = by_id[row.sequence_id]
        assert rec["user_id"] == row.user_id
        assert rec["completed_window_label"] == row.completed_window_label
        assert rec["endpoint_label"] == row.endpoint_label
        assert rec["official_insider_flag"] == row.official_insider_flag
        assert rec["official_incident_id"] == row.official_incident_id
        assert rec["answer_scenario_ids"] == list(row.answer_scenario_ids)
        assert rec["endpoint_answer_scenario_ids"] == list(row.endpoint_answer_scenario_ids)
        assert rec["official_incident_id"] is None or rec["official_insider_flag"] == 1


def test_h14_official_incident_id_null_for_contextual_only():
    syn = build_synthetic_bundle()
    contextual = [
        r
        for r in syn["identifiers"]
        if r.official_insider_flag != 1 and r.completed_window_label == 1
    ]
    assert contextual
    for row in contextual:
        assert row.official_incident_id is None
        assert len(row.answer_scenario_ids) >= 1
    official = [r for r in syn["identifiers"] if r.official_insider_flag == 1]
    assert official
    for row in official:
        assert row.official_incident_id == "rSYN-1"


def test_h15_multi_scenario_window_metadata_preserved():
    syn = build_synthetic_bundle()
    multi = [r for r in syn["identifiers"] if len(r.answer_scenario_ids) >= 2]
    assert multi
    for row in multi:
        assert row.answer_scenario_ids == tuple(sorted(set(row.answer_scenario_ids)))
        assert set(row.answer_scenario_ids) >= {1, 4}
        assert row.official_incident_id is None
        assert row.official_insider_flag != 1
    one = [r for r in syn["identifiers"] if r.answer_scenario_ids == (1,) and r.official_insider_flag == 1]
    assert one
