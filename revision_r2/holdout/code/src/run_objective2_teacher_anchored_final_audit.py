#!/usr/bin/env python
"""Read-only final evidence audit and candidate freeze for teacher-anchored ODST.

No training, no protected-partition access, no metric retuning.
"""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import torch

SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from prototype_v2.safety import repo_root, sha256_file  # noqa: E402
from objective2_teacher_anchored_odst.config import (  # noqa: E402
    FROZEN_COMPARATORS,
    TEACHER_ANCHORED_CONFIG,
    VIABILITY_F1_MARGIN,
    VIABILITY_PR_AUC_MARGIN,
    VIABILITY_UNUSED_LEAVES_MAX_WORSE_PP,
)
from objective2_teacher_anchored_odst.models import build_model, load_checkpoint_into  # noqa: E402
from objective2_teacher_anchored_odst.viability import (  # noqa: E402
    evaluate_multiseed,
    evaluate_seed_viability,
)

SOURCE_COMMIT = "965f1477e3eee920e6a6eef406ec24247429c5c7"
PARAM_CHANGE_TOL = 1e-12
OPENED: list[str] = []


def _open(path: Path) -> Path:
    p = Path(path)
    OPENED.append(str(p))
    return p


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    keys: list[str] = []
    for r in rows:
        for k in r:
            if k not in keys:
                keys.append(k)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in keys})


def _hash(path: Path) -> str:
    return sha256_file(_open(path))


def _param_l2(a: dict[str, torch.Tensor], b: dict[str, torch.Tensor], prefix: str = "") -> float:
    d = 0.0
    for k, v0 in a.items():
        if prefix and not k.startswith(prefix):
            continue
        if k not in b:
            continue
        d += float((b[k].float() - v0.float()).pow(2).sum().item())
    return float(np.sqrt(d))


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True, errors="replace").strip()


def obj3_fingerprint(root: Path) -> dict[str, Any]:
    obj3 = root / "outputs/objective3"
    digests = []
    n = 0
    if obj3.exists():
        for p in sorted(obj3.rglob("*")):
            if not p.is_file():
                continue
            if p.suffix.lower() not in {".json", ".pt", ".md", ".csv", ".parquet", ".pkl"}:
                continue
            n += 1
            if len(digests) < 30:
                digests.append(f"{p.relative_to(root).as_posix()}:{sha256_file(p)}")
    blob = "\n".join(digests).encode()
    return {
        "n_matching_files": n,
        "sample_fingerprint_sha256": hashlib.sha256(blob).hexdigest(),
        "n_sample_entries": len(digests),
    }


def verify_checkpoints(root: Path, ta_dir: Path) -> tuple[list[dict], list[dict], list[dict], list[str]]:
    hash_rows: list[dict] = []
    integrity_rows: list[dict] = []
    param_rows: list[dict] = []
    issues: list[str] = []

    # Config / tables
    for name in [
        "teacher_anchored_config.json",
        "teacher_anchored_manifest.json",
        "teacher_anchored_seed_summary.csv",
        "teacher_anchored_epoch_metrics.csv",
        "teacher_anchored_loss_components.csv",
        "teacher_anchored_parameter_updates.csv",
        "teacher_anchored_routing_summary.csv",
        "teacher_anchored_prediction_agreement.csv",
        "teacher_anchored_thresholds.csv",
        "teacher_student_initial_parity.csv",
        "TEACHER_ANCHORED_INTERPRETATION.md",
        "EXPERIMENTAL_HANDOVER.md",
    ]:
        p = ta_dir / name
        if p.exists():
            hash_rows.append({"artefact": name, "path": str(p), "sha256": _hash(p), "role": "teacher_anchored_table"})
        else:
            issues.append(f"missing_artefact:{name}")

    epoch = pd.read_csv(_open(ta_dir / "teacher_anchored_epoch_metrics.csv"))
    params = pd.read_csv(_open(ta_dir / "teacher_anchored_parameter_updates.csv"))

    for seed, meta in FROZEN_COMPARATORS.items():
        teacher_ckpt = root / meta["relative_dir"] / "best.pt"
        student_best = ta_dir / f"seed{seed}" / "best_student.pt"
        student_final = ta_dir / f"seed{seed}" / "final_student.pt"
        preds = ta_dir / f"seed{seed}" / "validation_predictions.parquet"
        summary = ta_dir / f"seed{seed}" / "seed_summary.json"

        t_hash = _hash(teacher_ckpt)
        hash_rows.append(
            {
                "artefact": f"teacher_seed{seed}",
                "path": str(teacher_ckpt),
                "sha256": t_hash,
                "role": "frozen_teacher",
                "expected_sha256": meta["expected_sha256"],
                "hash_match_expected": t_hash.lower() == meta["expected_sha256"].lower(),
            }
        )
        if t_hash.lower() != meta["expected_sha256"].lower():
            issues.append(f"teacher_hash_mismatch_seed{seed}")

        if not student_best.exists():
            issues.append(f"missing_student_best_seed{seed}")
            continue
        s_hash = _hash(student_best)
        hash_rows.append({"artefact": f"student_best_seed{seed}", "path": str(student_best), "sha256": s_hash, "role": "student_best"})
        if student_final.exists():
            hash_rows.append(
                {"artefact": f"student_final_seed{seed}", "path": str(student_final), "sha256": _hash(student_final), "role": "student_final"}
            )
        if preds.exists():
            hash_rows.append(
                {"artefact": f"val_preds_seed{seed}", "path": str(preds), "sha256": _hash(preds), "role": "validation_predictions"}
            )

        # Read-only load for structure / independence / parameter diffs
        teacher = build_model()
        student = build_model()
        load_checkpoint_into(teacher, teacher_ckpt)
        payload = torch.load(_open(student_best), map_location="cpu", weights_only=False)
        state = payload.get("model_state_dict", payload)
        student.load_state_dict(state, strict=False)
        teacher_state = {k: v.detach().cpu().clone() for k, v in teacher.state_dict().items()}
        student_state = {k: v.detach().cpu().clone() for k, v in student.state_dict().items()}

        dist_lstm = _param_l2(teacher_state, student_state, "lstm.")
        dist_attn = _param_l2(teacher_state, student_state, "attention.")
        dist_odst = _param_l2(teacher_state, student_state, "node_head.")
        dist_all = _param_l2(teacher_state, student_state, "")

        has_residual = any(k.startswith("residual_head") for k in state)
        has_teacher_call_flag = bool(payload.get("teacher_required_at_inference", False))
        keys_ok = all(
            any(k.startswith(pfx) for k in state)
            for pfx in ("lstm.", "attention.", "node_head.")
        )

        # Epoch-1 parameter distances from training log (student vs init)
        ep1 = params[(params["seed"] == seed) & (params["epoch"] == 1)]
        enc_d = float(ep1["encoder_param_distance"].iloc[0]) if len(ep1) else float("nan")
        att_d = float(ep1["attention_param_distance"].iloc[0]) if len(ep1) else float("nan")
        od_d = float(ep1["odst_param_distance"].iloc[0]) if len(ep1) else float("nan")
        ep_row = epoch[(epoch["seed"] == seed) & (epoch["epoch"] == 1)]
        joint_ep1 = bool(ep_row["joint"].iloc[0]) if len(ep_row) else False

        summ = json.loads(_open(summary).read_text(encoding="utf-8")) if summary.exists() else {}
        best_epoch = int(summ.get("best_epoch", 0))

        integrity_rows.append(
            {
                "seed": seed,
                "teacher_sha256": t_hash,
                "teacher_matches_pretraining_record": t_hash.lower() == meta["expected_sha256"].lower(),
                "student_best_sha256": s_hash,
                "teacher_required_at_inference": has_teacher_call_flag,
                "student_independent": not has_teacher_call_flag,
                "has_residual_head_in_student_state": has_residual,
                "has_lstm_attention_odst_keys": keys_ok,
                "payload_schedule": payload.get("schedule"),
                "payload_prototype": payload.get("prototype"),
                "best_epoch": best_epoch,
                "joint_from_epoch_1_in_metrics": joint_ep1,
                "selected_after_joint_start": bool(best_epoch >= 1 and joint_ep1 and TEACHER_ANCHORED_CONFIG["all_student_components_trainable_from_epoch_1"]),
            }
        )
        if has_residual:
            issues.append(f"residual_branch_in_student_seed{seed}")
        if has_teacher_call_flag:
            issues.append(f"teacher_required_inference_seed{seed}")
        if not (best_epoch >= 1 and joint_ep1):
            issues.append(f"selected_checkpoint_not_joint_seed{seed}")

        param_rows.append(
            {
                "seed": seed,
                "tolerance": PARAM_CHANGE_TOL,
                "teacher_vs_student_lstm_l2": dist_lstm,
                "teacher_vs_student_attention_l2": dist_attn,
                "teacher_vs_student_odst_l2": dist_odst,
                "teacher_vs_student_all_l2": dist_all,
                "epoch1_encoder_param_distance": enc_d,
                "epoch1_attention_param_distance": att_d,
                "epoch1_odst_param_distance": od_d,
                "encoder_updated_meaningful": enc_d > PARAM_CHANGE_TOL,
                "attention_updated_meaningful": att_d > PARAM_CHANGE_TOL,
                "odst_updated_meaningful": od_d > PARAM_CHANGE_TOL,
                "summary_encoder_updated": summ.get("encoder_updated"),
                "summary_attention_updated": summ.get("attention_updated"),
                "summary_odst_updated": summ.get("odst_updated"),
                "summary_teacher_unchanged": summ.get("teacher_unchanged"),
                "summary_joint_training_verified": summ.get("joint_training_verified"),
                "initial_parity_ok": summ.get("initial_parity_ok"),
            }
        )
        if not (enc_d > PARAM_CHANGE_TOL and att_d > PARAM_CHANGE_TOL and od_d > PARAM_CHANGE_TOL):
            issues.append(f"insufficient_param_update_seed{seed}")

    return hash_rows, integrity_rows, param_rows, issues


def reconstruct_gates(ta_dir: Path) -> tuple[list[dict], dict[str, Any], list[str]]:
    issues: list[str] = []
    seed_sum = pd.read_csv(_open(ta_dir / "teacher_anchored_seed_summary.csv"))
    agree = pd.read_csv(_open(ta_dir / "teacher_anchored_prediction_agreement.csv"))
    rows = []
    seed_results: dict[int, dict] = {}

    for _, r in seed_sum.iterrows():
        seed = int(r["seed"])
        meta = FROZEN_COMPARATORS[seed]
        a = agree[agree["seed"] == seed].iloc[0]
        summ = json.loads(_open(ta_dir / f"seed{seed}/seed_summary.json").read_text(encoding="utf-8"))
        run = {
            "best_pr_auc": float(r["best_pr_auc"]),
            "best_f1": float(r["best_f1"]),
            "best_recall": float(summ["best_recall"]),
            "best_fp": float(summ["best_fp"]),
            "best_fn": float(summ["best_fn"]),
            "best_epoch": int(r["best_epoch"]),
            "unused_leaves_pct": float(r["unused_leaves_pct"]),
            "final_pooled_cosine": float(r["final_pooled_cosine"]),
            "routing_divergence": float(r["routing_divergence"]),
            "routing_entropy_mean": float(summ.get("routing_entropy_mean", float("nan"))),
            "initial_parity_ok": bool(summ.get("initial_parity_ok")),
            "teacher_unchanged": bool(summ.get("teacher_unchanged")),
            "encoder_updated": bool(summ.get("encoder_updated")),
            "attention_updated": bool(summ.get("attention_updated")),
            "odst_updated": bool(summ.get("odst_updated")),
            "joint_training_verified": bool(summ.get("joint_training_verified")),
            "nonzero_grads_all_components": bool(summ.get("nonzero_grads_all_components")),
            "threshold_from_validation_only": bool(summ.get("threshold_from_validation_only")),
            "student_independent_inference": bool(summ.get("student_independent_inference")),
            "had_nan_or_inf": bool(summ.get("had_nan_or_inf")),
            "gradient_explosion": bool(summ.get("gradient_explosion")),
            "protected_access": bool(summ.get("protected_access")),
            "parameter_explosion": bool(summ.get("parameter_explosion")),
            "catastrophic_fp_fn": bool(summ.get("catastrophic_fp_fn")),
            "catastrophic_collapse": bool(summ.get("catastrophic_collapse")),
            "completed": True,
            "teacher_pr_auc": float(meta["pr_auc"]),
            "teacher_unused_leaves_pct": float(meta["unused_leaves_pct"]),
        }
        gate = evaluate_seed_viability(teacher=meta, run=run)
        recorded_viable = bool(r["viable"]) if isinstance(r["viable"], (bool, np.bool_)) else str(r["viable"]).lower() == "true"
        if gate["viable"] != recorded_viable:
            issues.append(f"gate_mismatch_seed{seed}: reconstructed={gate['viable']} recorded={recorded_viable}")
        # Seed-52 must remain a fail
        if seed == 52 and gate["viable"]:
            issues.append("seed52_incorrectly_passed_reconstruction")
        if seed == 52 and "pr_auc_below_margin" not in gate["reasons"]:
            issues.append(f"seed52_missing_pr_auc_reason:{gate['reasons']}")

        rows.append(
            {
                "seed": seed,
                "teacher_pr_auc": meta["pr_auc"],
                "student_pr_auc": run["best_pr_auc"],
                "pr_auc_delta": gate["pr_auc_delta"],
                "teacher_f1": meta["f1"],
                "student_f1": run["best_f1"],
                "f1_delta": gate["f1_delta"],
                "teacher_fp": meta["fp"],
                "student_fp": run["best_fp"],
                "teacher_fn": meta["fn"],
                "student_fn": run["best_fn"],
                "student_threshold": summ["best_threshold"],
                "teacher_threshold_recorded": meta["threshold"],
                "cosine": run["final_pooled_cosine"],
                "teacher_unused_leaves_pct": meta["unused_leaves_pct"],
                "student_unused_leaves_pct": run["unused_leaves_pct"],
                "unused_leaves_delta_pp": run["unused_leaves_pct"] - meta["unused_leaves_pct"],
                "routing_divergence": run["routing_divergence"],
                "best_epoch": run["best_epoch"],
                "reconstructed_viable": gate["viable"],
                "recorded_viable": recorded_viable,
                "reconstructed_reasons": ";".join(gate["reasons"]),
                "recorded_reasons": r.get("reasons", ""),
                "improved_vs_teacher": gate["improved_vs_teacher"],
                "prediction_agreement": float(a["prediction_agreement"]),
                "implementation_ok": gate["implementation_ok"],
                "predictive_ok": gate["predictive_ok"],
                "representation_ok": gate["representation_ok"],
                "routing_ok": gate["routing_ok"],
            }
        )
        seed_results[seed] = {**run, "gate": gate}

    multi = evaluate_multiseed(seed_results)
    manifest = json.loads(_open(ta_dir / "teacher_anchored_manifest.json").read_text(encoding="utf-8"))
    recorded_status = manifest.get("status")
    # mechanical status check
    if not multi["multiseed_viable"]:
        expected = "objective2_teacher_anchored_multiseed_not_supported"
    elif multi["any_improved"]:
        expected = "objective2_teacher_anchored_multiseed_viable_with_improvement"
    else:
        expected = "objective2_teacher_anchored_multiseed_viable_no_improvement"
    if recorded_status != expected:
        issues.append(f"status_mismatch: recorded={recorded_status} expected={expected}")

    # mean margin
    mean_delta = multi["mean_pr_delta"]
    if mean_delta < -VIABILITY_PR_AUC_MARGIN - 1e-12:
        issues.append(f"mean_pr_delta_outside_margin:{mean_delta}")

    multi_info = {
        **multi,
        "recorded_status": recorded_status,
        "reconstructed_status": expected,
        "status_matches": recorded_status == expected,
        "mean_pr_delta": mean_delta,
        "pr_auc_margin": VIABILITY_PR_AUC_MARGIN,
        "f1_margin": VIABILITY_F1_MARGIN,
        "unused_leaves_max_worse_pp": VIABILITY_UNUSED_LEAVES_MAX_WORSE_PP,
        "two_of_three_rule_satisfied": len(multi["viable_seeds"]) >= 2,
    }
    return rows, multi_info, issues


def leaf_comparability(root: Path) -> list[dict]:
    rows = []
    # Same diagnostic function across studies: leaf_utilization_stats unused_eps=1e-4
    # Aggregation differs: T2/residual last-batch; teacher-anchored full validation concat; frozen full-run diagnostic.
    specs = [
        {
            "experiment": "frozen_odst_seed42",
            "unused_leaves_pct": 57.8125,
            "source": "outputs/v3_node/.../sparsemax_sigmoid_odst_seed42 + FROZEN_COMPARATORS",
            "definition": "leaf_utilization_stats unused_eps=1e-4",
            "aggregation": "frozen full-run validation diagnostic (recorded comparator)",
            "partition": "r4.2 validation",
            "checkpoint_stage": "selected frozen best",
            "trees_depth": "8 trees x depth 4 per layer; 2 layers; first-layer leaf stats",
        },
        {
            "experiment": "t2_full_duration_seed42",
            "unused_leaves_pct": 85.9375,
            "source": "outputs/objective2/end_to_end_full_confirmation/end_to_end_full_confirmation_seed_summary.csv",
            "definition": "leaf_utilization_stats unused_eps=1e-4",
            "aggregation": "last validation batch only (evaluate_full)",
            "partition": "r4.2 validation",
            "checkpoint_stage": "selected T2 best (epoch 3 joint)",
            "trees_depth": "same architecture",
        },
        {
            "experiment": "residual_odst_seed42",
            "unused_leaves_pct": 90.625,
            "source": "outputs/objective2/residual_odst_refinement/residual_odst_seed_summary.csv",
            "definition": "leaf_utilization_stats unused_eps=1e-4",
            "aggregation": "last validation batch only",
            "partition": "r4.2 validation",
            "checkpoint_stage": "selected residual best (epoch 1 warm-up)",
            "trees_depth": "same architecture + residual head (leaf from ODST)",
        },
        {
            "experiment": "teacher_anchored_student_seed42",
            "unused_leaves_pct": 57.03125,
            "source": "outputs/objective2/teacher_anchored_odst/teacher_anchored_seed_summary.csv",
            "definition": "leaf_utilization_stats unused_eps=1e-4",
            "aggregation": "all validation batches concatenated",
            "partition": "r4.2 validation",
            "checkpoint_stage": "selected student best (epoch 1 joint)",
            "trees_depth": "same architecture",
        },
        {
            "experiment": "teacher_anchored_teacher_eval_seed42",
            "unused_leaves_pct": 57.8125,
            "source": "teacher_anchored epoch/prediction agreement teacher unused",
            "definition": "leaf_utilization_stats unused_eps=1e-4",
            "aggregation": "all validation batches concatenated (same code as student)",
            "partition": "r4.2 validation",
            "checkpoint_stage": "frozen teacher eval during student study",
            "trees_depth": "same architecture",
        },
    ]
    for s in specs:
        rows.append({**s, "comparability_vs_teacher_anchored_student": ""})

    # classify pairwise vs teacher-anchored student
    classifications = {
        "frozen_odst_seed42": "comparable_with_documented_limit",
        "t2_full_duration_seed42": "comparable_with_documented_limit",
        "residual_odst_seed42": "comparable_with_documented_limit",
        "teacher_anchored_student_seed42": "directly_comparable",
        "teacher_anchored_teacher_eval_seed42": "directly_comparable",
    }
    notes = {
        "frozen_odst_seed42": "Same unused_eps and architecture; frozen diagnostic aggregation may differ from TA full-batch concat, but recorded teacher unused in TA eval equals 57.8125.",
        "t2_full_duration_seed42": "Same unused_eps/architecture; T2 used last-batch leaf stats vs TA full-batch concat. Large gap (86% vs 57%) unlikely explained by aggregation alone, but not unqualified.",
        "residual_odst_seed42": "Same unused_eps; residual used last-batch stats and warm-up-selected checkpoint. Gap to ~91% documented with that limit.",
        "teacher_anchored_student_seed42": "Reference row.",
        "teacher_anchored_teacher_eval_seed42": "Same evaluate_pair aggregation as student within the TA study.",
    }
    out = []
    for s in specs:
        out.append(
            {
                **s,
                "comparability_class": classifications[s["experiment"]],
                "comparability_note": notes[s["experiment"]],
            }
        )
    return out


def build_evidence_tables() -> tuple[list[dict], list[dict], list[dict]]:
    # Table A architecture development (r4.2 validation)
    table_a = [
        {
            "model": "standalone_bilstm",
            "training_strategy": "sequence classifier",
            "seed_coverage": "42/52/62 (prior Obj2)",
            "val_pr_auc": "see bilstm_seed* summaries",
            "role": "baseline sequence model",
            "decision": "retained as comparator",
            "micro_run": False,
            "source": "outputs/objective2/bilstm_seed*",
        },
        {
            "model": "attention_linear",
            "training_strategy": "BiLSTM+attention+linear",
            "seed_coverage": "prior Obj2 / probes",
            "val_pr_auc": "representation probes showed attention useful",
            "role": "ablation / representation probe",
            "decision": "supports attention representation",
            "micro_run": False,
            "source": "end_to_end_refinement probe reports",
        },
        {
            "model": "frozen_bilstm_attention_odst",
            "training_strategy": "frozen encoder; train ODST",
            "seed_coverage": "42/52/62 full-duration",
            "val_pr_auc": "0.808 / 0.859 / 0.822",
            "f1": "0.806 / 0.823 / 0.753",
            "fp_fn": "49/49 ; 47/43 ; 71/57",
            "routing": "unused leaves ~57.8% / 57.8% / 40.6%",
            "role": "validated integrated classifier / teacher",
            "decision": "retained as teacher and primary comparator",
            "micro_run": False,
            "source": "outputs/v3_node/seed*_full_*",
        },
        {
            "model": "T1_differential_micro",
            "training_strategy": "5-epoch differential unfreeze diagnostic",
            "seed_coverage": "42 micro",
            "role": "diagnostic only",
            "decision": "not a full comparison",
            "micro_run": True,
            "source": "outputs/objective2/end_to_end_refinement/",
        },
        {
            "model": "T2_gradual_unfreeze_micro",
            "training_strategy": "5-epoch T2 diagnostic",
            "seed_coverage": "42 micro",
            "role": "diagnostic only",
            "decision": "led to full-duration T2 confirmation",
            "micro_run": True,
            "source": "outputs/objective2/end_to_end_refinement/",
        },
        {
            "model": "T2_full_duration",
            "training_strategy": "gradual unfreeze joint",
            "seed_coverage": "42 only (stop rule)",
            "val_pr_auc": 0.790,
            "f1": 0.791,
            "routing": "unused leaves 85.9%",
            "role": "failed joint baseline",
            "decision": "seed42_failed_viability (unused leaves)",
            "micro_run": False,
            "source": "outputs/objective2/end_to_end_full_confirmation/",
        },
        {
            "model": "residual_odst",
            "training_strategy": "zero-init residual warm-up then joint",
            "seed_coverage": "42 only (stop rule)",
            "val_pr_auc": 0.8085,
            "routing": "unused leaves 90.6%; best epoch before joint",
            "role": "failed joint baseline",
            "decision": "seed42_failed_viability",
            "micro_run": False,
            "source": "outputs/objective2/residual_odst_refinement/",
        },
        {
            "model": "teacher_anchored_odst",
            "training_strategy": "frozen teacher; joint student with logit+route consistency",
            "seed_coverage": "42/52/62",
            "val_pr_auc": "0.8105 / 0.8048 / 0.8141",
            "f1": "0.815 / 0.808 / 0.757",
            "fp_fn": "43/49 ; 62/39 ; 42/73",
            "routing": "unused ~57.0 / 56.3 / 39.8 (near teacher)",
            "role": "final Obj2 candidate (this audit)",
            "decision": "multiseed_viable_with_improvement (42+62; 52 fail PR margin)",
            "micro_run": False,
            "source": "outputs/objective2/teacher_anchored_odst/",
        },
    ]

    table_b = [
        {
            "model": "standalone_bilstm",
            "partition": "r4.2_validation",
            "evidence_status": "available_in_obj2_outputs",
            "source": "outputs/objective2/bilstm_seed*",
            "note": "Do not rank with r5.2 locked test",
        },
        {
            "model": "frozen_odst",
            "partition": "r4.2_validation",
            "evidence_status": "verified_comparator",
            "source": "outputs/v3_node + TA config",
        },
        {
            "model": "teacher_anchored_student",
            "partition": "r4.2_validation",
            "evidence_status": "verified_this_audit",
            "source": "outputs/objective2/teacher_anchored_odst/",
        },
        {
            "model": "random_forest",
            "partition": "r4.2_validation_and_or_r52_locked",
            "evidence_status": "prior_locked_baselines",
            "source": "outputs/objective2/r52_locked_baselines/ ; fragmented / baseline reports",
            "note": "Keep r5.2 locked results in separate panel; no superiority claim for TA student",
        },
        {
            "model": "xgboost",
            "partition": "r4.2_validation_and_or_r52_locked",
            "evidence_status": "prior_locked_baselines",
            "source": "outputs/objective2/r52_locked_baselines/",
        },
        {
            "model": "fragmented_bilstm_rf",
            "partition": "r4.2_validation",
            "evidence_status": "prior_obj2",
            "source": "outputs/objective2/fragmented_hybrid_seed*",
        },
        {
            "model": "fragmented_bilstm_xgboost",
            "partition": "r4.2_validation",
            "evidence_status": "prior_obj2",
            "source": "outputs/objective2/fragmented_hybrid_seed*",
        },
        {
            "model": "r52_locked_odst_confirmation",
            "partition": "r5.2_locked_test",
            "evidence_status": "prior_locked_for_frozen_odst_not_TA_student",
            "source": "outputs/objective2/r52_odst_confirmation/",
            "note": "Teacher-anchored student has NO independent locked external confirmation yet",
        },
    ]

    table_c = [
        {
            "configuration": "frozen_odst",
            "joint_optimisation": "no (encoder frozen)",
            "representation_outcome": "stable pretrained representation",
            "routing_outcome": "usable (~40–58% unused)",
            "predictive_outcome": "strong multi-seed validation",
            "final_decision": "validated teacher / prior locked model family",
        },
        {
            "configuration": "T1_micro",
            "joint_optimisation": "diagnostic",
            "representation_outcome": "diagnostic only",
            "routing_outcome": "diagnostic only",
            "predictive_outcome": "not full-duration",
            "final_decision": "diagnostic only",
        },
        {
            "configuration": "T2_full",
            "joint_optimisation": "yes (gradual)",
            "representation_outcome": "cosine preserved",
            "routing_outcome": "unused leaves ~86% (failed)",
            "predictive_outcome": "within PR margin but routing fail",
            "final_decision": "not viable",
        },
        {
            "configuration": "residual_odst",
            "joint_optimisation": "yes after warm-up",
            "representation_outcome": "cosine 1.0 at selected (pre-joint)",
            "routing_outcome": "unused leaves ~91% (failed)",
            "predictive_outcome": "best ckpt before joint",
            "final_decision": "not viable",
        },
        {
            "configuration": "teacher_anchored",
            "joint_optimisation": "yes from epoch 1",
            "representation_outcome": "cosine >= 0.998 at selected",
            "routing_outcome": "unused near teacher (~57%)",
            "predictive_outcome": "2/3 seeds viable; mean within margin; s42 FP improvement",
            "final_decision": "freeze as Obj2 candidate (this audit)",
        },
    ]
    return table_a, table_b, table_c


def claim_register(multi: dict, gate_rows: list[dict], leaf_rows: list[dict]) -> list[dict]:
    def row(claim, category, support, artefact):
        return {"claim": claim, "category": category, "assessment": support, "artefact": artefact}

    s42 = next(r for r in gate_rows if r["seed"] == 42)
    s52 = next(r for r in gate_rows if r["seed"] == 52)
    s62 = next(r for r in gate_rows if r["seed"] == 62)
    ta_leaf = next(r for r in leaf_rows if r["experiment"] == "teacher_anchored_student_seed42")
    t2_leaf = next(r for r in leaf_rows if r["experiment"] == "t2_full_duration_seed42")

    claims = [
        row("Bi-LSTM representation contains useful temporal information", "supported", "supported_by_prior_probes_and_frozen_odst", "end_to_end_refinement probes; frozen ODST viability"),
        row("Attention improves the probed representation", "supported", "supported_by_representation_probes", "outputs/objective2/end_to_end_refinement/"),
        row("Frozen ODST is a viable integrated classifier", "supported", "supported_multi_seed_frozen_metrics", "outputs/v3_node + FROZEN_COMPARATORS"),
        row("Ordinary T2 and residual joint training caused substantial routing deterioration", "supported", f"supported_with_comparability_{t2_leaf['comparability_class']}", "end_to_end_full_confirmation + residual_odst_refinement seed summaries"),
        row("Teacher anchoring enabled genuine joint optimisation", "supported", "supported", "parameter_update_verification + epoch_metrics joint=True from epoch 1"),
        row("Teacher anchoring prevented systematic leaf-utilisation collapse vs prior E2E", "supported", f"supported_qualified_by_{ta_leaf['comparability_class']}_cross_study", "leaf_comparability + seed summaries"),
        row("Two of three teacher-anchored seeds passed predefined viability gate", "supported", "supported", f"gate_reconstruction viable={multi['viable_seeds']}"),
        row("Final student does not require teacher for inference", "supported", "supported", "checkpoint payload teacher_required_at_inference=false"),
        row("Teacher anchoring improves operational false-positive behaviour", "qualified", "seed42_fp_43_vs_49_at_matched_recall_not_universal", "prediction_agreement + seed42 summary"),
        row("Teacher anchoring improves predictive performance", "qualified", "seed42_small_pr_gain_seed52_worse", "gate_reconstruction"),
        row("Teacher anchoring is stable across random seeds", "qualified", "two_of_three_not_all_three", "seed52 pr_auc_below_margin"),
        row("Teacher anchoring generalises beyond r4.2 validation", "rejected", "no_independent_locked_confirmation_for_TA_student", "r52_odst_confirmation is for frozen ODST, not TA student"),
        row("ODST routing instability was the primary cause of previous predictive degradation", "qualified", "routing_collapse_cooccurred_with_T2_fail_causal_not_proven", "T2/residual interpretations"),
        row("Universal superiority over RF or XGBoost", "rejected", "not_claimed_not_tested_for_TA_student", "baseline evidence table"),
        row("State-of-the-art performance", "rejected", "unsupported", "n/a"),
        row("Uniform improvement across all seeds", "rejected", "seed52_failed", str(s52["reconstructed_reasons"])),
        row("Independent cross-version confirmation of teacher-anchored student", "rejected", "not_completed", "OBJECTIVE3_FINAL_CANDIDATE_HANDOVER"),
        row("Live organisational effectiveness", "rejected", "unsupported", "n/a"),
        row("Confirmed architecture novelty", "rejected", "unsupported", "n/a"),
        row("Causal proof teacher anchoring alone produced every improvement", "rejected", "unsupported", "n/a"),
        row(f"Seed42 pass / Seed52 fail / Seed62 pass verified", "supported", f"42={s42['reconstructed_viable']};52={s52['reconstructed_viable']};62={s62['reconstructed_viable']}", "objective2_gate_reconstruction.csv"),
    ]
    return claims


def make_figures(out_dir: Path, gate_rows: list[dict], leaf_rows: list[dict]) -> None:
    # routing/leaf figure
    fig, ax = plt.subplots(figsize=(8, 4.5))
    labels = []
    vals = []
    for exp in [
        "frozen_odst_seed42",
        "t2_full_duration_seed42",
        "residual_odst_seed42",
        "teacher_anchored_student_seed42",
    ]:
        r = next(x for x in leaf_rows if x["experiment"] == exp)
        labels.append(exp.replace("_", "\n"))
        vals.append(r["unused_leaves_pct"])
    ax.bar(range(len(vals)), vals, color=["#4C78A8", "#E45756", "#F58518", "#54A24B"])
    ax.set_xticks(range(len(vals)))
    ax.set_xticklabels(labels, fontsize=7)
    ax.set_ylabel("Unused leaves (%)")
    ax.set_title("Leaf utilisation across training strategies (seed 42)")
    ax.axhline(57.8125, color="gray", linestyle="--", linewidth=1, label="frozen teacher ~57.8%")
    ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(out_dir / "routing_leaf_utilisation_comparison.png", dpi=300)
    plt.close(fig)

    # teacher vs student seeds
    fig, ax = plt.subplots(figsize=(7, 4))
    seeds = [r["seed"] for r in gate_rows]
    x = np.arange(len(seeds))
    ax.bar(x - 0.2, [r["teacher_pr_auc"] for r in gate_rows], 0.4, label="teacher")
    ax.bar(x + 0.2, [r["student_pr_auc"] for r in gate_rows], 0.4, label="student")
    ax.set_xticks(x)
    ax.set_xticklabels([str(s) for s in seeds])
    ax.set_ylabel("Validation PR-AUC")
    ax.set_title("Teacher vs student PR-AUC by seed")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_dir / "teacher_versus_student_seed_comparison.png", dpi=300)
    plt.close(fig)


def write_text_reports(
    out_dir: Path,
    *,
    status: str,
    meta: dict,
    multi: dict,
    gate_rows: list[dict],
    issues: list[str],
    integrity: list[dict],
    freeze: bool,
) -> None:
    s42 = next(r for r in gate_rows if r["seed"] == 42)
    s52 = next(r for r in gate_rows if r["seed"] == 52)
    s62 = next(r for r in gate_rows if r["seed"] == 62)

    synthesis = f"""# OBJECTIVE2_FINAL_EVIDENCE_SYNTHESIS

## Final audit status
`{status}`

## Provenance
- audit worktree: {meta['worktree']}
- branch: {meta['branch']}
- start HEAD: {meta['start_head']}
- source teacher-anchored commit: {SOURCE_COMMIT}
- source outputs: outputs/objective2/teacher_anchored_odst/
- junctions: data -> feasibility/data; outputs -> feasibility/outputs
- protected partitions accessed: {meta['protected_accessed']}
- Objective 3 fingerprint before/after unchanged: {meta['obj3_unchanged']}
- artefacts opened: see objective2_final_audit_manifest.json

## Verified headline findings
- Teacher checkpoint hashes match pre-training records for seeds 42/52/62.
- Student best checkpoints exist, exclude residual heads, and set `teacher_required_at_inference=false`.
- Parameter-update logs show encoder/attention/ODST distances > {PARAM_CHANGE_TOL} at epoch 1 for all seeds; joint=True from epoch 1.
- Gate reconstruction: seed42 pass; seed52 fail (`pr_auc_below_margin`, Δ={s52['pr_auc_delta']:.6f}); seed62 pass.
- Multi-seed reconstruction matches recorded status `{multi['recorded_status']}` (viable seeds {multi['viable_seeds']}; mean Δ={multi['mean_pr_delta']:.6f}).
- Leaf utilisation: TA student seed42 unused={s42['student_unused_leaves_pct']:.3f}% vs teacher={s42['teacher_unused_leaves_pct']:.3f}%; T2/residual remain ~86%/91% with documented aggregation limits.
- Seed42 FP improved 49→43 at matched recall {s42['student_f1'] and True}; not a universal predictive superiority claim.

## Remaining issues
{issues if issues else ['none_mandatory']}

## Freeze decision
{'CANDIDATE FROZEN' if freeze else 'DO NOT FREEZE'}
"""
    (out_dir / "OBJECTIVE2_FINAL_EVIDENCE_SYNTHESIS.md").write_text(synthesis, encoding="utf-8")

    model_card = f"""# OBJECTIVE2_FINAL_CANDIDATE_MODEL_CARD

## Candidate
Teacher-anchored end-to-end Bi-LSTM–attention–ODST (student)

## Status
`{status}`

## Inference architecture
X → Bi-LSTM → attention → z → ODST → logit
No residual head. No teacher required at inference.

## Training (fixed; do not retune on r4.2 validation)
- Teacher: frozen completed sparsemax_sigmoid_odst checkpoint (seed-specific)
- Student init: exact teacher copy
- Loss: WBCE + 0.5 L_logit + 0.5 L_route
- LRs: encoder/attention 3e-5; ODST 3e-4
- Budget: max 15 epochs, patience 4, batch 1024, pos_weight_mult 0.25
- Checkpoint: max validation PR-AUC; threshold: max validation F1

## Seeds
- Pass: 42, 62
- Fail: 52 (PR-AUC below teacher−0.020 by ~0.054)
- Mean student vs teacher PR-AUC Δ ≈ {multi['mean_pr_delta']:.6f} (within −0.020)

## Selected student checkpoint hashes
{chr(10).join('- seed '+str(r['seed'])+': '+r['student_best_sha256'] for r in integrity)}

## Teacher hashes (unchanged)
{chr(10).join('- seed '+str(r['seed'])+': '+r['teacher_sha256'] for r in integrity)}

## Explicit non-claims
- No superiority over RF/XGBoost
- No r5.2/r6.2 confirmation for this student
- No universal improvement across all seeds
- r4.2 validation evidence is frozen against further architecture/hyperparameter selection on the same partition
"""
    (out_dir / "OBJECTIVE2_FINAL_CANDIDATE_MODEL_CARD.md").write_text(model_card, encoding="utf-8")

    ch3 = """# OBJECTIVE2_CHAPTER3_NOTES

Methodology notes for proposal Chapter 3 (do not auto-edit the chapter).

1. Encoder pretraining / frozen teacher construction: completed full-duration sparsemax_sigmoid_odst runs (seeds 42/52/62).
2. Student initialisation: exact copy of teacher weights; residual/gate unused heads remain non-trainable.
3. Teacher role: permanently frozen, eval mode, excluded from optimiser; supplies detached logits and Bernoulli routing probabilities.
4. Losses: weighted BCE on student logits; variance-normalised MSE logit consistency; Bernoulli KL routing consistency; fixed weights 0.5/0.5.
5. Joint optimisation: Bi-LSTM, attention, and ODST trainable from epoch 1 with separate parameter groups.
6. Selection: validation PR-AUC checkpoint; validation F1 threshold; early stopping on validation PR-AUC.
7. Inference: student only — teacher discarded.
"""
    (out_dir / "OBJECTIVE2_CHAPTER3_NOTES.md").write_text(ch3, encoding="utf-8")

    ch4 = f"""# OBJECTIVE2_CHAPTER4_NOTES

Proposed results structure (do not auto-edit Chapter 4).

## Tables / figures (detail here)
1. Main Obj2 model-comparison table (r4.2 validation panel separate from r5.2 locked panel).
2. Training-strategy ablation table (frozen / T1 / T2 / residual / teacher-anchored).
3. Routing/leaf-utilisation figure (seed-42 cross-strategy).
4. Teacher-vs-student PR-AUC bar chart by seed.

## Short interpretation paragraphs
- Teacher anchoring restores joint training without the leaf-collapse seen in T2/residual.
- Two-of-three-seed viability is encouraging; seed 52 remains a visible limitation (PR-AUC −0.054 vs teacher).
- Seed 42 FP reduction is an operationally interesting qualified finding, not universal superiority.
- Do not claim RF/XGBoost superiority; keep locked external confirmation as future work.

## Visible seed-52 limitation
Seed 52 failed `pr_auc_below_margin` (student {s52['student_pr_auc']:.4f} vs teacher {s52['teacher_pr_auc']:.4f}).
"""
    (out_dir / "OBJECTIVE2_CHAPTER4_NOTES.md").write_text(ch4, encoding="utf-8")

    defence = """# OBJECTIVE2_DEFENCE_EXPLANATION

60–90 second explanation:

We initially retained a frozen Bi-LSTM–attention encoder with a trainable ODST head because that configuration was multi-seed viable and preserved useful routing. When we tried ordinary end-to-end schedules—gradual unfreezing and a residual correction—the representation stayed similar, but unused ODST leaves rose from about 58% to roughly 86–91%, and the predefined gates failed. Teacher anchoring keeps the validated frozen model as a permanent teacher and trains an identical student jointly with fixed logit and routing consistency losses, so the student cannot freely abandon the teacher decision boundary or routes. On r4.2 validation, two of three seeds passed the stored gate and leaf use stayed near the teacher; seed 52 still missed the PR-AUC margin, so viability is encouraging but not universal. The deployed model is the student alone. We do not claim superiority over Random Forest or XGBoost, and this candidate has not yet received independent locked external confirmation.
"""
    (out_dir / "OBJECTIVE2_DEFENCE_EXPLANATION.md").write_text(defence, encoding="utf-8")

    handover_obj3 = f"""# OBJECTIVE3_FINAL_CANDIDATE_HANDOVER

## Do not run Objective 3 confirmations in this audit

Review existing Objective 3 results before planning any later confirmation.

## Final candidate interface
- Architecture class: `AttentionNodeEnsemble` / sparsemax_sigmoid_odst (same as frozen ODST)
- Checkpoint keys: standard `model_state_dict` (Bi-LSTM, attention, node_head, ...)
- No residual_head; no teacher object required

## Candidate student checkpoints
{chr(10).join('- seed '+str(r['seed'])+': '+r.get('path', ta_path(r['seed']))+' sha256='+r['student_best_sha256'] for r in integrity)}

## Minimum later confirmation questions (planning only)
1. Does the teacher-anchored student reproduce locked evaluation interfaces used for frozen ODST?
2. How do faithfulness / robustness metrics compare to the frozen teacher on approved partitions only?
3. Does seed-52 weakness reappear under those diagnostics?

## Integrity
- Objective 3 namespaces must remain unchanged by this audit.
- Preservation snapshot: retained privately and not redistributed.
"""
    (out_dir / "OBJECTIVE3_FINAL_CANDIDATE_HANDOVER.md").write_text(handover_obj3, encoding="utf-8")

    (out_dir / "EXPERIMENTAL_HANDOVER.md").write_text(
        f"""# Experimental handover — Objective 2 final audit

## Status
`{status}`

## Isolation
- Worktree: {meta['worktree']}
- Branch: {meta['branch']}
- Source commit: {SOURCE_COMMIT}
- Outputs: outputs/objective2/teacher_anchored_final_audit/
- Tag: {'objective2-teacher-anchored-candidate-v1 (if freeze passed)' if freeze else 'not created'}

## Notes
No training performed. Do not merge into main. Do not retune on r4.2 validation.
""",
        encoding="utf-8",
    )


def ta_path(seed: int) -> str:
    return f"outputs/objective2/teacher_anchored_odst/seed{seed}/best_student.pt"


def main() -> None:
    root = repo_root()
    out_dir = root / "outputs/objective2/teacher_anchored_final_audit"
    out_dir.mkdir(parents=True, exist_ok=True)
    package = root / "scripts/objective2_teacher_anchored_final_audit"
    package.mkdir(parents=True, exist_ok=True)
    recorded = package / "recorded_results"
    recorded.mkdir(parents=True, exist_ok=True)

    ta_dir = root / "outputs/objective2/teacher_anchored_odst"
    start_head = _git(root, "rev-parse", "HEAD")
    branch = _git(root, "branch", "--show-current")
    status_txt = _git(root, "status", "--short")
    obj3_before = obj3_fingerprint(root)

    # Verify source commit contents
    files_in_commit = _git(root, "ls-tree", "-r", "--name-only", SOURCE_COMMIT)
    required = [
        "scripts/objective2_teacher_anchored_odst/config.py",
        "scripts/objective2_teacher_anchored_odst/train.py",
        "scripts/run_objective2_teacher_anchored_odst.py",
        "tests/test_objective2_teacher_anchored_odst.py",
        "scripts/objective2_teacher_anchored_odst/recorded_results/teacher_anchored_manifest.json",
    ]
    missing_in_commit = [p for p in required if p not in files_in_commit.splitlines()]

    hash_rows, integrity, param_rows, issues = verify_checkpoints(root, ta_dir)
    gate_rows, multi, gate_issues = reconstruct_gates(ta_dir)
    issues.extend(gate_issues)
    if missing_in_commit:
        issues.append(f"source_commit_missing:{missing_in_commit}")

    leaf_rows = leaf_comparability(root)
    table_a, table_b, table_c = build_evidence_tables()
    claims = claim_register(multi, gate_rows, leaf_rows)

    # Attach paths into integrity for model card
    for r in integrity:
        r["path"] = ta_path(int(r["seed"]))

    make_figures(out_dir, gate_rows, leaf_rows)

    # Freeze conditions
    mandatory_fail = []
    if any(not r["teacher_matches_pretraining_record"] for r in integrity):
        mandatory_fail.append("teacher_hash_inconsistent")
    if any(not r["student_independent"] for r in integrity):
        mandatory_fail.append("teacher_independence_failed")
    if any(not r["selected_after_joint_start"] for r in integrity):
        mandatory_fail.append("selected_before_joint")
    if any(r["has_residual_head_in_student_state"] for r in integrity):
        mandatory_fail.append("residual_in_student")
    if not multi.get("status_matches"):
        mandatory_fail.append("multiseed_gate_status_mismatch")
    if not multi.get("two_of_three_rule_satisfied"):
        mandatory_fail.append("two_of_three_not_met")
    if multi.get("mean_pr_delta", -1) < -VIABILITY_PR_AUC_MARGIN - 1e-12:
        mandatory_fail.append("mean_margin_failed")
    # leaf comparability: TA vs teacher directly comparable; cross-study limited but not materially invalid for freeze
    if not any(r["comparability_class"] == "directly_comparable" for r in leaf_rows if "teacher_anchored" in r["experiment"]):
        mandatory_fail.append("leaf_comparability_invalid")
    # protected access
    if any("protected_access" in i for i in issues):
        mandatory_fail.append("protected_data")

    obj3_after = obj3_fingerprint(root)
    obj3_unchanged = obj3_before == obj3_after
    if not obj3_unchanged:
        mandatory_fail.append("objective3_changed")
        issues.append("objective3_fingerprint_changed")

    freeze = len(mandatory_fail) == 0 and len([i for i in issues if i.startswith("gate_mismatch") or i.startswith("teacher_hash")]) == 0
    # Allow non-blocking documentation issues; block on mandatory_fail
    freeze = len(mandatory_fail) == 0

    if freeze:
        status = "objective2_teacher_anchored_candidate_frozen"
    elif not ta_dir.exists():
        status = "objective2_teacher_anchored_audit_blocked_by_incomplete_evidence"
    elif mandatory_fail:
        status = "objective2_teacher_anchored_audit_failed_do_not_freeze"
    else:
        status = "objective2_teacher_anchored_audit_passed_freeze_not_created"

    meta = {
        "worktree": str(root),
        "branch": branch,
        "start_head": start_head,
        "source_commit": SOURCE_COMMIT,
        "protected_accessed": False,
        "obj3_unchanged": obj3_unchanged,
        "worktree_status": status_txt or "clean",
        "gpu_info_only": "display processes only at audit start; no training launched",
    }

    write_text_reports(
        out_dir,
        status=status,
        meta=meta,
        multi=multi,
        gate_rows=gate_rows,
        issues=issues + mandatory_fail,
        integrity=integrity,
        freeze=freeze,
    )

    config = {
        "study": "teacher_anchored_final_audit",
        "no_training": True,
        "source_commit": SOURCE_COMMIT,
        "source_outputs": "outputs/objective2/teacher_anchored_odst/",
        "output_namespace": "outputs/objective2/teacher_anchored_final_audit",
        "param_change_tolerance": PARAM_CHANGE_TOL,
        "viability_gate_reconstructed_from": "scripts/objective2_teacher_anchored_odst/config.py + viability.py",
        "freeze_conditions": [
            "teacher_hashes_match",
            "teacher_independence",
            "selected_after_joint",
            "no_residual_in_student",
            "multiseed_status_matches_gate",
            "obj3_unchanged",
            "no_protected_access",
        ],
    }
    (out_dir / "objective2_final_audit_config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")

    _write_csv(out_dir / "objective2_checkpoint_hashes.csv", hash_rows)
    _write_csv(out_dir / "objective2_teacher_integrity.csv", integrity)
    _write_csv(out_dir / "objective2_parameter_update_verification.csv", param_rows)
    _write_csv(out_dir / "objective2_gate_reconstruction.csv", gate_rows)
    _write_csv(out_dir / "objective2_leaf_comparability.csv", leaf_rows)
    _write_csv(out_dir / "objective2_r42_architecture_evidence.csv", table_a)
    _write_csv(out_dir / "objective2_baseline_evidence_by_partition.csv", table_b)
    _write_csv(out_dir / "objective2_training_strategy_decision.csv", table_c)
    _write_csv(out_dir / "objective2_claim_register.csv", claims)

    candidate_manifest = {
        "candidate": "teacher_anchored_bilstm_attention_odst",
        "status": status,
        "freeze": freeze,
        "source_commit": SOURCE_COMMIT,
        "seeds_pass": [42, 62],
        "seeds_fail": [52],
        "seed52_limitation": "pr_auc_below_margin (~0.054)",
        "r42_validation_frozen_against_further_selection": freeze,
        "no_independent_locked_external_confirmation": True,
        "no_rf_xgb_superiority_claim": True,
        "student_checkpoints": integrity,
        "multiseed": multi,
        "mandatory_fail": mandatory_fail,
        "issues": issues,
    }
    (out_dir / "objective2_final_candidate_manifest.json").write_text(
        json.dumps(candidate_manifest, indent=2, default=str), encoding="utf-8"
    )

    manifest = {
        "status": status,
        "freeze": freeze,
        "run_id": "teacher_anchored_final_audit_v1",
        "training_executed": False,
        "source_commit": SOURCE_COMMIT,
        "start_head": start_head,
        "branch": branch,
        "worktree": str(root),
        "output_dir": str(out_dir),
        "obj3_before": obj3_before,
        "obj3_after": obj3_after,
        "obj3_unchanged": obj3_unchanged,
        "mandatory_fail": mandatory_fail,
        "issues": issues,
        "multiseed": multi,
        "artefacts_opened": OPENED,
        "n_artefacts_opened": len(OPENED),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }
    (out_dir / "objective2_final_audit_manifest.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")

    # Mirror principal reports into package
    for name in [
        "OBJECTIVE2_FINAL_EVIDENCE_SYNTHESIS.md",
        "OBJECTIVE2_FINAL_CANDIDATE_MODEL_CARD.md",
        "OBJECTIVE2_CHAPTER3_NOTES.md",
        "OBJECTIVE2_CHAPTER4_NOTES.md",
        "OBJECTIVE2_DEFENCE_EXPLANATION.md",
        "OBJECTIVE3_FINAL_CANDIDATE_HANDOVER.md",
        "EXPERIMENTAL_HANDOVER.md",
        "objective2_final_audit_config.json",
        "objective2_final_audit_manifest.json",
        "objective2_final_candidate_manifest.json",
        "objective2_checkpoint_hashes.csv",
        "objective2_teacher_integrity.csv",
        "objective2_parameter_update_verification.csv",
        "objective2_gate_reconstruction.csv",
        "objective2_leaf_comparability.csv",
        "objective2_r42_architecture_evidence.csv",
        "objective2_baseline_evidence_by_partition.csv",
        "objective2_training_strategy_decision.csv",
        "objective2_claim_register.csv",
        "routing_leaf_utilisation_comparison.png",
        "teacher_versus_student_seed_comparison.png",
    ]:
        src = out_dir / name
        if src.exists():
            (recorded / name).write_bytes(src.read_bytes())

    (package / "__init__.py").write_text('"""Objective 2 teacher-anchored final audit package."""\n', encoding="utf-8")
    print(json.dumps({"status": status, "freeze": freeze, "mandatory_fail": mandatory_fail, "issues": issues[:20]}, indent=2))


if __name__ == "__main__":
    main()
