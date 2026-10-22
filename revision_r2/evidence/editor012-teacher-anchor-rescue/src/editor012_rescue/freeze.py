"""Phase A protocol freeze: hash imported evidence and write locked artefacts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .constants import (
    ANCHOR_FORMULATIONS,
    BASE_COMMIT,
    C2OPT_CHECKPOINTS,
    EDITOR009_RESULTS_COMMIT,
    EDITOR010_RESULTS_COMMIT,
    EDITOR010_WORKTREE,
    EDITOR011_RESULTS_COMMIT,
    EDITOR011_WORKTREE,
    ET1_LOGIT_DISTILL_WEIGHT,
    ET1_TEMPERATURE,
    EXPECTED_INNER_SELECT_N,
    EXPECTED_INNER_SELECT_POS,
    EXPECTED_INNER_TRAIN_N,
    EXPECTED_INNER_TRAIN_POS,
    EXPECTED_TRAIN_SHA256,
    EXPECTED_USER_MAPPING_SHA256,
    EXPECTED_VAL_MALICIOUS_USERS,
    EXPECTED_VAL_SHA256,
    EXPECTED_VAL_USERS,
    EXPECTED_VAL_WINDOWS_PER_USER,
    FACTORIAL,
    LAMBDA_ROUTE,
    ODST046,
    ORIGINAL_SINGLE_TEACHER_LOGIT_ANCHOR,
    PRIMARY_SEEDS,
    R2OPT_CHECKPOINTS,
    REVIEW_REL,
    TOPT_CHECKPOINTS,
)
from .io_util import write_json
from .producing import pin_producing_sources
from .safety import (
    EXPECTED_ARCHITECTURE_SHA256,
    EXPECTED_ODST_SHA256,
    EXPECTED_SCALER_SHA256,
    REVIEW_ROOT,
    TRAIN_NPZ,
    VAL_NPZ,
    Editor012ProtocolError,
    refuse_historical_write,
    refuse_r52_test,
    require_hash,
    sha256_file,
    utc_now,
)


def _review(*parts: str) -> Path:
    path = REVIEW_ROOT.joinpath(*parts)
    refuse_historical_write(path)
    return path


def _hash_if_exists(path: Path, role: str) -> dict[str, Any]:
    rec: dict[str, Any] = {"role": role, "path": str(path), "exists": path.is_file()}
    if path.is_file():
        rec["sha256"] = sha256_file(path)
        rec["bytes"] = int(path.stat().st_size)
    return rec


def source_register() -> dict[str, Any]:
    sources = [
        _hash_if_exists(
            EDITOR010_WORKTREE
            / "review/editor010_capacity_objective_teacher_rescue/03_odst_landscape/EDITOR010_ODST_GRID.json",
            "EDITOR010_ODST_GRID",
        ),
        _hash_if_exists(
            EDITOR010_WORKTREE
            / "src/editor010_rescue/train.py",
            "EDITOR010_ET1_TRAIN_IMPL",
        ),
        _hash_if_exists(
            EDITOR010_WORKTREE
            / "src/editor010_rescue/constants.py",
            "EDITOR010_ET1_WEIGHT",
        ),
        _hash_if_exists(
            EDITOR010_WORKTREE
            / "review/editor010_capacity_objective_teacher_rescue/06_promoted_full_r52/EDITOR010_PROMOTION_FREEZE.json",
            "EDITOR010_PROMOTION_FREEZE",
        ),
        _hash_if_exists(
            EDITOR010_WORKTREE
            / "review/editor010_capacity_objective_teacher_rescue/01_inner_development/EDITOR010_INNER_SPLIT.json",
            "EDITOR010_INNER_SPLIT",
        ),
        _hash_if_exists(
            EDITOR010_WORKTREE
            / "review/editor010_capacity_objective_teacher_rescue/01_inner_development/EDITOR010_INNER_SPLIT_CHECKSUMS.json",
            "EDITOR010_INNER_SPLIT_CHECKSUMS",
        ),
        _hash_if_exists(
            EDITOR011_WORKTREE
            / "review/editor011_matched_route_confirmation/00_protocol/EDITOR011_ODST046_LOCK.json",
            "EDITOR011_ODST046_LOCK",
        ),
        _hash_if_exists(
            EDITOR011_WORKTREE
            / "review/editor011_matched_route_confirmation/01_teacher_training/EDITOR011_TOPT_CHECKPOINTS.json",
            "EDITOR011_TOPT_CHECKPOINTS",
        ),
        _hash_if_exists(
            EDITOR011_WORKTREE
            / "review/editor011_matched_route_confirmation/02_student_training/EDITOR011_STUDENT_CHECKPOINTS.json",
            "EDITOR011_STUDENT_CHECKPOINTS",
        ),
        _hash_if_exists(
            EDITOR011_WORKTREE
            / "review/editor011_matched_route_confirmation/05_statistics/EDITOR011_VALIDATION_USER_MAPPING.json",
            "EDITOR011_USER_MAPPING",
        ),
        _hash_if_exists(TRAIN_NPZ, "r52_train_npz"),
        _hash_if_exists(VAL_NPZ, "r52_validation_npz"),
    ]
    for seed, spec in TOPT_CHECKPOINTS.items():
        rec = _hash_if_exists(Path(spec["checkpoint"]), f"T-OPT_seed{seed}")
        rec["expected_sha256"] = spec["sha256"]
        rec["hash_match"] = rec.get("sha256") == spec["sha256"]
        sources.append(rec)
    for seed, spec in C2OPT_CHECKPOINTS.items():
        rec = _hash_if_exists(Path(spec["checkpoint"]), f"C2-OPT_seed{seed}")
        rec["expected_sha256"] = spec["sha256"]
        rec["hash_match"] = rec.get("sha256") == spec["sha256"]
        sources.append(rec)
    for seed, spec in R2OPT_CHECKPOINTS.items():
        rec = _hash_if_exists(Path(spec["checkpoint"]), f"R2-OPT_seed{seed}")
        rec["expected_sha256"] = spec["sha256"]
        rec["hash_match"] = rec.get("sha256") == spec["sha256"]
        sources.append(rec)
    pins = pin_producing_sources()
    return {
        "task_id": "EDITOR-012",
        "status": "PHASE_A_FROZEN_BEFORE_RESULTS",
        "hash_method": "SHA-256 of file bytes",
        "read_only_inspection": True,
        "EDITOR009_RESULTS_COMMIT": EDITOR009_RESULTS_COMMIT,
        "EDITOR010_RESULTS_COMMIT": EDITOR010_RESULTS_COMMIT,
        "EDITOR011_RESULTS_COMMIT": EDITOR011_RESULTS_COMMIT,
        "BASE_COMMIT": BASE_COMMIT,
        "historical_packets_readonly": True,
        "ET1_recovered_from_producing_artefacts": True,
        "ET1_formula": "L = L_task + 0.5 * mean((student_logit - mean(T-OPT logits))^2)",
        "ET1_temperature": ET1_TEMPERATURE,
        "ET1_lambda": ET1_LOGIT_DISTILL_WEIGHT,
        "ET1_equal_weight": True,
        "ET1_route_anchor": False,
        "teacher_ensemble": "T-OPT(42), T-OPT(52), T-OPT(62)",
        "producing_pins": pins,
        "sources": sources,
        "r52_test_opened": False,
        "r52_test_hashed": False,
    }


def write_protocol_packet() -> dict[str, Any]:
    for sub in (
        "00_protocol",
        "01_inner_anchor_search",
        "02_factorial_confirmation",
        "03_extended_stability",
        "04_mechanism",
        "05_statistics",
        "06_editor_response",
        "07_paper_handover",
    ):
        (_review(sub)).mkdir(parents=True, exist_ok=True)

    try:
        refuse_r52_test(
            r"C:\PhD\07_Projects\cert-r42-feasibility\data\processed\r5.2\tensors\r52_T20_s1_test.npz"
        )
        raise Editor012ProtocolError("r5.2 TEST deny-list failed to fire")
    except Editor012ProtocolError as exc:
        if "TEST" not in str(exc):
            raise

    require_hash(TRAIN_NPZ, EXPECTED_TRAIN_SHA256, role="train")
    require_hash(VAL_NPZ, EXPECTED_VAL_SHA256, role="validation")
    for seed, spec in TOPT_CHECKPOINTS.items():
        require_hash(Path(spec["checkpoint"]), spec["sha256"], role=f"T-OPT:{seed}")

    register = source_register()
    write_json(_review("00_protocol", "EDITOR012_SOURCE_EVIDENCE_REGISTER.json"), register)

    formulations = {
        "frozen_before_results": True,
        "ORIGINAL_SINGLE_TEACHER_LOGIT_ANCHOR": ORIGINAL_SINGLE_TEACHER_LOGIT_ANCHOR,
        "ET1": {
            "id": "A0",
            "loss": "L_task + 0.5 * MSE(student_logit, equal_weight_mean(T-OPT logits))",
            "temperature": None,
            "lambda_et1": ET1_LOGIT_DISTILL_WEIGHT,
            "route": False,
            "recovered_from": "editor010_rescue/train.py train_head_distill",
            "not_reconstructed_from_console_summary": True,
        },
        "anchors": ANCHOR_FORMULATIONS,
        "route_on_best_two": {"lambda_route": LAMBDA_ROUTE, "conditional": True},
        "screening_seed": 42,
        "inner_metric": "INNER_SELECT PR-AUC",
        "tie_break": ["F1", "simpler_anchor_formulation"],
        "promotion": "at most 2 formulations that beat A0 or are within 0.001 and simpler",
    }
    write_json(_review("00_protocol", "EDITOR012_TEACHER_ANCHOR_FORMULATIONS.json"), formulations)

    lock = {
        "frozen_before_results": True,
        "architecture": "20x13 -> Bi-LSTM -> temporal attention -> ODST-046",
        "odst046": ODST046,
        "primary_seeds": list(PRIMARY_SEEDS),
        "start": "all matched students begin from same-seed T-OPT bytes",
        "factorial": FACTORIAL,
        "no_historical_single_teacher_logit_anchor": True,
        "no_new_odst_search": True,
        "no_focal_search": True,
        "no_pairwise_ranking_search": True,
    }
    write_json(_review("00_protocol", "EDITOR012_FACTORIAL_LOCK.json"), lock)

    protocol = {
        "task_id": "EDITOR-012",
        "campaign": "EDITOR-012 TEACHER-ANCHOR PREDICTIVE RESCUE",
        "status": "PHASE_A_FROZEN_BEFORE_RESULTS",
        "scientific_question": "Does an appropriately formulated teacher anchor add predictive value beyond matched teacher initialisation?",
        "authorised_partitions": ["CERT r5.2 TRAIN", "CERT r5.2 VALIDATION"],
        "TEST_ACCESS": "PROHIBITED",
        "R51_EXECUTION": "PROHIBITED",
        "R62_EXECUTION": "PROHIBITED",
        "inner_search_uses": "EDITOR-010 INNER_TRAIN / INNER_SELECT only",
        "official_validation_never_used_to_promote": True,
        "user_mapping": {
            "n_users": EXPECTED_VAL_USERS,
            "windows_per_user": EXPECTED_VAL_WINDOWS_PER_USER,
            "malicious_users": EXPECTED_VAL_MALICIOUS_USERS,
            "expected_sha256": EXPECTED_USER_MAPPING_SHA256,
        },
        "inner_split_expected": {
            "n_inner_train": EXPECTED_INNER_TRAIN_N,
            "n_inner_select": EXPECTED_INNER_SELECT_N,
            "n_inner_train_pos": EXPECTED_INNER_TRAIN_POS,
            "n_inner_select_pos": EXPECTED_INNER_SELECT_POS,
        },
        "bootstrap": {
            "n_resamples": 2000,
            "seed": 42,
            "sampling_unit": "validation user",
            "f1_thresholds": "frozen condition thresholds; not retuned in-replicate",
        },
        "TA2_temporary_identifier": "optimised ODST + ensemble teacher predictive anchor + optional route anchor",
        "do_not_relabel_historical_C5": True,
        "frozen_before_first_training_result": True,
    }
    write_json(_review("00_protocol", "EDITOR012_PROTOCOL.json"), protocol)

    checksums = {
        "task_id": "EDITOR-012",
        "r52_test_opened": False,
        "r52_test_hashed": False,
        "inputs": [
            {
                "role": "r52_train_npz",
                "path": str(TRAIN_NPZ),
                "sha256": EXPECTED_TRAIN_SHA256,
                "status": "MATCH",
            },
            {
                "role": "r52_validation_npz",
                "path": str(VAL_NPZ),
                "sha256": EXPECTED_VAL_SHA256,
                "status": "MATCH",
            },
            {
                "role": "producing_architecture",
                "sha256": EXPECTED_ARCHITECTURE_SHA256,
                "status": "MATCH",
            },
            {
                "role": "producing_odst",
                "sha256": EXPECTED_ODST_SHA256,
                "status": "MATCH",
            },
            {
                "role": "trainonly_scaler",
                "sha256": EXPECTED_SCALER_SHA256,
                "status": "MATCH",
            },
        ],
        "denied_tensors": {
            "r52_test": {
                "canonical_relative_path": "data/processed/r5.2/tensors/r52_T20_s1_test.npz",
                "status": "HARD_DENY",
                "not_opened": True,
                "not_hashed": True,
            }
        },
        "topt_hashes": {str(k): v["sha256"] for k, v in TOPT_CHECKPOINTS.items()},
    }
    write_json(_review("00_protocol", "EDITOR012_INPUT_CHECKSUMS.json"), checksums)

    pretraining = {
        "task_id": "EDITOR-012",
        "status": "PRETRAINING",
        "frozen_utc": utc_now(),
        "review_rel": str(REVIEW_REL),
        "no_training_result_viewed": True,
    }
    write_json(_review("00_protocol", "EDITOR012_RUN_MANIFEST_PRETRAINING.json"), pretraining)
    return {
        "register": register,
        "formulations": formulations,
        "lock": lock,
        "protocol": protocol,
        "checksums": checksums,
    }
