#!/usr/bin/env python3
"""EDITOR-008A: metadata-only untouched-target inventory and lock.

Does not read answer CSVs, labels, feature values, score arrays, or r5.2 TEST tensors.
Does not write method specifications.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
COMMIT_D1 = "d5a6416bfe5ea582b2439803ffc0d896c091d844"
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


def refuse_test_open(path: Path) -> None:
    text = str(path).replace("\\", "/").lower()
    if "r52_t20_s1_test" in text or text.endswith("/r52_t20_s1_test.npz"):
        raise SystemExit("EDITOR008_PROTOCOL_BLOCKED r5.2 TEST open attempted")


def rec(path: Path, role: str) -> dict[str, Any]:
    refuse_test_open(path)
    return {
        "path": str(path),
        "sha256": sha256_file(path),
        "byte_size": path.stat().st_size,
        "role": role,
        "contents_semantically_inspected": False,
    }


def release(
    version: str,
    path_or_identifier: str,
    *,
    available_locally: bool,
    prior_training_use: bool,
    prior_validation_use: bool,
    prior_diagnostic_use: bool,
    prior_score_generation: bool,
    prior_feature_distribution_inspection: bool,
    prior_label_or_answer_inspection: bool,
    prior_other_empirical_use: bool,
    provenance_evidence: list[str],
    untouched_status: str,
    eligible: str,
    eligibility_reason: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    row = {
        "version": version,
        "path_or_identifier": path_or_identifier,
        "available_locally": available_locally,
        "prior_training_use": prior_training_use,
        "prior_validation_use": prior_validation_use,
        "prior_diagnostic_use": prior_diagnostic_use,
        "prior_score_generation": prior_score_generation,
        "prior_feature_distribution_inspection": prior_feature_distribution_inspection,
        "prior_label_or_answer_inspection": prior_label_or_answer_inspection,
        "prior_other_empirical_use": prior_other_empirical_use,
        "provenance_evidence": provenance_evidence,
        "untouched_status": untouched_status,
        "eligible_as_generation2_final_target": eligible,
        "eligibility_reason": eligibility_reason,
    }
    if extra:
        row.update(extra)
    return row


def main() -> int:
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    head = git("rev-parse", "HEAD")
    status = git("status", "--short")
    ancestor = subprocess.call(["git", "merge-base", "--is-ancestor", COMMIT_D1, "HEAD"], cwd=ROOT) == 0
    tracked_clean = git("diff", "--name-only") == "" and git("diff", "--cached", "--name-only") == ""
    leftovers = [ln[3:] for ln in status.splitlines() if ln.startswith("??") and "editor008_" not in ln]
    if branch != "repository-hardening" or not ancestor or not tracked_clean:
        raise SystemExit("EDITOR008_PROTOCOL_BLOCKED_DIRTY_WORKTREE")
    extra = sorted(set(leftovers) - set(D1_LEFTOVERS))
    missing = sorted(set(D1_LEFTOVERS) - set(leftovers))
    if extra:
        raise SystemExit("EDITOR008_PROTOCOL_BLOCKED_DIRTY_WORKTREE")

    barrier = {
        "labels_before_final_model_freeze": "PROHIBITED",
        "answer_contents_before_final_model_freeze": "PROHIBITED",
        "feature_values_before_final_model_freeze": "PROHIBITED",
        "feature_distribution_before_final_model_freeze": "PROHIBITED",
        "score_distribution_before_final_model_freeze": "PROHIBITED",
        "target_scaler_fit": "PROHIBITED",
        "target_calibration_fit": "PROHIBITED",
        "target_threshold_selection": "PROHIBITED",
        "target_hyperparameter_selection": "PROHIBITED",
        "target_model_selection": "PROHIBITED",
        "target_specific_method_design": "PROHIBITED",
        "schema_header_filename_check_after_lock": "PERMITTED_WITHOUT_VALUE_DISTRIBUTIONS",
    }

    consumed_common = [
        "review/editor007d1_freeze_compliance/",
        "review/editor007d_cross_version_synthesis/",
        "manifests/experiment_registry.csv",
        "src/dataset_registry.py",
        "paper/manuscript/source/03_methodology.tex",
    ]

    releases = [
        release(
            "CERT r2",
            r"C:\PhD\06_Datasets\answers\r2.csv",
            available_locally=False,
            prior_training_use=False,
            prior_validation_use=False,
            prior_diagnostic_use=False,
            prior_score_generation=False,
            prior_feature_distribution_inspection=False,
            prior_label_or_answer_inspection=True,
            prior_other_empirical_use=False,
            provenance_evidence=[
                "Answer-bundle filename exists in C:\\PhD\\06_Datasets\\answers\\ (filename/size only; CSV not opened in EDITOR-008).",
                "Sister-repo cert-r42-feasibility/docs/cert_r42_notes.md catalogues the answer path and includes extracted answer-catalog rows. This EDITOR-008 pass did not reopen the CSV.",
                "No local raw log directory named r2 was found under C:\\PhD\\06_Datasets.",
            ],
            untouched_status="UNRESOLVED",
            eligible="NO",
            eligibility_reason="Conservative: no local raw logs, and prior answer-cataloguing in the research programme prevents an untouched claim.",
        ),
        release(
            "CERT r3.1",
            r"C:\PhD\06_Datasets\answers\r3.1-*.csv",
            available_locally=False,
            prior_training_use=False,
            prior_validation_use=False,
            prior_diagnostic_use=False,
            prior_score_generation=False,
            prior_feature_distribution_inspection=False,
            prior_label_or_answer_inspection=True,
            prior_other_empirical_use=False,
            provenance_evidence=[
                "Answer-bundle filenames r3.1-1.csv and r3.1-2.csv exist (not opened in EDITOR-008).",
                "Sister-repo cert_r42_notes.md catalogues those paths and extracted answer-catalog rows.",
                "No local raw r3.1 log directory found.",
            ],
            untouched_status="UNRESOLVED",
            eligible="NO",
            eligibility_reason="Conservative: no local raw logs; prior answer-cataloguing blocks an untouched claim.",
        ),
        release(
            "CERT r3.2",
            r"C:\PhD\06_Datasets\answers\r3.2-*.csv",
            available_locally=False,
            prior_training_use=False,
            prior_validation_use=False,
            prior_diagnostic_use=False,
            prior_score_generation=False,
            prior_feature_distribution_inspection=False,
            prior_label_or_answer_inspection=True,
            prior_other_empirical_use=False,
            provenance_evidence=[
                "Answer-bundle filenames r3.2-1.csv and r3.2-2.csv exist (not opened in EDITOR-008).",
                "Sister-repo cert_r42_notes.md catalogues those paths and extracted answer-catalog rows.",
                "No local raw r3.2 log directory found.",
            ],
            untouched_status="UNRESOLVED",
            eligible="NO",
            eligibility_reason="Conservative: no local raw logs; prior answer-cataloguing blocks an untouched claim.",
        ),
        release(
            "CERT r4.1",
            r"C:\PhD\06_Datasets\answers\r4.1-*.csv",
            available_locally=False,
            prior_training_use=False,
            prior_validation_use=False,
            prior_diagnostic_use=False,
            prior_score_generation=False,
            prior_feature_distribution_inspection=False,
            prior_label_or_answer_inspection=True,
            prior_other_empirical_use=False,
            provenance_evidence=[
                "Answer-bundle filenames r4.1-1.csv, r4.1-2.csv, r4.1-3.csv exist (not opened in EDITOR-008).",
                "Sister-repo cert_r42_notes.md catalogues those paths.",
                "No local raw r4.1 log directory found. dataset_registry.py does not register 4.1.",
            ],
            untouched_status="UNRESOLVED",
            eligible="NO",
            eligibility_reason="Conservative: no local raw logs; cannot certify untouched status.",
        ),
        release(
            "CERT r4.2",
            r"C:\PhD\06_Datasets\CERT_r4.2\data\raw\r4.2",
            available_locally=True,
            prior_training_use=True,
            prior_validation_use=True,
            prior_diagnostic_use=True,
            prior_score_generation=True,
            prior_feature_distribution_inspection=True,
            prior_label_or_answer_inspection=True,
            prior_other_empirical_use=True,
            provenance_evidence=consumed_common
            + [
                "src/dataset_registry.py role=primary_development_dataset",
                "manifests/experiment_registry.csv objective1_r42_time_aware_sequences",
                "paper/manuscript/source/03_methodology.tex: CERT r4.2 supported representation development",
                "Processed tensors exist as filenames r42_T20_s1_{train,validation,test}.npz (not opened in EDITOR-008).",
            ],
            untouched_status="CONSUMED",
            eligible="NO",
            eligibility_reason="Known consumed development release. Mandatory CONSUMED preservation.",
            extra={
                "raw_top_level_filenames_only": [
                    "LDAP",
                    "device.csv",
                    "email.csv",
                    "file.csv",
                    "http.csv",
                    "license.txt",
                    "logon.csv",
                    "psychometric.csv",
                    "readme.txt",
                ]
            },
        ),
        release(
            "CERT r5.1",
            r"C:\PhD\06_Datasets\r5.1\r5.1",
            available_locally=True,
            prior_training_use=False,
            prior_validation_use=False,
            prior_diagnostic_use=True,
            prior_score_generation=True,
            prior_feature_distribution_inspection=True,
            prior_label_or_answer_inspection=True,
            prior_other_empirical_use=True,
            provenance_evidence=consumed_common
            + [
                "review/editor007c1_r51_result_freeze/",
                "EDITOR-007D/007D1: R51_SECONDARY_STRESS_ONLY; not future untouched target",
                r"C:\PhD\06_Datasets\derived\teacher_anchored_r51_editor007c_scores",
            ],
            untouched_status="CONSUMED",
            eligible="NO",
            eligibility_reason="Known consumed diagnostic/secondary-stress release. Cannot become a Generation-2 untouched target.",
            extra={
                "raw_top_level_filenames_only": [
                    "LDAP",
                    "decoy_file.csv",
                    "device.csv",
                    "email.csv",
                    "file.csv",
                    "http.csv",
                    "license.txt",
                    "logon.csv",
                    "psychometric.csv",
                    "readme.txt",
                ]
            },
        ),
        release(
            "CERT r5.2 TRAIN/VALIDATION",
            r"C:\PhD\06_Datasets\CERT r5.2\r5.2",
            available_locally=True,
            prior_training_use=True,
            prior_validation_use=True,
            prior_diagnostic_use=True,
            prior_score_generation=True,
            prior_feature_distribution_inspection=True,
            prior_label_or_answer_inspection=True,
            prior_other_empirical_use=True,
            provenance_evidence=consumed_common
            + [
                "manifests/experiment_registry.csv teacher_anchored_r52_reproducibility and related r5.2 validation experiments",
                "Frozen validation tensor filename r52_T20_s1_validation.npz (hashed historically; not reopened for values in EDITOR-008).",
            ],
            untouched_status="CONSUMED",
            eligible="NO",
            eligibility_reason="Known consumed train/validation release.",
            extra={
                "raw_top_level_filenames_only": [
                    "LDAP",
                    "decoy_file.csv",
                    "device.csv",
                    "email.csv",
                    "file.csv",
                    "http.csv",
                    "license.txt",
                    "logon.csv",
                    "psychometric.csv",
                    "readme.txt",
                ]
            },
        ),
        release(
            "CERT r5.2 TEST",
            r"C:\PhD\07_Projects\cert-r42-feasibility\data\processed\r5.2\tensors\r52_T20_s1_test.npz",
            available_locally=True,
            prior_training_use=False,
            prior_validation_use=False,
            prior_diagnostic_use=True,
            prior_score_generation=True,
            prior_feature_distribution_inspection=False,
            prior_label_or_answer_inspection=True,
            prior_other_empirical_use=True,
            provenance_evidence=[
                "manifests/experiment_registry.csv r52_one_pass_test completed_with_scope_limit",
                "paper/manuscript/source/03_methodology.tex: r5.2 test partition was used once already for reference models",
                "Filename observed in directory listing only. EDITOR-008 did not open or hash the TEST tensor.",
            ],
            untouched_status="CONSUMED",
            eligible="NO",
            eligibility_reason="r5.2 TEST remains prohibited and cannot serve as the cross-release Generation-2 target. File was not opened in EDITOR-008.",
            extra={"file_opened_in_editor008": False, "partition_not_a_separate_cert_release": True},
        ),
        release(
            "CERT r6.1",
            r"C:\PhD\06_Datasets\answers\r6.1-*.csv",
            available_locally=False,
            prior_training_use=False,
            prior_validation_use=False,
            prior_diagnostic_use=False,
            prior_score_generation=False,
            prior_feature_distribution_inspection=False,
            prior_label_or_answer_inspection=True,
            prior_other_empirical_use=False,
            provenance_evidence=[
                "Answer-bundle filenames r6.1-1.csv, r6.1-2.csv, r6.1-3.csv, r6.1-5.csv exist (not opened in EDITOR-008). r6.1-4 filename not present.",
                "Sister-repo cert_r42_notes.md catalogues those paths.",
                "No local raw r6.1 log directory or archive found under C:\\PhD\\06_Datasets.",
                "C:\\PhD\\06_Datasets\\CERT_r6.2 is an empty placeholder directory (0 files), not r6.1 data.",
            ],
            untouched_status="UNRESOLVED",
            eligible="NO",
            eligibility_reason="Conservative: no local raw logs; cannot certify untouched status; answer-bundle filenames exist in the programme workspace.",
        ),
        release(
            "CERT r6.2",
            r"C:\PhD\06_Datasets\r6.2\r6.2",
            available_locally=True,
            prior_training_use=False,
            prior_validation_use=False,
            prior_diagnostic_use=True,
            prior_score_generation=True,
            prior_feature_distribution_inspection=True,
            prior_label_or_answer_inspection=True,
            prior_other_empirical_use=True,
            provenance_evidence=consumed_common
            + [
                "manifests/experiment_registry.csv r62_model_free_matching_stage2b1a",
                "review/editor006c_r62_input_bundle/ and EDITOR-006E scores",
                "EDITOR-007D/007D1: R62_EXTERNAL; not future untouched target",
            ],
            untouched_status="CONSUMED",
            eligible="NO",
            eligibility_reason="Known consumed diagnostic/external-stress release. Cannot become a Generation-2 untouched target.",
            extra={
                "raw_top_level_filenames_only": [
                    "LDAP",
                    "decoy_file.csv",
                    "device.csv",
                    "email.csv",
                    "file.csv",
                    "http.csv",
                    "license-exactdata.txt",
                    "license-wikipedia.txt",
                    "logon.csv",
                    "psychometric.csv",
                    "readme.txt",
                ]
            },
        ),
    ]

    eligible_targets = [r["version"] for r in releases if r["eligible_as_generation2_final_target"] == "YES"]
    n_eligible = len(eligible_targets)
    if n_eligible >= 2:
        rule = "USE_ALL_ELIGIBLE_UNTOUCHED_TARGETS"
        protocol = "PROSPECTIVE_UNTOUCHED_TARGETS_LOCKED"
        available = True
    elif n_eligible == 1:
        rule = "SINGLE_ELIGIBLE_TARGET"
        protocol = "PROSPECTIVE_UNTOUCHED_TARGETS_LOCKED"
        available = True
    else:
        rule = "NO_PROSPECTIVE_TARGET_AVAILABLE"
        protocol = "BLOCKED"
        available = False

    inventory = {
        "task_id": "EDITOR-008A",
        "inventory_scope": "metadata_only",
        "answer_csvs_opened": False,
        "label_arrays_opened": False,
        "feature_values_inspected": False,
        "r52_test_tensor_opened": False,
        "untouched_definition": "UNOBSERVED_BY_THIS_RESEARCH_PROGRAM_BEFORE_PROSPECTIVE_LOCK",
        "cross_release_not_cross_population": True,
        "D1_leftovers_present": leftovers,
        "D1_leftovers_expected": D1_LEFTOVERS,
        "D1_leftovers_match": leftovers == D1_LEFTOVERS and not missing,
        "releases": releases,
        "N_ELIGIBLE_UNTOUCHED_TARGETS": n_eligible,
        "ELIGIBLE_UNTOUCHED_TARGETS": eligible_targets,
        "PROSPECTIVE_UNTOUCHED_TARGET_AVAILABLE": available,
        "EDITOR008_PROSPECTIVE_TARGET_PROTOCOL": protocol,
        "FINAL_TARGET_SELECTION_RULE": rule,
        "conservative_eligibility_rule": "If provenance cannot establish that a version is genuinely untouched, eligible_as_generation2_final_target=NO.",
    }
    dump_json(OUT / "EDITOR008_UNTOUCHED_TARGET_INVENTORY.json", inventory)
    inv_sha = sha256_file(OUT / "EDITOR008_UNTOUCHED_TARGET_INVENTORY.json")

    lock = {
        "task_id": "EDITOR-008A",
        "FINAL_UNTOUCHED_TARGETS": eligible_targets,
        "FINAL_TARGET_COUNT": n_eligible,
        "FINAL_TARGET_SELECTION_RULE": rule,
        "PROSPECTIVE_UNTOUCHED_TARGET_AVAILABLE": available,
        "EDITOR008_PROSPECTIVE_TARGET_PROTOCOL": protocol,
        "PROSPECTIVE_FINAL_TARGET_CLAIM": "NOT_AVAILABLE" if not available else "LOCKED",
        "TARGET_LOCK_TIMESTAMP": utc_now(),
        "TARGET_INVENTORY_SHA256": inv_sha,
        "CROSS_RELEASE_NOT_CROSS_POPULATION": True,
        "TARGET_NO_INSPECTION_BARRIER": "ACTIVE",
        "target_no_inspection_barrier": barrier,
        "controlling_editor007d1_commit": COMMIT_D1,
        "PRIMARY_PORTABILITY_PHENOTYPE": "P2_R62_SEVERE_DISTRIBUTION_AND_DECISION_SHIFT",
        "note": (
            "No eligible prospective untouched CERT release was locked. "
            "Phase B may draft a retrospective source-domain/LOVO protocol only, "
            "with the prospective untouched-target claim removed."
        ),
    }
    dump_json(OUT / "EDITOR008_FINAL_TARGET_LOCK.json", lock)

    provenance_files = [
        rec(ROOT / "review" / "editor007d1_freeze_compliance" / "EDITOR007D1_INTERNAL_CONSISTENCY.json", "d1_leftover_and_gate_record"),
        rec(ROOT / "review" / "editor007d1_freeze_compliance" / "EDITOR007D1_EDITOR008_RELEASE_GATE.json", "d1_editor008_authorisation"),
        rec(ROOT / "review" / "editor007d1_freeze_compliance" / "EDITOR007D1_PORTABILITY_PHENOTYPE.json", "frozen_phenotype"),
        rec(ROOT / "manifests" / "experiment_registry.csv", "experiment_registry"),
        rec(ROOT / "src" / "dataset_registry.py", "dataset_registry"),
        rec(ROOT / "manifests" / "dataset_split_hashes.csv", "dataset_split_hashes"),
        rec(ROOT / "paper" / "manuscript" / "source" / "03_methodology.tex", "manuscript_methodology_provenance"),
        rec(Path(r"C:\PhD\07_Projects\cert-r42-feasibility\docs\cert_r42_notes.md"), "sister_repo_answer_path_catalogue"),
        rec(OUT / "EDITOR008_UNTOUCHED_TARGET_INVENTORY.json", "phase_a_inventory"),
        rec(OUT / "EDITOR008_FINAL_TARGET_LOCK.json", "phase_a_lock"),
    ]
    checksums = {
        "task_id": "EDITOR-008A",
        "n_artefacts": len(provenance_files),
        "artefacts": provenance_files,
        "not_hashed": [
            "Raw CERT activity CSVs (byte sizes recorded in inventory filenames only).",
            "Answer CSVs (filenames/sizes only; contents not opened).",
            "r52_T20_s1_test.npz (filename observed; file not opened or hashed).",
            "Score/label NPY arrays (not opened).",
        ],
    }
    dump_json(OUT / "EDITOR008_TARGET_LOCK_CHECKSUMS.json", checksums)

    manifest = {
        "task_id": "EDITOR-008A",
        "branch": branch,
        "HEAD": head,
        "controlling_editor007d1_commit": COMMIT_D1,
        "editor007d1_is_ancestor": ancestor,
        "tracked_working_tree_clean": tracked_clean,
        "leftovers": leftovers,
        "leftovers_match_editor007d1_record": leftovers == D1_LEFTOVERS,
        "leftovers_unstaged": True,
        "leftovers_untouched": True,
        "r52_test_accessed": False,
        "new_model_training": False,
        "new_predictive_inference": False,
        "candidate_target_labels_inspected": False,
        "candidate_target_feature_distributions_inspected": False,
        "candidate_target_scores_inspected": False,
        "historical_editor007d_modified": False,
        "historical_editor007d1_modified": False,
        "N_ELIGIBLE_UNTOUCHED_TARGETS": n_eligible,
        "FINAL_TARGET_SELECTION_RULE": rule,
        "timestamp_utc": utc_now(),
        "files_created": sorted(p.name for p in OUT.iterdir() if p.is_file()),
    }
    dump_json(OUT / "EDITOR008_TARGET_LOCK_MANIFEST.json", manifest)
    print("N_ELIGIBLE", n_eligible)
    print("RULE", rule)
    print("INV_SHA", inv_sha)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
