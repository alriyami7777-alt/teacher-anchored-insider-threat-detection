"""EDITOR-011 matched confirmation orchestrator."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import torch

from .bootstrap import paired_user_cluster_mean_across_seeds
from .constants import (
    ATTENTION_LINEAR,
    BOOTSTRAP_RESAMPLES,
    BOOTSTRAP_SEED,
    ENCODER_ARCH,
    HISTORICAL,
    LAMBDA_LOGIT_C2,
    LAMBDA_LOGIT_R2,
    LAMBDA_ROUTE_C2,
    LAMBDA_ROUTE_R2,
    LR_ATTENTION,
    LR_ENCODER,
    LR_ODST,
    ODST046,
    SEEDS,
    WEIGHT_DECAY,
)
from .data import load_train_validation, make_loaders
from .evaluate import evaluate_pair, hash_gate_checkpoint
from .io_util import write_csv, write_json
from .models import (
    architecture_identity,
    assert_odst046,
    assert_teacher_student_match,
    enable_student,
    freeze_teacher,
    state_dict_sha256,
)
from .producing import (
    build_odst046_model,
    import_load_v1,
    import_set_seed,
    load_state_dict,
    pin_producing_sources,
)
from .safety import (
    EXPECTED_SCALER_SHA256,
    OUTPUT_ROOT,
    REVIEW_ROOT,
    Editor011Blocked,
    Editor011ProtocolError,
    refuse_historical_write,
    refuse_r52_test,
    sha256_bytes,
    sha256_file,
    utc_now,
)
from .train import train_student, train_teacher

RESULT_COLS = [
    "condition",
    "seed",
    "validation_PR_AUC",
    "validation_F1",
    "precision",
    "recall",
    "FP",
    "FN",
    "Brier",
    "log_loss",
    "predicted_positive_fraction",
    "best_epoch",
    "best_checkpoint_sha256",
]


def _review(*parts: str) -> Path:
    path = REVIEW_ROOT.joinpath(*parts)
    refuse_historical_write(path)
    return path


def _device() -> torch.device:
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def _set_seed(seed: int) -> None:
    set_seed = import_set_seed()
    set_seed(int(seed))
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False


def _mean(xs: list[float]) -> float:
    return float(np.mean(xs)) if xs else float("nan")


def _row_from_pack(pack: dict[str, Any]) -> dict[str, Any]:
    return {k: pack.get(k, "") for k in RESULT_COLS}


def verify_identities() -> dict[str, Any]:
    try:
        refuse_r52_test(
            r"C:\PhD\07_Projects\cert-r42-feasibility\data\processed\r5.2\tensors\r52_T20_s1_test.npz"
        )
        raise Editor011Blocked("r5.2 TEST deny-list failed to fire")
    except Editor011ProtocolError as exc:
        if "TEST" not in str(exc):
            raise
    pins = pin_producing_sources()
    if ODST046["n_trees"] != 4 or ODST046["depth"] != 4 or float(ODST046["temperature"]) != 0.5:
        raise Editor011Blocked("EDITOR011_BLOCKED_MATCHED_COMPARISON_INVALID ODST-046 lock mismatch")
    if abs(float(ODST046["lr"]) - 1e-3) > 1e-15 or float(ODST046["weight_decay"]) != 0.0:
        raise Editor011Blocked("EDITOR011_BLOCKED_MATCHED_COMPARISON_INVALID ODST-046 optimiser lock mismatch")
    if LAMBDA_ROUTE_R2 != 0.5 or LAMBDA_LOGIT_R2 != 0.0:
        raise Editor011Blocked("EDITOR011_BLOCKED_MATCHED_COMPARISON_INVALID R2 identity mismatch")
    if LAMBDA_ROUTE_C2 != 0.0 or LAMBDA_LOGIT_C2 != 0.0:
        raise Editor011Blocked("EDITOR011_BLOCKED_MATCHED_COMPARISON_INVALID C2 identity mismatch")
    teacher = build_odst046_model()
    student = build_odst046_model()
    assert_odst046(teacher)
    assert_odst046(student)
    assert_teacher_student_match(teacher, student)
    t_ident = architecture_identity(teacher)
    if t_ident["n_trees_total"] != 8 or t_ident["depth"] != 4:
        raise Editor011Blocked("EDITOR011_BLOCKED_MATCHED_COMPARISON_INVALID route tensor identity")
    return {
        "r52_test_hard_denied": True,
        "odst046_identity_verified": True,
        "route_only_r2_identity_verified": True,
        "teacher_student_architecture_matched": True,
        "producing_pins": pins,
        "architecture": t_ident,
        "lambda_logit_C2": LAMBDA_LOGIT_C2,
        "lambda_route_C2": LAMBDA_ROUTE_C2,
        "lambda_logit_R2": LAMBDA_LOGIT_R2,
        "lambda_route_R2": LAMBDA_ROUTE_R2,
        "logit_anchor_active_in_R2OPT": False,
    }


def recover_user_mapping(bundle: dict[str, Any]) -> dict[str, Any]:
    val = bundle["val"]
    n = int(len(val["y"]))
    if "user" not in val:
        return {
            "USER_MAPPING_RECOVERED": False,
            "USER_CLUSTER_BOOTSTRAP_STATUS": "UNAVAILABLE_PROVENANCE_INSUFFICIENT",
            "reason": "validation npz has no proven user field",
        }
    users = np.asarray(val["user"]).astype(str).reshape(-1)
    if users.size != n:
        return {
            "USER_MAPPING_RECOVERED": False,
            "USER_CLUSTER_BOOTSTRAP_STATUS": "UNAVAILABLE_PROVENANCE_INSUFFICIENT",
            "reason": f"user length {users.size} != validation N {n}",
        }
    y = np.asarray(val["y"]).reshape(-1)
    uniq, counts = np.unique(users, return_counts=True)
    malicious = sorted({str(u) for u, lab in zip(users, y) if lab > 0.5})
    mapping_hash = sha256_bytes(("\n".join(users.tolist())).encode("utf-8"))
    seq_ids = np.asarray(val["sequence_id"]).astype(str).reshape(-1) if "sequence_id" in val else None
    return {
        "USER_MAPPING_RECOVERED": True,
        "USER_CLUSTER_BOOTSTRAP_STATUS": "AVAILABLE",
        "n_sequences": n,
        "n_users": int(len(uniq)),
        "per_user_count_min": int(counts.min()),
        "per_user_count_max": int(counts.max()),
        "per_user_count_mean": float(counts.mean()),
        "n_malicious_users": int(len(malicious)),
        "malicious_users": malicious,
        "mapping_sha256": mapping_hash,
        "sequence_id_present": seq_ids is not None,
        "sequence_id_n": int(seq_ids.size) if seq_ids is not None else 0,
        "ordering_source": "frozen validation npz user field aligned to sequence index",
        "proven_by": "EDITOR010_INPUT_CHECKSUMS.json keys include user; same hashed validation tensor",
    }


def _build_initialized_teacher(seed: int, train_loader, device: torch.device) -> torch.nn.Module:
    spec = ATTENTION_LINEAR[seed]
    hash_gate_checkpoint(spec["checkpoint"], spec["sha256"])
    model = build_odst046_model()
    load_v1 = import_load_v1()
    load_v1(model, spec["checkpoint"])
    model.apply_frozen_node_trainability()
    model.to(device)
    x_init, _ = next(iter(train_loader))
    model.data_aware_initialize_from_batch(x_init.to(device))
    assert_odst046(model)
    return model


def run_campaign() -> dict[str, Any]:
    started = utc_now()
    identities = verify_identities()
    bundle = load_train_validation()
    user_map = recover_user_mapping(bundle)
    write_json(_review("05_statistics", "EDITOR011_VALIDATION_USER_MAPPING.json"), user_map)
    device = _device()
    pos_weight = float(bundle["pos_weight"])
    scaler_hash = EXPECTED_SCALER_SHA256
    data_split_hash = sha256_bytes(f"{bundle['train_sha256']}|{bundle['val_sha256']}".encode("utf-8"))
    arch_hash = sha256_bytes(repr(sorted(ENCODER_ARCH.items())).encode("utf-8"))
    opt_hash = sha256_bytes(
        f"Adam|enc={LR_ENCODER}|att={LR_ATTENTION}|odst={LR_ODST}|wd={WEIGHT_DECAY}".encode("utf-8")
    )

    teacher_rows = []
    teacher_ckpts: dict[int, dict[str, Any]] = {}
    teacher_models: dict[int, torch.nn.Module] = {}
    t_viable = True
    for seed in SEEDS:
        _set_seed(seed)
        train_loader, val_loader = make_loaders(bundle, seed=seed)
        model = _build_initialized_teacher(seed, train_loader, device)
        pack = train_teacher(
            seed=seed,
            model=model,
            train_loader=train_loader,
            val_loader=val_loader,
            device=device,
            pos_weight=pos_weight,
        )
        if not np.isfinite(pack["validation_PR_AUC"]) or pack["validation_PR_AUC"] < 0.70:
            t_viable = False
        teacher_rows.append(_row_from_pack(pack))
        teacher_ckpts[seed] = {
            "seed": seed,
            "checkpoint": pack["best_checkpoint"],
            "sha256": pack["best_checkpoint_sha256"],
            "best_epoch": pack["best_epoch"],
            "validation_PR_AUC": pack["validation_PR_AUC"],
            "config": dict(ENCODER_ARCH),
            "odst": dict(ODST046),
        }
        teacher_models[seed] = model
        np.save(OUTPUT_ROOT / "T-OPT" / f"seed{seed}" / "val_logits.npy", pack["student_logits"])
        np.save(OUTPUT_ROOT / "T-OPT" / f"seed{seed}" / "val_y.npy", pack["y_val"])
        write_json(OUTPUT_ROOT / "T-OPT" / f"seed{seed}" / "history.json", pack["epoch_rows"])

    write_json(_review("01_teacher_training", "EDITOR011_TOPT_CHECKPOINTS.json"), teacher_ckpts)
    write_csv(_review("01_teacher_training", "EDITOR011_TOPT_RESULTS.csv"), teacher_rows, RESULT_COLS)
    if not t_viable:
        raise Editor011Blocked("EDITOR011_BLOCKED_TOPT_NOT_REPRODUCIBLE")

    student_rows = []
    history_rows = []
    paired_proof = {}
    student_ckpts: dict[str, dict[int, dict[str, Any]]] = {"C2-OPT": {}, "R2-OPT": {}}
    val_logits: dict[tuple[str, int], np.ndarray] = {}
    val_y: np.ndarray | None = None
    mechanism_rows = []
    grad_all = []

    for seed in SEEDS:
        t_path = Path(teacher_ckpts[seed]["checkpoint"])
        t_sha = teacher_ckpts[seed]["sha256"]
        start_sha = hash_gate_checkpoint(t_path, t_sha)
        teacher = build_odst046_model()
        load_state_dict(teacher, t_path, strict=True)
        teacher.to(device)
        freeze_teacher(teacher)
        assert_odst046(teacher)
        init_hash = state_dict_sha256(teacher.state_dict())

        for condition, w_logit, w_route in (
            ("C2-OPT", LAMBDA_LOGIT_C2, LAMBDA_ROUTE_C2),
            ("R2-OPT", LAMBDA_LOGIT_R2, LAMBDA_ROUTE_R2),
        ):
            _set_seed(seed)
            train_loader, val_loader = make_loaders(bundle, seed=seed)
            student = build_odst046_model()
            load_state_dict(student, t_path, strict=True)
            student.to(device)
            enable_student(student)
            assert_teacher_student_match(teacher, student)
            start_hash = state_dict_sha256(student.state_dict())
            if start_hash != init_hash or start_sha != t_sha:
                raise Editor011Blocked("EDITOR011_BLOCKED_MATCHED_COMPARISON_INVALID paired-start hash mismatch")
            pack = train_student(
                condition=condition,
                seed=seed,
                teacher=teacher,
                student=student,
                train_loader=train_loader,
                val_loader=val_loader,
                device=device,
                pos_weight=pos_weight,
                w_logit=w_logit,
                w_route=w_route,
            )
            student_rows.append(_row_from_pack(pack))
            history_rows.extend(pack["epoch_rows"])
            grad_all.extend(pack["grad_rows"])
            student_ckpts[condition][seed] = {
                "seed": seed,
                "checkpoint": pack["best_checkpoint"],
                "sha256": pack["best_checkpoint_sha256"],
                "best_epoch": pack["best_epoch"],
                "w_logit": w_logit,
                "w_route": w_route,
                "start_checkpoint_sha256": start_sha,
            }
            val_logits[(condition, seed)] = np.asarray(pack["student_logits"])
            val_y = np.asarray(pack["y_val"])
            np.save(OUTPUT_ROOT / condition / f"seed{seed}" / "val_logits.npy", pack["student_logits"])
            np.save(OUTPUT_ROOT / condition / f"seed{seed}" / "val_y.npy", pack["y_val"])
            write_json(OUTPUT_ROOT / condition / f"seed{seed}" / "history.json", pack["epoch_rows"])
            mechanism_rows.append(
                {
                    "condition": condition,
                    "seed": seed,
                    "route_MAE": pack["route_MAE"],
                    "route_KL": pack["route_KL"],
                    "hard_route_agreement": pack["hard_route_agreement"],
                    "dominant_leaf_agreement": pack["dominant_leaf_agreement"],
                    "teacher_logit_deviation": pack["teacher_logit_deviation"],
                }
            )
            if condition == "C2-OPT":
                paired_proof[str(seed)] = {
                    "seed": seed,
                    "T_OPT_checkpoint_SHA256": t_sha,
                    "C2_start_checkpoint_SHA256": start_sha,
                    "architecture_hash": arch_hash,
                    "initial_parameter_hash": init_hash,
                    "scaler_hash": scaler_hash,
                    "data_split_hash": data_split_hash,
                    "optimizer_config_hash": opt_hash,
                }
            else:
                paired_proof[str(seed)]["R2_start_checkpoint_SHA256"] = start_sha
                if not (
                    paired_proof[str(seed)]["C2_start_checkpoint_SHA256"]
                    == paired_proof[str(seed)]["R2_start_checkpoint_SHA256"]
                    == paired_proof[str(seed)]["T_OPT_checkpoint_SHA256"]
                ):
                    raise Editor011Blocked("EDITOR011_BLOCKED_MATCHED_COMPARISON_INVALID paired-start hashes differ")

        # T-OPT teacher-relative vs itself is identity; record teacher metrics already saved.
        t_eval = evaluate_pair(
            student=teacher, teacher=teacher, loader=make_loaders(bundle, seed=seed)[1], device=device
        )
        val_logits[("T-OPT", seed)] = np.asarray(t_eval["student_logits"])

    write_json(_review("02_student_training", "EDITOR011_PAIRED_START_PROOF.json"), {
        "verified": True,
        "rule": "C2_start_checkpoint_SHA256 == R2_start_checkpoint_SHA256 == T_OPT_checkpoint_SHA256",
        "seeds": paired_proof,
    })
    write_json(_review("02_student_training", "EDITOR011_STUDENT_CHECKPOINTS.json"), student_ckpts)
    write_csv(_review("02_student_training", "EDITOR011_TRAINING_HISTORY_SUMMARY.csv"), history_rows)

    all_rows = []
    for r in teacher_rows:
        all_rows.append(r)
    all_rows.extend(student_rows)
    write_csv(_review("03_results", "EDITOR011_VALIDATION_RESULTS.csv"), all_rows, RESULT_COLS)

    def _metric(cond: str, seed: int, key: str) -> float:
        for r in all_rows:
            if r["condition"] == cond and int(r["seed"]) == seed:
                return float(r[key])
        raise KeyError(f"{cond} seed {seed} {key}")

    deltas = []
    for seed in SEEDS:
        d_pr = _metric("R2-OPT", seed, "validation_PR_AUC") - _metric("C2-OPT", seed, "validation_PR_AUC")
        d_f1 = _metric("R2-OPT", seed, "validation_F1") - _metric("C2-OPT", seed, "validation_F1")
        d_br = _metric("R2-OPT", seed, "Brier") - _metric("C2-OPT", seed, "Brier")
        d_ll = _metric("R2-OPT", seed, "log_loss") - _metric("C2-OPT", seed, "log_loss")
        d_fp = int(_metric("R2-OPT", seed, "FP") - _metric("C2-OPT", seed, "FP"))
        d_fn = int(_metric("R2-OPT", seed, "FN") - _metric("C2-OPT", seed, "FN"))
        deltas.append(
            {
                "seed": seed,
                "DELTA_PR_AUC_R2OPT_minus_C2OPT": d_pr,
                "DELTA_F1_R2OPT_minus_C2OPT": d_f1,
                "DELTA_Brier_R2OPT_minus_C2OPT": d_br,
                "DELTA_LogLoss_R2OPT_minus_C2OPT": d_ll,
                "DELTA_FP": d_fp,
                "DELTA_FN": d_fn,
            }
        )
    r2_prs = [_metric("R2-OPT", s, "validation_PR_AUC") for s in SEEDS]
    c2_prs = [_metric("C2-OPT", s, "validation_PR_AUC") for s in SEEDS]
    t_prs = [_metric("T-OPT", s, "validation_PR_AUC") for s in SEEDS]
    mean_delta = _mean([d["DELTA_PR_AUC_R2OPT_minus_C2OPT"] for d in deltas])
    pos_seeds = sum(1 for d in deltas if d["DELTA_PR_AUC_R2OPT_minus_C2OPT"] > 0)
    primary = {
        "R2_OPT_mean_PR_AUC": _mean(r2_prs),
        "C2_OPT_mean_PR_AUC": _mean(c2_prs),
        "T_OPT_mean_PR_AUC": _mean(t_prs),
        "per_seed": deltas,
        "MEAN_DELTA_R2OPT_MINUS_C2OPT": mean_delta,
        "POSITIVE_DELTA_SEEDS": f"{pos_seeds}/3",
        "R2_OPT_mean_F1": _mean([_metric("R2-OPT", s, "validation_F1") for s in SEEDS]),
        "C2_OPT_mean_F1": _mean([_metric("C2-OPT", s, "validation_F1") for s in SEEDS]),
    }
    write_json(_review("03_results", "EDITOR011_PRIMARY_MATCHED_COMPARISON.json"), primary)

    secondary_rows = []
    refs = {
        "T-OPT": _mean(t_prs),
        "Original_C2": HISTORICAL["Original_C2"]["paper_facing_mean"],
        "Original_C5": HISTORICAL["Original_C5"]["paper_facing_mean"],
        "Attention_linear": HISTORICAL["Attention_linear"]["paper_facing_mean"],
        "EDITOR009_R2": HISTORICAL["EDITOR009_R2"]["paper_facing_mean"],
        "EDITOR010_P1": HISTORICAL["EDITOR010_P1"]["mean_PR_AUC"],
        "EDITOR010_P4_ET1": HISTORICAL["EDITOR010_P4_ET1"]["paper_facing_mean"],
    }
    r2_mean = primary["R2_OPT_mean_PR_AUC"]
    for name, val in refs.items():
        secondary_rows.append(
            {
                "reference": name,
                "reference_mean_PR_AUC": val,
                "R2_OPT_mean_PR_AUC": r2_mean,
                "delta_R2OPT_minus_reference": r2_mean - val,
                "inference_status": "secondary_reference_only_not_primary_matched_inference",
            }
        )
    write_csv(_review("03_results", "EDITOR011_SECONDARY_REFERENCES.csv"), secondary_rows)

    write_csv(_review("04_mechanism", "EDITOR011_TEACHER_RELATIVE_METRICS.csv"), mechanism_rows)
    r2_mae = _mean([r["route_MAE"] for r in mechanism_rows if r["condition"] == "R2-OPT"])
    c2_mae = _mean([r["route_MAE"] for r in mechanism_rows if r["condition"] == "C2-OPT"])
    r2_kl = _mean([r["route_KL"] for r in mechanism_rows if r["condition"] == "R2-OPT"])
    c2_kl = _mean([r["route_KL"] for r in mechanism_rows if r["condition"] == "C2-OPT"])
    r2_hard = _mean([r["hard_route_agreement"] for r in mechanism_rows if r["condition"] == "R2-OPT"])
    c2_hard = _mean([r["hard_route_agreement"] for r in mechanism_rows if r["condition"] == "C2-OPT"])
    r2_leaf = _mean([r["dominant_leaf_agreement"] for r in mechanism_rows if r["condition"] == "R2-OPT"])
    c2_leaf = _mean([r["dominant_leaf_agreement"] for r in mechanism_rows if r["condition"] == "C2-OPT"])
    mechanism_ruling = {
        "R2_OPT_route_MAE_lt_C2": bool(r2_mae < c2_mae),
        "R2_OPT_route_KL_lt_C2": bool(r2_kl < c2_kl),
        "R2_OPT_hard_route_agreement_gt_C2": bool(r2_hard > c2_hard),
        "R2_OPT_dominant_leaf_agreement_gt_C2": bool(r2_leaf > c2_leaf),
        "means": {
            "R2_OPT_route_MAE": r2_mae,
            "C2_OPT_route_MAE": c2_mae,
            "R2_OPT_route_KL": r2_kl,
            "C2_OPT_route_KL": c2_kl,
            "R2_OPT_hard_route_agreement": r2_hard,
            "C2_OPT_hard_route_agreement": c2_hard,
            "R2_OPT_dominant_leaf_agreement": r2_leaf,
            "C2_OPT_dominant_leaf_agreement": c2_leaf,
        },
        "intended_mechanism": "route fidelity without logit-rank over-constraint",
        "lambda_logit": 0.0,
    }
    write_json(_review("04_mechanism", "EDITOR011_MECHANISM_RULING.json"), mechanism_ruling)
    write_json(
        _review("04_mechanism", "EDITOR011_GRADIENT_SANITY.json"),
        {
            "logit_anchor_active_in_R2OPT": False,
            "rows": [g for g in grad_all if g["condition"] == "R2-OPT"],
            "summary": {
                "logit_anchor_gradient_absent": all(
                    g.get("logit_anchor_gradient_absent", True) for g in grad_all if g["condition"] == "R2-OPT"
                ),
                "route_gradient_exists": any(
                    g.get("route_gradient_exists", False) for g in grad_all if g["condition"] == "R2-OPT"
                ),
                "task_gradient_exists": any(
                    g.get("task_gradient_exists", False) for g in grad_all if g["condition"] == "R2-OPT"
                ),
            },
        },
    )

    if user_map.get("USER_MAPPING_RECOVERED") and val_y is not None:
        users = np.asarray(bundle["val"]["user"]).astype(str)
        boot = paired_user_cluster_mean_across_seeds(
            users,
            val_y,
            [val_logits[("C2-OPT", seed)] for seed in SEEDS],
            [val_logits[("R2-OPT", seed)] for seed in SEEDS],
            n_valid=BOOTSTRAP_RESAMPLES,
            seed=BOOTSTRAP_SEED,
        )
        boot["malicious_users_represented"] = user_map["n_malicious_users"]
        boot["effective_malicious_cluster_support"] = user_map["n_malicious_users"]
        boot["three_seeds_are_not_independent_experimental_units"] = True
        boot_status = "AVAILABLE"
    else:
        boot = {
            "USER_CLUSTER_BOOTSTRAP_STATUS": "UNAVAILABLE_PROVENANCE_INSUFFICIENT",
        }
        boot_status = "UNAVAILABLE_PROVENANCE_INSUFFICIENT"
    write_json(_review("05_statistics", "EDITOR011_USER_CLUSTER_BOOTSTRAP.json"), boot)

    ci_lo = boot.get("ci95_pr_auc", [float("nan"), float("nan")])[0] if boot_status == "AVAILABLE" else float("nan")
    if _mean(r2_prs) > _mean(c2_prs) and pos_seeds == 3 and boot_status == "AVAILABLE" and ci_lo > 0:
        gate = "STRONG_ROUTE_ANCHOR_CONFIRMATION"
        rescue = "MATCHED_ROUTE_ANCHOR_RESCUE_CONFIRMED_STRONG"
    elif _mean(r2_prs) > _mean(c2_prs) and pos_seeds == 3:
        gate = "CONSISTENT_ROUTE_ANCHOR_CONFIRMATION"
        rescue = "MATCHED_ROUTE_ANCHOR_RESCUE_CONFIRMED_CONSISTENT"
    elif mean_delta > 0:
        gate = "MIXED_ROUTE_ANCHOR_EFFECT"
        rescue = "MATCHED_ROUTE_ANCHOR_RESCUE_MIXED"
    else:
        gate = "NO_ROUTE_ANCHOR_GAIN"
        rescue = "MATCHED_ROUTE_ANCHOR_RESCUE_FAILED"

    et1 = HISTORICAL["EDITOR010_P4_ET1"]["paper_facing_mean"]
    if r2_mean > et1 + 0.002:
        vs_et1 = "BETTER"
    elif r2_mean < et1 - 0.002:
        vs_et1 = "WORSE"
    else:
        vs_et1 = "SIMILAR"

    odst_rescue = {
        "ODST046_TEACHER_VIABLE": "YES" if t_viable else "NO",
        "ODST046_C2_BEATS_ORIGINAL_C2": bool(_mean(c2_prs) > HISTORICAL["Original_C2"]["paper_facing_mean"]),
        "ODST046_R2_BEATS_ORIGINAL_R2": bool(r2_mean > HISTORICAL["EDITOR009_R2"]["paper_facing_mean"]),
        "ODST046_R2_BEATS_ATTENTION_LINEAR": bool(r2_mean > HISTORICAL["Attention_linear"]["paper_facing_mean"]),
    }

    evidence = {
        "editor_issue_teacher_initialisation_is_load_bearing": {
            "evidence": "C2-OPT is the matched teacher-initialisation-only control under ODST-046.",
            "C2_OPT_mean_PR_AUC": _mean(c2_prs),
        },
        "editor_issue_original_C5_gives_almost_no_incremental_gain": {
            "evidence": "original C5 retained the antagonistic static logit anchor.",
            "EDITOR009_gradient": "cos(task, logit anchor) ≈ -0.25; route cosine ≈ +0.15",
            "repaired_condition": "R2-OPT removes logit anchoring (lambda_logit=0).",
        },
        "editor_issue_is_anchoring_itself_useful": {
            "answer_source": "R2-OPT versus C2-OPT only",
            "PRIMARY_ROUTE_ANCHOR_CONFIRMATION": gate,
            "mean_delta": mean_delta,
            "positive_delta_seeds": f"{pos_seeds}/3",
        },
        "editor_issue_ODST_optimisation": {
            "evidence": "EDITOR-010 selected ODST-046; EDITOR-011 tests repaired anchoring under that configuration.",
        },
        "editor_issue_random_init_collapse": {
            "preserve_EDITOR009": "random encoder + ODST fails to enter viable basin; raw-index route anchoring is additionally invalid under random initialisation. Route indexing alone did not cause the collapse.",
        },
        "R2_OPT_is_not_historical_C5": True,
    }
    write_json(_review("06_paper_handover", "EDITOR011_EDITOR_RESPONSE_EVIDENCE.json"), evidence)

    next_action = (
        "Freeze T-OPT / C2-OPT / R2-OPT identities and wait for authorised final-model / final-test strategy."
        if rescue in {
            "MATCHED_ROUTE_ANCHOR_RESCUE_CONFIRMED_STRONG",
            "MATCHED_ROUTE_ANCHOR_RESCUE_CONFIRMED_CONSISTENT",
        }
        else "Return the matched R2-OPT versus C2-OPT result honestly. Do not launch additional rescue searches. ET1 remains the strongest teacher-guided EDITOR-010 candidate."
    )
    best_route = "R2-OPT" if r2_mean >= HISTORICAL["EDITOR009_R2"]["paper_facing_mean"] else "EDITOR009_R2"
    if gate == "NO_ROUTE_ANCHOR_GAIN":
        best_route = "none_confirmed_beyond_C2-OPT"

    rescue_gate = {
        "EDITOR011_PAPER_RESCUE_GATE": rescue,
        "PRIMARY_ROUTE_ANCHOR_CONFIRMATION": gate,
        "R2_OPT_VS_ET1": vs_et1,
        "odst_rescue_gate": odst_rescue,
        "BEST_CURRENT_ROUTE_ANCHORED_CONDITION": best_route,
        "NEXT_RECOMMENDED_ACTION": next_action,
        "r52_test_accessed": False,
    }
    write_json(_review("06_paper_handover", "EDITOR011_PAPER_RESCUE_GATE.json"), rescue_gate)
    handover_md = "\n".join(
        [
            "# EDITOR-011 paper rescue handover",
            "",
            f"Primary confirmation: **{gate}**",
            f"Paper rescue gate: **{rescue}**",
            "",
            f"R2-OPT mean PR-AUC = {r2_mean:.6f}",
            f"C2-OPT mean PR-AUC = {_mean(c2_prs):.6f}",
            f"Mean Δ(R2-OPT − C2-OPT) = {mean_delta:.6f} ({pos_seeds}/3 seeds positive)",
            "",
            "R2-OPT is a new repaired condition. It is not historical C5.",
            "ET1 remains ensemble logit distillation, not route anchoring.",
            "",
            next_action,
            "",
        ]
    )
    path_md = _review("06_paper_handover", "EDITOR011_PAPER_RESCUE_HANDOVER.md")
    refuse_historical_write(path_md)
    path_md.write_text(handover_md, encoding="utf-8")

    manifest = {
        "task_id": "EDITOR-011",
        "status": "COMPLETE",
        "started_utc": started,
        "finished_utc": utc_now(),
        "r52_test_accessed": False,
        "r51_rerun": False,
        "r62_rerun": False,
        "identities": identities,
        "T_OPT_VIABLE": "YES" if t_viable else "NO",
        "PRIMARY_ROUTE_ANCHOR_CONFIRMATION": gate,
        "EDITOR011_PAPER_RESCUE_GATE": rescue,
        "paired_start_verified": True,
        "device": str(device),
    }
    write_json(_review("EDITOR011_RUN_MANIFEST.json"), manifest)
    return {
        "identities": identities,
        "primary": primary,
        "user_map": user_map,
        "boot": boot,
        "gate": gate,
        "rescue": rescue,
        "mechanism": mechanism_ruling,
        "odst_rescue": odst_rescue,
        "vs_et1": vs_et1,
        "best_route": best_route,
        "next_action": next_action,
        "teacher_ckpts": teacher_ckpts,
        "t_prs": t_prs,
        "c2_prs": c2_prs,
        "r2_prs": r2_prs,
        "deltas": deltas,
        "boot_status": boot_status,
    }


def finish_from_artifacts() -> dict[str, Any]:
    """Complete bootstrap and paper handover from saved logits after training."""
    import json

    primary = json.loads(_review("03_results", "EDITOR011_PRIMARY_MATCHED_COMPARISON.json").read_text(encoding="utf-8"))
    user_map = json.loads(_review("05_statistics", "EDITOR011_VALIDATION_USER_MAPPING.json").read_text(encoding="utf-8"))
    mechanism_ruling = json.loads(_review("04_mechanism", "EDITOR011_MECHANISM_RULING.json").read_text(encoding="utf-8"))
    bundle = load_train_validation()
    users = np.asarray(bundle["val"]["user"]).astype(str)
    y = np.asarray(bundle["val"]["y"])
    c2s = [np.load(OUTPUT_ROOT / "C2-OPT" / f"seed{s}" / "val_logits.npy") for s in SEEDS]
    r2s = [np.load(OUTPUT_ROOT / "R2-OPT" / f"seed{s}" / "val_logits.npy") for s in SEEDS]
    print("[EDITOR-011] starting user-cluster bootstrap", flush=True)
    boot = paired_user_cluster_mean_across_seeds(
        users, y, c2s, r2s, n_valid=BOOTSTRAP_RESAMPLES, seed=BOOTSTRAP_SEED
    )
    boot["malicious_users_represented"] = user_map["n_malicious_users"]
    boot["effective_malicious_cluster_support"] = user_map["n_malicious_users"]
    boot["three_seeds_are_not_independent_experimental_units"] = True
    write_json(_review("05_statistics", "EDITOR011_USER_CLUSTER_BOOTSTRAP.json"), boot)
    print("[EDITOR-011] bootstrap complete", flush=True)

    r2_mean = float(primary["R2_OPT_mean_PR_AUC"])
    c2_mean = float(primary["C2_OPT_mean_PR_AUC"])
    t_mean = float(primary["T_OPT_mean_PR_AUC"])
    mean_delta = float(primary["MEAN_DELTA_R2OPT_MINUS_C2OPT"])
    pos_seeds = int(str(primary["POSITIVE_DELTA_SEEDS"]).split("/")[0])
    ci_lo = float(boot["ci95_pr_auc"][0])
    if r2_mean > c2_mean and pos_seeds == 3 and ci_lo > 0:
        gate = "STRONG_ROUTE_ANCHOR_CONFIRMATION"
        rescue = "MATCHED_ROUTE_ANCHOR_RESCUE_CONFIRMED_STRONG"
    elif r2_mean > c2_mean and pos_seeds == 3:
        gate = "CONSISTENT_ROUTE_ANCHOR_CONFIRMATION"
        rescue = "MATCHED_ROUTE_ANCHOR_RESCUE_CONFIRMED_CONSISTENT"
    elif mean_delta > 0:
        gate = "MIXED_ROUTE_ANCHOR_EFFECT"
        rescue = "MATCHED_ROUTE_ANCHOR_RESCUE_MIXED"
    else:
        gate = "NO_ROUTE_ANCHOR_GAIN"
        rescue = "MATCHED_ROUTE_ANCHOR_RESCUE_FAILED"

    et1 = HISTORICAL["EDITOR010_P4_ET1"]["paper_facing_mean"]
    if r2_mean > et1 + 0.002:
        vs_et1 = "BETTER"
    elif r2_mean < et1 - 0.002:
        vs_et1 = "WORSE"
    else:
        vs_et1 = "SIMILAR"

    odst_rescue = {
        "ODST046_TEACHER_VIABLE": "YES",
        "ODST046_C2_BEATS_ORIGINAL_C2": bool(c2_mean > HISTORICAL["Original_C2"]["paper_facing_mean"]),
        "ODST046_R2_BEATS_ORIGINAL_R2": bool(r2_mean > HISTORICAL["EDITOR009_R2"]["paper_facing_mean"]),
        "ODST046_R2_BEATS_ATTENTION_LINEAR": bool(r2_mean > HISTORICAL["Attention_linear"]["paper_facing_mean"]),
    }
    evidence = {
        "editor_issue_teacher_initialisation_is_load_bearing": {
            "evidence": "C2-OPT is the matched teacher-initialisation-only control under ODST-046.",
            "C2_OPT_mean_PR_AUC": c2_mean,
        },
        "editor_issue_original_C5_gives_almost_no_incremental_gain": {
            "evidence": "original C5 retained the antagonistic static logit anchor.",
            "EDITOR009_gradient": "cos(task, logit anchor) ≈ -0.25; route cosine ≈ +0.15",
            "repaired_condition": "R2-OPT removes logit anchoring (lambda_logit=0).",
        },
        "editor_issue_is_anchoring_itself_useful": {
            "answer_source": "R2-OPT versus C2-OPT only",
            "PRIMARY_ROUTE_ANCHOR_CONFIRMATION": gate,
            "mean_delta": mean_delta,
            "positive_delta_seeds": f"{pos_seeds}/3",
        },
        "editor_issue_ODST_optimisation": {
            "evidence": "EDITOR-010 selected ODST-046; EDITOR-011 tests repaired anchoring under that configuration.",
        },
        "editor_issue_random_init_collapse": {
            "preserve_EDITOR009": "random encoder + ODST fails to enter viable basin; raw-index route anchoring is additionally invalid under random initialisation. Route indexing alone did not cause the collapse.",
        },
        "R2_OPT_is_not_historical_C5": True,
    }
    write_json(_review("06_paper_handover", "EDITOR011_EDITOR_RESPONSE_EVIDENCE.json"), evidence)
    next_action = (
        "Freeze T-OPT / C2-OPT / R2-OPT identities and wait for authorised final-model / final-test strategy."
        if rescue in {
            "MATCHED_ROUTE_ANCHOR_RESCUE_CONFIRMED_STRONG",
            "MATCHED_ROUTE_ANCHOR_RESCUE_CONFIRMED_CONSISTENT",
        }
        else "Return the matched R2-OPT versus C2-OPT result honestly. Do not launch additional rescue searches. ET1 remains the strongest teacher-guided EDITOR-010 candidate."
    )
    best_route = "R2-OPT" if r2_mean >= HISTORICAL["EDITOR009_R2"]["paper_facing_mean"] else "EDITOR009_R2"
    if gate == "NO_ROUTE_ANCHOR_GAIN":
        best_route = "none_confirmed_beyond_C2-OPT"
    rescue_gate = {
        "EDITOR011_PAPER_RESCUE_GATE": rescue,
        "PRIMARY_ROUTE_ANCHOR_CONFIRMATION": gate,
        "R2_OPT_VS_ET1": vs_et1,
        "odst_rescue_gate": odst_rescue,
        "BEST_CURRENT_ROUTE_ANCHORED_CONDITION": best_route,
        "NEXT_RECOMMENDED_ACTION": next_action,
        "r52_test_accessed": False,
        "T_OPT_mean_PR_AUC": t_mean,
        "mechanism": mechanism_ruling,
        "bootstrap_ci95_pr_auc": boot["ci95_pr_auc"],
    }
    write_json(_review("06_paper_handover", "EDITOR011_PAPER_RESCUE_GATE.json"), rescue_gate)
    path_md = _review("06_paper_handover", "EDITOR011_PAPER_RESCUE_HANDOVER.md")
    path_md.write_text(
        "\n".join(
            [
                "# EDITOR-011 paper rescue handover",
                "",
                f"Primary confirmation: **{gate}**",
                f"Paper rescue gate: **{rescue}**",
                "",
                f"R2-OPT mean PR-AUC = {r2_mean:.6f}",
                f"C2-OPT mean PR-AUC = {c2_mean:.6f}",
                f"Mean Δ(R2-OPT − C2-OPT) = {mean_delta:.6f} ({pos_seeds}/3 seeds positive)",
                f"User-cluster 95% CI = {boot['ci95_pr_auc']}",
                "",
                "R2-OPT is a new repaired condition. It is not historical C5.",
                "ET1 remains ensemble logit distillation, not route anchoring.",
                "",
                next_action,
                "",
            ]
        ),
        encoding="utf-8",
    )
    write_json(
        _review("EDITOR011_RUN_MANIFEST.json"),
        {
            "task_id": "EDITOR-011",
            "status": "COMPLETE",
            "finished_utc": utc_now(),
            "r52_test_accessed": False,
            "r51_rerun": False,
            "r62_rerun": False,
            "T_OPT_VIABLE": "YES",
            "PRIMARY_ROUTE_ANCHOR_CONFIRMATION": gate,
            "EDITOR011_PAPER_RESCUE_GATE": rescue,
            "paired_start_verified": True,
            "user_mapping_recovered": True,
            "USER_CLUSTER_BOOTSTRAP_STATUS": "AVAILABLE",
        },
    )
    return {"gate": gate, "rescue": rescue, "boot": boot, "primary": primary}


def main() -> None:
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--finish-from-artifacts":
        finish_from_artifacts()
        return
    run_campaign()


if __name__ == "__main__":
    main()
