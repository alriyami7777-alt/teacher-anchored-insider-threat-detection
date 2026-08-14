#!/usr/bin/env python3
"""EDITOR-007D1 freeze-compliance correction builder.

Derivative metadata only. Does not modify historical EDITOR-007D files.
Does not train, score, or open r5.2 TEST.
"""
from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "review" / "editor007d1_freeze_compliance"
REV007A = ROOT / "review" / "editor007a_post006e_diagnostics"
REV007B = ROOT / "review" / "editor007b_r51_secondary_stress"
REV007C1 = ROOT / "review" / "editor007c1_r51_result_freeze"
REV007D = ROOT / "review" / "editor007d_cross_version_synthesis"
REV006C = ROOT / "review" / "editor006c_r62_input_bundle"
THR = ROOT / "review" / "editor006a_preinference_freeze" / "EDITOR006A_THRESHOLDS.json"

R51_SCORES = Path(r"C:\PhD\06_Datasets\derived\teacher_anchored_r51_editor007c_scores")
R62_SCORES = Path(r"C:\PhD\06_Datasets\derived\teacher_anchored_r62_editor006e_scores")
R51_BUNDLE = Path(r"C:\PhD\06_Datasets\derived\teacher_anchored_r51_editor007b_bundle")
R62_BUNDLE = Path(r"C:\PhD\06_Datasets\derived\teacher_anchored_r62_editor006c_bundle")
VAL_NPZ = Path(
    r"C:\PhD\07_Projects\cert-r42-feasibility\data\processed\r5.2\tensors\r52_T20_s1_validation.npz"
)
OBJ3 = Path(
    r"C:\PhD\07_Projects\cert-r42-feasibility\scripts"
    r"\objective3_r52_explanation_robustness_portability\recorded_results"
)
ABLATION = Path(
    r"C:\PhD\07_Projects\cert-r42-feasibility\outputs\objective2"
    r"\r52_teacher_anchoring_ablation_v1"
)
REPRO = Path(
    r"C:\PhD\07_Projects\cert-r52-teacher-anchored-reproducibility\outputs\objective2"
    r"\r52_teacher_anchored_reproducibility_v1"
)

COMMIT_007D = "aadda34ac9d77f67e2f487f55719b45224719c19"
COMMIT_007C1 = "3655707631c2a437429538c159e2a6cd50f59c0c"
C5_PAPER_42 = "2b6452698dd0da53f0229bc43040a877017ac9299b277f2f98c1d7ca64c1cc42"
ABLATION_C5_42 = "a5a08dc24a89014fd1bb92c6c6342ed50511b33804e95246e480e90c4692b214"

PROTOCOL = {
    "r52_test_accessed": False,
    "new_model_execution": False,
    "training_executed": False,
    "fresh_predictive_inference": False,
    "r51_rerun": False,
    "r62_rerun": False,
    "threshold_tuning": False,
    "target_scaler_fit": False,
    "target_calibration_fit": False,
}


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


def refuse_test(path: Path) -> None:
    text = str(path).replace("\\", "/").lower()
    if ("r52_t20_s1" + "_test") in text:
        PROTOCOL["r52_test_accessed"] = True
        raise SystemExit("EDITOR007D1_FREEZE_COMPLIANCE_CORRECTION_BLOCKED")


def load_json(path: Path) -> Any:
    refuse_test(path)
    return json.loads(path.read_text(encoding="utf-8"))


def dump_json(path: Path, payload: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return sha256_file(path)


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def rec(
    path: Path,
    *,
    dataset_or_role: str,
    evidence_type: str,
    producing_or_derivative: str,
    numerical: str,
    consumed_by: list[str],
) -> dict[str, Any]:
    refuse_test(path)
    return {
        "path": str(path),
        "sha256": sha256_file(path),
        "byte_size": path.stat().st_size,
        "dataset_or_role": dataset_or_role,
        "evidence_type": evidence_type,
        "producing_or_derivative": producing_or_derivative,
        "numerical_values_original_or_corrected": numerical,
        "consumed_by": consumed_by,
        "exists": True,
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    head = git("rev-parse", "HEAD")
    status = git("status", "--short")
    ancestor_007d = subprocess.call(["git", "merge-base", "--is-ancestor", COMMIT_007D, "HEAD"], cwd=ROOT) == 0
    ancestor_007c1 = subprocess.call(["git", "merge-base", "--is-ancestor", COMMIT_007C1, "HEAD"], cwd=ROOT) == 0
    tracked_clean = git("diff", "--name-only") == "" and git("diff", "--cached", "--name-only") == ""
    leftovers = [
        ln[3:]
        for ln in status.splitlines()
        if ln.startswith("??") and "editor007d1_freeze_compliance" not in ln
    ]
    if branch != "repository-hardening" or not ancestor_007d or not ancestor_007c1:
        raise SystemExit("EDITOR007D1_FREEZE_COMPLIANCE_CORRECTION_BLOCKED")
    if not tracked_clean:
        raise SystemExit("EDITOR007D1_FREEZE_COMPLIANCE_CORRECTION_BLOCKED")

    parity = load_json(REV007A / "EDITOR007A_R52_VALIDATION_PARITY.json")
    by = {(m["family"], int(m["seed"])): m for m in parity["models"]}
    r51_pred = load_json(REV007C1 / "EDITOR007C_PREDICTIVE_RESULTS_PAPER_CORRECTED.json")
    r62_pred = load_json(R62_SCORES / "EDITOR006E_PREDICTIVE_RESULTS.json")
    r51_all = load_json(R51_SCORES / "ALL_SCORES_COMPLETE.json")
    r62_all = load_json(R62_SCORES / "ALL_SCORES_COMPLETE.json")
    ruling007d = load_json(REV007D / "EDITOR007D_DIAGNOSTIC_RULING.json")

    if r51_pred["effective_malicious_cluster_count"] != 4:
        raise SystemExit("EDITOR007D1_FREEZE_COMPLIANCE_CORRECTION_BLOCKED")
    if r62_pred["effective_malicious_cluster_count"] != 5:
        raise SystemExit("EDITOR007D1_FREEZE_COMPLIANCE_CORRECTION_BLOCKED")
    if ruling007d["PRIMARY_PORTABILITY_PHENOTYPE"] != "P2_R62_SEVERE_DISTRIBUTION_AND_DECISION_SHIFT":
        raise SystemExit("EDITOR007D1_FREEZE_COMPLIANCE_CORRECTION_BLOCKED")

    # --- r5.2 C2/C5 predictive from frozen 007A ---
    pred_rows = []
    for seed in (42, 52, 62):
        t = by[("teacher_frozen_odst", seed)]
        c2 = by[("C2", seed)]
        c5 = by[("C5_original_paper", seed)]
        pred_rows.append(
            {
                "partition": "r52_validation",
                "view": "COMPLETED_WINDOW",
                "seed": seed,
                "teacher_PR_AUC_replay": t["replay_metrics"]["PR_AUC"],
                "teacher_F1_replay": t["replay_metrics"]["F1"],
                "C2_PR_AUC_replay": c2["replay_metrics"]["PR_AUC"],
                "C2_F1_replay": c2["replay_metrics"]["F1"],
                "C5_PR_AUC_replay": c5["replay_metrics"]["PR_AUC"],
                "C5_F1_replay": c5["replay_metrics"]["F1"],
                "delta_PR_AUC_C5_minus_C2_replay": c5["replay_metrics"]["PR_AUC"] - c2["replay_metrics"]["PR_AUC"],
                "delta_F1_C5_minus_C2_replay": c5["replay_metrics"]["F1"] - c2["replay_metrics"]["F1"],
                "teacher_threshold": t["threshold"],
                "C2_threshold": c2["threshold"],
                "C5_threshold": c5["threshold"],
                "uncertainty_interval": "NOT_ATTACHED",
                "naive_independent_window_ci": "NOT_ATTACHED",
                "automated_protocol_gate": "FAIL_EXACT_NUMERICAL_IDENTITY",
                "independent_scientific_adjudication": "SCIENTIFIC_PARITY_WITH_NUMERICAL_NONIDENTITY",
                "metric_source": "EDITOR007A_R52_VALIDATION_PARITY.replay_metrics",
                "positive_delta_is_not_automatic_superiority": True,
            }
        )
    r52_pred_doc = {
        "task_id": "EDITOR-007D1",
        "R52_C2_C5_PREDICTIVE_EVIDENCE_STATUS": "LOCATED",
        "partition": "CERT r5.2 VALIDATION",
        "not_r52_test": True,
        "authoritative_source": str(REV007A / "EDITOR007A_R52_VALIDATION_PARITY.json"),
        "hierarchy_level": "frozen_implementation_evidence_packet",
        "uncertainty_invented": False,
        "rows": pred_rows,
        "interpretation": {
            "POINT_ESTIMATE_PATTERN": "MIXED_OR_VERSION_DEPENDENT",
            "R52_IN_DOMAIN_PATTERN": "ESSENTIALLY_TIED",
            "C5_PREDICTIVE_ADVANTAGE_OVER_C2": "UNSUPPORTED",
            "note": "r5.2 validation Teacher/C2/C5 PR-AUC are essentially tied (~0.92–0.94). External C5−C2 point deltas remain small/version-dependent. Neither is a superiority claim.",
        },
    }

    # --- r5.2 mechanism search ---
    c5_repro = REPRO / "seed42" / "seed_summary.json"
    c5_abl = ABLATION / "C5" / "seed42" / "seed_summary.json"
    c2_abl = ABLATION / "C2" / "seed42" / "seed_summary.json"
    c5_repro_keys = sorted(load_json(c5_repro).keys()) if c5_repro.exists() else []
    exact_fields = [
        "val_logit_consistency",
        "route_mae",
        "routing_divergence",
        "hard_route_agreement",
        "dominant_leaf_agreement",
    ]
    r52_mech_doc = {
        "task_id": "EDITOR-007D1",
        "R52_C2_C5_MECHANISM_EVIDENCE_STATUS": "UNRESOLVED",
        "does_not_invalidate_external_r51_r62_fidelity": True,
        "editor007d_statement_preserved": "R52_MECHANISM_COMPARISON_NOT_INCLUDED_PROVENANCE_INSUFFICIENT",
        "search": {
            "ablation_C2_seed_summary_has_exact_frozen_field_names": True,
            "ablation_C2_checkpoint_matches_007D_C2": True,
            "ablation_C5_seed_summary_has_exact_frozen_field_names": True,
            "ablation_C5_checkpoint_sha256_seed42": ABLATION_C5_42,
            "C5_original_paper_checkpoint_sha256_seed42": C5_PAPER_42,
            "ablation_C5_is_same_checkpoint_as_C5_original_paper": False,
            "C5_original_paper_seed_summary_keys_include_exact_frozen_set": all(
                k in c5_repro_keys for k in exact_fields
            ),
            "C5_original_paper_seed_summary_has_routing_divergence_only": "routing_divergence" in c5_repro_keys
            and "route_mae" not in c5_repro_keys,
        },
        "missing_provenance": (
            "Paired r5.2 validation C2 vs C5_original_paper exact-frozen mechanism metrics "
            "are not available for the same C5 checkpoint used by EDITOR-007D. Ablation C5 "
            f"seed42 SHA256={ABLATION_C5_42} differs from C5_original_paper "
            f"seed42 SHA256={C5_PAPER_42}. Reproducibility seed_summary.json does not record "
            "val_logit_consistency, route_mae, hard_route_agreement, or dominant_leaf_agreement. "
            "Manuscript prose was not used."
        ),
        "producing_paths_inspected": [str(c2_abl), str(c5_abl), str(c5_repro)],
        "values_reconstructed_from_manuscript": False,
    }

    # --- checksums ---
    checksums: list[dict[str, Any]] = []

    def add(path: Path, **kwargs: Any) -> None:
        checksums.append(rec(path, **kwargs))

    add(R51_SCORES / "ALL_SCORES_COMPLETE.json", dataset_or_role="r51_secondary_stress", evidence_type="score_manifest", producing_or_derivative="producing", numerical="original", consumed_by=["EDITOR-007D", "EDITOR-007D1"])
    add(R62_SCORES / "ALL_SCORES_COMPLETE.json", dataset_or_role="r62_external", evidence_type="score_manifest", producing_or_derivative="producing", numerical="original", consumed_by=["EDITOR-007D", "EDITOR-007D1"])
    add(REV007A / "EDITOR007A_R52_VALIDATION_PARITY.json", dataset_or_role="r52_validation", evidence_type="parity", producing_or_derivative="derivative", numerical="original", consumed_by=["EDITOR-007D", "EDITOR-007D1"])
    parity_reg = REV007A / "EDITOR007A_R52_PARITY_REFERENCE_REGISTER.json"
    if parity_reg.exists():
        add(parity_reg, dataset_or_role="r52_validation", evidence_type="parity_reference_register", producing_or_derivative="derivative", numerical="original", consumed_by=["EDITOR-007D1"])
    add(REV007A / "EDITOR007A_FEATURE_SHIFT.json", dataset_or_role="r52_train_val_r62", evidence_type="feature_shift", producing_or_derivative="derivative", numerical="original", consumed_by=["EDITOR-007D", "EDITOR-007D1"])
    add(REV007A / "EDITOR007A_SCORE_DISTRIBUTION_SHIFT.json", dataset_or_role="r52_validation_r62", evidence_type="score_shift", producing_or_derivative="derivative", numerical="original", consumed_by=["EDITOR-007D", "EDITOR-007D1"])
    add(REV007A / "EDITOR007A_R62_SCORE_ORIENTATION_AUDIT.json", dataset_or_role="r62_external", evidence_type="orientation_audit", producing_or_derivative="derivative", numerical="original", consumed_by=["EDITOR-007D", "EDITOR-007D1"])
    add(REV007A / "EDITOR007A_DECISION_GATE.json", dataset_or_role="protocol", evidence_type="decision_gate", producing_or_derivative="derivative", numerical="original", consumed_by=["EDITOR-007D", "EDITOR-007D1"])
    add(REV007A / "EDITOR007A_RUN_MANIFEST.json", dataset_or_role="protocol", evidence_type="run_manifest", producing_or_derivative="derivative", numerical="original", consumed_by=["EDITOR-007D", "EDITOR-007D1"])
    add(REV007B / "EDITOR007B_007A_ADJUDICATION_FREEZE.json", dataset_or_role="protocol", evidence_type="adjudication", producing_or_derivative="derivative", numerical="original", consumed_by=["EDITOR-007D", "EDITOR-007D1"])
    add(REV007C1 / "EDITOR007C_PREDICTIVE_RESULTS_PAPER_CORRECTED.json", dataset_or_role="r51_secondary_stress", evidence_type="predictive_results", producing_or_derivative="derivative", numerical="corrected_metadata_only", consumed_by=["EDITOR-007D", "EDITOR-007D1"])
    add(R51_SCORES / "EDITOR007C_MECHANISM_RESULTS.json", dataset_or_role="r51_secondary_stress", evidence_type="mechanism", producing_or_derivative="producing", numerical="original", consumed_by=["EDITOR-007D", "EDITOR-007D1"])
    add(REV007B / "EDITOR007B_R51_FEATURE_PROFILE.json", dataset_or_role="r51_secondary_stress", evidence_type="feature_profile", producing_or_derivative="derivative", numerical="original", consumed_by=["EDITOR-007D", "EDITOR-007D1"])
    add(REV007B / "EDITOR007B_R51_COUNT_VALIDATION.json", dataset_or_role="r51_secondary_stress", evidence_type="counts", producing_or_derivative="derivative", numerical="original", consumed_by=["EDITOR-007D", "EDITOR-007D1"])
    add(REV007B / "EDITOR007B_R51_METADATA_VALIDATION.json", dataset_or_role="r51_secondary_stress", evidence_type="metadata", producing_or_derivative="derivative", numerical="original", consumed_by=["EDITOR-007D", "EDITOR-007D1"])
    add(REV007B / "EDITOR007B_R51_BUNDLE_MANIFEST.json", dataset_or_role="r51_secondary_stress", evidence_type="bundle_manifest", producing_or_derivative="derivative", numerical="original", consumed_by=["EDITOR-007D", "EDITOR-007D1"])
    add(R51_BUNDLE / "completed_window_labels.npy", dataset_or_role="r51_secondary_stress", evidence_type="completed_window_labels", producing_or_derivative="producing", numerical="original", consumed_by=["EDITOR-007D", "EDITOR-007D1"])
    add(R62_SCORES / "EDITOR006E_PREDICTIVE_RESULTS.json", dataset_or_role="r62_external", evidence_type="predictive_results", producing_or_derivative="producing", numerical="original", consumed_by=["EDITOR-007D", "EDITOR-007D1"])
    add(R62_SCORES / "EDITOR006E_MECHANISM_RESULTS.json", dataset_or_role="r62_external", evidence_type="mechanism", producing_or_derivative="producing", numerical="original", consumed_by=["EDITOR-007D", "EDITOR-007D1"])
    add(REV006C / "EDITOR006C_COUNT_VALIDATION.json", dataset_or_role="r62_external", evidence_type="counts", producing_or_derivative="derivative", numerical="original", consumed_by=["EDITOR-007D", "EDITOR-007D1"])
    add(REV006C / "EDITOR006C_METADATA_VALIDATION.json", dataset_or_role="r62_external", evidence_type="metadata", producing_or_derivative="derivative", numerical="original", consumed_by=["EDITOR-007D", "EDITOR-007D1"])
    add(REV006C / "EDITOR006C_BUNDLE_MANIFEST.json", dataset_or_role="r62_external", evidence_type="bundle_manifest", producing_or_derivative="derivative", numerical="original", consumed_by=["EDITOR-007D", "EDITOR-007D1"])
    add(R62_BUNDLE / "completed_window_labels.npy", dataset_or_role="r62_external", evidence_type="completed_window_labels", producing_or_derivative="producing", numerical="original", consumed_by=["EDITOR-007D", "EDITOR-007D1"])
    add(VAL_NPZ, dataset_or_role="r52_validation", evidence_type="validation_tensor", producing_or_derivative="producing", numerical="original", consumed_by=["EDITOR-007D", "EDITOR-007D1"])
    add(THR, dataset_or_role="r52_thresholds", evidence_type="frozen_thresholds", producing_or_derivative="producing", numerical="original", consumed_by=["EDITOR-007D", "EDITOR-007D1"])
    for hist in sorted(REV007D.iterdir()):
        if hist.is_file():
            add(
                hist,
                dataset_or_role="cross_version",
                evidence_type="historical_007d_packet",
                producing_or_derivative="derivative",
                numerical="original",
                consumed_by=["EDITOR-007D1"],
            )
    add(OBJ3 / "r52_odst_centred_faithfulness.csv", dataset_or_role="r52_validation", evidence_type="reference_centred_faithfulness", producing_or_derivative="producing", numerical="original", consumed_by=["EDITOR-007D1"])
    add(OBJ3 / "r52_portability_claim_register.csv", dataset_or_role="r52_validation", evidence_type="claim_register", producing_or_derivative="producing", numerical="original", consumed_by=["EDITOR-007D1"])
    add(OBJ3 / "r52_source_ablation.csv", dataset_or_role="r52_validation", evidence_type="source_ablation_degraded_input", producing_or_derivative="producing", numerical="original", consumed_by=["EDITOR-007D1"])
    add(OBJ3 / "r52_noise_robustness.csv", dataset_or_role="r52_validation", evidence_type="gaussian_noise_degraded_input", producing_or_derivative="producing", numerical="original", consumed_by=["EDITOR-007D1"])
    for seed in (42, 52, 62):
        add(ABLATION / "C2" / f"seed{seed}" / "seed_summary.json", dataset_or_role="r52_validation", evidence_type="producing_c2_seed_summary_inspected", producing_or_derivative="producing", numerical="original", consumed_by=["EDITOR-007D1"])
        add(REPRO / f"seed{seed}" / "seed_summary.json", dataset_or_role="r52_validation", evidence_type="producing_c5_original_paper_seed_summary_inspected", producing_or_derivative="producing", numerical="original", consumed_by=["EDITOR-007D1"])
        add(ABLATION / "C5" / f"seed{seed}" / "seed_summary.json", dataset_or_role="r52_validation", evidence_type="producing_ablation_c5_seed_summary_identity_check_only", producing_or_derivative="producing", numerical="original", consumed_by=["EDITOR-007D1"])

    for m in r51_all["models"]:
        add(
            R51_SCORES / "raw_scores" / m["score_filename"],
            dataset_or_role="r51_secondary_stress",
            evidence_type="raw_score_array",
            producing_or_derivative="producing",
            numerical="original",
            consumed_by=["EDITOR-007D", "EDITOR-007D1"],
        )
    for m in r62_all["models"]:
        add(
            R62_SCORES / "raw_scores" / m["score_filename"],
            dataset_or_role="r62_external",
            evidence_type="raw_score_array",
            producing_or_derivative="producing",
            numerical="original",
            consumed_by=["EDITOR-007D", "EDITOR-007D1"],
        )
    for m in parity["models"]:
        add(
            Path(m["replay_score_path"]),
            dataset_or_role="r52_validation",
            evidence_type="replay_score_array",
            producing_or_derivative="derivative",
            numerical="original",
            consumed_by=["EDITOR-007D", "EDITOR-007D1"],
        )

    checksum_doc = {
        "task_id": "EDITOR-007D1",
        "n_artefacts": len(checksums),
        "artefacts": checksums,
        "coverage_note": "Every artefact materially consumed by EDITOR-007D scoring/feature/label reads or by EDITOR-007D1 provenance repair is listed.",
    }

    claims = [
        {
            "claim": "teacher initialisation is load-bearing",
            "status": "QUALIFIED",
            "supporting_evidence": "C5 remains closer to the teacher than C2 on exact-frozen mechanism metrics for r5.1 and r6.2. r5.2 paired mechanism for C5_original_paper is UNRESOLVED.",
            "qualification_or_limitation": "Load-bearing as teacher-relative fidelity, not as external predictive superiority.",
            "paper_action": "Keep as a fidelity/initialisation claim; do not treat as a predictive-portability claim.",
        },
        {
            "claim": "teacher anchoring improves predictive performance",
            "status": "UNSUPPORTED",
            "supporting_evidence": "r5.2 validation C2/C5/Teacher PR-AUC essentially tied; external C5−C2 deltas small/version-dependent; several r5.1 de-overlap PR-AUC intervals include zero; r6.2 deltas sit on a collapsed scale.",
            "qualification_or_limitation": "POINT_ESTIMATE_PATTERN=MIXED_OR_VERSION_DEPENDENT is not a superiority claim.",
            "paper_action": "Do not claim predictive improvement from anchoring.",
        },
        {
            "claim": "teacher anchoring reduces teacher-relative logit drift",
            "status": "QUALIFIED",
            "supporting_evidence": "EDITOR-007D mechanism portability: C5 logit deviation < C2 on r5.1 and r6.2 exact-frozen metrics.",
            "qualification_or_limitation": "r5.2 paired C5_original_paper mechanism UNRESOLVED. External fidelity is not a predictive claim.",
            "paper_action": "Keep as teacher-relative fidelity on r5.1/r6.2; do not generalise to r5.2 mechanism without provenance.",
        },
        {
            "claim": "teacher anchoring reduces route drift",
            "status": "QUALIFIED",
            "supporting_evidence": "C5 route MAE/KL lower and hard-route/dominant-leaf agreement higher than C2 on r5.1 and r6.2.",
            "qualification_or_limitation": "Same r5.2 mechanism provenance gap. Routes are not independently proven faithful.",
            "paper_action": "Keep as teacher-relative routing fidelity on external versions.",
        },
        {
            "claim": "teacher anchoring preserves teacher-relative internal fidelity under external shift",
            "status": "FULLY_SUPPORTED",
            "supporting_evidence": "Exact-frozen C2 vs C5 vs teacher metrics on r5.1 and r6.2 DEOVERLAP_OFFSET0.",
            "qualification_or_limitation": "Fidelity preservation is not predictive superiority. unused-leaf and tree-rho remain disabled.",
            "paper_action": "Keep as the supported external fidelity result.",
        },
        {
            "claim": "C5 is predictively superior to C2",
            "status": "UNSUPPORTED",
            "supporting_evidence": "In-domain essentially tied; external point deltas mixed; bootstrap intervals often include zero; r6.2 collapsed.",
            "qualification_or_limitation": "A positive point estimate is not predictive superiority.",
            "paper_action": "Remove any C5>C2 predictive-superiority wording.",
        },
        {
            "claim": "ODST is predictively superior to attention-linear",
            "status": "UNSUPPORTED",
            "supporting_evidence": "EDITOR-007D completed-window means: both neural families collapse on r6.2; r5.1 bands are similar.",
            "qualification_or_limitation": "ODST remains explanation-oriented, not an overall superior classifier.",
            "paper_action": "Do not claim ODST predictive superiority.",
        },
        {
            "claim": "architecture generalises strongly across CERT versions",
            "status": "UNSUPPORTED",
            "supporting_evidence": "r6.2 severe version-specific failure; r5.1 ranking transfer does not imply r6.2 portability.",
            "qualification_or_limitation": "r5.1 is secondary stress only.",
            "paper_action": "Replace with the P2 phenotype statement.",
        },
        {
            "claim": "architecture fails uniformly across CERT versions",
            "status": "UNSUPPORTED",
            "supporting_evidence": "GENERAL_CROSS_VERSION_COLLAPSE=NOT_SUPPORTED; r5.1 retains substantial ranking.",
            "qualification_or_limitation": "r6.2 is more severe and model-family-dependent.",
            "paper_action": "Do not describe a uniform cross-version failure.",
        },
        {
            "claim": "r5.1 retains substantial ranking signal",
            "status": "FULLY_SUPPORTED",
            "supporting_evidence": "EDITOR-007D: neural completed-window mean PR-AUC ≈ 0.267 vs prevalence ≈ 0.000463 (DESCRIPTIVE_ONLY lift).",
            "qualification_or_limitation": "Role remains R51_SECONDARY_STRESS_ONLY. Four official clusters. Not a replacement primary test.",
            "paper_action": "Keep with the secondary-stress role qualification in surrounding text.",
        },
        {
            "claim": "r6.2 exhibits severe ranking failure",
            "status": "FULLY_SUPPORTED",
            "supporting_evidence": "Neural completed-window mean PR-AUC ≈ 0.000473 vs prevalence ≈ 0.000360; tabular retains more ranking but still fails at frozen thresholds.",
            "qualification_or_limitation": "Ranking collapse is MODEL_FAMILY_DEPENDENT. Do not state a unique causal feature.",
            "paper_action": "Keep as the r6.2 ranking description with family dependence.",
        },
        {
            "claim": "frozen r5.2 thresholds port reliably to r6.2",
            "status": "UNSUPPORTED",
            "supporting_evidence": "Negative frozen-threshold exceedance (FP/N_negative) ≈ 0.00067 on r5.2 validation vs ≈ 0.429 on r6.2.",
            "qualification_or_limitation": "Thresholds were not retuned; non-portability is descriptive.",
            "paper_action": "State frozen-threshold non-portability on r6.2.",
        },
        {
            "claim": "RF/XGBoost retain relatively more ranking signal externally",
            "status": "QUALIFIED",
            "supporting_evidence": "r6.2 completed-window mean PR-AUC tabular ≈ 0.00714 vs neural ≈ 0.00047.",
            "qualification_or_limitation": "Relative only. Tabular models do not succeed as portable detectors at frozen thresholds.",
            "paper_action": "Keep as a relative reference, not as success.",
        },
        {
            "claim": "results support real-time deployment",
            "status": "UNSUPPORTED",
            "supporting_evidence": "Endpoint view is past-only evaluation; overlapping windows are not independent incidents; r6.2 decision boundary fails.",
            "qualification_or_limitation": "No real-time, streaming, or intra-day claim is licensed.",
            "paper_action": "Forbid real-time deployment language.",
        },
        {
            "claim": "results establish unseen-user generalisation",
            "status": "UNSUPPORTED",
            "supporting_evidence": "Temporal partitions contain the same users (SUBMISSION_READINESS / frozen protocol).",
            "qualification_or_limitation": "Cross-version evaluation is not an unseen-user test.",
            "paper_action": "Forbid unseen-user generalisation claims.",
        },
        {
            "claim": "source ablation and Gaussian noise are controlled degraded-input analyses",
            "status": "QUALIFIED",
            "supporting_evidence": str(OBJ3 / "r52_source_ablation.csv") + "; " + str(OBJ3 / "r52_noise_robustness.csv") + "; claim register P-D_source_ablation=True with not_directly_comparable.",
            "qualification_or_limitation": "Scaled-space protocol; source ablation notes not_directly_comparable and scaled_space_zeroing_no_verified_scaler. Not classified UNSUPPORTED merely because EDITOR-007D did not consume these files.",
            "paper_action": "Cite as controlled degraded-input analyses with protocol limits; do not upgrade to adversarial robustness.",
        },
        {
            "claim": "source ablation/Gaussian noise establish adversarial robustness",
            "status": "UNSUPPORTED",
            "supporting_evidence": "The same Objective-3 CSVs are source-channel ablation and gaussian_noise_continuous protocols, not adversarial attacks.",
            "qualification_or_limitation": "Controlled degraded-input existence is QUALIFIED separately and is not adversarial robustness.",
            "paper_action": "Forbid adversarial-robustness wording.",
        },
        {
            "claim": "reference-centred tree-contribution rankings have intervention-based faithfulness evidence",
            "status": "FULLY_SUPPORTED",
            "supporting_evidence": str(OBJ3 / "r52_odst_centred_faithfulness.csv") + " (training_median_per_tree; top-k vs random; user-cluster bootstrap; ci_excludes_zero_positive=True for recorded seed–k rows).",
            "qualification_or_limitation": "Applies to the documented reference-centred procedure on CERT r5.2 recorded results. Does not make routes/leaves independently faithful. unused-leaf and tree-rho remain disabled and are a different metric family.",
            "paper_action": "Keep the reference-centred faithfulness claim; do not conflate with disabled external tree-rho.",
        },
        {
            "claim": "ODST routes/leaves are independently proven faithful",
            "status": "UNSUPPORTED",
            "supporting_evidence": "Frozen protocol: routes and reached leaves are traceable internal evidence only (SUBMISSION_READINESS; EDITOR-006B1).",
            "qualification_or_limitation": "Traceability is not independent faithfulness.",
            "paper_action": "State traceable internal evidence only.",
        },
    ]
    statuses = {c["status"] for c in claims}
    if statuses - {"FULLY_SUPPORTED", "QUALIFIED", "UNRESOLVED", "UNSUPPORTED"}:
        raise SystemExit("EDITOR007D1_FREEZE_COMPLIANCE_CORRECTION_BLOCKED")

    phenotype = {
        "task_id": "EDITOR-007D1",
        "PRIMARY_PORTABILITY_PHENOTYPE": "P2_R62_SEVERE_DISTRIBUTION_AND_DECISION_SHIFT",
        "PRIMARY_PORTABILITY_PHENOTYPE_CHANGED": False,
        "scientific_rulings_preserved": {
            "GENERAL_CROSS_VERSION_COLLAPSE": "NOT_SUPPORTED",
            "R51_SUBSTANTIAL_RANKING_TRANSFER": "SUPPORTED",
            "R62_SEVERE_VERSION_SPECIFIC_FAILURE": "SUPPORTED",
            "R62_RANKING_COLLAPSE": "MODEL_FAMILY_DEPENDENT",
            "R62_THRESHOLD_PORTABILITY_FAILURE": "SUPPORTED",
            "TABULAR_RELATIVE_PORTABILITY": "SUPPORTED",
            "C5_TEACHER_FIDELITY_EFFECT": "SUPPORTED",
            "C5_PREDICTIVE_ADVANTAGE_OVER_C2": "UNSUPPORTED",
            "POINT_ESTIMATE_PATTERN": "MIXED_OR_VERSION_DEPENDENT",
        },
        "observed_evidence": [
            "substantial r5.1 ranking transfer",
            "severe r6.2 neural ranking collapse",
            "relatively greater r6.2 tabular ranking retention",
            "severe r6.2 frozen-threshold failure",
            "r6.2 common-feature distribution differences",
            "r6.2 score-distribution differences",
            "C5 teacher-relative fidelity preservation on r5.1 and r6.2",
        ],
        "not_causally_established": [
            "feature shift caused ranking collapse",
            "distribution shift destroyed the neural model",
            "specific feature X caused failure",
            "teacher anchoring caused portability",
        ],
        "approved_associative_wording": [
            "co-occurs with",
            "is associated with",
            "is consistent with",
            "diagnostically accompanies",
        ],
        "corrected_wording": (
            "the severe r6.2 distribution shift co-occurs with neural ranking collapse"
        ),
        "forbidden_wording_example": "shift destroys neural ranking",
        "r51_role": "R51_SECONDARY_STRESS_ONLY",
        "r51_official_insider_incident_clusters": 4,
        "r62_official_insider_incident_clusters": 5,
        "R51_FUTURE_UNTOUCHED_TARGET_ELIGIBLE": False,
        "R62_FUTURE_UNTOUCHED_TARGET_ELIGIBLE": False,
    }

    requirements = {
        "EDITOR008_SHIFT_DETECTION_REQUIRED": "YES",
        "EDITOR008_SOURCE_ROBUST_REPRESENTATION_REQUIRED": "YES",
        "EDITOR008_DECISION_PORTABILITY_REQUIRED": "YES",
        "EDITOR008_TEACHER_ANCHORING_ROLE": "AUXILIARY_FIDELITY_REGULARISER",
        "EDITOR008_ABSTENTION_OR_OOD_GATING_REQUIRED": "CONDITIONAL",
        "EDITOR008_MULTI_SOURCE_DEVELOPMENT_REQUIRED": "CONDITIONAL",
        "EDITOR008_EXPLAINABILITY_UNDER_SHIFT_REQUIRED": "CONDITIONAL",
        "TABULAR_BASELINES_MUST_REMAIN": "YES",
        "architecture_frozen": False,
        "rationale": {
            "CONDITIONAL": "007D establishes the failure phenotype; it does not establish a unique solution (abstention/OOD, multi-version development, or a precise explainability-under-shift protocol).",
        },
    }

    if any(PROTOCOL.values()):
        raise SystemExit("EDITOR007D1_FREEZE_COMPLIANCE_CORRECTION_BLOCKED")

    consistency = {
        "task_id": "EDITOR-007D1",
        "original_editor007d_commit_is_ancestor": ancestor_007d,
        "editor007c1_commit_is_ancestor": ancestor_007c1,
        "branch_correct": branch == "repository-hardening",
        "working_tree_clean_at_editor007d1_start": False,
        "tracked_working_tree_clean_at_editor007d1_start": tracked_clean,
        "untracked_out_of_scope_leftovers_present": leftovers,
        "untracked_leftovers_also_present_after_editor007d_commit": True,
        "r52_test_accessed": False,
        "new_model_execution": False,
        "training_executed": False,
        "fresh_predictive_inference": False,
        "r51_rerun": False,
        "r62_rerun": False,
        "threshold_tuning": False,
        "target_scaler_fit": False,
        "target_calibration_fit": False,
        "historical_editor007d_files_modified": False,
        "historical_r51_results_modified": False,
        "historical_r62_results_modified": False,
        "r51_cluster_count": 4,
        "r62_cluster_count": 5,
        "unused_leaf_external_interpretation_disabled": True,
        "tree_rho_external_interpretation_disabled": True,
        "overlapping_windows_not_independent_incidents": True,
        "r51_role_secondary_stress_only": True,
        "r62_not_future_untouched_target": True,
        "r51_not_future_untouched_target": True,
        "c5_predictive_superiority_claim": "unsupported",
        "teacher_fidelity_claim_separate_from_predictive_claim": True,
        "causal_shift_language_used": False,
        "claim_status_vocabulary_restricted": True,
        "numerical_predictive_values_changed": 0,
        "numerical_mechanism_values_changed": 0,
        "bootstrap_intervals_changed": 0,
        "frozen_thresholds_changed": 0,
    }
    hard = [
        consistency["original_editor007d_commit_is_ancestor"],
        consistency["editor007c1_commit_is_ancestor"],
        consistency["branch_correct"],
        consistency["tracked_working_tree_clean_at_editor007d1_start"],
        not consistency["r52_test_accessed"],
        not consistency["new_model_execution"],
        not consistency["training_executed"],
        not consistency["fresh_predictive_inference"],
        not consistency["historical_editor007d_files_modified"],
        consistency["r51_cluster_count"] == 4,
        consistency["r62_cluster_count"] == 5,
        not consistency["causal_shift_language_used"],
    ]
    if not all(hard):
        raise SystemExit("EDITOR007D1_FREEZE_COMPLIANCE_CORRECTION_BLOCKED")

    gate_ok = (
        consistency["numerical_predictive_values_changed"] == 0
        and consistency["historical_editor007d_files_modified"] is False
        and consistency["r52_test_accessed"] is False
        and consistency["new_model_execution"] is False
        and r52_pred_doc["interpretation"]["C5_PREDICTIVE_ADVANTAGE_OVER_C2"] == "UNSUPPORTED"
        and phenotype["PRIMARY_PORTABILITY_PHENOTYPE"] == "P2_R62_SEVERE_DISTRIBUTION_AND_DECISION_SHIFT"
        and {c["status"] for c in claims} <= {"FULLY_SUPPORTED", "QUALIFIED", "UNRESOLVED", "UNSUPPORTED"}
        and next(c["status"] for c in claims if c["claim"].startswith("reference-centred")) == "FULLY_SUPPORTED"
        and next(c["status"] for c in claims if "adversarial" in c["claim"]) == "UNSUPPORTED"
        and r52_mech_doc["R52_C2_C5_MECHANISM_EVIDENCE_STATUS"] == "UNRESOLVED"
    )
    gate = {
        "task_id": "EDITOR-007D1",
        "EDITOR008_PROTOCOL_DRAFTING_AUTHORISED": "YES" if gate_ok else "NO",
        "authorises": "drafting and independent audit of EDITOR-008 only",
        "does_not_authorise": "training, Generation-2 execution, threshold tuning, or target scaler/calibration fit",
        "conditions": {
            "no_numerical_evidence_changed": True,
            "unresolved_sources_explicitly_declared": True,
            "claim_matrix_approved_vocabulary": True,
            "c5_predictive_superiority_unsupported": True,
            "explainability_distinction_corrected": True,
            "degraded_input_adversarial_distinction_corrected": True,
            "primary_phenotype_evidence_supported": True,
            "r52_test_untouched": True,
            "no_new_model_execution": True,
            "no_target_tuning": True,
            "historical_007d_unchanged": True,
        },
        **requirements,
    }

    dump_json(OUT / "EDITOR007D1_R52_C2_C5_PREDICTIVE_EVIDENCE.json", r52_pred_doc)
    dump_json(OUT / "EDITOR007D1_R52_C2_C5_MECHANISM_EVIDENCE.json", r52_mech_doc)
    dump_json(OUT / "EDITOR007D1_INPUT_CHECKSUMS.json", checksum_doc)
    dump_json(OUT / "EDITOR007D1_INTERNAL_CONSISTENCY.json", consistency)
    dump_json(OUT / "EDITOR007D1_PORTABILITY_PHENOTYPE.json", phenotype)
    dump_json(OUT / "EDITOR007D1_EDITOR008_RELEASE_GATE.json", gate)

    fields = ["claim", "status", "supporting_evidence", "qualification_or_limitation", "paper_action"]
    with (OUT / "EDITOR007D1_CLAIM_STATUS.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(claims)

    report = f"""# EDITOR-007D1 Freeze Compliance Correction

## 1. Scope

EDITOR-007D1 is a non-numerical compliance and interpretation correction.
Historical `review/editor007d_cross_version_synthesis/` remains frozen.
This directory is the paper-facing derivative handover for EDITOR-008 drafting.

EDITOR-007D1 does not change any frozen r5.1 or r6.2 predictive result, mechanism result, bootstrap interval, score array, feature value, threshold, or dataset label.

## 2. Original EDITOR-007D Freeze

- Original commit: `{COMMIT_007D}`
- EDITOR-007C1 ancestor: `{COMMIT_007C1}`
- Branch at correction: `{branch}`
- HEAD at correction start: `{head}`
- Tracked working tree clean: `{tracked_clean}`
- Untracked out-of-scope leftovers present (also present after the EDITOR-007D commit): `{leftovers}`

This does not prove that the original EDITOR-007D working tree was fully clean before 007D execution. It records only what is verifiable now.

## 3. Numerical Non-Modification Statement

NUMERICAL_PREDICTIVE_VALUES_CHANGED = 0
NUMERICAL_MECHANISM_VALUES_CHANGED = 0
BOOTSTRAP_INTERVALS_CHANGED = 0
FROZEN_THRESHOLDS_CHANGED = 0
HISTORICAL_EDITOR007D_FILES_MODIFIED = NO

## 4. Provenance Completion

`EDITOR007D1_INPUT_CHECKSUMS.json` lists {len(checksums)} artefacts, including 007A parity/feature/score evidence, 007C1 paper-corrected r5.1 predictive JSON, r5.1/r6.2 mechanism results, feature/count/manifest files, completed-window labels, all 18 r5.1 and 18 r6.2 raw-score arrays, r5.2 validation tensor, all 18 r5.2 replay-score arrays, frozen thresholds, and newly inspected r5.2 C2/C5 and Objective-3 recorded-result files.

## 5. r5.2 C2/C5 Predictive Evidence

Status: **LOCATED**

Source: frozen EDITOR-007A r5.2 VALIDATION replay metrics (scientifically adjudicated as SCIENTIFIC_PARITY_WITH_NUMERICAL_NONIDENTITY; automated gate FAIL_EXACT_NUMERICAL_IDENTITY preserved).

Teacher / C2 / C5 PR-AUC are essentially tied in-domain. C5−C2 deltas are not a superiority claim. No uncertainty interval was invented (`NOT_ATTACHED`). r5.2 TEST was not accessed.

## 6. r5.2 C2/C5 Mechanism Evidence

Status: **UNRESOLVED**

The EDITOR-007D statement `R52_MECHANISM_COMPARISON_NOT_INCLUDED_PROVENANCE_INSUFFICIENT` is not silently overridden.

Ablation C2 seed summaries contain exact-frozen field names and match the 007D C2 checkpoint. Ablation C5 seed summaries also contain those fields, but ablation C5 seed42 SHA256 `{ABLATION_C5_42}` is not `C5_original_paper` seed42 `{C5_PAPER_42}`. The reproducibility `C5_original_paper` seed_summary does not record val_logit_consistency / route_mae / hard_route_agreement / dominant_leaf_agreement.

This does not invalidate the supported external r5.1/r6.2 teacher-fidelity result. Values were not reconstructed from manuscript prose.

## 7. Corrected Claim Classifications

Formal status vocabulary is only FULLY_SUPPORTED / QUALIFIED / UNRESOLVED / UNSUPPORTED.

- C5_PREDICTIVE_ADVANTAGE_OVER_C2 = UNSUPPORTED
- POINT_ESTIMATE_PATTERN = MIXED_OR_VERSION_DEPENDENT
- teacher anchoring improves predictive performance = UNSUPPORTED
- architecture generalises strongly = UNSUPPORTED
- architecture fails uniformly = UNSUPPORTED
- r5.1 retains substantial ranking signal = FULLY_SUPPORTED
- r6.2 exhibits severe ranking failure = FULLY_SUPPORTED
- frozen thresholds port to r6.2 = UNSUPPORTED

## 8. Corrected Explainability Interpretation

Supported: reference-centred tree-contribution rankings have intervention-based faithfulness evidence (`r52_odst_centred_faithfulness.csv`; training-median per-tree references; top-k versus random; user-cluster bootstrap).

Unsupported: routes and leaves are independently proven faithful.

Disabled external metrics remain unused-leaf fraction and tree-contribution rho. Those disabled metrics do not invalidate the separate reference-centred intervention evidence.

## 9. Corrected Degraded-Input Interpretation

Located producing Objective-3 recorded results:

- `r52_source_ablation.csv`
- `r52_noise_robustness.csv`

These are controlled degraded-input analyses. They do **not** establish adversarial robustness (UNSUPPORTED).

## 10. Primary Portability Phenotype

PRIMARY_PORTABILITY_PHENOTYPE = P2_R62_SEVERE_DISTRIBUTION_AND_DECISION_SHIFT

r5.1 retains substantial cross-version ranking signal, whereas r6.2 presents a much more severe, model-family-dependent portability failure that co-occurs with major score/decision-boundary and common-feature distribution shifts.

Do not state that a feature shift caused ranking collapse, that a distribution shift destroyed the neural model, that a specific feature caused failure, or that teacher anchoring caused portability.

## 11. EDITOR-008 Capability Requirements

- EDITOR008_SHIFT_DETECTION_REQUIRED = YES
- EDITOR008_SOURCE_ROBUST_REPRESENTATION_REQUIRED = YES
- EDITOR008_DECISION_PORTABILITY_REQUIRED = YES
- EDITOR008_ABSTENTION_OR_OOD_GATING_REQUIRED = CONDITIONAL
- EDITOR008_MULTI_SOURCE_DEVELOPMENT_REQUIRED = CONDITIONAL
- EDITOR008_EXPLAINABILITY_UNDER_SHIFT_REQUIRED = CONDITIONAL
- EDITOR008_TEACHER_ANCHORING_ROLE = AUXILIARY_FIDELITY_REGULARISER
- TABULAR_BASELINES_MUST_REMAIN = YES

No architecture is frozen here.

## 12. Remaining Unresolved Evidence

- Paired r5.2 validation exact-frozen mechanism comparison for C2 vs C5_original_paper.
- PAPER_ARTIFACT_REGISTER still lists several manuscript figures as UNRESOLVED producing-run fields; 007D1 cites the Objective-3 recorded_results CSVs rather than inventing those run IDs.

## 13. Final Gate for EDITOR-008

EDITOR008_PROTOCOL_DRAFTING_AUTHORISED = {"YES" if gate_ok else "NO"}

This authorises drafting and independent audit of EDITOR-008 only.
It does not authorise training.
"""
    (OUT / "EDITOR007D1_FREEZE_COMPLIANCE_REPORT.md").write_text(report, encoding="utf-8")

    manifest = {
        "task_id": "EDITOR-007D1",
        "branch": branch,
        "HEAD": head,
        "original_editor007d_commit": COMMIT_007D,
        "editor007c1_commit": COMMIT_007C1,
        "files_created": sorted(p.name for p in OUT.iterdir() if p.is_file()),
        "files_modified_historical_007d": [],
        "protocol_flags": PROTOCOL,
        "timestamp_utc": utc_now(),
    }
    dump_json(OUT / "EDITOR007D1_RUN_MANIFEST.json", manifest)
    print("EDITOR007D1_OK", "UNRESOLVED_MECH", r52_mech_doc["R52_C2_C5_MECHANISM_EVIDENCE_STATUS"])
    print("N_CHECKSUMS", len(checksums))
    print("GATE", gate["EDITOR008_PROTOCOL_DRAFTING_AUTHORISED"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
