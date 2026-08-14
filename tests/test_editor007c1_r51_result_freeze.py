"""EDITOR-007C1 tests. Does not score r5.1. Does not rerun r6.2. No r5.2 TEST."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
THIS = Path(__file__).resolve()
REVIEW = ROOT / "review" / "editor007c1_r51_result_freeze"
META007B = ROOT / "review" / "editor007b_r51_secondary_stress" / "EDITOR007B_R51_METADATA_VALIDATION.json"
COUNT007B = ROOT / "review" / "editor007b_r51_secondary_stress" / "EDITOR007B_R51_COUNT_VALIDATION.json"
MAN007B = ROOT / "review" / "editor007b_r51_secondary_stress" / "EDITOR007B_R51_BUNDLE_MANIFEST.json"
BOOT = ROOT / "src" / "editor006b_harness" / "bootstrap.py"
RUNNER007C = ROOT / "scripts" / "run_editor007c_r51_secondary_stress.py"
SCORES = Path(r"C:\PhD\06_Datasets\derived\teacher_anchored_r51_editor007c_scores")

INCORRECT_W = "Five official insider–incident clusters are represented."
CORRECT_W = "Four official insider–incident clusters are represented."
APPROVED = [
    "deoverlap_user_cluster_bootstrap.42.effective_malicious_cluster_count",
    "deoverlap_user_cluster_bootstrap.42.frozen_wording",
    "deoverlap_user_cluster_bootstrap.52.effective_malicious_cluster_count",
    "deoverlap_user_cluster_bootstrap.52.frozen_wording",
    "deoverlap_user_cluster_bootstrap.62.effective_malicious_cluster_count",
    "deoverlap_user_cluster_bootstrap.62.frozen_wording",
]
FROZEN_IDENTITIES = {
    "authorisation_sha256": "8e6747e30b5e8e631c4e68bf925108a9a689eb9eaca4d9d86b35ef1b48293693",
    "r51_external_runner_sha256": "03b3c47aecbcec28fd3cceb0509c70bd6553e74f6d352e3b88697bfec7acab57",
    "r51_bundle_manifest_sha256": "366a1dd742a24b9470326c411dd5b40a7a2424c9c48ae3c5eb4b523f7fe01903",
    "sequence_order_sha256": "9c5f9f36bded4fb0d70820fe54cd91964a0286fd134bbb806f4562dc15ce7118",
}


def _sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _walk(a, b, prefix: str = ""):
    diffs = []
    if type(a) is not type(b) and not (
        isinstance(a, (int, float)) and isinstance(b, (int, float))
    ):
        diffs.append((prefix, a, b))
        return diffs
    if isinstance(a, dict):
        keys = set(a) | set(b)
        for key in sorted(keys, key=str):
            path = f"{prefix}.{key}" if prefix else str(key)
            if key not in a or key not in b:
                diffs.append((path, a.get(key) if isinstance(a, dict) else None, b.get(key) if isinstance(b, dict) else None))
            else:
                diffs.extend(_walk(a[key], b[key], path))
        return diffs
    if isinstance(a, list):
        if len(a) != len(b):
            diffs.append((prefix, a, b))
            return diffs
        for i, (left, right) in enumerate(zip(a, b)):
            diffs.extend(_walk(left, right, f"{prefix}[{i}]"))
        return diffs
    if a != b:
        diffs.append((prefix, a, b))
    return diffs


def _fn_source(tree: ast.AST, name: str) -> str:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(BOOT.read_text(encoding="utf-8"), node) or ""
    raise AssertionError(f"function {name} not found")


def test_c101_completion_hashes_verify():
    assert not (SCORES / "EXECUTION_ABORTED.json").exists()
    complete = _json(SCORES / "EXECUTION_COMPLETE.json")
    freeze = _json(REVIEW / "EDITOR007C1_RESULT_FREEZE.json")
    assert complete["complete"] is True
    assert freeze["execution_status"] == "COMPLETE"
    assert freeze["execution_complete_bound_hashes_match"] is True
    for key, expected in FROZEN_IDENTITIES.items():
        assert freeze[key] == expected
    assert freeze["editor007c_authorisation_commit"] == "057b8c39f2133c9b7b031681702900b86d319ce7"
    bound = complete["file_sha256"]
    for name, expected in bound.items():
        observed = _sha256_file(SCORES / name)
        assert observed == expected, name
        assert freeze["completion_file_sha256"][name] == observed
    exec_sha = _sha256_file(SCORES / "EXECUTION_COMPLETE.json")
    assert freeze["completion_file_sha256"]["EXECUTION_COMPLETE.json"] == exec_sha
    score_sha = _sha256_file(SCORES / "SCORE_COMPLETE.json")
    assert freeze["completion_file_sha256"]["SCORE_COMPLETE.json"] == score_sha


def test_c102_all_18_raw_score_hashes_verify():
    freeze = _json(REVIEW / "EDITOR007C1_RESULT_FREEZE.json")
    all_scores = _json(SCORES / "ALL_SCORES_COMPLETE.json")
    score_complete = _json(SCORES / "SCORE_COMPLETE.json")
    by_sc = {Path(s["path"]).name: s for s in score_complete["scores"]}
    rows = freeze["raw_scores"]
    assert len(rows) == 18
    assert len(all_scores["models"]) == 18
    assert freeze["raw_score_hashes"] == "18/18 PASS"
    for rec, row in zip(all_scores["models"], rows):
        name = rec["score_filename"]
        observed = _sha256_file(SCORES / "raw_scores" / name)
        sc = by_sc[name]
        assert observed == rec["score_sha256"] == sc["sha256"] == row["observed_sha256"]
        assert row["status"] == "PASS"
        assert row["family"] == rec["family"]
        assert row["seed"] == rec["seed"]
        assert row["checkpoint_sha256"] == rec["checkpoint_sha256"]
        assert row["frozen_threshold"] == rec["threshold"]
        assert row["raw_score_count"] == rec["score_count"] == 996000


def test_c103_original_predictive_result_remains_unchanged():
    freeze = _json(REVIEW / "EDITOR007C1_RESULT_FREEZE.json")
    corr = _json(REVIEW / "EDITOR007C1_METADATA_CORRECTION.json")
    path = SCORES / "EDITOR007C_PREDICTIVE_RESULTS.json"
    observed = _sha256_file(path)
    expected = "2a3744937e04e8c469d4aa1ed4f43ebd0c31881df76852c2d23c775ec99b08de"
    assert observed == expected
    assert freeze["completion_file_sha256"]["EDITOR007C_PREDICTIVE_RESULTS.json"] == expected
    assert corr["source_predictive_results_sha256"] == expected
    assert freeze["original_outputs_modified"] is False
    assert corr["numerical_results_changed"] is False
    assert corr["bootstrap_recomputed"] is False
    assert corr["predictive_inference_rerun"] is False
    mech = _sha256_file(SCORES / "EDITOR007C_MECHANISM_RESULTS.json")
    run = _sha256_file(SCORES / "EDITOR007C_RUN_MANIFEST.json")
    assert mech == "f7185f18c9fe35db287dc6c0a5da8478a01b5f3ea03c2f8de90cb21a6a76b360"
    assert run == "0fb9dae25b379c9d8ab098649e782cafbb1b3e6faa6c329308a5a9307ebd52c2"


def test_c104_effective_r51_cluster_count_is_four():
    meta = _json(META007B)
    counts = _json(COUNT007B)
    man = _json(MAN007B)
    status = _json(REVIEW / "EDITOR007C1_R51_EVIDENCE_STATUS.json")
    assert meta["official_insiders_true_count"] == 4
    assert meta["official_incidents"] == ["r5.1-1", "r5.1-2", "r5.1-3", "r5.1-4"]
    assert meta["effective_malicious_cluster_count"] == 4
    assert counts["assertions"]["official_insiders"]["observed"] == 4
    assert counts["assertions"]["official_incidents"]["observed"] == 4
    assert len(man["official_mapped_insiders"]) == 4
    assert len(man["official_incidents"]) == 4
    assert set(man["official_mapped_insiders"]) == {"JTC1885", "LBE0376", "BGC0686", "JAK0783"}
    assert status["official_insider_incident_clusters"] == 4
    assert status["one_to_one_official_insider_incident_mapping"] is True
    assert status["source_of_cluster_count"].startswith("EDITOR-007B")
    assert "not inferred from EDITOR-007C" in status["source_of_cluster_count"]


def test_c105_seventeen_event_level_users_do_not_become_seventeen_incidents():
    meta = _json(META007B)
    counts = _json(COUNT007B)
    status = _json(REVIEW / "EDITOR007C1_R51_EVIDENCE_STATUS.json")
    users = meta["event_level_labelled_users"]
    assert len(users) == 17
    assert counts["assertions"]["event_level_labelled_users"]["observed"] == 17
    assert len(meta["contextual_users"]) == 13
    assert meta["contextual_users_official_incident_null"] is True
    assert meta["invented_official_incident_ids_for_contextual_users"] is False
    assert counts["assertions"]["official_incidents"]["observed"] != 17
    assert status["event_level_labelled_users"] == 17
    assert status["official_incidents"] == 4
    assert status["contextual_users_are_not_additional_official_incidents"] is True


def test_c106_hard_coded_five_is_metadata_only():
    src = BOOT.read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = _fn_source(tree, "paired_user_cluster_bootstrap")
    assert '"effective_malicious_cluster_count": 5' in fn
    assert INCORRECT_W in fn
    loop = fn.index("while len(deltas_pr)")
    meta = fn.index('"effective_malicious_cluster_count": 5')
    wording = fn.index(INCORRECT_W)
    assert loop < meta
    assert loop < wording
    after_return = fn[fn.index("return {"):]
    assert "effective_malicious_cluster_count" in after_return
    before_return = fn[: fn.index("return {")]
    assert "effective_malicious_cluster_count" not in before_return
    freeze = _json(REVIEW / "EDITOR007C1_RESULT_FREEZE.json")
    assert freeze["bootstrap_numerics_ruling"] == "BOOTSTRAP_NUMERICS_UNAFFECTED_METADATA_ONLY"
    corr = _json(REVIEW / "EDITOR007C1_METADATA_CORRECTION.json")
    assert corr["bootstrap_numerical_effect"] == "UNALTERED"
    assert corr["correction_type"] == "POST_HOC_METADATA_ONLY"


def test_c107_bootstrap_user_sampling_does_not_use_hard_coded_five():
    src = BOOT.read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = _fn_source(tree, "paired_user_cluster_bootstrap")
    assert "unique = np.unique(users)" in fn
    assert "rng.choice(unique, size=len(unique), replace=True)" in fn
    assert "size=5" not in fn
    assert "n_clusters = 5" not in fn
    sampling = fn[: fn.index("return {")]
    assert "effective_malicious_cluster_count" not in sampling


def test_c108_pr_auc_f1_bootstrap_numerics_do_not_use_hard_coded_five():
    src = BOOT.read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = _fn_source(tree, "paired_user_cluster_bootstrap")
    assert "n_valid: int = BOOTSTRAP_VALID_RESAMPLES" in fn
    assert "while len(deltas_pr) < n_valid" in fn
    assert "attempted > n_valid * 50" in fn
    assert "p5 = np.concatenate(parts_c5)" in fn
    assert "_pr_auc(yb, p5)" in fn
    assert "_f1(yb, p5, threshold_c5)" in fn
    assert "np.percentile(pr, 2.5)" in fn
    assert "np.percentile(f1, 97.5)" in fn
    numeric = fn[: fn.index("return {")]
    assert "cluster_count" not in numeric
    assert INCORRECT_W not in numeric
    pred = _json(SCORES / "EDITOR007C_PREDICTIVE_RESULTS.json")
    paper = _json(REVIEW / "EDITOR007C_PREDICTIVE_RESULTS_PAPER_CORRECTED.json")
    for seed in ("42", "52", "62"):
        a = pred["deoverlap_user_cluster_bootstrap"][seed]
        b = paper["deoverlap_user_cluster_bootstrap"][seed]
        assert a["n_valid_resamples"] == b["n_valid_resamples"] == 2000
        assert a["percentile_95"] == b["percentile_95"]
        assert a["point_delta_PR_AUC_C5_minus_C2"] == b["point_delta_PR_AUC_C5_minus_C2"]
        assert a["point_delta_F1_C5_minus_C2"] == b["point_delta_F1_C5_minus_C2"]


def test_c109_paper_corrected_derivative_changes_only_approved_json_paths():
    original = _json(SCORES / "EDITOR007C_PREDICTIVE_RESULTS.json")
    paper = _json(REVIEW / "EDITOR007C_PREDICTIVE_RESULTS_PAPER_CORRECTED.json")
    diffs = _walk(original, paper)
    paths = [p for p, _, _ in diffs]
    assert paths == APPROVED
    corr = _json(REVIEW / "EDITOR007C1_METADATA_CORRECTION.json")
    diff_doc = _json(REVIEW / "EDITOR007C1_CORRECTION_DIFF.json")
    assert corr["affected_fields"] == APPROVED
    assert diff_doc["approved_paths"] == APPROVED
    assert diff_doc["approved_metadata_fields_changed"] == 6
    assert diff_doc["unexpected_fields_changed"] == 0
    for seed in ("42", "52", "62"):
        assert original["deoverlap_user_cluster_bootstrap"][seed]["effective_malicious_cluster_count"] == 5
        assert original["deoverlap_user_cluster_bootstrap"][seed]["frozen_wording"] == INCORRECT_W
        assert paper["deoverlap_user_cluster_bootstrap"][seed]["effective_malicious_cluster_count"] == 4
        assert paper["deoverlap_user_cluster_bootstrap"][seed]["frozen_wording"] == CORRECT_W
    assert original["effective_malicious_cluster_count"] == paper["effective_malicious_cluster_count"] == 4
    assert original["frozen_wording"] == paper["frozen_wording"] == CORRECT_W
    mech_txt = (SCORES / "EDITOR007C_MECHANISM_RESULTS.json").read_text(encoding="utf-8")
    run_txt = (SCORES / "EDITOR007C_RUN_MANIFEST.json").read_text(encoding="utf-8")
    assert "Five official" not in mech_txt
    assert "Five official" not in run_txt
    assert corr["provenance"]["other_result_files_with_incorrect_five_cluster_metadata"] == []
    assert corr["provenance"]["paper_facing_derivatives_for_mechanism_or_run_manifest"] is False
    assert not (REVIEW / "EDITOR007C_MECHANISM_RESULTS_PAPER_CORRECTED.json").exists()
    assert not (REVIEW / "EDITOR007C_RUN_MANIFEST_PAPER_CORRECTED.json").exists()


def test_c110_no_numeric_result_changes():
    original = _json(SCORES / "EDITOR007C_PREDICTIVE_RESULTS.json")
    paper = _json(REVIEW / "EDITOR007C_PREDICTIVE_RESULTS_PAPER_CORRECTED.json")
    diffs = _walk(original, paper)
    numeric_changed = [
        (p, old, new)
        for p, old, new in diffs
        if isinstance(old, (int, float)) and not isinstance(old, bool) and p not in set(APPROVED)
    ]
    assert numeric_changed == []
    cluster_paths = [p for p, _, _ in diffs if p.endswith("effective_malicious_cluster_count")]
    assert len(cluster_paths) == 3
    diff_doc = _json(REVIEW / "EDITOR007C1_CORRECTION_DIFF.json")
    assert diff_doc["numeric_values_changed"] == 0
    assert diff_doc["unexpected_fields_changed"] == 0
    assert original["scenario_deoverlap_summary"] == paper["scenario_deoverlap_summary"]


def test_c111_unused_leaf_and_tree_rho_remain_disabled():
    mech = _json(SCORES / "EDITOR007C_MECHANISM_RESULTS.json")
    status = _json(REVIEW / "EDITOR007C1_R51_EVIDENCE_STATUS.json")
    report = (REVIEW / "EDITOR007C1_RESULT_FREEZE_REPORT.md").read_text(encoding="utf-8")
    assert status["unused_leaf_fraction"] == "DISABLED_NOT_REPRODUCIBLE"
    assert status["tree_contribution_rho"] == "DISABLED_NOT_REPRODUCIBLE"
    assert mech["unused_leaf_fraction"] == "UNUSED_LEAF_METRIC_NOT_REPRODUCIBLE"
    assert mech["tree_contribution_rho"] == "TREE_CONTRIBUTION_RHO_NOT_REPRODUCIBLE"
    names = {m["metric_name"]: m["status"] for m in mech["registry"]["metrics"]}
    assert names["unused_leaf_fraction"] == "DISABLED_NOT_REPRODUCIBLE"
    assert names["tree_contribution_rho"] == "DISABLED_NOT_REPRODUCIBLE"
    assert "DISABLED_NOT_REPRODUCIBLE" in report
    assert status["no_new_predictive_claim"] is True
    assert status["this_task_freezes_evidence_only"] is True
    assert status["r5.1_does_not_replace_r6.2"] is True
    assert status["r5.1_is_not_primary_confirmation"] is True
    assert status["C2_remains_first_class_control"] is True


def _module_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def _call_names(path: Path) -> set[str]:
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


def test_c112_no_model_is_loaded():
    imports = _module_imports(THIS)
    forbidden = ("torch", "joblib", "xgboost", "editor006b_harness.model_loaders",
                 "editor006b_harness.scoring", "editor006b_harness.mechanism")
    for name in imports:
        assert name not in forbidden
        assert not any(name == f or name.startswith(f + ".") for f in forbidden)
    calls = _call_names(THIS)
    assert "load" not in calls or "torch" not in imports
    assert "load_state_dict" not in calls
    assert list(REVIEW.glob("*.py")) == []
    sys_modules_probe = [n for n in imports if "model_loaders" in n or n == "torch"]
    assert sys_modules_probe == []


def test_c113_no_predictive_inference_executes():
    calls = _call_names(THIS)
    for name in ("write_scores_phase_streaming", "infer_neural", "infer_classical",
                 "paired_user_cluster_bootstrap", "main"):
        assert name not in calls
    corr = _json(REVIEW / "EDITOR007C1_METADATA_CORRECTION.json")
    assert corr["predictive_inference_rerun"] is False
    assert corr["bootstrap_recomputed"] is False
    report = (REVIEW / "EDITOR007C1_RESULT_FREEZE_REPORT.md").read_text(encoding="utf-8")
    assert "does not load a predictive model" in report.lower()
    assert RUNNER007C.is_file()


def test_c114_no_r62_rerun():
    status = _json(REVIEW / "EDITOR007C1_R51_EVIDENCE_STATUS.json")
    freeze = _json(REVIEW / "EDITOR007C1_RESULT_FREEZE.json")
    assert freeze["dataset_id"] == "CERT r5.1"
    assert freeze["dataset_role"] == "R51_SECONDARY_STRESS_ONLY"
    assert status["r5.1_does_not_replace_r6.2"] is True
    assert status["dataset"] == "CERT r5.1"
    imports = _module_imports(THIS)
    assert not any("006e" in n.lower() or "r62" in n.lower() for n in imports)
    report = (REVIEW / "EDITOR007C1_RESULT_FREEZE_REPORT.md").read_text(encoding="utf-8")
    assert "does not rerun r5.1 or r6.2" in report.lower()


def test_c115_no_r52_test_access():
    marker = "r52_T20_s1" + "_test"
    for path in (
        REVIEW / "EDITOR007C1_RESULT_FREEZE.json",
        REVIEW / "EDITOR007C1_METADATA_CORRECTION.json",
        REVIEW / "EDITOR007C1_R51_EVIDENCE_STATUS.json",
        REVIEW / "EDITOR007C1_CORRECTION_DIFF.json",
        REVIEW / "EDITOR007C1_RESULT_FREEZE_REPORT.md",
    ):
        assert marker not in path.read_text(encoding="utf-8")
    report = (REVIEW / "EDITOR007C1_RESULT_FREEZE_REPORT.md").read_text(encoding="utf-8")
    assert "does not open r5.2 TEST" in report
    imports = _module_imports(THIS)
    assert "numpy" not in [n for n in imports if "test" in n.lower()]
    assert not any("r52" in n.lower() for n in imports)
