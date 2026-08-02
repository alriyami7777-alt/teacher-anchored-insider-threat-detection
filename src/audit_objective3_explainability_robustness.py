#!/usr/bin/env python3
"""Read-only Objective 3 explainability/robustness audit and preregistration.

Does not train models, run inference, generate explanations, apply perturbations,
or open locked r5.2/r6.2 test tensors.
"""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "objective3" / "audit_and_preregistration"
BRANCH = "main"
HEAD = "83e5bd4cee0b41b991afe7498cef643c54d7c1f1"
PROTOCOL = "obj3_prereg_v1_r42_dev_then_r52_val"
STATUS = "objective3_checkpoint_or_protocol_gap"

SISTER_NODE = Path(__file__).resolve().parent / "prototype_v3_node"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in fieldnames})


def git_status() -> tuple[str, str]:
    short = subprocess.check_output(["git", "status", "--short"], cwd=ROOT, text=True)
    full = subprocess.check_output(["git", "status"], cwd=ROOT, text=True)
    (OUT / "git_status_short.txt").write_text(short, encoding="utf-8")
    (OUT / "git_status_full.txt").write_text(full, encoding="utf-8")
    return short, full


def classify_dirty(short: str) -> dict[str, list[str]]:
    tracked_mod: list[str] = []
    untracked: list[str] = []
    staged: list[str] = []
    for line in short.splitlines():
        if not line.strip():
            continue
        code = line[:2]
        path = line[3:].strip()
        if code.strip() == "??":
            untracked.append(path)
        elif code[0] != " " and code[0] != "?":
            staged.append(path)
            if code[1] != " ":
                tracked_mod.append(path)
        else:
            tracked_mod.append(path)

    def bucket(paths: list[str]) -> dict[str, list[str]]:
        obj2, obj3, proto, other = [], [], [], []
        for p in paths:
            pl = p.lower().replace("\\", "/")
            if "objective3" in pl or "obj3" in pl:
                obj3.append(p)
            elif "objective2" in pl or "obj2" in pl or "close_objective2" in pl:
                obj2.append(p)
            elif "prototype" in pl or "v2_" in pl or "v2/" in pl or "grande" in pl or "sequence_ensemble_v2" in pl:
                proto.append(p)
            else:
                other.append(p)
        return {"objective2": obj2, "objective3": obj3, "prototypes": proto, "other": other}

    return {
        "tracked_modified": tracked_mod,
        "untracked": untracked,
        "staged": staged,
        "by_theme_modified": bucket(tracked_mod),
        "by_theme_untracked": bucket(untracked),
    }


def component_manifest() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    def add(**kwargs: Any) -> None:
        base = {
            "component_name": "",
            "component_category": "",
            "file_or_output_path": "",
            "git_status": "",
            "implementation_status": "",
            "execution_status": "",
            "evidence_status": "",
            "model_target": "",
            "dataset_version": "",
            "partition": "",
            "seeds": "",
            "checkpoint": "",
            "threshold_source": "",
            "explanation_method": "",
            "perturbation_type": "",
            "metrics": "",
            "output_files": "",
            "tests_available": "",
            "reproducibility_status": "",
            "protocol_identifier": "",
            "leakage_risk": "",
            "comparability_status": "",
            "notes": "",
        }
        base.update(kwargs)
        rows.append(base)

    # Core Obj3 modules (dirty)
    add(
        component_name="objective3_locked_common",
        component_category="protocol_library",
        file_or_output_path="scripts/objective3_locked_common.py",
        git_status="tracked_modified",
        implementation_status="implemented_and_tested",
        execution_status="completed_run",
        evidence_status="preliminary_result",
        model_target="joint_soft_forest;standalone_bilstm;attention_linear;fragmented_xgb",
        dataset_version="CERT r4.2",
        partition="validation",
        seeds="42;52;62",
        threshold_source="objective2_test_evaluation_manifest.json",
        explanation_method="n/a_protocol",
        metrics="protocol helpers; stability; degradation aggregation",
        tests_available="tests/test_objective3_pilot.py",
        reproducibility_status="reproducible_helpers",
        protocol_identifier="obj3_pilot_r42_validation_locked_obj2",
        leakage_risk="low_if_validation_only",
        comparability_status="protocol_mismatch_vs_selected_odst",
        notes="Dirty worktree (+132/-2). Still targets pre-ODST Obj2 model set; ODST not in OBJECTIVE3_MODEL_IDS.",
    )
    add(
        component_name="objective3_inference",
        component_category="inference_library",
        file_or_output_path="scripts/objective3_inference.py",
        git_status="tracked_clean_or_unchanged_in_status",
        implementation_status="implemented_and_tested",
        execution_status="completed_run",
        evidence_status="preliminary_result",
        model_target="bilstm;sequence_ensemble;fragmented",
        dataset_version="CERT r4.2",
        partition="validation",
        explanation_method="attention_weights;soft_forest_routing",
        tests_available="tests/test_objective3_pilot.py",
        reproducibility_status="deterministic_given_checkpoint",
        protocol_identifier="obj3_pilot_r42_validation_locked_obj2",
        leakage_risk="medium_if_test_flag_used",
        comparability_status="does_not_load_AttentionNodeEnsemble_ODST",
        notes="No ODST/NODE loader. Soft-forest routing extras only for joint soft forest.",
    )
    add(
        component_name="objective3_analysis",
        component_category="explanation_analysis",
        file_or_output_path="scripts/objective3_analysis.py",
        git_status="tracked_clean_or_unchanged_in_status",
        implementation_status="implemented_and_tested",
        execution_status="completed_run",
        evidence_status="preliminary_result",
        model_target="attention_models;joint_soft_forest",
        dataset_version="CERT r4.2",
        partition="validation",
        explanation_method="temporal_attention;soft_tree_routing_proxy;feature_channel_masking",
        metrics="entropy;concentration;leaf_utilisation;mean_abs_delta_p;metric_degradation",
        tests_available="yes",
        reproducibility_status="reproducible",
        protocol_identifier="obj3_pilot_r42_validation_locked_obj2",
        leakage_risk="low",
        comparability_status="soft_forest_not_odst",
        notes="Leaf contribution is an explicit proxy without leaf_logit params. No ODST feature-selection analysis.",
    )
    add(
        component_name="objective3_perturbations",
        component_category="robustness_library",
        file_or_output_path="scripts/objective3_perturbations.py",
        git_status="tracked_modified",
        implementation_status="implemented_and_tested",
        execution_status="completed_run",
        evidence_status="preliminary_result",
        model_target="all_obj3_pilot_models",
        dataset_version="CERT r4.2",
        partition="validation",
        perturbation_type="random_observation_masking;missing_random_features;missing_complete_days;gaussian_noise_continuous;feature_channel_mask",
        metrics="paired_deterministic_masks",
        tests_available="yes",
        reproducibility_status="paired_rng_via_sha256",
        protocol_identifier="obj3_pilot_r42_validation_locked_obj2",
        leakage_risk="low",
        comparability_status="usable_after_odst_wiring",
        notes="Dirty (+92/-10). No log-source group masking; no temporal reorder/jitter; no faithfulness deletion curves.",
    )
    add(
        component_name="run_objective3_pilot",
        component_category="cli_orchestrator",
        file_or_output_path="scripts/run_objective3_pilot.py",
        git_status="tracked_modified",
        implementation_status="implemented_and_tested",
        execution_status="completed_run",
        evidence_status="preliminary_result",
        model_target="OBJECTIVE3_MODEL_IDS",
        dataset_version="CERT r4.2",
        partition="validation_default",
        seeds="42;52;62",
        threshold_source="locked_obj2_manifest",
        explanation_method="attention;soft_tree;feature_masking",
        perturbation_type="four_canonical_scenarios",
        output_files="outputs/objective3/validation_seed*_multi5_*",
        tests_available="yes",
        reproducibility_status="manifest_hashed",
        protocol_identifier="obj3_pilot_r42_validation_locked_obj2",
        leakage_risk="controlled_by_confirm_flag",
        comparability_status="completed_for_superseded_model_set",
        notes="Dirty (+282/-71). Completed multi5 pilots exist; still excludes selected ODST architecture.",
    )
    add(
        component_name="generate_objective3_report_assets",
        component_category="reporting",
        file_or_output_path="scripts/generate_objective3_report_assets.py",
        git_status="tracked_modified",
        implementation_status="implemented_and_tested",
        execution_status="completed_run",
        evidence_status="preliminary_result",
        dataset_version="CERT r4.2",
        partition="validation",
        output_files="outputs/objective3/report_assets_combined_multi5/",
        tests_available="yes",
        reproducibility_status="csv_figure_only",
        protocol_identifier="obj3_pilot_r42_validation_locked_obj2",
        leakage_risk="none",
        comparability_status="aggregates_pilot_outputs",
        notes="Does not load models. Dirty (+249 lines).",
    )
    add(
        component_name="test_objective3_pilot",
        component_category="unit_tests",
        file_or_output_path="tests/test_objective3_pilot.py",
        git_status="tracked_modified",
        implementation_status="implemented_and_tested",
        execution_status="completed_run",
        evidence_status="diagnostic_evidence",
        tests_available="self",
        reproducibility_status="pytest",
        protocol_identifier="obj3_unit_tests",
        leakage_risk="none",
        notes="Dirty (+299 lines). Covers perturbations, analysis, CLI safety, synthetic inference; not full ODST.",
    )

    # Completed pilot outputs
    add(
        component_name="validation_seed42_multi5_pilot",
        component_category="pilot_output",
        file_or_output_path="outputs/objective3/validation_seed42_multi5_20260722_223612/",
        git_status="untracked_or_ignored_outputs",
        implementation_status="implemented_and_tested",
        execution_status="completed_run",
        evidence_status="preliminary_result",
        model_target="attention_linear;joint_soft_forest;standalone_bilstm;fragmented_xgb",
        dataset_version="CERT r4.2",
        partition="validation",
        seeds="42",
        threshold_source="locked_obj2",
        explanation_method="attention;soft_tree;feature_masking",
        perturbation_type="four_scenarios_x_3_levels_x_5_pert_seeds",
        metrics="PR-AUC/F1 degradation; flip rate; explanation cosine/L1",
        output_files="robustness/attention/soft_tree/feature_masking CSVs+PNGs",
        tests_available="partial",
        reproducibility_status="protocol_manifest_present",
        protocol_identifier="obj3_pilot_r42_validation_locked_obj2",
        leakage_risk="low",
        comparability_status="not_selected_architecture",
        notes="smoke=false; test_evaluated=false. Useful methods template but wrong primary model for Obj3 closure.",
    )
    add(
        component_name="validation_seed52_62_multi5_pilot",
        component_category="pilot_output",
        file_or_output_path="outputs/objective3/validation_seed52_62_multi5_20260722_231443/",
        git_status="untracked_or_ignored_outputs",
        implementation_status="implemented_and_tested",
        execution_status="completed_run",
        evidence_status="preliminary_result",
        model_target="same_as_seed42_pilot",
        dataset_version="CERT r4.2",
        partition="validation",
        seeds="52;62",
        threshold_source="locked_obj2",
        explanation_method="attention;soft_tree;feature_masking",
        perturbation_type="four_scenarios_x_3_levels_x_5_pert_seeds",
        metrics="same_as_seed42",
        protocol_identifier="obj3_pilot_r42_validation_locked_obj2",
        leakage_risk="low",
        comparability_status="not_selected_architecture",
        notes="Completes three-seed coverage for superseded Obj2 pilot set.",
    )

    # Missing / not implemented for selected ODST scope
    add(
        component_name="prototype_v3_node_architecture_package",
        component_category="model_architecture",
        file_or_output_path="scripts/prototype_v3_node/ (MISSING in this repo)",
        git_status="absent_here_present_in_sister_repo",
        implementation_status="not_implemented",
        execution_status="not_run",
        evidence_status="no_evidence",
        model_target="sparsemax_sigmoid_odst",
        dataset_version="CERT r4.2 / r5.2 checkpoints exist",
        explanation_method="native_odst_feature_selection_routing",
        tests_available="no_in_this_repo",
        reproducibility_status="blocked",
        protocol_identifier=PROTOCOL,
        leakage_risk="n/a",
        comparability_status="blocking_gap",
        notes=(
            f"Sister path exists: {SISTER_NODE}. Contains architecture.py, odst.py, diagnostics.py, "
            "train.py. Feasibility repo has ODST checkpoints/outputs but cannot load AttentionNodeEnsemble locally."
        ),
    )
    add(
        component_name="native_odst_explanation_extraction",
        component_category="explanation_method",
        file_or_output_path="not_present",
        git_status="n/a",
        implementation_status="not_implemented",
        execution_status="not_run",
        evidence_status="no_evidence",
        model_target="sparsemax_sigmoid_odst",
        explanation_method="feature_selection_probs;split_usage;leaf_routing;tree_contribution",
        protocol_identifier=PROTOCOL,
        leakage_risk="n/a",
        comparability_status="required_for_exp_3_1",
        notes="r5.2 ODST summary.json already records routing diagnostics from training; Obj3 cannot yet extract them on demand.",
    )
    add(
        component_name="explanation_faithfulness_curves",
        component_category="explanation_validation",
        file_or_output_path="not_present",
        git_status="n/a",
        implementation_status="not_implemented",
        execution_status="not_run",
        evidence_status="no_evidence",
        explanation_method="top_k_deletion;random_deletion;bottom_k;insertion",
        metrics="comprehensiveness;sufficiency;AOPC;probability_reduction",
        protocol_identifier=PROTOCOL,
        notes="Feature-channel masking exists but is not a preregistered faithfulness protocol with ranked deletion curves.",
    )
    add(
        component_name="integrated_gradients",
        component_category="explanation_method",
        file_or_output_path="not_present",
        git_status="n/a",
        implementation_status="not_implemented",
        execution_status="not_run",
        evidence_status="no_evidence",
        explanation_method="integrated_gradients;grad_x_input",
        protocol_identifier=PROTOCOL,
        notes="No Captum/IG code. Binary/count features make naive interpolation questionable; treat as optional later.",
    )
    add(
        component_name="shap_lime_external",
        component_category="explanation_method",
        file_or_output_path="not_present",
        git_status="n/a",
        implementation_status="not_implemented",
        execution_status="not_run",
        evidence_status="no_evidence",
        explanation_method="SHAP;LIME",
        protocol_identifier=PROTOCOL,
        notes="Not recommended as primary Obj3 methods for sequential 20x13 tensors; costly and weak temporal preservation.",
    )
    add(
        component_name="missing_log_source_group_robustness",
        component_category="robustness_method",
        file_or_output_path="partially_via_feature_channel_mask",
        git_status="n/a",
        implementation_status="partially_implemented",
        execution_status="partially_run",
        evidence_status="diagnostic_evidence",
        perturbation_type="per_feature_channel_zeroing_only",
        protocol_identifier=PROTOCOL,
        notes="SAFE_FEATURES allow grouping logon/device/file/email/http count+binary pairs, but group masking not coded.",
    )
    add(
        component_name="temporal_jitter_reorder_robustness",
        component_category="robustness_method",
        file_or_output_path="not_present",
        git_status="n/a",
        implementation_status="not_implemented",
        execution_status="not_run",
        evidence_status="no_evidence",
        perturbation_type="timestep_zeroing_only_via_missing_complete_days",
        protocol_identifier=PROTOCOL,
        notes="Day zeroing exists; order jitter / bounded timestamp perturbation not implemented.",
    )
    add(
        component_name="r62_external_stress",
        component_category="dataset_shift",
        file_or_output_path="reserved",
        git_status="n/a",
        implementation_status="not_implemented",
        execution_status="not_run",
        evidence_status="no_evidence",
        dataset_version="CERT r6.2",
        partition="reserved",
        protocol_identifier="future_r62_preregistered_stress",
        leakage_risk="high_if_used_for_tuning",
        notes="Do not access during this audit. Reserved after r5.2 validation protocol freeze.",
    )
    return rows


def checkpoint_manifest() -> list[dict[str, Any]]:
    specs = [
        ("attn_lin_r42_s42", "outputs/baselines/sequence_ensemble/stage11_A_attn_linear/best.pt", "attention_linear", 42, "r4.2", "primary_neural_reference", True),
        ("attn_lin_r42_s52", "outputs/baselines/sequence_ensemble/pretrain_attn_linear_seed52/best.pt", "attention_linear", 52, "r4.2", "primary_neural_reference", True),
        ("attn_lin_r42_s62", "outputs/baselines/sequence_ensemble/pretrain_attn_linear_seed62/best.pt", "attention_linear", 62, "r4.2", "primary_neural_reference", True),
        ("odst_r42_s42", "outputs/v3_node/seed42_full_20260723_095912/seed42_full_20260723_095916/sparsemax_sigmoid_odst_seed42/best.pt", "sparsemax_sigmoid_odst", 42, "r4.2", "selected_architecture", True),
        ("odst_r42_s52", "outputs/v3_node/seed52_full_20260723_101933/seed52_full_20260723_101936/sparsemax_sigmoid_odst_seed52/best.pt", "sparsemax_sigmoid_odst", 52, "r4.2", "selected_architecture", True),
        ("odst_r42_s62", "outputs/v3_node/seed62_full_20260723_102938/seed62_full_20260723_102942/sparsemax_sigmoid_odst_seed62/best.pt", "sparsemax_sigmoid_odst", 62, "r4.2", "selected_architecture", True),
        ("attn_lin_r52_s42", "outputs/objective2/r52_odst_confirmation/attention_linear_seed42/best.pt", "attention_linear", 42, "r5.2", "locked_confirmation_reference", True),
        ("attn_lin_r52_s52", "outputs/objective2/r52_odst_confirmation/attention_linear_seed52/best.pt", "attention_linear", 52, "r5.2", "locked_confirmation_reference", True),
        ("attn_lin_r52_s62", "outputs/objective2/r52_odst_confirmation/attention_linear_seed62/best.pt", "attention_linear", 62, "r5.2", "locked_confirmation_reference", True),
        ("odst_r52_s42", "outputs/objective2/r52_odst_confirmation/odst_seed42/best.pt", "sparsemax_sigmoid_odst", 42, "r5.2", "locked_confirmation_selected", True),
        ("odst_r52_s52", "outputs/objective2/r52_odst_confirmation/odst_seed52/best.pt", "sparsemax_sigmoid_odst", 52, "r5.2", "locked_confirmation_selected", True),
        ("odst_r52_s62", "outputs/objective2/r52_odst_confirmation/odst_seed62/best.pt", "sparsemax_sigmoid_odst", 62, "r5.2", "locked_confirmation_selected", True),
        ("rf_frag_r42_s42", "outputs/objective2/fragmented_hybrid_seed42/random_forest/model.joblib", "fragmented_rf", 42, "r4.2", "optional_feature_importance_reference", True),
        ("xgb_frag_r42_s42", "outputs/objective2/fragmented_hybrid_seed42/xgboost/model.json", "fragmented_xgboost", 42, "r4.2", "optional_feature_importance_reference", True),
        ("rf_r52_s42", "outputs/objective2/r52_locked_baselines/random_forest_seed42/model.joblib", "classical_rf", 42, "r5.2", "optional_predictive_reference", True),
        ("xgb_r52_s42", "outputs/objective2/r52_locked_baselines/xgboost_seed42/model.json", "classical_xgboost", 42, "r5.2", "optional_predictive_reference", True),
    ]
    rows = []
    for cid, path, arch, seed, ds, role, frozen in specs:
        p = ROOT / path
        parent = p.parent
        thr = parent / "threshold.json"
        cfg = parent / "config.json"
        summ = parent / "summary.json"
        exists = p.exists()
        digest = sha256_file(p) if exists else ""
        head = "BiLSTM_attention" if "attn" in arch or "odst" in arch or "linear" in arch else "tabular_or_fragmented"
        clf = "linear" if "attention_linear" in arch else ("sparsemax_sigmoid_odst" if "odst" in arch else arch)
        loadable = "yes_via_sequence_ensemble" if arch == "attention_linear" and ds == "r4.2" else (
            "blocked_missing_prototype_v3_node_in_this_repo" if "odst" in arch else "artefact_present_loader_varies"
        )
        if arch == "attention_linear" and ds == "r5.2":
            loadable = "yes_with_r52_confirmation_codepath_elsewhere"
        rows.append(
            {
                "checkpoint_id": cid,
                "exact_path": path.replace("\\", "/"),
                "exists": str(exists).lower(),
                "dataset_version": f"CERT {ds}",
                "seed": seed,
                "architecture": arch,
                "encoder_configuration": "BiLSTM(h=64)+temporal_attention(dim=64)" if "odst" in arch or arch == "attention_linear" else "n/a_or_fragmented",
                "classifier_head": clf,
                "feature_count": 13 if "odst" in arch or arch == "attention_linear" else "not_recorded_here",
                "sequence_length": 20 if "odst" in arch or arch == "attention_linear" else "n/a",
                "training_partition": "train",
                "validation_partition": "validation",
                "threshold_file": str(thr.relative_to(ROOT)).replace("\\", "/") if thr.exists() else "missing",
                "checkpoint_sha256": digest,
                "checkpoint_metadata_available": str(cfg.exists() or summ.exists()).lower(),
                "config_present": str(cfg.exists()).lower(),
                "summary_present": str(summ.exists()).lower(),
                "loadability_evidence": loadable,
                "intended_objective3_role": role,
                "frozen": str(frozen).lower(),
                "can_evaluate_without_retraining": "yes_if_loader_available",
                "notes": (
                    "v3_node ODST lacks config.json; use summary.json+threshold.json"
                    if "v3_node" in path
                    else ""
                ),
            }
        )
    return rows


def explanation_method_audit() -> list[dict[str, Any]]:
    fields_common = [
        "method_name",
        "method_family",
        "implementation_status",
        "compatible_with_odst",
        "compatible_with_attention_linear",
        "requires_gradients",
        "baseline_defined",
        "padding_handling",
        "feature_interpolation_valid",
        "exposes_native_internals",
        "recommended_for_obj3",
        "priority",
        "blocking_dependency",
        "notes",
    ]
    # return list of dicts with those keys
    rows = [
        {
            "method_name": "temporal_attention_weights",
            "method_family": "native_attention",
            "implementation_status": "implemented_and_tested_for_sequence_ensemble",
            "compatible_with_odst": "yes_if_odst_model_exposes_attention",
            "compatible_with_attention_linear": "yes",
            "requires_gradients": "no",
            "baseline_defined": "n/a",
            "padding_handling": "full_T20_dense_days_no_pad_mask_in_schema",
            "feature_interpolation_valid": "n/a",
            "exposes_native_internals": "yes",
            "recommended_for_obj3": "yes_primary",
            "priority": "P0",
            "blocking_dependency": "wire_odst_loader_to_return_attention",
            "notes": "Existing Obj3 extracts attention for ensemble/linear; need ODST parity.",
        },
        {
            "method_name": "odst_feature_selection_and_routing",
            "method_family": "native_odst",
            "implementation_status": "not_implemented_in_obj3",
            "compatible_with_odst": "yes_designed_for_it",
            "compatible_with_attention_linear": "no",
            "requires_gradients": "no",
            "baseline_defined": "n/a",
            "padding_handling": "n/a_on_pooled_h",
            "feature_interpolation_valid": "n/a",
            "exposes_native_internals": "yes_when_diagnostics_hooked",
            "recommended_for_obj3": "yes_primary",
            "priority": "P0",
            "blocking_dependency": "port_prototype_v3_node_and_explanation_hooks",
            "notes": "Training summaries already log feature_selection_*, leaf_utilization, routing_entropy.",
        },
        {
            "method_name": "soft_forest_routing_proxy",
            "method_family": "native_soft_forest",
            "implementation_status": "implemented_and_tested",
            "compatible_with_odst": "no",
            "compatible_with_attention_linear": "no",
            "requires_gradients": "no",
            "baseline_defined": "n/a",
            "padding_handling": "n/a",
            "feature_interpolation_valid": "n/a",
            "exposes_native_internals": "partial_proxy",
            "recommended_for_obj3": "no_superseded",
            "priority": "archive",
            "blocking_dependency": "none",
            "notes": "Completed pilot evidence for joint soft forest only; not the selected architecture.",
        },
        {
            "method_name": "feature_channel_occlusion",
            "method_family": "perturbation_attribution",
            "implementation_status": "implemented_and_tested",
            "compatible_with_odst": "yes_after_loader",
            "compatible_with_attention_linear": "yes",
            "requires_gradients": "no",
            "baseline_defined": "zero_mask",
            "padding_handling": "zeros_entire_channel",
            "feature_interpolation_valid": "n/a",
            "exposes_native_internals": "no",
            "recommended_for_obj3": "yes_secondary_and_faithfulness_building_block",
            "priority": "P1",
            "blocking_dependency": "odst_loader",
            "notes": "Useful precursor to ranked deletion faithfulness.",
        },
        {
            "method_name": "integrated_gradients",
            "method_family": "gradient_based",
            "implementation_status": "not_implemented",
            "compatible_with_odst": "uncertain_needs_gradient_path_audit",
            "compatible_with_attention_linear": "likely",
            "requires_gradients": "yes",
            "baseline_defined": "no",
            "padding_handling": "undefined",
            "feature_interpolation_valid": "questionable_for_binary_and_counts",
            "exposes_native_internals": "no",
            "recommended_for_obj3": "optional_later_not_primary",
            "priority": "P3",
            "blocking_dependency": "gradient_path_through_odst_plus_baseline_policy",
            "notes": "Do not assume IG is automatically valid for all encoded features.",
        },
        {
            "method_name": "input_gradients_gradxinput",
            "method_family": "gradient_based",
            "implementation_status": "not_implemented",
            "compatible_with_odst": "uncertain",
            "compatible_with_attention_linear": "likely",
            "requires_gradients": "yes",
            "baseline_defined": "n/a",
            "padding_handling": "undefined",
            "feature_interpolation_valid": "n/a",
            "exposes_native_internals": "no",
            "recommended_for_obj3": "optional",
            "priority": "P3",
            "blocking_dependency": "gradient_path_audit",
            "notes": "r52 ODST folder contains odst_gradient_checks.json indicating prior gradient finiteness checks.",
        },
        {
            "method_name": "shap",
            "method_family": "external_explainer",
            "implementation_status": "not_implemented",
            "compatible_with_odst": "poor_for_full_sequence_model",
            "compatible_with_attention_linear": "poor",
            "requires_gradients": "no",
            "baseline_defined": "background_sample_required",
            "padding_handling": "problematic",
            "feature_interpolation_valid": "weak_temporal_structure",
            "exposes_native_internals": "no",
            "recommended_for_obj3": "no",
            "priority": "exclude",
            "blocking_dependency": "none",
            "notes": "Not recommended merely for popularity; costly and weak on sequential structure.",
        },
        {
            "method_name": "lime",
            "method_family": "external_explainer",
            "implementation_status": "not_implemented",
            "compatible_with_odst": "poor",
            "compatible_with_attention_linear": "poor",
            "requires_gradients": "no",
            "baseline_defined": "local_perturbations",
            "padding_handling": "problematic",
            "feature_interpolation_valid": "weak",
            "exposes_native_internals": "no",
            "recommended_for_obj3": "no",
            "priority": "exclude",
            "blocking_dependency": "none",
            "notes": "Would likely explain local surrogate rather than full temporal model faithfully.",
        },
        {
            "method_name": "ranked_deletion_faithfulness",
            "method_family": "explanation_validation",
            "implementation_status": "not_implemented",
            "compatible_with_odst": "yes_after_explanations",
            "compatible_with_attention_linear": "yes",
            "requires_gradients": "no",
            "baseline_defined": "random_and_bottom_ranked_controls",
            "padding_handling": "must_exclude_inactive_days_if_any",
            "feature_interpolation_valid": "n/a",
            "exposes_native_internals": "uses_explanations",
            "recommended_for_obj3": "yes_primary_exp_3_2",
            "priority": "P1",
            "blocking_dependency": "native_explanations_first",
            "notes": "Define deletion on features and/or timesteps with frozen thresholds.",
        },
        {
            "method_name": "explanation_stability_metrics",
            "method_family": "explanation_validation",
            "implementation_status": "partially_implemented",
            "compatible_with_odst": "yes_after_hooks",
            "compatible_with_attention_linear": "yes",
            "requires_gradients": "no",
            "baseline_defined": "n/a",
            "padding_handling": "n/a",
            "feature_interpolation_valid": "n/a",
            "exposes_native_internals": "uses_explanations",
            "recommended_for_obj3": "yes_primary_exp_3_3",
            "priority": "P1",
            "blocking_dependency": "odst_explanations",
            "notes": "Obj3 already computes cosine/L1 under perturbations; need Spearman/Jaccard/top-k and seed agreement for ODST.",
        },
    ]
    # silence unused
    _ = fields_common
    return rows


def robustness_method_audit() -> list[dict[str, Any]]:
    return [
        {
            "method_name": "missing_log_source_group_masking",
            "robustness_family": "missing_source",
            "implementation_status": "partially_implemented",
            "execution_status": "not_run_as_group_protocol",
            "feasible_with_current_features": "yes",
            "valid_bounds_source": "SAFE_FEATURES count+binary pairs",
            "proposed_groups": "logon;device;file;email;http",
            "label_definition_safe": "yes_if_zeroing_source_channels_only",
            "recommended": "yes_exp_3_4",
            "priority": "P1",
            "notes": "Mask count and has_* for one source together; keep is_active_day unless justified.",
        },
        {
            "method_name": "random_observation_masking",
            "robustness_family": "feature_corruption_missingness",
            "implementation_status": "implemented_and_tested",
            "execution_status": "completed_run_on_superseded_models",
            "feasible_with_current_features": "yes",
            "valid_bounds_source": "levels_5_10_20_percent",
            "proposed_groups": "n/a",
            "label_definition_safe": "yes",
            "recommended": "yes_retain",
            "priority": "P1",
            "notes": "Re-run on ODST/attention-linear after loader wiring.",
        },
        {
            "method_name": "missing_random_features",
            "robustness_family": "feature_corruption_missingness",
            "implementation_status": "implemented_and_tested",
            "execution_status": "completed_run_on_superseded_models",
            "feasible_with_current_features": "yes",
            "valid_bounds_source": "levels_5_10_20_percent",
            "proposed_groups": "n/a",
            "label_definition_safe": "yes",
            "recommended": "yes_retain",
            "priority": "P2",
            "notes": "",
        },
        {
            "method_name": "missing_complete_days",
            "robustness_family": "temporal_perturbation",
            "implementation_status": "implemented_and_tested",
            "execution_status": "completed_run_on_superseded_models",
            "feasible_with_current_features": "yes",
            "valid_bounds_source": "levels_5_10_20_percent",
            "proposed_groups": "n/a",
            "label_definition_safe": "caution_if_removing_malicious_days",
            "recommended": "yes_with_exclusion_rules",
            "priority": "P1",
            "notes": "Preregister exclusion: do not delete the only positive-evidence day when identifiable; prefer importance-conditioned ablation with frozen labels.",
        },
        {
            "method_name": "gaussian_noise_continuous",
            "robustness_family": "feature_corruption",
            "implementation_status": "implemented_and_tested",
            "execution_status": "completed_run_on_superseded_models",
            "feasible_with_current_features": "yes",
            "valid_bounds_source": "bounded_noise_on_continuous_indices_0_6",
            "proposed_groups": "continuous_only",
            "label_definition_safe": "yes",
            "recommended": "yes_retain",
            "priority": "P2",
            "notes": "Binary features already protected.",
        },
        {
            "method_name": "binary_feature_flips",
            "robustness_family": "feature_corruption",
            "implementation_status": "not_implemented",
            "execution_status": "not_run",
            "feasible_with_current_features": "yes_with_semantic_constraints",
            "valid_bounds_source": "has_* flags must remain consistent with counts where possible",
            "proposed_groups": "binary",
            "label_definition_safe": "conditional",
            "recommended": "optional",
            "priority": "P3",
            "notes": "Avoid inconsistent states (has_email=1 with email_count=0) unless explicitly testing inconsistency robustness.",
        },
        {
            "method_name": "within_window_event_order_jitter",
            "robustness_family": "temporal_perturbation",
            "implementation_status": "not_implemented",
            "execution_status": "not_run",
            "feasible_with_current_features": "limited_daily_aggregates_not_raw_events",
            "valid_bounds_source": "not_applicable_at_event_level",
            "proposed_groups": "n/a",
            "label_definition_safe": "mostly_n/a",
            "recommended": "no_as_primary",
            "priority": "exclude_or_defer",
            "notes": "Representation is daily aggregates (T=20 days), not raw event order within a day.",
        },
        {
            "method_name": "threshold_sensitivity_curves",
            "robustness_family": "class_prevalence_threshold_stress",
            "implementation_status": "prototype_elsewhere",
            "execution_status": "unknown",
            "feasible_with_current_features": "yes",
            "valid_bounds_source": "frozen_validation_threshold",
            "proposed_groups": "n/a",
            "label_definition_safe": "yes",
            "recommended": "yes_secondary",
            "priority": "P2",
            "notes": "Untracked scripts/analyse_threshold_sensitivity.py exists; do not retune thresholds on stress outputs.",
        },
        {
            "method_name": "r62_external_dataset_shift",
            "robustness_family": "dataset_shift",
            "implementation_status": "not_implemented",
            "execution_status": "not_run",
            "feasible_with_current_features": "later",
            "valid_bounds_source": "future_r62_readiness",
            "proposed_groups": "n/a",
            "label_definition_safe": "yes_if_preregistered",
            "recommended": "reserve",
            "priority": "P4",
            "notes": "After r5.2 validation Obj3 freeze; no retroactive tuning of r5.2 models.",
        },
    ]


def validity_risk_register() -> list[dict[str, Any]]:
    return [
        {
            "risk_id": "R01",
            "risk_description": "Using r5.2/r4.2 test labels to select explanation hyperparameters or perturbation severities.",
            "affected_component": "all_explanation_and_robustness",
            "severity": "critical",
            "current_control": "Obj3 pilot defaults to validation; confirm flag required for test.",
            "required_control": "Freeze all explanation/perturbation parameters on r4.2 development + r5.2 validation before any guarded test pass.",
            "status": "controlled_for_pilot_needs_extension_to_odst_protocol",
        },
        {
            "risk_id": "R02",
            "risk_description": "Retuning thresholds after robustness or explanation evaluation.",
            "affected_component": "threshold_application",
            "severity": "critical",
            "current_control": "Thresholds loaded from locked Obj2 manifest; no retune in pilot.",
            "required_control": "Continue frozen-threshold rule; store threshold hashes in every Obj3 run manifest.",
            "status": "controlled",
        },
        {
            "risk_id": "R03",
            "risk_description": "Explaining joint soft forest or surrogate instead of selected ODST architecture.",
            "affected_component": "objective3_model_targets",
            "severity": "high",
            "current_control": "None for selected architecture; pilot still targets soft forest.",
            "required_control": "Update OBJECTIVE3_MODEL_IDS to ODST + attention-linear; archive soft-forest Obj3 claims as historical pilot.",
            "status": "open",
        },
        {
            "risk_id": "R04",
            "risk_description": "Treating attention weights as automatically causal explanations.",
            "affected_component": "temporal_attention",
            "severity": "high",
            "current_control": "Not claimed as causal in code comments; faithfulness not yet measured.",
            "required_control": "Always pair attention with faithfulness deletion controls; report as native importance signal only.",
            "status": "open_pending_exp_3_2",
        },
        {
            "risk_id": "R05",
            "risk_description": "Interpreting scaled/latent ODST features as original raw events.",
            "affected_component": "odst_explanations",
            "severity": "high",
            "current_control": "Feature names map to 13 daily aggregates.",
            "required_control": "Map explanations only to SAFE_FEATURES / log sources; never claim event-id causality from aggregates.",
            "status": "control_defined",
        },
        {
            "risk_id": "R06",
            "risk_description": "Perturbing padding positions or impossible histories.",
            "affected_component": "perturbations",
            "severity": "medium",
            "current_control": "T=20 dense daily schema; no explicit pad mask.",
            "required_control": "Document that inactive days (is_active_day=0) should be handled explicitly; avoid creating count/binary inconsistencies.",
            "status": "open",
        },
        {
            "risk_id": "R07",
            "risk_description": "Deleting label-defining malicious evidence days during temporal ablation.",
            "affected_component": "missing_complete_days",
            "severity": "high",
            "current_control": "None specific.",
            "required_control": "Preregister exclusion or stratified reporting when positive-day removal collapses the label signal.",
            "status": "open",
        },
        {
            "risk_id": "R08",
            "risk_description": "Mixing soft-forest pilot metrics with ODST results without protocol qualification.",
            "affected_component": "reporting",
            "severity": "high",
            "current_control": "This audit separates them.",
            "required_control": "Separate artefact namespaces: objective3/pilot_softforest_archive vs objective3/odst_protocol.",
            "status": "open",
        },
        {
            "risk_id": "R09",
            "risk_description": "Averaging single-seed and three-seed outputs without qualification.",
            "affected_component": "aggregation",
            "severity": "medium",
            "current_control": "Pilot has three seeds for superseded models.",
            "required_control": "Require matched seeds 42/52/62 for primary ODST claims; mark n=1 separately.",
            "status": "control_defined",
        },
        {
            "risk_id": "R10",
            "risk_description": "Integrated gradients with invalid baselines for binary/count features.",
            "affected_component": "optional_ig",
            "severity": "medium",
            "current_control": "IG not implemented.",
            "required_control": "If IG added, preregister baseline (e.g., zero/inactive day) and report validity limits.",
            "status": "deferred",
        },
        {
            "risk_id": "R11",
            "risk_description": "Accessing r6.2 early and retrofitting r5.2 model choices.",
            "affected_component": "dataset_shift",
            "severity": "critical",
            "current_control": "r6.2 reserved; not used in Obj3 pilot.",
            "required_control": "Hard path denylist until preregistered external stress stage.",
            "status": "controlled",
        },
        {
            "risk_id": "R12",
            "risk_description": "Missing local AttentionNodeEnsemble code leads to silent use of wrong checkpoint loader.",
            "affected_component": "odst_loading",
            "severity": "critical",
            "current_control": "No ODST in current Obj3 loader.",
            "required_control": "Port/vendoring prototype_v3_node with hash-locked checkpoints before any ODST Obj3 run.",
            "status": "open_blocking",
        },
        {
            "risk_id": "R13",
            "risk_description": "Cherry-picking local explanation examples.",
            "affected_component": "local_explanation_sampling",
            "severity": "high",
            "current_control": "No frozen sample manifest yet.",
            "required_control": "Preregister stratified sampler by outcome x seed before viewing cases.",
            "status": "open",
        },
        {
            "risk_id": "R14",
            "risk_description": "Crossing chronological boundaries by using future windows in perturbations.",
            "affected_component": "temporal_perturbation",
            "severity": "medium",
            "current_control": "Perturbations act within existing tensors only.",
            "required_control": "Forbid regenerating sequences from future raw logs during Obj3.",
            "status": "controlled",
        },
    ]


def dependency_plan() -> list[dict[str, Any]]:
    return [
        {
            "task_id": "T01",
            "task_name": "Port or vendor prototype_v3_node into feasibility repo",
            "dependency": "none",
            "existing_code": str(SISTER_NODE),
            "required_new_code": "scripts/prototype_v3_node/* + tests for load-only",
            "model_training_required": "no",
            "GPU_required": "no",
            "estimated_compute_class": "metadata_only",
            "data_access_required": "no",
            "test_access_required": "no",
            "expected_output": "loadable AttentionNodeEnsemble from frozen checkpoints",
            "priority": "P0",
            "recommended_execution_order": 1,
        },
        {
            "task_id": "T02",
            "task_name": "Extend Obj3 inference to ODST + attention-linear selected set",
            "dependency": "T01",
            "existing_code": "scripts/objective3_inference.py",
            "required_new_code": "ODST LockedBundle kind; extras for attention + ODST diagnostics",
            "model_training_required": "no",
            "GPU_required": "optional",
            "estimated_compute_class": "GPU_light",
            "data_access_required": "r42_validation",
            "test_access_required": "no",
            "expected_output": "predict_with_extras for ODST",
            "priority": "P0",
            "recommended_execution_order": 2,
        },
        {
            "task_id": "T03",
            "task_name": "Implement native ODST explanation extraction (Exp 3.1)",
            "dependency": "T02",
            "existing_code": "prototype_v3_node/diagnostics.py; r52 routing_diagnostics.json schema",
            "required_new_code": "objective3_odst_explanations.py + unit tests",
            "model_training_required": "no",
            "GPU_required": "optional",
            "estimated_compute_class": "GPU_light",
            "data_access_required": "r42_validation_dev_sample",
            "test_access_required": "no",
            "expected_output": "feature_selection;routing;leaf;attention tables",
            "priority": "P0",
            "recommended_execution_order": 3,
        },
        {
            "task_id": "T04",
            "task_name": "Preregister stratified local-explanation sample manifest",
            "dependency": "T02",
            "existing_code": "none_frozen",
            "required_new_code": "sampling script using validation predictions only",
            "model_training_required": "no",
            "GPU_required": "no",
            "estimated_compute_class": "CPU_light",
            "data_access_required": "r42_validation",
            "test_access_required": "no",
            "expected_output": "objective3_local_sample_manifest.json",
            "priority": "P0",
            "recommended_execution_order": 4,
        },
        {
            "task_id": "T05",
            "task_name": "Implement faithfulness deletion/insertion curves (Exp 3.2)",
            "dependency": "T03",
            "existing_code": "feature_masking_analysis building block",
            "required_new_code": "ranked deletion; random/bottom controls; AOPC metrics",
            "model_training_required": "no",
            "GPU_required": "yes",
            "estimated_compute_class": "GPU_moderate",
            "data_access_required": "r42_dev_then_r52_val",
            "test_access_required": "no",
            "expected_output": "faithfulness CSVs+figures",
            "priority": "P1",
            "recommended_execution_order": 5,
        },
        {
            "task_id": "T06",
            "task_name": "Extend stability metrics (Exp 3.3)",
            "dependency": "T03",
            "existing_code": "explanation_stability cosine/L1",
            "required_new_code": "Spearman; Jaccard; top-k; seed agreement",
            "model_training_required": "no",
            "GPU_required": "optional",
            "estimated_compute_class": "GPU_light",
            "data_access_required": "r42_dev_then_r52_val",
            "test_access_required": "no",
            "expected_output": "stability tables",
            "priority": "P1",
            "recommended_execution_order": 6,
        },
        {
            "task_id": "T07",
            "task_name": "Implement missing log-source group masking (Exp 3.4)",
            "dependency": "T02",
            "existing_code": "mask_feature_channel",
            "required_new_code": "source group specs + runner",
            "model_training_required": "no",
            "GPU_required": "yes",
            "estimated_compute_class": "GPU_light",
            "data_access_required": "r42_dev_then_r52_val",
            "test_access_required": "no",
            "expected_output": "source ablation metrics at frozen thresholds",
            "priority": "P1",
            "recommended_execution_order": 7,
        },
        {
            "task_id": "T08",
            "task_name": "Re-run retained perturbation grid on ODST/attention-linear (Exp 3.5)",
            "dependency": "T02;T07",
            "existing_code": "objective3_perturbations + run_objective3_pilot robustness",
            "required_new_code": "model-set switch; output namespace",
            "model_training_required": "no",
            "GPU_required": "yes",
            "estimated_compute_class": "GPU_moderate",
            "data_access_required": "r52_validation",
            "test_access_required": "no",
            "expected_output": "odst robustness multi-seed tables",
            "priority": "P1",
            "recommended_execution_order": 8,
        },
        {
            "task_id": "T09",
            "task_name": "Unit tests and small synthetic/dev smoke for ODST Obj3 path",
            "dependency": "T01;T02;T03",
            "existing_code": "tests/test_objective3_pilot.py",
            "required_new_code": "tests/test_objective3_odst_explanations.py",
            "model_training_required": "no",
            "GPU_required": "no",
            "estimated_compute_class": "CPU_moderate",
            "data_access_required": "synthetic_or_tiny_slice",
            "test_access_required": "no",
            "expected_output": "green pytest for extraction/faithfulness scaffolding",
            "priority": "P0",
            "recommended_execution_order": 3,
        },
        {
            "task_id": "T10",
            "task_name": "Optional IG gradient-path audit (not primary)",
            "dependency": "T01",
            "existing_code": "r52 odst_gradient_checks.json evidence of prior checks",
            "required_new_code": "gradient path unit test only",
            "model_training_required": "no",
            "GPU_required": "optional",
            "estimated_compute_class": "GPU_light",
            "data_access_required": "tiny",
            "test_access_required": "no",
            "expected_output": "go/no-go note for IG",
            "priority": "P3",
            "recommended_execution_order": 9,
        },
        {
            "task_id": "T11",
            "task_name": "Guarded one-pass r5.2 test explanation/robustness decision gate",
            "dependency": "T05;T06;T07;T08",
            "existing_code": "confirm flag pattern",
            "required_new_code": "separate confirm + freeze report",
            "model_training_required": "no",
            "GPU_required": "yes",
            "estimated_compute_class": "GPU_moderate",
            "data_access_required": "r52_test_only_if_justified",
            "test_access_required": "yes_if_gate_passes",
            "expected_output": "optional confirmatory artefacts",
            "priority": "P2",
            "recommended_execution_order": 10,
        },
        {
            "task_id": "T12",
            "task_name": "Reserve r6.2 external stress protocol drafting only",
            "dependency": "T11",
            "existing_code": "none",
            "required_new_code": "protocol markdown only",
            "model_training_required": "no",
            "GPU_required": "no",
            "estimated_compute_class": "metadata_only",
            "data_access_required": "no",
            "test_access_required": "no",
            "expected_output": "future_r62_stress_protocol.md",
            "priority": "P4",
            "recommended_execution_order": 11,
        },
    ]


def write_dirty_report(classified: dict[str, Any]) -> Path:
    path = OUT / "objective3_dirty_worktree_report.md"
    lines = [
        "# Objective 3 dirty worktree report",
        "",
        f"- Generated (UTC): {datetime.now(timezone.utc).isoformat()}",
        f"- Branch: `{BRANCH}`",
        f"- HEAD: `{HEAD}`",
        "- Action taken: **none** (no reset/clean/stash/checkout/commit).",
        "",
        "## Tracked modified files",
        "",
    ]
    for p in classified["tracked_modified"]:
        lines.append(f"- `{p}`")
    lines += ["", "## Untracked files / dirs", ""]
    for p in classified["untracked"]:
        lines.append(f"- `{p}`")
    lines += ["", "## Staged files", ""]
    if classified["staged"]:
        for p in classified["staged"]:
            lines.append(f"- `{p}`")
    else:
        lines.append("- _None._")
    lines += [
        "",
        "## Theme classification (modified)",
        "",
        f"- Objective 3: {classified['by_theme_modified']['objective3']}",
        f"- Objective 2: {classified['by_theme_modified']['objective2']}",
        f"- Prototypes: {classified['by_theme_modified']['prototypes']}",
        f"- Other: {classified['by_theme_modified']['other']}",
        "",
        "## Theme classification (untracked)",
        "",
        f"- Objective 3: {classified['by_theme_untracked']['objective3']}",
        f"- Objective 2: {classified['by_theme_untracked']['objective2']}",
        f"- Prototypes: {classified['by_theme_untracked']['prototypes']}",
        f"- Other: {classified['by_theme_untracked']['other']}",
        "",
        "## Objective 3 dirty file interpretation",
        "",
        "Modified Obj3 files (`objective3_locked_common.py`, `objective3_perturbations.py`,",
        "`run_objective3_pilot.py`, `generate_objective3_report_assets.py`, `tests/test_objective3_pilot.py`)",
        "expand the multi-perturbation-seed pilot for the **locked Obj2 model set**",
        "(joint soft forest, attention–linear, standalone Bi-LSTM, fragmented XGBoost).",
        "They do **not** yet target the selected sparsemax–sigmoid ODST architecture.",
        "",
        "Untracked prototype trees (`prototype_v2*`, fusion leftovers, etc.) are outside the",
        "preregistered Obj3 ODST scope and must not be mixed into Obj3 claims.",
        "",
        "`docs/cert_r42_notes.md` is modified and treated as research notes (other), not an Obj3 result.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_prereg_plan() -> Path:
    path = OUT / "objective3_preregistered_experiment_plan.md"
    text = f"""# Objective 3 preregistered experiment plan

- Generated (UTC): {datetime.now(timezone.utc).isoformat()}
- Protocol identifier: `{PROTOCOL}`
- Selected architecture: Bi-LSTM–attention–sparsemax–sigmoid ODST
- Principal neural reference: Bi-LSTM–attention–linear
- Branch/HEAD at audit: `{BRANCH}` / `{HEAD}`

This plan states what the experiments will test. It does **not** claim that ODST is more
interpretable or more robust in advance.

## Shared protocol rules

1. No training or fine-tuning.
2. Frozen checkpoints and frozen validation-selected thresholds.
3. Develop/debug on synthetic or CERT r4.2 development artefacts.
4. Freeze explanation and perturbation parameters before r5.2 validation runs.
5. r5.2 test access only via a separate justified confirm gate after validation freeze.
6. r6.2 reserved for later external stress testing; not accessed now.
7. Primary models: ODST seeds 42/52/62 and attention–linear seeds 42/52/62.
8. RF/XGBoost may appear later as optional feature-importance references only.

### Blocking prerequisite

`scripts/prototype_v3_node/` is absent from this repository. Sister implementation exists at
`{SISTER_NODE}`. Experiments 3.1–3.5 that require ODST loading are blocked until the package
is ported/vendored and unit-tested for load-only inference.

---

## Experiment 3.1 — Native explanation extraction

- **Research question:** Can native attention and ODST routing/feature-selection signals be
  extracted deterministically from the selected frozen checkpoints?
- **Objective 3 / Chapter 3 link:** explanation generation foundation.
- **Evaluation expectation:** The experiment will test whether attention weights and ODST
  feature-selection/routing summaries can be exported without changing predictions.
- **Models / seeds:** ODST and attention–linear; 42, 52, 62.
- **Checkpoints:** r4.2 v3_node ODST + sequence-ensemble attention–linear for development;
  r5.2 confirmation checkpoints for preregistered validation stage.
- **Dataset / partition:** r4.2 validation (dev); then r5.2 validation (preregistered).
- **Sample selection:** global summaries on full validation; local cases from preregistered
  stratified manifest (TP/FN/FP/TN × seed), fixed size e.g. 40 sequences (10 per stratum) or
  the nearest balanced available count.
- **Explanation methods:** temporal attention; ODST feature-selection probabilities; split
  usage; leaf utilisation; routing entropy; per-tree contribution if exposed without altering
  inference.
- **Baseline/control:** deterministic repeated extraction (bit-identical tensors).
- **Primary metrics:** successful extraction rate; prediction invariance (max |Δp|≈0);
  attention entropy/concentration; ODST selection sparsity/support.
- **Secondary metrics:** malicious vs benign attention profile differences (descriptive only).
- **Threshold rule:** frozen; not used for extraction success.
- **Stopping rule:** all six checkpoints export without prediction drift beyond numerical tol.
- **Exclusion rule:** soft-forest pilot outputs excluded from primary tables.
- **Expected outputs:** CSV/parquet explanation tables; protocol manifest; hash snapshot.
- **Compute:** GPU_light.
- **Validity risks:** R03, R05, R12, R13.
- **Interpretation boundaries:** Native signals are not automatically faithful or causal.

## Experiment 3.2 — Explanation faithfulness

- **Research question:** Do top-ranked native explanations identify inputs whose removal
  changes model probability more than random or bottom-ranked controls?
- **Objective 3 / Chapter 3 link:** explanation validation (fidelity/faithfulness).
- **Evaluation expectation:** The analysis will evaluate whether ranked deletion produces
  larger probability reductions than controls. A favourable result would provide evidence that
  the explanations are informative for the model’s decisions, not that they are human-causal.
- **Models / seeds:** ODST + attention–linear; matched seeds.
- **Partition:** r4.2 tiny debug → freeze curve settings → r5.2 validation.
- **Perturbation definition:** zero top-k features and/or timesteps by explanation rank;
  random-k; bottom-k; optional insertion/restoration curves.
- **Primary metrics:** mean Δp; comprehensiveness; sufficiency; area over deletion curve.
- **Secondary metrics:** PR-AUC/F1 change at frozen threshold (reporting only).
- **Threshold rule:** frozen.
- **Stopping rule:** complete seed×model grid at preregistered k-grid.
- **Exclusion rule:** no severity retuning after seeing r5.2 validation outcomes beyond
  predeclared robustness of numeric tolerances.
- **Compute:** GPU_moderate.
- **Validity risks:** R01, R04, R07.
- **Interpretation boundaries:** Faithfulness ≠ end-user correctness.

## Experiment 3.3 — Explanation stability

- **Research question:** How stable are native explanations across seeds, tiny valid
  perturbations, and repeated deterministic runs?
- **Evaluation expectation:** The experiment will test rank correlation and top-k overlap.
  High stability would support reliability of the explanation pipeline; low stability would
  limit interpretive claims.
- **Primary metrics:** Spearman; top-k overlap; Jaccard; cosine similarity; seed agreement.
- **Secondary metrics:** prediction flip rate under the same tiny perturbations.
- **Partition / freeze rules:** same as 3.2.
- **Compute:** GPU_light.
- **Validity risks:** R09, R13.

## Experiment 3.4 — Missing-source robustness

- **Research question:** How does frozen ODST/attention–linear performance degrade when each
  major log-source feature group is masked?
- **Evaluation expectation:** The analysis will evaluate PR-AUC/F1/FP/FN changes at frozen
  thresholds under source ablation. It will not claim operational robustness without
  qualification.
- **Perturbation:** mask paired count + has_* channels for logon, device, file, email, HTTP.
- **Primary metrics:** PR-AUC, precision, recall, F1, FP, FN (frozen threshold).
- **Controls:** clean baseline; random channel group of matched width.
- **Compute:** GPU_light.
- **Validity risks:** R02, R06.

## Experiment 3.5 — Temporal and feature perturbation robustness

- **Research question:** How sensitive are frozen models to the retained non-adversarial
  perturbation grid (observation masking, feature missingness, complete-day missingness,
  bounded continuous noise)?
- **Evaluation expectation:** The experiment will quantify degradation and prediction/explanation
  stability versus severity levels 5/10/20% with multiple perturbation seeds.
- **Reuse:** existing `objective3_perturbations.py` after ODST wiring.
- **Primary metrics:** PR-AUC/F1 degradation; flip rate; explanation stability.
- **Exclusion:** no within-day event-order jitter (unsupported by daily aggregates).
- **Compute:** GPU_moderate.
- **Validity risks:** R07, R08.

## Optional later (not required for minimum Obj3 scope)

- Integrated gradients gradient-path audit (P3).
- Threshold-sensitivity curves with frozen thresholds (P2).
- Guarded one-pass r5.2 test confirmation (only if validation stage justifies it).
- r6.2 external stress (reserved).

## Recommended experimental sequence

1. Port `prototype_v3_node` + unit tests (home / metadata+CPU).
2. Wire Obj3 loader + smoke on r4.2 validation slice.
3. Exp 3.1 extraction on r4.2, then freeze schemas.
4. Exp 3.2–3.3 scaffolding on small r4.2 sample; freeze parameters.
5. Exp 3.4–3.5 on r4.2 smoke then r5.2 validation multi-seed.
6. Decide on guarded r5.2 test pass.
7. Keep r6.2 untouched until a separate preregistration.
"""
    path.write_text(text, encoding="utf-8")
    return path


def write_audit_summary(classified: dict[str, Any], ckpts: list[dict[str, Any]]) -> Path:
    path = OUT / "objective3_audit_summary.md"
    present = [c for c in ckpts if c["exists"] == "true"]
    missing = [c for c in ckpts if c["exists"] != "true"]
    odst_blocked = [c for c in present if "odst" in c["architecture"] and "blocked" in c["loadability_evidence"]]
    lines = [
        "# Objective 3 audit summary",
        "",
        f"- Generated (UTC): {datetime.now(timezone.utc).isoformat()}",
        f"- Branch: `{BRANCH}`",
        f"- HEAD: `{HEAD}`",
        f"- Final status label: `{STATUS}`",
        "",
        "## What is already implemented",
        "",
        "- Locked Obj3 pilot libraries for attention summaries, soft-forest routing proxies,",
        "  feature-channel masking, and four non-adversarial perturbations.",
        "- Completed r4.2 validation multi-seed pilots for the **superseded** Obj2 model set",
        "  (not ODST).",
        "- Unit tests covering perturbations, CLI safety, and synthetic inference.",
        "",
        "## What is preliminary",
        "",
        "- All completed Obj3 pilot metrics: useful engineering evidence, not selected-architecture results.",
        "- Dirty worktree Obj3 modifications expanding multi-perturbation-seed support.",
        "",
        "## What is prototype-only / absent",
        "",
        "- Native ODST explanation extraction in this repo.",
        "- Faithfulness deletion/insertion protocol.",
        "- Log-source group robustness as a first-class experiment.",
        "- Integrated gradients / SHAP / LIME.",
        "- r6.2 stress execution.",
        "",
        "## Checkpoint readiness",
        "",
        f"- Present artefacts hashed: {len(present)}",
        f"- Missing artefacts: {len(missing)}",
        f"- ODST checkpoints present but locally unloadable without porting `prototype_v3_node`: {len(odst_blocked)}",
        "",
        "## Separate component statuses",
        "",
        "- explanation extraction: `prototype_gap_for_odst` (attention ready; ODST blocked)",
        "- explanation faithfulness: `not_implemented`",
        "- explanation stability: `partial_for_attention_softforest_needs_odst_extension`",
        "- missing-source robustness: `partial_feature_channel_only`",
        "- temporal perturbation robustness: `day_masking_only`",
        "- external r6.2 stress testing: `reserved_not_started`",
        "",
        "## Recommended first implementation task",
        "",
        "Port/vendor `scripts/prototype_v3_node` from the sister node-development repository and",
        "add load-only unit tests against frozen ODST checkpoints (no training).",
        "",
        "## Dirty Obj3 files",
        "",
        f"- Modified: {classified['by_theme_modified']['objective3']}",
        f"- Untracked Obj3: {classified['by_theme_untracked']['objective3']}",
        "",
        "## Safety declaration for this audit",
        "",
        "- Models trained: no",
        "- New experiments executed: no",
        "- Prediction tensors opened: no",
        "- r5.2 test path accessed: no",
        "- r6.2 path accessed: no",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    short, _full = git_status()
    classified = classify_dirty(short)

    comp = component_manifest()
    write_csv(
        OUT / "objective3_component_manifest.csv",
        comp,
        list(comp[0].keys()),
    )

    ckpts = checkpoint_manifest()
    write_csv(OUT / "objective3_checkpoint_manifest.csv", ckpts, list(ckpts[0].keys()))

    expl = explanation_method_audit()
    write_csv(OUT / "objective3_explanation_method_audit.csv", expl, list(expl[0].keys()))

    robust = robustness_method_audit()
    write_csv(OUT / "objective3_robustness_method_audit.csv", robust, list(robust[0].keys()))

    risks = validity_risk_register()
    write_csv(OUT / "objective3_validity_risk_register.csv", risks, list(risks[0].keys()))

    deps = dependency_plan()
    write_csv(OUT / "objective3_implementation_dependency_plan.csv", deps, list(deps[0].keys()))

    write_dirty_report(classified)
    write_prereg_plan()
    write_audit_summary(classified, ckpts)

    present_selected = [
        c["checkpoint_id"]
        for c in ckpts
        if c["exists"] == "true"
        and c["architecture"] in {"attention_linear", "sparsemax_sigmoid_odst"}
    ]
    missing_selected = [
        c["checkpoint_id"]
        for c in ckpts
        if c["exists"] != "true"
        and c["architecture"] in {"attention_linear", "sparsemax_sigmoid_odst"}
    ]

    console = {
        "branch": BRANCH,
        "HEAD": HEAD,
        "worktree_status": "dirty",
        "modified_objective3_files": classified["by_theme_modified"]["objective3"],
        "untracked_objective3_files": classified["by_theme_untracked"]["objective3"],
        "completed_objective3_components": [
            "obj3_pilot_libraries",
            "r42_validation_multi5_pilots_for_superseded_obj2_models",
            "obj3_unit_tests",
        ],
        "preliminary_components": [
            "attention_softforest_feature_masking_robustness_results",
            "dirty_multi_pert_seed_extensions",
        ],
        "prototype_only_components": [
            "threshold_sensitivity_untracked_script",
            "soft_forest_routing_as_stand_in_for_odst",
        ],
        "selected_checkpoints_available": present_selected,
        "missing_checkpoints": missing_selected,
        "odst_loader_in_this_repo": False,
        "sister_prototype_v3_node_present": SISTER_NODE.exists(),
        "prediction_tensors_opened": [],
        "r52_test_path_accessed": False,
        "r62_path_accessed": False,
        "models_trained": False,
        "new_experiments_executed": False,
        "recommended_first_implementation_task": (
            "Port/vendor scripts/prototype_v3_node and add load-only ODST unit tests"
        ),
        "component_statuses": {
            "explanation_extraction": "prototype_gap_for_odst",
            "explanation_faithfulness": "not_implemented",
            "explanation_stability": "partial_needs_odst_extension",
            "missing_source_robustness": "partial_feature_channel_only",
            "temporal_perturbation_robustness": "day_masking_only",
            "external_r62_stress_testing": "reserved_not_started",
        },
        "final_objective3_audit_status": STATUS,
        "output_dir": str(OUT.relative_to(ROOT)).replace("\\", "/"),
        "cautious_conclusion": (
            "Objective 3 currently has a completed r4.2 validation pilot for superseded Obj2 "
            "models and reusable perturbation/attention tooling, but the selected ODST "
            "architecture cannot yet be loaded in this repository; porting prototype_v3_node "
            "and re-targeting the preregistered ODST/attention–linear protocol remain required "
            "before controlled experiment execution."
        ),
    }
    created = sorted(p.name for p in OUT.iterdir() if p.is_file())
    console["output_files_created"] = created
    (OUT / "objective3_audit_console_summary.json").write_text(
        json.dumps(console, indent=2), encoding="utf-8"
    )
    console["output_files_created"] = sorted(p.name for p in OUT.iterdir() if p.is_file())
    (OUT / "objective3_audit_console_summary.json").write_text(
        json.dumps(console, indent=2), encoding="utf-8"
    )
    print(json.dumps(console, indent=2))


if __name__ == "__main__":
    main()
