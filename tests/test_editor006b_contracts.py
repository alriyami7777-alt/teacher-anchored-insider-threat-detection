from __future__ import annotations

from editor006b_harness.contracts import load_freeze_bundle, validate_contracts
from editor006b_harness.safety import C2_SEED62_THRESHOLD, EXPECTED_FAMILIES, SEEDS


def test_t01_t04_contract_schema():
    bundle = load_freeze_bundle()
    validated = validate_contracts(bundle)
    assert validated["status"] == "PASS"
    assert validated["n_allow"] == 18
    assert validated["n_deny"] == 3
    assert validated["allow_deny_disjoint"] is True
    artefacts = validated["artefacts"]
    assert {a["family"] for a in artefacts} == set(EXPECTED_FAMILIES)
    for fam in EXPECTED_FAMILIES:
        assert sorted(int(a["seed"]) for a in artefacts if a["family"] == fam) == list(SEEDS)
    assert validated["c2_seed62_threshold"] == C2_SEED62_THRESHOLD
    assert validated["label_rule"] == "R52_LABEL_RULE_EVENT_LEVEL_ANSWER_MATCH"
