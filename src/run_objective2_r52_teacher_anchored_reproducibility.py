#!/usr/bin/env python
"""CERT r5.2 teacher-anchored train/validation reproducibility (locked from r4.2 candidate)."""

from __future__ import annotations


import os
import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import torch

SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from objective2_end_to_end_refinement.train_micro import make_diagnostic_subset  # noqa: E402
from objective2_r52_teacher_anchored_reproducibility.constants import (  # noqa: E402
    ARCHITECTURE,
    BATCH_SIZE,
    CANDIDATE_TAG,
    EXPECTED_TRAIN_POS,
    EXPECTED_VAL_POS,
    GRAD_CLIP_NORM,
    LOGIT_CONSISTENCY_WEIGHT,
    LR_ATTENTION,
    LR_ENCODER,
    LR_ODST,
    MAX_EPOCHS,
    OBJ2_AUDIT_COMMIT,
    OUTPUT_REL,
    PARITY_SUBSET_SEED,
    PARITY_SUBSET_SIZE,
    PATIENCE,
    POS_WEIGHT_MULT,
    R52_TEACHERS,
    ROUTE_CONSISTENCY_WEIGHT,
    SEEDS_ORDER,
    TA_SOURCE_COMMIT,
    VIABILITY_COSINE_MIN,
    VIABILITY_F1_MARGIN,
    VIABILITY_PR_AUC_MARGIN,
    VIABILITY_UNUSED_LEAVES_MAX_WORSE_PP,
)
from objective2_r52_teacher_anchored_reproducibility.data import (  # noqa: E402
    load_train_validation,
    make_loaders,
    pos_weight_from_train,
    sha256_file,
)
from objective2_r52_teacher_anchored_reproducibility.reports import make_figures, write_reports  # noqa: E402
from objective2_r52_teacher_anchored_reproducibility.safety import (  # noqa: E402
    ProtectedDataAccessError,
    assert_output_namespace,
    assert_path_allowed_for_read,
    refuse_test_loader_construction,
)
from objective2_r52_teacher_anchored_reproducibility.status import classify_final_status  # noqa: E402
from objective2_teacher_anchored_odst.models import (  # noqa: E402
    assert_teacher_not_in_optimizer,
    build_model,
    build_student_optimizer,
    enable_all_student_components,
    freeze_teacher,
    load_checkpoint_into,
    student_forward_with_routing,
)
from objective2_teacher_anchored_odst.train import parity_check, train_teacher_anchored  # noqa: E402
from objective2_teacher_anchored_odst.viability import evaluate_multiseed, evaluate_seed_viability  # noqa: E402
from prototype_v3_node.train import set_seed  # noqa: E402


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    assert_output_namespace(path)
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


def _gpu_blocked() -> tuple[bool, str]:
    if not torch.cuda.is_available():
        return True, "cuda_unavailable"
    try:
        smi = subprocess.check_output(
            ["nvidia-smi", "--query-compute-apps=pid,process_name,used_memory", "--format=csv,noheader"],
            text=True,
            errors="ignore",
        )
    except Exception as exc:
        return False, f"nvidia_smi_query_failed:{exc}"
    ignore = ("dwm.exe", "cursor.exe", "explorer.exe", "system", "shellhost.exe")
    for line in smi.splitlines():
        raw = line.strip()
        if not raw:
            continue
        low = raw.lower()
        if any(tok in low for tok in ignore):
            continue
        if "python" in low or "objective" in low or "ipython" in low or "jupyter" in low:
            return True, f"gpu_compute_process:{raw}"
    try:
        free, total = torch.cuda.mem_get_info()
        used_frac = 1.0 - free / max(total, 1)
        if used_frac > 0.50:
            return True, f"gpu_memory_fraction:{used_frac:.3f}"
    except Exception:
        pass
    return False, "gpu_clear"


def build_config_dict() -> dict[str, Any]:
    return {
        "study": "r52_teacher_anchored_reproducibility_v1",
        "candidate_tag": CANDIDATE_TAG,
        "obj2_audit_commit": OBJ2_AUDIT_COMMIT,
        "ta_source_commit": TA_SOURCE_COMMIT,
        "output_namespace": str(OUTPUT_REL).replace("\\", "/"),
        "max_epochs": MAX_EPOCHS,
        "patience": PATIENCE,
        "batch_size": BATCH_SIZE,
        "pos_weight_mult": POS_WEIGHT_MULT,
        "weight_decay": 0.0,
        "optimiser": "Adam",
        "lr_encoder": LR_ENCODER,
        "lr_attention": LR_ATTENTION,
        "lr_odst": LR_ODST,
        "grad_clip_norm": GRAD_CLIP_NORM,
        "logit_consistency_weight": LOGIT_CONSISTENCY_WEIGHT,
        "route_consistency_weight": ROUTE_CONSISTENCY_WEIGHT,
        "loss": "WBCE + 0.5*L_logit + 0.5*L_route",
        "threshold_rule": "maximum_validation_f1",
        "checkpoint_rule": "maximum_validation_pr_auc",
        "early_stopping_metric": "validation_pr_auc",
        "architecture": ARCHITECTURE,
        "viability": {
            "pr_auc_margin": VIABILITY_PR_AUC_MARGIN,
            "f1_margin": VIABILITY_F1_MARGIN,
            "cosine_min": VIABILITY_COSINE_MIN,
            "unused_leaves_max_worse_pp": VIABILITY_UNUSED_LEAVES_MAX_WORSE_PP,
        },
        "seeds_order": list(SEEDS_ORDER),
        "teachers": R52_TEACHERS,
        "partitions": {
            "train": "data/processed/r5.2/tensors/r52_T20_s1_train.npz",
            "validation": "data/processed/r5.2/tensors/r52_T20_s1_validation.npz",
            "test_forbidden": True,
        },
        "read_only_sources": {
            "r4_2_candidate_config": "scripts/objective2_teacher_anchored_odst/config.py",
            "r52_teachers": "outputs/objective2/r52_odst_confirmation/",
        },
    }


def verify_teachers(root: Path) -> list[dict[str, Any]]:
    rows = []
    for seed, meta in R52_TEACHERS.items():
        ckpt = root / meta["relative_dir"] / "best.pt"
        thr_path = root / meta["relative_dir"] / "threshold.json"
        ok = True
        reasons = []
        if not ckpt.is_file():
            ok = False
            reasons.append("missing_checkpoint")
            sha = ""
        else:
            assert_path_allowed_for_read(ckpt, context="teacher_ckpt")
            sha = sha256_file(ckpt)
            if sha != meta["expected_sha256"]:
                ok = False
                reasons.append("hash_mismatch")
        if not thr_path.is_file():
            ok = False
            reasons.append("missing_threshold_sidecar")
        # Provenance fields from checkpoint metadata (no test tensors).
        provenance = {}
        if ckpt.is_file():
            payload = torch.load(ckpt, map_location="cpu", weights_only=False)
            provenance = {
                "stage": payload.get("stage"),
                "fusion_variant": payload.get("fusion_variant"),
                "test_evaluated": payload.get("test_evaluated"),
                "r52_test_accessed": payload.get("r52_test_accessed"),
                "r62_accessed": payload.get("r62_accessed"),
                "seed_in_ckpt": payload.get("seed"),
            }
            if provenance.get("test_evaluated") or provenance.get("r52_test_accessed"):
                ok = False
                reasons.append("test_contaminated_teacher")
            if provenance.get("stage") not in {None, "odst_r52_frozen_encoder", "frozen_encoder_odst"}:
                # Allow documented frozen-encoder stage names only.
                if "frozen" not in str(provenance.get("stage", "")).lower():
                    ok = False
                    reasons.append(f"unexpected_stage:{provenance.get('stage')}")
            if int(provenance.get("seed_in_ckpt", seed)) != seed:
                ok = False
                reasons.append("seed_mismatch")
        rows.append(
            {
                "seed": seed,
                "checkpoint": str(ckpt),
                "sha256": sha,
                "expected_sha256": meta["expected_sha256"],
                "hash_ok": sha == meta["expected_sha256"] if sha else False,
                "teacher_pr_auc": meta["pr_auc"],
                "teacher_f1": meta["f1"],
                "teacher_threshold": meta["threshold"],
                "unused_leaves_pct": meta["unused_leaves_pct"],
                "provenance_ok": ok,
                "reasons": ";".join(reasons),
                **{f"meta_{k}": v for k, v in provenance.items()},
            }
        )
    return rows


def load_baseline_context(locked_root: Path | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if locked_root is None:
        return rows
    path = locked_root / "outputs/objective2/r52_locked_baselines/r52_all_validation_model_summary.csv"
    if not path.is_file():
        alt = locked_root / "outputs/objective2/objective2_validation_model_summary.csv"
        path = alt if alt.is_file() else path
    if not path.is_file():
        return rows
    df = pd.read_csv(path)
    for _, r in df.iterrows():
        rows.append({k: r[k] for k in df.columns})
    return rows


def load_historical_test_context(locked_root: Path | None) -> list[dict[str, Any]]:
    """Read high-level locked test summaries only (no test tensors / predictions used for selection)."""
    rows: list[dict[str, Any]] = []
    if locked_root is None:
        return rows
    path = locked_root / "outputs/objective2/objective2_test_model_summary.csv"
    if not path.is_file():
        return rows
    df = pd.read_csv(path)
    for _, r in df.iterrows():
        row = {k: r[k] for k in df.columns}
        row["panel"] = "historical_r52_locked_test_prior_frozen_and_baselines_only"
        row["teacher_anchored_student"] = False
        rows.append(row)
    return rows


def load_r42_ta_seed_summary(root: Path) -> list[dict[str, Any]]:
    path = root / "outputs/objective2/teacher_anchored_odst/teacher_anchored_seed_summary.csv"
    if not path.is_file():
        return []
    df = pd.read_csv(path)
    return [{k: r[k] for k in df.columns} for _, r in df.iterrows()]


def run_seed(
    root: Path,
    out_dir: Path,
    seed: int,
    device: torch.device,
    train_ds,
    val_ds,
    audits,
) -> dict[str, Any]:
    refuse_test_loader_construction(partition="train")
    refuse_test_loader_construction(partition="validation")
    set_seed(seed)
    train_loader, val_loader = make_loaders(train_ds, val_ds, batch_size=BATCH_SIZE, seed=seed)
    y_val = np.asarray([float(val_ds[i][1]) for i in range(len(val_ds))], dtype=np.float32)
    # Faster: pull labels tensor once
    y_val = val_ds.tensors[1].numpy().astype(np.float32)

    diag_ds = make_diagnostic_subset(val_ds, PARITY_SUBSET_SIZE, PARITY_SUBSET_SEED)
    indices = list(getattr(diag_ds, "indices", list(range(len(diag_ds)))))
    from torch.utils.data import DataLoader

    diag_loader = DataLoader(diag_ds, batch_size=PARITY_SUBSET_SIZE, shuffle=False, num_workers=0)

    meta = R52_TEACHERS[seed]
    frozen_ckpt = root / meta["relative_dir"] / "best.pt"
    assert_path_allowed_for_read(frozen_ckpt, context="teacher")
    before_hash = sha256_file(frozen_ckpt)
    if before_hash != meta["expected_sha256"]:
        raise RuntimeError(f"Teacher hash mismatch seed={seed}: {before_hash}")

    teacher = build_model()
    student = build_model()
    load_checkpoint_into(teacher, frozen_ckpt)
    load_checkpoint_into(student, frozen_ckpt)
    freeze_teacher(teacher)
    enable_all_student_components(student)
    teacher.to(device)
    student.to(device)

    # Optimiser exclusion check before training
    opt, _ = build_student_optimizer(
        student, {"lr_encoder": LR_ENCODER, "lr_attention": LR_ATTENTION, "lr_odst": LR_ODST}
    )
    assert_teacher_not_in_optimizer(teacher, opt)
    del opt

    parity = parity_check(teacher, student, diag_loader, device, indices)
    if not parity["initial_parity_ok"]:
        raise RuntimeError(
            "objective2_r52_teacher_anchored_blocked_initial_parity: " + json.dumps(parity, default=str)
        )

    teacher_state0 = {k: v.detach().cpu().clone() for k, v in teacher.state_dict().items()}
    student_state0 = {k: v.detach().cpu().clone() for k, v in student.state_dict().items()}
    import hashlib

    h = hashlib.sha256()
    for k in sorted(student_state0):
        h.update(k.encode())
        h.update(student_state0[k].cpu().numpy().tobytes())
    student_init_state_sha = h.hexdigest()

    n_pos = EXPECTED_TRAIN_POS
    n_neg = audits[0].n_neg
    pos_w = pos_weight_from_train(n_pos, n_neg, POS_WEIGHT_MULT)
    pos_weight = torch.tensor([pos_w], dtype=torch.float32)

    print(
        f"[r52-ta] seed={seed} device={device} pos_weight={pos_w:.6f} "
        f"max_epochs={MAX_EPOCHS} patience={PATIENCE}",
        flush=True,
    )
    result = train_teacher_anchored(
        teacher=teacher,
        student=student,
        train_loader=train_loader,
        val_loader=val_loader,
        diag_loader=diag_loader,
        y_val=y_val,
        device=device,
        pos_weight=pos_weight,
        seed=seed,
        teacher_initial_state=teacher_state0,
        student_initial_state=student_state0,
    )
    after_hash = sha256_file(frozen_ckpt)
    if after_hash != before_hash:
        raise RuntimeError("Teacher checkpoint file mutated on disk")

    # Independent inference without teacher
    student.eval()
    with torch.no_grad():
        xb0 = val_ds.tensors[0][:8].to(device)
        _ = student_forward_with_routing(student, xb0)

    result["catastrophic_fp_fn"] = bool(
        result["best_fp"] > max(3.0 * meta["fp"], meta["fp"] + 100)
        and result["best_fn"] > max(3.0 * meta["fn"], meta["fn"] + 100)
    )
    result["initial_parity_ok"] = parity["initial_parity_ok"]
    result["parity"] = parity
    result["teacher_pr_auc"] = meta["pr_auc"]
    result["teacher_f1"] = meta["f1"]
    result["teacher_recall"] = meta["recall"]
    result["teacher_fp"] = meta["fp"]
    result["teacher_fn"] = meta["fn"]
    result["teacher_unused_leaves_pct"] = meta["unused_leaves_pct"]
    result["teacher_routing_entropy_mean"] = meta["routing_entropy_mean"]
    result["teacher_checkpoint"] = str(frozen_ckpt)
    result["teacher_checkpoint_sha256"] = after_hash
    result["student_initial_state_sha256"] = student_init_state_sha
    gate = evaluate_seed_viability(
        teacher={
            "pr_auc": meta["pr_auc"],
            "f1": meta["f1"],
            "recall": meta["recall"],
            "fp": meta["fp"],
            "unused_leaves_pct": meta["unused_leaves_pct"],
            "routing_entropy_mean": meta["routing_entropy_mean"],
        },
        run=result,
    )
    result["gate"] = gate

    seed_dir = out_dir / f"seed{seed}"
    assert_output_namespace(seed_dir)
    seed_dir.mkdir(parents=True, exist_ok=True)
    if result["best_state"] is not None:
        best_path = seed_dir / "best_student.pt"
        torch.save(
            {
                "model_state_dict": result["best_state"],
                "epoch": result["best_epoch"],
                "seed": seed,
                "best_val_pr_auc": result["best_pr_auc"],
                "schedule": "teacher_anchored_joint",
                "prototype": "r52_teacher_anchored_reproducibility",
                "test_evaluated": False,
                "teacher_required_at_inference": False,
                "teacher_checkpoint_sha256": after_hash,
            },
            best_path,
        )
        result["best_checkpoint_path"] = str(best_path)
        result["best_checkpoint_sha256"] = sha256_file(best_path)
    if result["final_state"] is not None:
        final_path = seed_dir / "final_student.pt"
        torch.save(
            {
                "model_state_dict": result["final_state"],
                "epoch": result["epochs_trained"],
                "seed": seed,
                "diagnostic_only": True,
            },
            final_path,
        )
        result["final_checkpoint_path"] = str(final_path)
        result["final_checkpoint_sha256"] = sha256_file(final_path)

    bm = result["best_metrics"]
    if bm is not None:
        pd.DataFrame(
            {
                "y_true": bm["y_true"],
                "student_logit": bm["student"]["logits"],
                "teacher_logit": bm["teacher"]["logits"],
                "student_prob": bm["student"]["probs"],
                "teacher_prob": bm["teacher"]["probs"],
                "student_threshold": result["best_threshold"],
            }
        ).to_csv(seed_dir / "validation_predictions.csv", index=False)

    (seed_dir / "teacher_student_initial_parity.json").write_text(json.dumps(parity, indent=2), encoding="utf-8")
    (seed_dir / "seed_summary.json").write_text(
        json.dumps(
            {
                k: v
                for k, v in result.items()
                if k
                not in {
                    "best_state",
                    "final_state",
                    "best_metrics",
                    "final_metrics",
                    "epoch_rows",
                    "loss_rows",
                    "grad_rows",
                    "param_rows",
                    "routing_rows",
                }
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument(
        "--locked-baselines-root",
        type=Path,
        default=(Path(os.environ["CERT_R52_LOCKED_BASELINES_ROOT"]) if os.environ.get("CERT_R52_LOCKED_BASELINES_ROOT") else None),
    )
    parser.add_argument("--device", choices=["auto", "cuda", "cpu"], default="auto")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--skip-hash-verify", action="store_true")
    parser.add_argument("--run-id", default="r52_teacher_anchored_reproducibility_v1")
    args = parser.parse_args()

    root = (args.root or Path(__file__).resolve().parents[1]).resolve()
    out_dir = assert_output_namespace(root / OUTPUT_REL)
    out_dir.mkdir(parents=True, exist_ok=True)

    cfg = build_config_dict()
    (out_dir / "r52_teacher_anchored_config.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    start_head = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    branch = subprocess.check_output(["git", "-C", str(root), "branch", "--show-current"], text=True).strip()
    status_txt = subprocess.check_output(["git", "-C", str(root), "status", "--short"], text=True)

    # Teacher provenance
    teacher_rows = verify_teachers(root)
    _write_csv(out_dir / "r52_teacher_provenance.csv", teacher_rows)
    if any(not r["provenance_ok"] for r in teacher_rows):
        status = "objective2_r52_teacher_anchored_blocked_missing_teacher"
        manifest = {
            "status": status,
            "training_executed": False,
            "teacher_rows": teacher_rows,
            "start_head": start_head,
            "branch": branch,
        }
        (out_dir / "r52_teacher_anchored_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        write_reports(out_dir, results={}, status=status, multi=None, meta={"worktree": str(root), "branch": branch, "start_head": start_head})
        print(json.dumps(manifest, indent=2, default=str))
        return

    # Partition audit / interface
    try:
        train_ds, val_ds, audits, prep_meta = load_train_validation(
            root, verify_hashes=not args.skip_hash_verify
        )
    except RuntimeError as exc:
        msg = str(exc)
        if "blocked_interface_mismatch" in msg:
            status = "objective2_r52_teacher_anchored_blocked_interface_mismatch"
        else:
            status = "objective2_r52_teacher_anchored_incomplete"
        manifest = {"status": status, "error": msg, "training_executed": False}
        (out_dir / "r52_teacher_anchored_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(json.dumps(manifest, indent=2))
        return
    except ProtectedDataAccessError as exc:
        status = "objective2_r52_teacher_anchored_stopped_safety_failure"
        manifest = {"status": status, "error": str(exc), "training_executed": False}
        (out_dir / "r52_teacher_anchored_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(json.dumps(manifest, indent=2))
        return

    partition_rows = []
    for a in audits:
        partition_rows.append(
            {
                "partition": a.name,
                "path": a.path,
                "sha256": a.sha256,
                "shape": str(a.shape),
                "n_pos": a.n_pos,
                "n_neg": a.n_neg,
                "sequence_length": a.sequence_length,
                "feature_dim": a.feature_dim,
                "feature_names": "|".join(a.feature_names),
                **prep_meta,
            }
        )
    _write_csv(out_dir / "r52_partition_and_preprocessing_audit.csv", partition_rows)

    # Gate reconstruction (frozen r4.2 values)
    gate_rows = [
        {"rule": "seed_pr_auc_margin", "value": VIABILITY_PR_AUC_MARGIN, "source": "r4.2_teacher_anchored_config"},
        {"rule": "seed_f1_margin", "value": VIABILITY_F1_MARGIN, "source": "r4.2_teacher_anchored_config"},
        {"rule": "seed_cosine_min", "value": VIABILITY_COSINE_MIN, "source": "r4.2_teacher_anchored_config"},
        {
            "rule": "seed_unused_leaves_max_worse_pp",
            "value": VIABILITY_UNUSED_LEAVES_MAX_WORSE_PP,
            "source": "r4.2_teacher_anchored_config",
        },
        {"rule": "multiseed_min_viable_seeds", "value": 2, "source": "r4.2_evaluate_multiseed"},
        {"rule": "multiseed_mean_pr_delta_min", "value": -VIABILITY_PR_AUC_MARGIN, "source": "r4.2_evaluate_multiseed"},
        {"rule": "checkpoint_rule", "value": "maximum_validation_pr_auc", "source": "r4.2_teacher_anchored_config"},
        {"rule": "threshold_rule", "value": "maximum_validation_f1", "source": "r4.2_teacher_anchored_config"},
    ]
    _write_csv(out_dir / "r52_gate_reconstruction.csv", gate_rows)

    baseline_rows = load_baseline_context(args.locked_baselines_root if args.locked_baselines_root and args.locked_baselines_root.exists() else None)
    for r in baseline_rows:
        r["panel"] = "r52_validation_context_read_only"
    _write_csv(out_dir / "r52_validation_baseline_context.csv", baseline_rows)
    hist_test = load_historical_test_context(
        args.locked_baselines_root if args.locked_baselines_root and args.locked_baselines_root.exists() else None
    )
    _write_csv(out_dir / "r52_historical_locked_test_context.csv", hist_test)

    gpu_blocked, gpu_reason = False, "n/a"
    if args.device == "cpu":
        device = torch.device("cpu")
    else:
        gpu_blocked, gpu_reason = _gpu_blocked()
        if args.device == "cuda" and not torch.cuda.is_available():
            gpu_blocked = True
            gpu_reason = "cuda_requested_unavailable"
        device = torch.device("cuda" if (not gpu_blocked and torch.cuda.is_available()) else "cpu")
        if args.device == "cuda" and device.type != "cuda":
            gpu_blocked = True

    if args.prepare_only or gpu_blocked:
        status = "objective2_r52_teacher_anchored_prepared_gpu_blocked"
        manifest = {
            "status": status,
            "run_id": args.run_id,
            "gpu_blocked": True,
            "gpu_block_reason": gpu_reason,
            "training_executed": False,
            "start_head": start_head,
            "branch": branch,
            "device": str(device),
            "expected_train_pos": EXPECTED_TRAIN_POS,
            "expected_val_pos": EXPECTED_VAL_POS,
        }
        (out_dir / "r52_teacher_anchored_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        write_reports(
            out_dir,
            results={},
            status=status,
            multi=None,
            meta={"worktree": str(root), "branch": branch, "start_head": start_head},
        )
        print(json.dumps(manifest, indent=2))
        return

    results: dict[int, dict[str, Any]] = {}
    safety_failure = False
    parity_blocked = False
    try:
        for seed in SEEDS_ORDER:
            print(f"[r52-ta] launching seed {seed}", flush=True)
            results[seed] = run_seed(root, out_dir, seed, device, train_ds, val_ds, audits)
            # Stop only on safety / implementation catastrophe for seed 42
            if seed == 42:
                r = results[42]
                if r.get("had_nan_or_inf") or r.get("protected_access") or not r.get("teacher_unchanged", True):
                    safety_failure = True
                    break
                if not r.get("initial_parity_ok"):
                    parity_blocked = True
                    break
    except RuntimeError as exc:
        msg = str(exc)
        if "blocked_initial_parity" in msg:
            parity_blocked = True
            status = "objective2_r52_teacher_anchored_blocked_initial_parity"
        elif "Teacher" in msg or "protected" in msg.lower() or "nan" in msg.lower():
            safety_failure = True
            status = "objective2_r52_teacher_anchored_stopped_safety_failure"
        else:
            status = "objective2_r52_teacher_anchored_incomplete"
        manifest = {
            "status": status,
            "error": msg,
            "seeds_completed": sorted(results.keys()),
            "training_executed": bool(results),
        }
        (out_dir / "r52_teacher_anchored_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        write_reports(
            out_dir,
            results=results,
            status=status,
            multi=None,
            meta={"worktree": str(root), "branch": branch, "start_head": start_head},
        )
        print(json.dumps(manifest, indent=2))
        return

    if safety_failure:
        status = "objective2_r52_teacher_anchored_stopped_safety_failure"
        multi = None
        implementation_ok_all = False
    elif parity_blocked:
        status = "objective2_r52_teacher_anchored_blocked_initial_parity"
        multi = None
        implementation_ok_all = False
    else:
        multi = evaluate_multiseed(results)
        implementation_ok_all = all((r.get("gate") or {}).get("implementation_ok", False) for r in results.values())
        status = classify_final_status(
            multiseed=multi,
            implementation_ok_all=implementation_ok_all,
            incomplete=len(results) < 3,
        )

    # Aggregate CSVs
    all_epoch, all_loss, all_grad, all_param, all_routing = [], [], [], [], []
    seed_summary, thresholds, parity_rows, agreement_rows = [], [], [], []
    for seed, r in results.items():
        all_epoch.extend(r["epoch_rows"])
        all_loss.extend(r["loss_rows"])
        all_grad.extend(r["grad_rows"])
        all_param.extend(r["param_rows"])
        all_routing.extend(r["routing_rows"])
        g = r["gate"]
        p = r["parity"]
        bm = r["best_metrics"]
        seed_summary.append(
            {
                "seed": seed,
                "best_epoch": r["best_epoch"],
                "best_pr_auc": r["best_pr_auc"],
                "teacher_pr_auc": r["teacher_pr_auc"],
                "pr_auc_delta": g["pr_auc_delta"],
                "best_f1": r["best_f1"],
                "teacher_f1": r["teacher_f1"],
                "f1_delta": g["f1_delta"],
                "best_fp": r["best_fp"],
                "best_fn": r["best_fn"],
                "teacher_fp": r["teacher_fp"],
                "teacher_fn": r["teacher_fn"],
                "viable": g["viable"],
                "implementation_ok": g["implementation_ok"],
                "predictive_ok": g["predictive_ok"],
                "representation_ok": g["representation_ok"],
                "routing_ok": g["routing_ok"],
                "improved_vs_teacher": g["improved_vs_teacher"],
                "reasons": ";".join(g["reasons"]),
                "unused_leaves_pct": r["unused_leaves_pct"],
                "teacher_unused_leaves_pct": r["teacher_unused_leaves_pct"],
                "final_pooled_cosine": r["final_pooled_cosine"],
                "routing_divergence": r["routing_divergence"],
                "teacher_unchanged": r["teacher_unchanged"],
                "encoder_updated": r["encoder_updated"],
                "attention_updated": r["attention_updated"],
                "odst_updated": r["odst_updated"],
                "best_checkpoint_sha256": r.get("best_checkpoint_sha256"),
                "teacher_checkpoint_sha256": r.get("teacher_checkpoint_sha256"),
            }
        )
        thresholds.append(
            {
                "seed": seed,
                "student_threshold": r["best_threshold"],
                "teacher_threshold": bm["teacher_threshold"],
                "selection_rule": "maximum_validation_f1",
                "partition": "validation",
            }
        )
        parity_rows.append(
            {
                "seed": seed,
                **{k: v for k, v in p.items() if k != "parity_indices"},
                "n_indices": len(p.get("parity_indices", [])),
                "teacher_checkpoint_sha256": r.get("teacher_checkpoint_sha256"),
                "student_initial_state_sha256": r.get("student_initial_state_sha256"),
            }
        )
        agreement_rows.append(
            {
                "seed": seed,
                "prediction_agreement": bm["prediction_agreement"],
                "pct_predictions_changed": bm["pct_predictions_changed"],
                "pct_predictions_changed_positive": bm["pct_predictions_changed_positive"],
                "pct_predictions_changed_negative": bm["pct_predictions_changed_negative"],
                "pearson_logits": bm["pearson_logits"],
                "spearman_logits": bm["spearman_logits"],
                "student_pr_auc": bm["student"]["pr_auc"],
                "teacher_pr_auc": bm["teacher"]["pr_auc"],
                "student_f1": bm["student"]["f1"],
                "teacher_f1": bm["teacher"]["f1"],
                "student_fp": bm["student"]["fp"],
                "teacher_fp": bm["teacher"]["fp"],
                "student_fn": bm["student"]["fn"],
                "teacher_fn": bm["teacher"]["fn"],
                "student_unused_leaves_pct": bm["student"]["unused_leaves_pct"],
                "teacher_unused_leaves_pct": bm["teacher"]["unused_leaves_pct"],
            }
        )

    _write_csv(out_dir / "r52_teacher_anchored_seed_summary.csv", seed_summary)
    _write_csv(out_dir / "r52_teacher_anchored_epoch_metrics.csv", all_epoch)
    _write_csv(out_dir / "r52_teacher_anchored_loss_components.csv", all_loss)
    _write_csv(out_dir / "r52_teacher_anchored_gradient_summary.csv", all_grad)
    _write_csv(out_dir / "r52_teacher_anchored_parameter_updates.csv", all_param)
    _write_csv(out_dir / "r52_teacher_anchored_routing_summary.csv", all_routing)
    _write_csv(out_dir / "r52_teacher_anchored_thresholds.csv", thresholds)
    _write_csv(out_dir / "r52_teacher_student_initial_parity.csv", parity_rows)
    _write_csv(out_dir / "r52_teacher_anchored_prediction_agreement.csv", agreement_rows)

    r42_rows = load_r42_ta_seed_summary(root)
    repro_rows = []
    r42_by = {int(r["seed"]): r for r in r42_rows if "seed" in r}
    for seed in SEEDS_ORDER:
        r52 = results.get(seed)
        r42 = r42_by.get(seed, {})
        repro_rows.append(
            {
                "seed": seed,
                "r42_student_pr_auc": r42.get("best_pr_auc"),
                "r42_teacher_pr_auc": r42.get("teacher_pr_auc"),
                "r42_pr_auc_delta": r42.get("pr_auc_delta"),
                "r42_viable": r42.get("viable"),
                "r52_student_pr_auc": None if r52 is None else r52["best_pr_auc"],
                "r52_teacher_pr_auc": None if r52 is None else r52["teacher_pr_auc"],
                "r52_pr_auc_delta": None if r52 is None else r52["gate"]["pr_auc_delta"],
                "r52_viable": None if r52 is None else r52["gate"]["viable"],
                "procedure_identical": True,
            }
        )
    _write_csv(out_dir / "r42_vs_r52_reproducibility_summary.csv", repro_rows)

    make_figures(out_dir, results, r42_context=r42_rows)
    write_reports(
        out_dir,
        results=results,
        status=status,
        multi=multi,
        meta={
            "worktree": str(root),
            "branch": branch,
            "start_head": start_head,
            "worktree_status": status_txt.strip() or "clean",
        },
    )

    manifest = {
        "status": status,
        "run_id": args.run_id,
        "training_executed": True,
        "gpu_blocked": False,
        "device": str(device),
        "seeds_executed": sorted(results.keys()),
        "multiseed": multi,
        "start_head": start_head,
        "branch": branch,
        "output_dir": str(out_dir),
        "candidate_tag": CANDIDATE_TAG,
        "obj2_audit_commit": OBJ2_AUDIT_COMMIT,
        "ta_source_commit": TA_SOURCE_COMMIT,
        "consistency_weights": {"logit": LOGIT_CONSISTENCY_WEIGHT, "route": ROUTE_CONSISTENCY_WEIGHT},
        "r52_test_accessed": False,
        "teachers_unchanged_on_disk": True,
        "objective3_untouched": True,
        "implementation_ok_all": implementation_ok_all if results else False,
    }
    (out_dir / "r52_teacher_anchored_manifest.json").write_text(
        json.dumps(manifest, indent=2, default=str), encoding="utf-8"
    )
    print(json.dumps(manifest, indent=2, default=str))


if __name__ == "__main__":
    main()
