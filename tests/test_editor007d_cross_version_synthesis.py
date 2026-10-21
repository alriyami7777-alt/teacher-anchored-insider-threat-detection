"""EDITOR-007D tests. Does not score. Does not train. No r5.2 TEST."""
from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_editor007d_cross_version_synthesis.py"
REVIEW = ROOT / "review" / "editor007d_cross_version_synthesis"
PRED_R51 = ROOT / "review" / "editor007c1_r51_result_freeze" / "EDITOR007C_PREDICTIVE_RESULTS_PAPER_CORRECTED.json"
THR = ROOT / "review" / "editor006a_preinference_freeze" / "EDITOR006A_THRESHOLDS.json"

FAMILIES = (
    "teacher_frozen_odst",
    "C2",
    "C5_original_paper",
    "attention_linear",
    "RF_40",
    "XGBoost_40",
)
REQUIRED_CLAIMS = {
    "teacher initialisation is load-bearing",
    "anchoring constrains teacher-relative logit drift",
    "anchoring constrains routing drift",
    "anchoring improves predictive performance",
    "ODST is predictively superior to attention-linear",
    "model generalises across CERT versions",
    "frozen thresholds are portable",
    "RF/XGBoost remain strong engineered-tabular references",
    "reference-centred explanation evidence",
    "degraded-input evidence",
}


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def _calls(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            names.add(func.id)
        elif isinstance(func, ast.Attribute):
            names.add(func.attr)
    return names


def test_d01_no_model_imports():
    names = _imports(SCRIPT)
    forbidden = (
        "torch",
        "joblib",
        "xgboost",
        "editor006b_harness.model_loaders",
        "editor006b_harness.scoring",
        "editor006b_harness.mechanism",
    )
    for name in names:
        assert name not in forbidden
        assert not any(name == f or name.startswith(f + ".") for f in forbidden)


def test_d02_no_predictive_inference_calls():
    calls = _calls(SCRIPT)
    for name in (
        "infer_neural",
        "infer_classical",
        "load_neural_checkpoint",
        "load_rf",
        "load_xgb",
        "write_scores_phase_streaming",
        "paired_user_cluster_bootstrap",
    ):
        assert name not in calls
    man = _json(REVIEW / "EDITOR007D_RUN_MANIFEST.json")
    assert man["protocol_flags"]["predictive_inference_executed"] is False
    assert man["protocol_flags"]["predictive_model_loaded"] is False


def test_d03_no_r52_test_access():
    marker = "r52_T20_s1" + "_test"
    src = SCRIPT.read_text(encoding="utf-8")
    assert marker not in src
    man = _json(REVIEW / "EDITOR007D_RUN_MANIFEST.json")
    assert man["protocol_flags"]["r52_test_opened"] is False
    assert man["val_npz_is_validation_not_test"] is True
    assert "validation.npz" in str(man.get("val_npz_sha256") or "") or man["val_npz_sha256"].startswith("5ac2e7e8")
    blob = json.dumps(man)
    assert marker not in blob
    report = (REVIEW / "EDITOR007D_REPORT.md").read_text(encoding="utf-8")
    assert marker not in report


def test_d04_r51_corrected_derivative_used():
    man = _json(REVIEW / "EDITOR007D_RUN_MANIFEST.json")
    assert Path(man["r51_predictive_source"]) == PRED_R51
    assert PRED_R51.name == "EDITOR007C_PREDICTIVE_RESULTS_PAPER_CORRECTED.json"
    ruling = _json(REVIEW / "EDITOR007D_DIAGNOSTIC_RULING.json")
    assert ruling["r51_cluster_count"] == 4
    pred = _json(PRED_R51)
    assert pred["effective_malicious_cluster_count"] == 4


def test_d05_r51_cluster_count_exactly_four():
    ctx = _json(REVIEW / "EDITOR007D_DATASET_CONTEXT.json")
    r51 = next(r for r in ctx["rows"] if r["dataset"] == "r51_secondary_stress")
    assert r51["effective_malicious_cluster_count"] == 4
    assert r51["official_mapped_insiders"] == 4
    assert r51["official_incidents"] == 4
    cmp_rows = _json(REVIEW / "EDITOR007D_C2_C5_COMPARISON.json")["rows"]
    r51_boot = [r for r in cmp_rows if r["dataset"] == "r51_secondary_stress" and r["view"] == "DEOVERLAP_OFFSET0"]
    assert r51_boot
    assert all(r["effective_malicious_cluster_count"] == 4 for r in r51_boot)
    assert all("Four official" in r["frozen_wording"] for r in r51_boot)


def test_d06_r62_cluster_count_exactly_five():
    ctx = _json(REVIEW / "EDITOR007D_DATASET_CONTEXT.json")
    r62 = next(r for r in ctx["rows"] if r["dataset"] == "r62_external")
    assert r62["effective_malicious_cluster_count"] == 5
    assert r62["official_mapped_insiders"] == 5
    assert r62["official_incidents"] == 5
    cmp_rows = _json(REVIEW / "EDITOR007D_C2_C5_COMPARISON.json")["rows"]
    r62_boot = [r for r in cmp_rows if r["dataset"] == "r62_external" and r["view"] == "DEOVERLAP_OFFSET0"]
    assert all(r["effective_malicious_cluster_count"] == 5 for r in r62_boot)


def test_d07_no_unused_leaf_metric():
    mech = _json(REVIEW / "EDITOR007D_MECHANISM_PORTABILITY.json")["rows"]
    assert mech
    assert all(r["unused_leaf_fraction"] == "DISABLED_NOT_REPRODUCIBLE" for r in mech)
    text = json.dumps(mech)
    assert "UNUSED_LEAF" not in text or all(
        isinstance(r["unused_leaf_fraction"], str) for r in mech
    )


def test_d08_no_tree_rho_metric():
    mech = _json(REVIEW / "EDITOR007D_MECHANISM_PORTABILITY.json")["rows"]
    assert all(r["tree_contribution_rho"] == "DISABLED_NOT_REPRODUCIBLE" for r in mech)
    assert all(
        r["r52_mechanism_comparison"] == "R52_MECHANISM_COMPARISON_NOT_INCLUDED_PROVENANCE_INSUFFICIENT"
        for r in mech
    )


def test_d09_same_frozen_thresholds_preserved():
    expected = {(r["family"], int(r["seed"])): float(r["threshold"]) for r in _json(THR)["thresholds"]}
    rows = _json(REVIEW / "EDITOR007D_THRESHOLD_PORTABILITY.json")["rows"]
    matched = [r for r in rows if r.get("threshold") is not None]
    assert matched
    for row in matched:
        assert row["threshold_matches_frozen_006a"] is True
        assert abs(float(row["threshold"]) - expected[(row["family"], int(row["seed"]))]) < 1e-15
    man = _json(REVIEW / "EDITOR007D_RUN_MANIFEST.json")
    assert man["protocol_flags"]["threshold_selection_executed"] is False


def test_d10_seed_mapping_preserved():
    rows = [r for r in _json(REVIEW / "EDITOR007D_MODEL_PORTABILITY.json")["rows"] if r.get("PR_AUC") is not None]
    seeds = {int(r["seed"]) for r in rows}
    assert seeds == {42, 52, 62}
    families = {r["family"] for r in rows}
    assert families == set(FAMILIES)
    for fam in FAMILIES:
        for seed in (42, 52, 62):
            hit = [r for r in rows if r["family"] == fam and int(r["seed"]) == seed]
            assert hit


def test_d11_prevalence_derived_correctly():
    rows = [r for r in _json(REVIEW / "EDITOR007D_MODEL_PORTABILITY.json")["rows"] if r.get("PR_AUC") is not None]
    for row in rows:
        assert row["prevalence"] == row["N_positive"] / row["N"]
        assert row["negative_count"] == row["N"] - row["N_positive"]


def test_d12_negative_threshold_exceedance_is_fp_over_n_negative():
    rows = [r for r in _json(REVIEW / "EDITOR007D_THRESHOLD_PORTABILITY.json")["rows"] if r.get("FP") is not None]
    assert rows
    for row in rows:
        expected = row["FP"] / row["negative_count"]
        assert abs(row["negative_threshold_exceedance"] - expected) < 1e-15


def test_d13_r51_r62_views_not_mixed():
    rows = _json(REVIEW / "EDITOR007D_MODEL_PORTABILITY.json")["rows"]
    r51 = [r for r in rows if r["dataset"] == "r51_secondary_stress" and r.get("N") is not None]
    r62 = [r for r in rows if r["dataset"] == "r62_external" and r.get("N") is not None]
    assert {r["N"] for r in r51 if r["view"] == "COMPLETED_WINDOW"} == {996000}
    assert {r["N"] for r in r62 if r["view"] == "COMPLETED_WINDOW"} == {1988000}
    assert {r["N"] for r in r51 if r["view"] == "DEOVERLAP_OFFSET0"} == {50000}
    assert {r["N"] for r in r62 if r["view"] == "DEOVERLAP_OFFSET0"} == {100000}
    assert {r["N_positive"] for r in r51 if r["view"] == "COMPLETED_WINDOW"} == {461}
    assert {r["N_positive"] for r in r62 if r["view"] == "COMPLETED_WINDOW"} == {715}


def test_d14_r52_validation_not_mislabeled_test():
    ctx = _json(REVIEW / "EDITOR007D_DATASET_CONTEXT.json")
    r52 = next(r for r in ctx["rows"] if r["dataset"] == "r52_validation")
    assert r52["dataset_role"] == "R52_VALIDATION_IN_DOMAIN_REFERENCE"
    assert "TEST" not in r52["dataset_role"]
    assert "TEST" not in r52["dataset_label"]
    report = (REVIEW / "EDITOR007D_REPORT.md").read_text(encoding="utf-8")
    assert "R52_VALIDATION_IN_DOMAIN_REFERENCE" in report
    man = _json(REVIEW / "EDITOR007D_RUN_MANIFEST.json")
    assert man["val_npz_is_validation_not_test"] is True


def test_d15_no_scenario_cross_version_matching():
    ruling = _json(REVIEW / "EDITOR007D_DIAGNOSTIC_RULING.json")
    report = (REVIEW / "EDITOR007D_REPORT.md").read_text(encoding="utf-8")
    assert "SCENARIOS_NOT_CROSS_VERSION_MATCHED_UNITS" in report
    assert ruling["r51_cluster_count"] == 4
    assert ruling["r62_cluster_count"] == 5
    ctx = _json(REVIEW / "EDITOR007D_DATASET_CONTEXT.json")
    ids51 = next(r for r in ctx["rows"] if r["dataset"] == "r51_secondary_stress")["official_incident_ids"]
    ids62 = next(r for r in ctx["rows"] if r["dataset"] == "r62_external")["official_incident_ids"]
    assert ids51 != ids62


def test_d16_no_pvalue_significance_testing():
    feat = _json(REVIEW / "EDITOR007D_FEATURE_SHIFT.json")
    assert feat["p_values_used"] is False
    assert all(r["no_pvalue_used"] is True for r in feat["rows"])
    report = (REVIEW / "EDITOR007D_REPORT.md").read_text(encoding="utf-8")
    assert "No p-value ranking" in report
    assert "significance-star" in report
    src = SCRIPT.read_text(encoding="utf-8")
    assert "ttest" not in src.lower()
    assert "p_value" not in src or "no_pvalue" in src


def test_d17_no_new_training():
    man = _json(REVIEW / "EDITOR007D_RUN_MANIFEST.json")
    assert man["protocol_flags"]["training_executed"] is False
    assert man["protocol_flags"]["scaler_fit_executed"] is False
    assert man["protocol_flags"]["calibration_fit_executed"] is False
    src = SCRIPT.read_text(encoding="utf-8")
    assert "optimizer" not in src.lower()
    assert ".fit(" not in src


def test_d18_no_dataset_rerun():
    man = _json(REVIEW / "EDITOR007D_RUN_MANIFEST.json")
    flags = man["protocol_flags"]
    assert flags["new_dataset_evaluated"] is False
    assert flags["predictive_inference_executed"] is False
    src = SCRIPT.read_text(encoding="utf-8")
    assert "run_editor006e" not in src
    assert "run_editor007c" not in src


def test_d19_no_new_pivot_architecture_frozen():
    src = SCRIPT.read_text(encoding="utf-8")
    report = (REVIEW / "EDITOR007D_REPORT.md").read_text(encoding="utf-8")
    assert "architecture_frozen_in_007d" in src
    assert "No architecture is frozen in EDITOR-007D" in report
    ruling = _json(REVIEW / "EDITOR007D_DIAGNOSTIC_RULING.json")
    assert ruling["PRIMARY_PORTABILITY_PHENOTYPE"] == "P2_R62_SEVERE_DISTRIBUTION_AND_DECISION_SHIFT"
    assert "Do not freeze an architecture here" in ruling["questions"]["Q9"]["answer"]


def test_d20_claim_impact_table_complete():
    payload = _json(REVIEW / "EDITOR007D_CLAIM_IMPACT.json")
    names = {c["claim"] for c in payload["claims"]}
    assert names == REQUIRED_CLAIMS
    allowed = {
        "FULLY_SUPPORTED",
        "SUPPORTED_WITH_QUALIFICATION",
        "NEGATIVE_RESULT",
        "UNSUPPORTED",
        "SUPERSEDED_BY_PIVOT",
    }
    assert {c["status"] for c in payload["claims"]} <= allowed
    report = (REVIEW / "EDITOR007D_REPORT.md").read_text(encoding="utf-8")
    assert "## TABLE 10 — Current-paper claim impact" in report
    for claim in REQUIRED_CLAIMS:
        assert claim in report
    man = _json(REVIEW / "EDITOR007D_RUN_MANIFEST.json")
    assert man["task_id"] == "EDITOR-007D"
    assert all(v is False for v in man["protocol_flags"].values())
