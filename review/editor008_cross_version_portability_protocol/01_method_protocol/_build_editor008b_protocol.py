#!/usr/bin/env python3
"""EDITOR-008B: freeze source-robust portability protocol (no training code)."""
from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
LOCK_DIR = ROOT / "review" / "editor008_cross_version_portability_protocol" / "00_target_lock"
COMMIT_D1 = "d5a6416bfe5ea582b2439803ffc0d896c091d844"
COMMIT_008A = "0eef55cbb00c410626f273a7878e81cb166c310d"
D1_LEFTOVERS = [
    "EDITOR006B_REVIEW_PACKAGE.zip",
    "EDITOR006B_REVIEW_PACKAGE/",
    "review/editor004a_r51_model_free_audit/",
    "review/editor005a_r62_model_free_audit/",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def dump_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def rec(path: Path, role: str) -> dict[str, Any]:
    return {
        "path": str(path),
        "sha256": sha256_file(path),
        "byte_size": path.stat().st_size,
        "role": role,
    }


def main() -> int:
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    head = git("rev-parse", "HEAD")
    if head != COMMIT_008A:
        # Allow being at 008A or a descendant that is still only 008A+untracked protocol
        if subprocess.call(["git", "merge-base", "--is-ancestor", COMMIT_008A, "HEAD"], cwd=ROOT) != 0:
            raise SystemExit("EDITOR008_PROTOCOL_BLOCKED missing 008A ancestor")
    lock = json.loads((LOCK_DIR / "EDITOR008_FINAL_TARGET_LOCK.json").read_text(encoding="utf-8"))
    if lock["FINAL_TARGET_SELECTION_RULE"] != "NO_PROSPECTIVE_TARGET_AVAILABLE":
        raise SystemExit("EDITOR008_PROTOCOL_BLOCKED unexpected target lock")

    unresolved_numeric = [
        {
            "parameter": "Generation-2 FIXED_ALERT_BUDGET_RATE",
            "STATUS": "REQUIRES_PRETRAINING_NUMERIC_FREEZE",
            "historical_source": "r5.2 calibration-alert BUDGETS=(0.0005,0.001,0.0025,0.005,0.01)",
            "adopted_as_generation2_operating_point": False,
            "reason": "Historical r5.2-only alert-burden candidates are not prospectively frozen for multi-source Generation-2 decision portability.",
        },
        {
            "parameter": "Generation-2 FIXED_FPR numeric anchor",
            "STATUS": "REQUIRES_PRETRAINING_NUMERIC_FREEZE",
            "historical_source": None,
            "adopted_as_generation2_operating_point": False,
            "reason": "No source-only fixed-FPR numeric operating point was found that is scientifically compatible with domain-balanced multi-source Generation-2.",
        },
        {
            "parameter": "GroupDRO step-size / group-weight learning-rate / robustness radius",
            "STATUS": "REQUIRES_PRETRAINING_NUMERIC_FREEZE",
            "reason": "No frozen GroupDRO hyperparameters exist in this research programme.",
        },
        {
            "parameter": "CORAL alignment penalty weight",
            "STATUS": "REQUIRES_PRETRAINING_NUMERIC_FREEZE",
            "reason": "No frozen CORAL hyperparameters exist in this research programme.",
        },
        {
            "parameter": "Optional abstention/OOD gate numeric threshold",
            "STATUS": "REQUIRES_PRETRAINING_NUMERIC_FREEZE",
            "reason": "Abstention is optional and not part of the primary predictor; no numeric gate is frozen.",
        },
    ]

    problem = {
        "task_id": "EDITOR-008B",
        "manuscript": "Teacher-Anchored Differentiable Sequence–Ensemble Learning for Explainable Insider Threat Detection",
        "scientific_purpose": (
            "Cross-release portability of explainable insider-threat detectors under heterogeneous "
            "CERT releases, where strong within-release ranking and teacher-relative fidelity do not "
            "guarantee ranking or decision portability."
        ),
        "CROSS_RELEASE_NOT_CROSS_POPULATION": True,
        "cross_release_limitation": (
            "CERT releases belong to the same synthetic benchmark lineage. The Generation-2 experiment "
            "evaluates cross-release transfer within that benchmark family. It does not establish "
            "cross-organisation, cross-population, or real-world external generalisation."
        ),
        "untouched_target_definition": "UNOBSERVED_BY_THIS_RESEARCH_PROGRAM_BEFORE_PROSPECTIVE_LOCK",
        "untouched_target_is_not": "an independently sampled real-world population",
        "PROSPECTIVE_FINAL_TARGET_CLAIM": "NOT_AVAILABLE",
        "EDITOR008_PROSPECTIVE_TARGET_PROTOCOL": "BLOCKED",
        "paper_mode_if_executed_later": "RETROSPECTIVE_SOURCE_DOMAIN_LOVO_PORTABILITY_STUDY",
        "PRIMARY_PORTABILITY_PHENOTYPE": "P2_R62_SEVERE_DISTRIBUTION_AND_DECISION_SHIFT",
        "not_a_new_bilstm_architecture": True,
        "not_an_optimizer_novelty_claim": True,
        "inherited_predictive_pathway": [
            "20-day sequence",
            "Bi-LSTM",
            "temporal attention",
            "predictive head",
        ],
    }

    sources = {
        "task_id": "EDITOR-008B",
        "VERSION": "DOMAIN",
        "SOURCE_DOMAIN_WEIGHTING": "DOMAIN_BALANCED_NOT_SAMPLE_BALANCED",
        "source_domains": [
            {
                "version": "CERT r4.2",
                "role": "GENERATION2_SOURCE_DEVELOPMENT_DOMAIN",
                "previously_observed": True,
                "historical_role": "primary_development_dataset",
            },
            {
                "version": "CERT r5.2 TRAIN/VALIDATION",
                "role": "GENERATION2_SOURCE_DEVELOPMENT_DOMAIN",
                "previously_observed": True,
                "historical_role": "in_domain_train_validation",
                "TEST": "PROHIBITED",
            },
            {
                "version": "CERT r5.1",
                "role": "GENERATION2_SOURCE_DEVELOPMENT_DOMAIN",
                "labels": [
                    "GENERATION2_SOURCE_DEVELOPMENT_DOMAIN",
                    "PREVIOUSLY_OBSERVED_DIAGNOSTICALLY",
                ],
                "historical_results": "frozen_historical_evidence",
                "may_be_presented_as_prospective_untouched_target": False,
            },
            {
                "version": "CERT r6.2",
                "role": "GENERATION2_SOURCE_DEVELOPMENT_DOMAIN",
                "labels": [
                    "GENERATION2_SOURCE_DEVELOPMENT_DOMAIN",
                    "PREVIOUSLY_OBSERVED_DIAGNOSTICALLY",
                ],
                "historical_results": "frozen_historical_evidence",
                "may_be_presented_as_prospective_untouched_target": False,
                "special_fold_or_objective": False,
            },
        ],
        "R52_TEST_ROLE": "PROHIBITED",
        "symmetric_domain_treatment": True,
        "r62_is_one_lovo_domain_only": True,
    }

    firewall = {
        "task_id": "EDITOR-008B",
        "r62_specific_feature_targeting": "PROHIBITED",
        "email_count_specific_remediation": "PROHIBITED",
        "has_file_activity_specific_remediation": "PROHIBITED",
        "total_events_specific_remediation": "PROHIBITED",
        "r62_specific_threshold_remediation": "PROHIBITED",
        "r62_specific_hyperparameters": "PROHIBITED",
        "r62_specific_model_selection_weight": "PROHIBITED",
        "justification": "general domain-generalisation principles; all source versions treated symmetrically as domains",
        "r62_special_fold": False,
        "r62_special_objective": False,
    }

    architecture = {
        "task_id": "EDITOR-008B",
        "BiLSTM_ATTENTION_ARCHITECTURE": "INHERITED_NOT_NEW_CONTRIBUTION",
        "inherited_pathway": "20-day sequence → Bi-LSTM → temporal attention → predictive head",
        "ODST_ROLE": "EXPLANATION_ORIENTED_DIFFERENTIABLE_HEAD",
        "ATTENTION_LINEAR_ROLE": "PRIMARY_NEURAL_EFFICIENCY_AND_CALIBRATION_REFERENCE",
        "architectural_novelty_claimed": False,
        "RF": "REQUIRED",
        "XGBOOST": "REQUIRED",
        "tabular_schema_compatibility": "source-release engineered-feature schema must be verified before training; untouched-target check is schema/header identity only",
        "do_not_silently_alter_target_features": True,
        "do_not_drop_tabular_baselines_for_inconvenience": True,
    }

    preprocess = {
        "task_id": "EDITOR-008B",
        "scaling": "SOURCE_ONLY",
        "lovo": {
            "fit_scaler_on": "training source domains only",
            "apply_frozen_fold_scaler_to": "held-out source domain",
        },
        "final_source_trained_model": {
            "fit_final_scaler_on": "all declared source-development domains only",
            "freeze_scaler_before_target_access": True,
        },
        "never_fit_scaler_on_untouched_target": True,
        "do_not_independently_normalise_target_releases": True,
        "calibration": "SOURCE_ONLY if used; report raw and calibrated separately",
    }

    method = {
        "task_id": "EDITOR-008B",
        "primary_method_family": [
            "MULTI_SOURCE_DOMAIN_BALANCED_TRAINING",
            "GROUPDRO_STYLE_SOURCE_RISK_OPTIMISATION",
            "SOURCE_ONLY_CORAL_REPRESENTATION_ALIGNMENT",
        ],
        "GroupDRO_role": "control worst-source/domain risk",
        "CORAL_role": "reduce source-domain representation covariance discrepancy",
        "separately_ablatable": True,
        "may_use_final_target_information": False,
        "preferred_neural_alignment_location": "attended representation",
        "target_alignment_loss": "PROHIBITED",
        "GroupDRO_fairness": {
            "initial_source_domain_weighting": "symmetric",
            "sample_count_must_not_determine_domain_importance": True,
            "no_r62_specific_weight": True,
            "no_target_domain_weight": True,
            "per_domain_risk_must_be_reported": True,
            "learned_adaptive_domain_weights_must_be_logged": True,
            "natural_emphasis_of_current_worst_source": "PERMITTED",
            "designing_weighting_rule_to_make_r62_dominate": "PROHIBITED",
        },
        "not_an_optimizer_novelty_claim": True,
        "TRAINING_AUTHORISED": "NO",
        "unresolved_numeric_parameters": unresolved_numeric,
    }

    selection = {
        "task_id": "EDITOR-008B",
        "design": "LEAVE_ONE_SOURCE_VERSION_OUT",
        "for_every_source_release_d": {
            "TRAIN": "all source domains except d",
            "HELD_OUT_SOURCE": "d",
        },
        "held_out_release_is_development_evidence_only": True,
        "random_split_cross_release_windows_as_substitute": "PROHIBITED",
        "primary_ranking_metric": "PR_AUC",
        "always_report_prevalence_beside_pr_auc": True,
        "domain_balanced_selection_hierarchy": {
            "PRIMARY": "best worst held-out-domain PR-AUC rank",
            "TIE_BREAK_1": "best mean held-out-domain PR-AUC rank",
            "TIE_BREAK_2": "highest equal-domain mean held-out PR-AUC",
            "TIE_BREAK_3": "simpler configuration",
        },
        "prohibited_selection_criteria": [
            "pooled window count",
            "pooled PR-AUC across all held-out windows",
            "r62-specific priority",
            "target results",
        ],
        "compute_pr_auc_separately_on_each_held_out_source_domain": True,
        "rank_configurations_within_each_held_out_domain": True,
        "equal_domain_weight": True,
    }

    decision = {
        "task_id": "EDITOR-008B",
        "ranking_separated_from_decisions": True,
        "PRIMARY_RANKING": "PR_AUC",
        "thresholded_decision_results": "SECONDARY",
        "WORST_SOURCE_F1_PRIMARY_THRESHOLD": "REMOVED",
        "preferred_ordering": [
            "FIXED_ALERT_BUDGET / FIXED_FLAGGING_RATE",
            "FIXED_FPR SOURCE-FROZEN SCORE THRESHOLD",
            "LEGACY F1 THRESHOLD — descriptive comparison only",
        ],
        "DECISION_OPERATING_POINT_VALUES": "UNRESOLVED_PENDING_PRETRAINING_NUMERIC_FREEZE",
        "PORTABLE_DECISION_PRIMARY": "UNRESOLVED_PENDING_NUMERIC_FREEZE",
        "PORTABLE_DECISION_SECONDARY": "UNRESOLVED_PENDING_NUMERIC_FREEZE",
        "LEGACY_F1_THRESHOLD_ROLE": "DESCRIPTIVE_REFERENCE_ONLY",
        "legacy_reference": "review/editor006a_preinference_freeze/EDITOR006A_THRESHOLDS.json",
        "historical_r52_alert_budgets": {
            "path": str(
                ROOT / "src" / "objective2_r52_calibration_alert_burden" / "constants.py"
            ),
            "recorded_config": str(
                Path(
                    r"C:\PhD\07_Projects\cert-r52-calibration-alert-burden\scripts"
                    r"\objective2_r52_calibration_alert_burden\recorded_results\calibration_alert_config.json"
                )
            ),
            "budgets": [0.0005, 0.001, 0.0025, 0.005, 0.01],
            "scientifically_compatible_as_generation2_freeze": False,
            "reason": "r5.2-validation alert-burden candidates; not independently audited as multi-source Generation-2 source-frozen operating points.",
        },
        "TRAINING_AUTHORISED": "NO",
        "no_target_labels_to_choose_or_modify_budget": True,
        "report_at_frozen_budget_when_later_frozen": [
            "coverage / flagging rate",
            "precision",
            "recall",
            "F1",
            "FP",
            "FN",
        ],
    }

    shift = {
        "task_id": "EDITOR-008B",
        "status": "MANDATORY_DIAGNOSTIC",
        "detector_must_not_modify_predictions": True,
        "primary_detector": "MMD on common-13 feature representations",
        "SHIFT_DETECTION_PRIMARY": "RAW_COMMON13_MMD",
        "secondary_detector": "MMD on learned attended representations",
        "SHIFT_DETECTION_SECONDARY": "ATTENDED_REPRESENTATION_MMD",
        "optional_descriptive_channel": "score-distribution divergence",
        "score_distribution_must_not_replace_model_free_feature_detector": True,
        "source_only_construction": {
            "kernel": "RBF",
            "bandwidth": "source-only median heuristic",
            "source_shift_envelope": "maximum observed inter-source-domain MMD",
            "alternative_envelope": "another explicitly justified source-only deterministic envelope, documented before training",
        },
        "final_target_flagged_only_after_all_freezes": True,
        "output": ["IN_SOURCE_ENVELOPE", "PORTABILITY_WARNING"],
        "no_target_labels_involved": True,
        "warning_cannot_trigger_retraining_under_same_protocol": True,
        "abstention_ood": {
            "status": "OPTIONAL",
            "part_of_primary_predictor": False,
            "UNGATED_FULL_COVERAGE_RESULTS": "MANDATORY",
            "GATED_RESULTS": "SECONDARY",
            "COVERAGE": "REPORTED",
            "SELECTIVE_METRICS": "REPORTED",
            "TARGET_LABEL_OPTIMISATION": "PROHIBITED",
            "portability_warning_cannot_hide_failed_ungated_model": True,
        },
    }

    teacher = {
        "task_id": "EDITOR-008B",
        "TEACHER_ANCHORING_ROLE": "AUXILIARY_FIDELITY_REGULARISER",
        "not_an_additive_rung_in_main_portability_ladder": True,
        "orthogonal_branch_on_matched_ODST": {
            "T0": "teacher/reference ODST",
            "T1": "teacher-initialisation-only student",
            "T2": "T1 + teacher anchoring",
            "only_difference_T1_T2": "teacher-relative anchoring regularisation",
        },
        "TEACHER_INITIALISATION_ONLY_CONTROL": "REQUIRED",
        "separate": ["predictive portability", "teacher-relative fidelity"],
        "R52_C2_C5_ORIGINAL_MECHANISM": "UNRESOLVED",
        "do_not_substitute_wrong_r52_C5_checkpoint": True,
        "do_not_fill_unresolved_r52_mechanism_gap": True,
        "no_predictive_superiority_from_anchoring_unless_prospective_gates_pass": True,
    }

    stats = {
        "task_id": "EDITOR-008B",
        "overlapping_stride_one_windows": "CORRELATED_OBSERVATIONS",
        "seeds": "REPRODUCIBILITY_REPETITIONS_NOT_INDEPENDENT_EXPERIMENTAL_UNITS",
        "inferential_uncertainty": "USER_CLUSTER_AWARE_RESAMPLING where defensible",
        "incident_resampling": "INSIDER_INCIDENT_CLUSTER_AWARE_RESAMPLING where official mapping is reliable",
        "tiny_effective_malicious_cluster_counts": "must be explicitly reported",
        "if_insufficient": "INFERENTIAL_CLAIM = NOT_SUPPORTED; use descriptive uncertainty",
        "evaluation_views_separately_labelled": [
            "COMPLETED_WINDOW",
            "DEOVERLAP",
            "ENDPOINT_PAST_ONLY",
        ],
        "do_not_pool_views": True,
        "completed_window_not_independent_incidents": True,
        "endpoint_past_only_does_not_imply_realtime": True,
        "primary_ranking": "PR_AUC",
        "always_report_prevalence_beside_pr_auc": True,
        "secondary_predictive": [
            "F1",
            "precision",
            "recall",
            "FP",
            "FN",
            "predicted-positive fraction",
            "negative threshold exceedance",
        ],
        "calibration_if_frozen": ["Brier", "log loss", "reliability summary"],
        "portability_metrics": [
            "LOVO per-domain PR_AUC",
            "domain-balanced source selection",
            "final-target PR_AUC if a prospective target later exists",
            "source-to-held-out ranking retention",
            "portable decision-policy behaviour",
            "shift-detector status",
        ],
        "explainability_under_shift": {
            "status": "SECONDARY_PROSPECTIVE_ANALYSIS",
            "procedure": "REFERENCE_CENTRED TOP-k VERSUS RANDOM INTERVENTION-BASED FAITHFULNESS",
            "centring": "source/training reference centring",
            "REFERENCE_CENTRED_TREE_CONTRIBUTION_FAITHFULNESS": "SUPPORTED",
            "ROUTE_LEAF_TRACEABILITY": "SUPPORTED_AS_INTERNAL_EVIDENCE",
            "ROUTE_LEAF_INDEPENDENT_FAITHFULNESS": "UNSUPPORTED",
            "if_sparse_malicious_evidence": "FAITHFULNESS_INFERENCE = INSUFFICIENT_CLUSTER_SUPPORT",
            "secondary_question": "Does reference-centred tree-contribution intervention faithfulness remain positive under a prospectively untouched cross-release shift?",
            "not_a_model_selection_criterion": True,
        },
        "degraded_input": {
            "SOURCE_ABLATION": "CONTROLLED_DEGRADED_INPUT_ANALYSIS",
            "GAUSSIAN_NOISE": "CONTROLLED_DEGRADED_INPUT_ANALYSIS",
            "ADVERSARIAL_ROBUSTNESS": "UNSUPPORTED",
            "new_adversarial_evasion_or_poisoning": "NOT_AUTHORISED",
        },
    }

    no_tune = {
        "task_id": "EDITOR-008B",
        "target_labels_before_final_freeze": "PROHIBITED",
        "target_feature_distribution_before_final_freeze": "PROHIBITED",
        "target_score_distribution_before_final_freeze": "PROHIBITED",
        "target_threshold_selection": "PROHIBITED",
        "target_scaler_fit": "PROHIBITED",
        "target_calibration_fit": "PROHIBITED",
        "target_hyperparameter_selection": "PROHIBITED",
        "target_model_selection": "PROHIBITED",
        "target_specific_architecture_change": "PROHIBITED",
        "post_target_failure_retraining_under_same_protocol": "PROHIBITED",
        "target_failure_is_retained_as_a_result": True,
    }

    gates = {
        "task_id": "EDITOR-008B",
        "do_not_combine_into_generic_success": True,
        "separate_findings": [
            "RANKING_PORTABILITY",
            "DECISION_PORTABILITY",
            "SHIFT_DIAGNOSIS",
            "TEACHER_FIDELITY",
            "PREDICTIVE_SUPERIORITY",
            "EXPLAINABILITY",
        ],
        "shift_warning_with_strong_predictive_performance": "POSSIBLE",
        "shift_warning_with_failure": "POSSIBLE",
        "teacher_fidelity_with_predictive_failure": "POSSIBLE",
        "predictive_superiority_permitted_only_if": [
            "comparison prospectively declared",
            "baseline matched",
            "target untouched (not available under this lock)",
            "cluster-aware uncertainty adequate",
            "prospectively frozen comparison supports the claim",
        ],
        "positive_point_estimates_alone_insufficient": True,
        "final_target_claim_scope": {
            "FINAL_TARGET_COUNT": 0,
            "GENERALISATION_CLAIM_SCOPE": "NOT_AVAILABLE_NO_PROSPECTIVE_TARGET",
            "do_not_claim_generic_CERT_portability": True,
            "do_not_pool_away_failures": True,
        },
    }

    execution = {
        "task_id": "EDITOR-008B",
        "execute_now": False,
        "TRAINING_AUTHORISED": "NO",
        "future_order_do_not_execute_now": [
            "complete all source-only implementation/testing",
            "complete LOVO model/hyperparameter selection",
            "freeze architecture",
            "freeze preprocessing/scaler",
            "freeze model checkpoints",
            "freeze portable decision policy",
            "freeze calibration if used",
            "freeze shift detector",
            "freeze optional abstention rule",
            "freeze explanation-analysis protocol",
            "hash all artefacts",
            "receive explicit final-target authorisation",
            "perform schema-only compatibility gate",
            "score each locked target exactly once (none locked under this protocol)",
            "compute predeclared predictive outputs",
            "compute predeclared shift diagnostics",
            "compute predeclared secondary analyses",
            "freeze all outcomes immediately",
        ],
        "no_rescue_retraining_under_same_protocol": True,
    }

    contribution = {
        "task_id": "EDITOR-008B",
        "intended_contribution": (
            "A prospectively controlled source-robust portability framework for explainable "
            "insider-threat detection, combining version-as-domain multi-source development, "
            "domain-robust optimisation, source-only representation alignment, prevalence-robust "
            "portable decision policies, source-frozen shift diagnosis, and dependence-aware "
            "cross-release evaluation."
        ),
        "explicit_exclusions": [
            "NOT a new Bi-LSTM architecture",
            "NOT evidence that teacher anchoring improves prediction",
            "NOT cross-population generalisation",
            "NOT real-world deployment validation",
            "NOT adversarial robustness",
        ],
        "PROSPECTIVE_FINAL_TARGET_CLAIM": "NOT_AVAILABLE",
        "optimizer_novelty_claim": False,
    }

    dump_json(OUT / "EDITOR008_PROBLEM_DEFINITION.json", problem)
    dump_json(OUT / "EDITOR008_SOURCE_DOMAIN_ROLE_LOCK.json", sources)
    dump_json(OUT / "EDITOR008_DIAGNOSTIC_TO_DESIGN_FIREWALL.json", firewall)
    dump_json(OUT / "EDITOR008_ARCHITECTURE_ROLE.json", architecture)
    dump_json(OUT / "EDITOR008_PREPROCESSING_SPEC.json", preprocess)
    dump_json(OUT / "EDITOR008_METHOD_SPECIFICATION.json", method)
    dump_json(OUT / "EDITOR008_SOURCE_ONLY_SELECTION_RULES.json", selection)
    dump_json(OUT / "EDITOR008_DECISION_PORTABILITY_SPEC.json", decision)
    dump_json(OUT / "EDITOR008_SHIFT_DETECTION_SPEC.json", shift)
    dump_json(OUT / "EDITOR008_TEACHER_ANCHORING_ROLE.json", teacher)
    dump_json(OUT / "EDITOR008_METRIC_AND_STATISTICS_SPEC.json", stats)
    dump_json(OUT / "EDITOR008_NO_TARGET_TUNING_CONTRACT.json", no_tune)
    dump_json(OUT / "EDITOR008_SUCCESS_FAILURE_GATES.json", gates)
    dump_json(OUT / "EDITOR008_EXECUTION_SEQUENCE.json", execution)
    dump_json(OUT / "EDITOR008_CONTRIBUTION_LOCK.json", contribution)

    ablation_rows = [
        {
            "rung": "A0",
            "parent": "",
            "only_change": "single-source ERM neural reference",
            "description": "single-source ERM neural reference",
            "scores_or_predictions_change": "YES",
            "ladder": "CORE_PREDICTIVE",
        },
        {
            "rung": "A1",
            "parent": "A0",
            "only_change": "source composition",
            "description": "A0 + multi-source training",
            "scores_or_predictions_change": "YES",
            "ladder": "CORE_PREDICTIVE",
        },
        {
            "rung": "A2",
            "parent": "A1",
            "only_change": "source-risk optimisation",
            "description": "A1 + GroupDRO",
            "scores_or_predictions_change": "YES",
            "ladder": "CORE_PREDICTIVE",
        },
        {
            "rung": "A3",
            "parent": "A2",
            "only_change": "representation alignment",
            "description": "A2 + CORAL",
            "scores_or_predictions_change": "YES",
            "ladder": "CORE_PREDICTIVE",
        },
        {
            "rung": "A4",
            "parent": "A3",
            "only_change": "decision rule",
            "description": "A3 + portable decision policy",
            "scores_or_predictions_change": "NO_MODEL_SCORES_CHECKPOINT_UNCHANGED_FROM_A3",
            "ladder": "CORE_PREDICTIVE",
        },
        {
            "rung": "A5",
            "parent": "A4",
            "only_change": "diagnostic reporting",
            "description": "A4 + shift diagnostic",
            "scores_or_predictions_change": "NO_PREDICTIONS_UNCHANGED",
            "ladder": "CORE_PREDICTIVE",
        },
        {
            "rung": "H0",
            "parent": "matched source-training regime after portability protocol freeze",
            "only_change": "head = attention-linear",
            "description": "attention-linear head",
            "scores_or_predictions_change": "YES_SEPARATE_FROM_PORTABILITY_LADDER",
            "ladder": "HEAD_COMPARISON",
        },
        {
            "rung": "H1",
            "parent": "matched source-training regime after portability protocol freeze",
            "only_change": "head = ODST",
            "description": "ODST head; not required to outperform attention-linear predictively",
            "scores_or_predictions_change": "YES_SEPARATE_FROM_PORTABILITY_LADDER",
            "ladder": "HEAD_COMPARISON",
        },
        {
            "rung": "T0",
            "parent": "matched ODST branch",
            "only_change": "teacher/reference ODST",
            "description": "teacher/reference ODST",
            "scores_or_predictions_change": "ORTHOGONAL",
            "ladder": "TEACHER_ANCHORING_ORTHOGONAL",
        },
        {
            "rung": "T1",
            "parent": "T0",
            "only_change": "teacher-initialisation-only student",
            "description": "teacher-initialisation-only student",
            "scores_or_predictions_change": "ORTHOGONAL",
            "ladder": "TEACHER_ANCHORING_ORTHOGONAL",
        },
        {
            "rung": "T2",
            "parent": "T1",
            "only_change": "teacher-relative anchoring regularisation",
            "description": "T1 + teacher anchoring",
            "scores_or_predictions_change": "ORTHOGONAL",
            "ladder": "TEACHER_ANCHORING_ORTHOGONAL",
        },
    ]
    fields = ["rung", "parent", "only_change", "description", "scores_or_predictions_change", "ladder"]
    with (OUT / "EDITOR008_ABLATION_MATRIX.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(ablation_rows)

    protocol_md = f"""# EDITOR-008 Source-Robust Portability Protocol

PROTOCOL FREEZE ONLY. No Generation-2 training or predictive inference is authorised.

Claude ruling incorporated: `CLAUDE_EDITOR008_AUDIT_PASS_WITH_REQUIRED_REVISIONS`.

Target-lock commit (must precede this method freeze): `{COMMIT_008A}`

## Prospective target status

`PROSPECTIVE_FINAL_TARGET_CLAIM = NOT_AVAILABLE`

No eligible untouched CERT release was locked in EDITOR-008A. This method freeze is a
**retrospective source-domain / leave-one-version-out portability protocol**.
It does not authorise a prospective untouched-target claim.

## Cross-release limitation

CERT releases belong to the same synthetic benchmark lineage. The Generation-2 experiment
evaluates cross-release transfer within that benchmark family. It does not establish
cross-organisation, cross-population, or real-world external generalisation.

An “untouched target” means `UNOBSERVED_BY_THIS_RESEARCH_PROGRAM_BEFORE_PROSPECTIVE_LOCK`.
It does not mean an independently sampled real-world population.

## Contribution

A prospectively controlled source-robust portability framework for explainable insider-threat
detection, combining version-as-domain multi-source development, domain-robust optimisation,
source-only representation alignment, prevalence-robust portable decision policies,
source-frozen shift diagnosis, and dependence-aware cross-release evaluation.

This is **not** a new Bi-LSTM architecture, **not** an optimizer novelty claim, **not**
evidence that teacher anchoring improves prediction, **not** cross-population generalisation,
**not** real-world deployment validation, and **not** adversarial robustness.

Inherited pathway (fixed): 20-day sequence → Bi-LSTM → temporal attention → predictive head.

## Source domains

- CERT r4.2
- CERT r5.2 TRAIN/VALIDATION only (`R52_TEST = PROHIBITED`)
- CERT r5.1 = `GENERATION2_SOURCE_DEVELOPMENT_DOMAIN` + `PREVIOUSLY_OBSERVED_DIAGNOSTICALLY`
- CERT r6.2 = `GENERATION2_SOURCE_DEVELOPMENT_DOMAIN` + `PREVIOUSLY_OBSERVED_DIAGNOSTICALLY`

`VERSION = DOMAIN`. Weighting is domain-balanced, not sample-balanced. r6.2 is one LOVO
domain only. No r6.2-specific fold, objective, feature remedy, or selection weight.

## Method family

MULTI_SOURCE_DOMAIN_BALANCED_TRAINING + GROUPDRO_STYLE_SOURCE_RISK_OPTIMISATION +
SOURCE_ONLY_CORAL_REPRESENTATION_ALIGNMENT.

GroupDRO and CORAL remain separately ablatable. No target-alignment loss.

## Selection

LEAVE_ONE_SOURCE_VERSION_OUT. Primary metric PR-AUC with prevalence reported beside it.

PRIMARY = best worst held-out-domain PR-AUC rank, then mean rank, then equal-domain mean
PR-AUC, then simpler configuration. Worst-source F1 is **not** the primary threshold rule.

## Decision portability

Operating-point values remain `UNRESOLVED_PENDING_PRETRAINING_NUMERIC_FREEZE`.
Historical r5.2 alert budgets `(0.0005, 0.001, 0.0025, 0.005, 0.01)` are cited but **not**
adopted as Generation-2 numbers. EDITOR-006A F1 thresholds are a descriptive legacy
reference only. `TRAINING_AUTHORISED = NO` until an independently audited source-only
numeric freeze.

## Shift detection

Mandatory diagnostic. Primary: MMD on common-13 features. Secondary: MMD on attended
representations. Detector does not alter predictions. Abstention/OOD is optional;
ungated full-coverage results remain mandatory.

## Ablations

One change per step: A0 ERM → A1 multi-source → A2 GroupDRO → A3 CORAL → A4 portable
decision (scores unchanged) → A5 shift diagnostic (predictions unchanged). Head comparison
and teacher-anchoring are orthogonal.

Teacher anchoring remains `AUXILIARY_FIDELITY_REGULARISER`. r5.2 C2 vs `C5_original_paper`
mechanism evidence remains `UNRESOLVED`.

## Training

**No training is authorised by EDITOR-008.**
"""
    (OUT / "EDITOR008_PROTOCOL.md").write_text(protocol_md, encoding="utf-8")

    handover = f"""# EDITOR-008 Independent Audit Handover

Independent review is required before implementation or training.

## Claude ruling incorporated

`CLAUDE_EDITOR008_AUDIT_PASS_WITH_REQUIRED_REVISIONS` = YES

All required revisions from that audit are incorporated in this freeze, including:
prevalence-robust decision policies instead of worst-source F1; explicit cross-release
limitation; diagnostic-to-design firewall; one-change-per-step ablation; teacher anchoring
as auxiliary only; and Phase-A target lock before method specification.

## Target-lock commit

`EDITOR008_TARGET_LOCK_COMMIT = {COMMIT_008A}`

`TARGET_LOCK_PRECEDES_METHOD_FREEZE = YES`

## Complete release inventory

See `00_target_lock/EDITOR008_UNTOUCHED_TARGET_INVENTORY.json`.

Discovered: r2, r3.1, r3.2, r4.1, r4.2, r5.1, r5.2 TRAIN/VALIDATION, r5.2 TEST, r6.1, r6.2.

## All eligible final targets

`ELIGIBLE_UNTOUCHED_TARGETS = []`

`FINAL_UNTOUCHED_TARGETS = []`

`FINAL_TARGET_COUNT = 0`

`FINAL_TARGET_SELECTION_RULE = NO_PROSPECTIVE_TARGET_AVAILABLE`

`PROSPECTIVE_FINAL_TARGET_CLAIM = NOT_AVAILABLE`

## Source-domain roles

CERT r4.2, CERT r5.2 TRAIN/VALIDATION, CERT r5.1, CERT r6.2 are Generation-2 source
development domains. r5.1 and r6.2 are previously observed diagnostically and cannot be
presented as prospective untouched targets. r5.2 TEST is PROHIBITED.

## Cross-release limitation

CERT releases belong to the same synthetic benchmark lineage. Cross-release transfer
within that family is not cross-organisation, cross-population, or real-world
external generalisation.

## Diagnostic-to-design firewall

r62-specific feature targeting, email_count / has_file_activity / total_events remedies,
r62-specific thresholds, hyperparameters, and selection weights are PROHIBITED.

## Inherited architecture status

BiLSTM-attention is inherited, not a new contribution. ODST is an explanation-oriented
differentiable head. Attention-linear is the primary neural efficiency/calibration reference.

## GroupDRO role

Control worst-source/domain risk. Initial weights symmetric. Sample count does not set
domain importance. Natural worst-source emphasis permitted; r6.2-designed domination prohibited.

## CORAL role

Reduce source-domain representation covariance discrepancy. Source-only. Preferred location:
attended representation. No target-alignment loss.

## LOVO design

For every source release d: train on all other source domains; hold out d as development
evidence only.

## Domain-balanced selection rule

PRIMARY = best worst held-out-domain PR-AUC rank; then mean rank; then equal-domain mean
PR-AUC; then simpler configuration. Pooled window count and r62-specific priority prohibited.

## Portable decision policies

Preferred: fixed alert budget, then fixed-FPR source-frozen threshold, then legacy F1 as
descriptive reference only. Worst-source F1 primary threshold = REMOVED.

## Numeric operating-point status

`DECISION_OPERATING_POINT_VALUES = UNRESOLVED_PENDING_PRETRAINING_NUMERIC_FREEZE`

Historical r5.2 budgets cited, not adopted. `TRAINING_AUTHORISED = NO`.

## MMD shift detector

Primary RAW common-13 MMD; secondary attended-representation MMD; source-only RBF median
heuristic; envelope = max inter-source MMD unless another source-only envelope is justified
before training. Detector does not alter predictions.

## Ablation ladder

A0→A1→A2→A3→A4→A5, one change per step. A4 does not change model scores. A5 does not change
predictions. Heads and teacher anchoring are orthogonal.

## Teacher anchoring role

`AUXILIARY_FIDELITY_REGULARISER`. T0/T1/T2 on matched ODST. Initialisation-only control
required. r5.2 C2 vs C5_original_paper mechanism remains UNRESOLVED.

## Mandatory baselines

SINGLE_SOURCE_NEURAL_ERM, MULTI_SOURCE_NEURAL_ERM, ATTENTION_LINEAR, ODST, RF, XGBOOST.

## Statistical dependence protocol

Overlapping windows are correlated observations. Seeds are reproducibility repetitions.
User-cluster-aware (and incident-cluster-aware where reliable) resampling. Tiny cluster
counts must be reported; otherwise inferential claims are not supported.

## Explainability-under-shift protocol

Secondary prospective analysis. Reference-centred top-k vs random intervention faithfulness
with source/training centring. Routes/leaves independently faithful = UNSUPPORTED.
Adversarial robustness = UNSUPPORTED.

## No-target-tuning contract

All target label, feature-distribution, score-distribution, threshold, scaler, calibration,
hyperparameter, and model-selection uses before final freeze are PROHIBITED. Target failure
cannot trigger rescue training.

## Unresolved parameters

Generation-2 alert-budget rate; fixed-FPR anchor; GroupDRO numeric hyperparameters; CORAL
penalty weight; optional abstention threshold. All `REQUIRES_PRETRAINING_NUMERIC_FREEZE`.

## Success/failure gates

RANKING_PORTABILITY, DECISION_PORTABILITY, SHIFT_DIAGNOSIS, TEACHER_FIDELITY,
PREDICTIVE_SUPERIORITY, and EXPLAINABILITY remain separate findings.

## Independent review request

This packet authorises **independent audit of the EDITOR-008 protocol only**.
It does **not** authorise implementation execution, training, inference, numeric operating-point
adoption, or Generation-2 result generation.
"""
    (OUT / "EDITOR008_INDEPENDENT_AUDIT_HANDOVER.md").write_text(handover, encoding="utf-8")

    checksum_paths = [
        rec(LOCK_DIR / "EDITOR008_FINAL_TARGET_LOCK.json", "phase_a_lock"),
        rec(LOCK_DIR / "EDITOR008_UNTOUCHED_TARGET_INVENTORY.json", "phase_a_inventory"),
        rec(LOCK_DIR / "EDITOR008_TARGET_LOCK_MANIFEST.json", "phase_a_manifest"),
        rec(ROOT / "review" / "editor007d1_freeze_compliance" / "EDITOR007D1_PORTABILITY_PHENOTYPE.json", "d1_phenotype"),
        rec(ROOT / "review" / "editor007d1_freeze_compliance" / "EDITOR007D1_EDITOR008_RELEASE_GATE.json", "d1_gate"),
        rec(ROOT / "review" / "editor007d1_freeze_compliance" / "EDITOR007D1_R52_C2_C5_MECHANISM_EVIDENCE.json", "unresolved_r52_mechanism"),
        rec(ROOT / "review" / "editor006a_preinference_freeze" / "EDITOR006A_THRESHOLDS.json", "legacy_f1_thresholds"),
        rec(ROOT / "src" / "objective2_r52_calibration_alert_burden" / "constants.py", "historical_r52_alert_budget_constants"),
        rec(
            Path(
                r"C:\PhD\07_Projects\cert-r52-calibration-alert-burden\scripts"
                r"\objective2_r52_calibration_alert_burden\recorded_results\calibration_alert_config.json"
            ),
            "historical_r52_alert_budget_recorded_config",
        ),
        rec(ROOT / "src" / "dataset_registry.py", "dataset_registry"),
        rec(ROOT / "manifests" / "experiment_registry.csv", "experiment_registry"),
    ]
    dump_json(
        OUT / "EDITOR008_INPUT_CHECKSUMS.json",
        {"task_id": "EDITOR-008B", "n_artefacts": len(checksum_paths), "artefacts": checksum_paths},
    )

    consistency = {
        "historical_editor007d_files_modified": False,
        "historical_editor007d1_files_modified": False,
        "r52_test_accessed": False,
        "r51_rerun": False,
        "r62_rerun": False,
        "new_model_training": False,
        "new_predictive_inference": False,
        "candidate_target_labels_inspected": False,
        "candidate_target_feature_distributions_inspected": False,
        "candidate_target_scores_inspected": False,
        "target_scaler_fit": False,
        "target_calibration_fit": False,
        "target_threshold_tuning": False,
        "target_model_selection": False,
        "all_eligible_targets_locked_or_no_target_fallback_declared": True,
        "target_lock_committed_before_method_protocol": True,
        "worst_source_f1_primary_threshold_rule": "REMOVED",
        "ablation_ladder_one_change_per_step": True,
        "r52_c2_c5_mechanism_unresolved_preserved": True,
        "teacher_anchoring_auxiliary_only": True,
        "cross_release_limitation_explicit": True,
        "executable_training_code_written": False,
    }
    manifest = {
        "task_id": "EDITOR-008B",
        "branch": branch,
        "HEAD": head,
        "EDITOR008_TARGET_LOCK_COMMIT": COMMIT_008A,
        "controlling_editor007d1_commit": COMMIT_D1,
        "PROSPECTIVE_FINAL_TARGET_CLAIM": "NOT_AVAILABLE",
        "TRAINING_AUTHORISED": "NO",
        "INDEPENDENT_AUDIT_REQUIRED": "YES",
        "leftovers": D1_LEFTOVERS,
        "timestamp_utc": utc_now(),
        "consistency": consistency,
        "unresolved_pretraining_numeric_items": [u["parameter"] for u in unresolved_numeric],
        "files_created": sorted(p.name for p in OUT.iterdir() if p.is_file()),
    }
    dump_json(OUT / "EDITOR008_RUN_MANIFEST.json", manifest)
    print("008B_OK", head)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
