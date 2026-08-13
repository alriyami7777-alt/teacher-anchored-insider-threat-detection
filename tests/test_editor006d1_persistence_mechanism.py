"""EDITOR-006D1 H2/H3 result persistence and mechanism-path tests.

Synthetic fixtures only. Does not score CERT r6.2.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from editor006b_harness.mechanism import STATUS_DISABLED, mechanism_registry
from editor006b_harness.safety import HarnessProtocolError, sha256_file

RUNNER_PATH = ROOT / "scripts" / "run_editor006e_r62_one_pass.py"


def _load_runner():
    spec = importlib.util.spec_from_file_location("run_editor006e_r62_one_pass_d1b", RUNNER_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


R = _load_runner()


def _dummy_analysis() -> dict:
    return {
        "by_family_seed": {
            "C2": {
                42: {
                    "COMPLETED_WINDOW": {"PR_AUC": 0.2, "F1": 0.1},
                    "ENDPOINT_PAST_ONLY": {"PR_AUC": 0.2, "F1": 0.1},
                    "DEOVERLAP_OFFSET0": {"PR_AUC": 0.2, "F1": 0.1},
                }
            }
        },
        "primary_c5_vs_c2": {
            42: {
                "COMPLETED_WINDOW": {
                    "delta_PR_AUC_C5_minus_C2": 0.01,
                    "positive_delta_is_not_automatic_superiority": True,
                }
            }
        },
        "deoverlap_user_cluster_bootstrap": {
            42: {"effective_malicious_cluster_count": 5}
        },
        "scenario_deoverlap_summary": {
            "kind": "descriptive_only",
            "scenario_identities": ["r6.2-1", "r6.2-2", "r6.2-3", "r6.2-4", "r6.2-5"],
            "n_scenario_identities": 5,
            "effective_malicious_cluster_count": 5,
        },
        "forbidden_claims": list(R.FORBIDDEN_CLAIMS),
        "effective_malicious_cluster_count": 5,
        "frozen_wording": "Five official insider–incident clusters are represented.",
        "threshold_selection_executed": False,
        "model_selection_executed": False,
        "calibration_fit_executed": False,
    }


def _write_required_outputs(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in R.REQUIRED_COMPLETE_FILES:
        (out_dir / name).write_text(json.dumps({"fixture": name}) + "\n", encoding="utf-8")


def test_d3_analysis_results_are_persisted(tmp_path: Path):
    out = tmp_path / "out"
    out.mkdir()
    path = R.persist_predictive_results(out, _dummy_analysis())
    assert path.name == "EDITOR006E_PREDICTIVE_RESULTS.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["task_id"] == "EDITOR-006E"
    assert payload["effective_malicious_cluster_count"] == 5
    assert payload["by_family_seed"]["C2"]["42"]["COMPLETED_WINDOW"]["PR_AUC"] == 0.2
    assert payload["primary_c5_vs_c2"]["42"]["COMPLETED_WINDOW"]["delta_PR_AUC_C5_minus_C2"] == 0.01
    assert payload["deoverlap_user_cluster_bootstrap"]["42"]["effective_malicious_cluster_count"] == 5
    assert payload["scenario_deoverlap_summary"]["n_scenario_identities"] == 5
    assert payload["threshold_selection_executed"] is False
    assert payload["model_selection_executed"] is False
    assert payload["calibration_fit_executed"] is False
    assert payload["frozen_wording"] == "Five official insider–incident clusters are represented."


def test_d3_run_manifest_persisted(tmp_path: Path):
    out = tmp_path / "out"
    out.mkdir()
    artefacts = [
        {
            "family": fam,
            "seed": seed,
            "expected_sha256": f"{i:064x}"[-64:],
            "path": f"/ckpt/{fam}_{seed}",
        }
        for i, (fam, seed) in enumerate(
            [
                (fam, seed)
                for fam in (
                    "teacher_frozen_odst",
                    "C2",
                    "C5_original_paper",
                    "attention_linear",
                    "RF_40",
                    "XGBoost_40",
                )
                for seed in (42, 52, 62)
            ]
        )
    ]
    assert len(artefacts) == 18
    gates = {
        "runner_sha256": "aa" * 32,
        "authorisation_sha256": "bb" * 32,
        "artefacts": artefacts,
        "thresholds": [{"family": "C2", "seed": 62, "threshold": R.C2_SEED62_THRESHOLD}],
    }
    preflight = {"status": "PASS", "n_components": 13, "components": []}
    score_man = {
        "scores": [
            {"family": a["family"], "seed": a["seed"], "n": 12, "sha256": "cc" * 32}
            for a in artefacts
        ]
    }
    path = R.persist_run_manifest(
        out,
        gates=gates,
        component_preflight=preflight,
        score_manifest=score_man,
        start_timestamp="2026-08-13T00:00:00Z",
        end_timestamp="2026-08-13T00:01:00Z",
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["task_id"] == "EDITOR-006E"
    assert len(payload["checkpoint_identities"]) == 18
    assert len(payload["raw_score_sha256"]) == 18
    assert payload["component_preflight_status"] == "PASS"
    assert payload["builder_execution_identity_status"] == R.BUILDER_EXECUTION_IDENTITY_STATUS
    assert payload["protocol_flags"]["threshold_selection_executed"] is False
    assert payload["protocol_flags"]["model_selection_executed"] is False
    assert payload["protocol_flags"]["calibration_fit_executed"] is False
    assert payload["scientific_views"] == [
        "COMPLETED_WINDOW",
        "ENDPOINT_PAST_ONLY",
        "DEOVERLAP_OFFSET0",
    ]


def test_d8_execution_complete_only_after_all_required_outputs(tmp_path: Path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "EXECUTION_STARTED.json").write_text("{}\n", encoding="utf-8")
    (out / "ALL_SCORES_COMPLETE.json").write_text("{}\n", encoding="utf-8")
    (out / "EDITOR006E_PREDICTIVE_RESULTS.json").write_text("{}\n", encoding="utf-8")
    (out / "EDITOR006E_RUN_MANIFEST.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(HarnessProtocolError, match="missing required outputs"):
        R.persist_execution_complete(out)
    assert not (out / "EXECUTION_COMPLETE.json").exists()
    _write_required_outputs(out)
    complete = R.persist_execution_complete(out)
    payload = json.loads(complete.read_text(encoding="utf-8"))
    assert payload["complete"] is True
    bound = payload["file_sha256"]
    for name in R.REQUIRED_COMPLETE_FILES:
        assert bound[name] == sha256_file(out / name)
    assert "EXECUTION_COMPLETE.json" not in bound


def test_d4_mechanism_result_path_actually_invoked(tmp_path: Path, monkeypatch):
    called = {"mechanism": 0, "families": []}

    def fake_load(*, family, seed, path, expected_sha256, deny_hashes, allow_hashes):
        called["families"].append((family, int(seed)))
        return {"model": object()}

    def fake_mech(**kwargs):
        called["mechanism"] += 1
        assert kwargs["deov"] is not None
        return {
            "view": "DEOVERLAP_OFFSET0",
            "no_c5_must_improve": True,
            "unused_leaf_fraction": "UNUSED_LEAF_METRIC_NOT_REPRODUCIBLE",
            "tree_contribution_rho": "TREE_CONTRIBUTION_RHO_NOT_REPRODUCIBLE",
            "per_seed": {},
            "paper_facing": ["student_teacher_logit_deviation"],
            "registry": mechanism_registry(),
        }

    monkeypatch.setattr(R, "load_neural_checkpoint", fake_load)
    monkeypatch.setattr(R, "mechanism_on_deoverlap", fake_mech)
    artefacts = []
    for family in (
        "teacher_frozen_odst",
        "C2",
        "C5_original_paper",
        "attention_linear",
        "RF_40",
    ):
        for seed in (42, 52, 62):
            artefacts.append(
                {
                    "family": family,
                    "seed": seed,
                    "path": str(tmp_path / f"{family}_{seed}"),
                    "expected_sha256": "ab" * 32,
                }
            )
    dense = np.zeros((2, 40, 13), dtype=np.float32)
    window_index = np.array([[0, 0], [0, 20], [1, 0], [1, 20]], dtype=np.int32)
    deov = np.array([1, 0, 1, 0], dtype=np.uint8)
    result = R.run_authorised_mechanism_pass(
        artefacts=artefacts,
        deny_hashes=set(),
        dense=dense,
        window_index=window_index,
        deov=deov,
    )
    assert called["mechanism"] == 1
    assert result["view"] == "DEOVERLAP_OFFSET0"
    assert result["no_c5_must_improve"] is True
    families = {f for f, _s in called["families"]}
    assert families == {"teacher_frozen_odst", "C2", "C5_original_paper"}
    assert len(called["families"]) == 9
    src = RUNNER_PATH.read_text(encoding="utf-8")
    assert "run_authorised_mechanism_pass" in src
    exec_src = src[src.index("def execute_external_one_pass") :]
    assert exec_src.index("run_authorised_mechanism_pass") < exec_src.index(
        "persist_execution_complete"
    )
    assert "C5 improves" not in src.lower()
    assert "c5 must improve" not in src.lower()


def test_d5_unused_leaf_and_tree_rho_remain_disabled(monkeypatch):
    reg = mechanism_registry()
    unused = next(m for m in reg["metrics"] if m["metric_name"] == "unused_leaf_fraction")
    rho = next(m for m in reg["metrics"] if m["metric_name"] == "tree_contribution_rho")
    assert unused["status"] == STATUS_DISABLED
    assert rho["status"] == STATUS_DISABLED
    enabled = {
        m["metric_name"]
        for m in reg["metrics"]
        if m["status"] != STATUS_DISABLED
    }
    assert "student_teacher_logit_deviation" in enabled
    assert "route_mae" in enabled
    assert "route_kl" in enabled
    assert "hard_route_agreement" in enabled
    assert "dominant_leaf_agreement" in enabled
    assert "unused_leaf_fraction" not in enabled
    assert "tree_contribution_rho" not in enabled

    def fake_compare(*, student, teacher, x):
        return {
            "student_teacher_logit_deviation": 0.1,
            "route_mae": 0.1,
            "route_kl": 0.1,
            "hard_route_agreement": 0.9,
            "dominant_leaf_agreement": 0.9,
            "unused_leaf_fraction": "UNUSED_LEAF_METRIC_NOT_REPRODUCIBLE",
            "tree_contribution_rho": "TREE_CONTRIBUTION_RHO_NOT_REPRODUCIBLE",
        }

    monkeypatch.setattr(R, "compare_student_teacher", fake_compare)
    dense = np.zeros((2, 40, 13), dtype=np.float32)
    window_index = np.array([[0, 0], [0, 20], [1, 0], [1, 20]], dtype=np.int32)
    deov = np.array([1, 1, 1, 1], dtype=np.uint8)
    loaded = {
        (fam, seed): object()
        for fam in R.MECHANISM_FAMILIES
        for seed in (42, 52, 62)
    }
    out = R.mechanism_on_deoverlap(
        loaded_by_key=loaded,
        dense=dense,
        window_index=window_index,
        deov=deov,
        batch_size=2,
    )
    assert out["unused_leaf_fraction"] == "UNUSED_LEAF_METRIC_NOT_REPRODUCIBLE"
    assert out["tree_contribution_rho"] == "TREE_CONTRIBUTION_RHO_NOT_REPRODUCIBLE"
    for seed_block in out["per_seed"].values():
        for block in seed_block.values():
            assert block["unused_leaf_fraction"] == "UNUSED_LEAF_METRIC_NOT_REPRODUCIBLE"
            assert block["tree_contribution_rho"] == "TREE_CONTRIBUTION_RHO_NOT_REPRODUCIBLE"
    assert out["no_c5_must_improve"] is True
    assert out["model_selection_executed"] is False
