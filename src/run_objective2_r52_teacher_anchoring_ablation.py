#!/usr/bin/env python
"""CERT r5.2 teacher-anchoring ablation (C1–C6) under the locked C5 protocol.

Same split, preprocessing, seeds {42,52,62}, optimiser, LRs, 15-epoch cap,
patience-4 on val PR-AUC, grad-clip 1.0, and F1 threshold rule. No retrospective
seed removal.

Primary train matrix: C1–C4, C6 (×3 seeds = 15 runs).
C5 predictive metrics are reused from the reproducibility table by default;
optional --train-c5 / --include-sensitivity for C5 retrain and λ∈{0.25,0.75}.
"""

from __future__ import annotations

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
import torch.nn as nn

SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from objective2_end_to_end_refinement.train_micro import make_diagnostic_subset  # noqa: E402
from objective2_r52_teacher_anchored_reproducibility.data import (  # noqa: E402
    load_train_validation,
    make_loaders,
    pos_weight_from_train,
    sha256_file,
)
from objective2_r52_teacher_anchoring_ablation.aggregate import mean_sd_table  # noqa: E402
from objective2_r52_teacher_anchoring_ablation.constants import (  # noqa: E402
    ABLATION_CONFIGS,
    ARCHITECTURE,
    BATCH_SIZE,
    C5_RECORDED_SEED_SUMMARY,
    EXPECTED_TRAIN_POS,
    GRAD_CLIP_NORM,
    LR_ATTENTION,
    LR_ENCODER,
    LR_ODST,
    MAX_EPOCHS,
    OUTPUT_REL,
    PARITY_SUBSET_SEED,
    PARITY_SUBSET_SIZE,
    PATIENCE,
    POS_WEIGHT_MULT,
    PRIMARY_ALL_IDS,
    PRIMARY_TRAIN_IDS,
    R52_TEACHERS,
    SEEDS_ORDER,
    SENSITIVITY_IDS,
)
from objective2_r52_teacher_anchoring_ablation.safety import (  # noqa: E402
    ProtectedDataAccessError,
    assert_output_namespace,
    assert_path_allowed_for_read,
    refuse_test_loader_construction,
)
from objective2_teacher_anchored_odst.models import (  # noqa: E402
    assert_teacher_not_in_optimizer,
    build_model,
    build_student_optimizer,
    enable_all_student_components,
    freeze_teacher,
    load_checkpoint_into,
    student_forward_with_routing,
)
from objective2_teacher_anchored_odst.train import (  # noqa: E402
    evaluate_pair,
    parity_check,
    train_teacher_anchored,
)
from prototype_v3_node.train import set_seed  # noqa: E402


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    assert_output_namespace(path)
    if not rows:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
        return
    keys: list[str] = []
    for r in rows:
        for k in r:
            if k not in keys:
                keys.append(k)
    path.parent.mkdir(parents=True, exist_ok=True)
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


def _metric_row_from_result(
    *,
    config_id: str,
    cfg: dict[str, Any],
    seed: int,
    result: dict[str, Any],
    teacher_meta: dict[str, Any],
    source: str,
) -> dict[str, Any]:
    t_pr = float(teacher_meta["pr_auc"])
    t_f1 = float(teacher_meta["f1"])
    s_pr = float(result["best_pr_auc"])
    s_f1 = float(result["best_f1"])
    return {
        "config_id": config_id,
        "seed": seed,
        "init": cfg["init"],
        "lambda_logit": cfg["lambda_logit"],
        "lambda_route": cfg["lambda_route"],
        "purpose": cfg["purpose"],
        "role": cfg.get("role", "primary"),
        "source": source,
        "best_epoch": result.get("best_epoch"),
        "pr_auc": s_pr,
        "f1": s_f1,
        "teacher_pr_auc": t_pr,
        "teacher_f1": t_f1,
        "delta_pr_auc": s_pr - t_pr,
        "delta_f1": s_f1 - t_f1,
        "val_logit_consistency": result.get("val_logit_consistency"),
        "val_route_consistency": result.get("val_route_consistency"),
        "route_mae": result.get("route_mae"),
        "hard_route_agreement": result.get("hard_route_agreement"),
        "dominant_leaf_agreement": result.get("dominant_leaf_agreement"),
        "unused_leaves_pct": result.get("unused_leaves_pct"),
        "unused_leaves_pct_all_layers": result.get("unused_leaves_pct_all_layers"),
        "tree_contrib_spearman": result.get("tree_contrib_spearman"),
        "tree_contrib_top3_jaccard": result.get("tree_contrib_top3_jaccard"),
        "tree_contrib_top5_jaccard": result.get("tree_contrib_top5_jaccard"),
        "tree_contrib_top10_jaccard": result.get("tree_contrib_top10_jaccard"),
        "routing_divergence": result.get("routing_divergence"),
        "pooled_cosine": result.get("final_pooled_cosine"),
        "best_checkpoint_sha256": result.get("best_checkpoint_sha256"),
        "teacher_checkpoint_sha256": result.get("teacher_checkpoint_sha256"),
    }


def load_c5_recorded_rows(root: Path) -> list[dict[str, Any]]:
    path = root / C5_RECORDED_SEED_SUMMARY
    if not path.is_file():
        return []
    df = pd.read_csv(path)
    cfg = ABLATION_CONFIGS["C5"]
    rows = []
    for _, r in df.iterrows():
        seed = int(r["seed"])
        meta = R52_TEACHERS[seed]
        rows.append(
            {
                "config_id": "C5",
                "seed": seed,
                "init": cfg["init"],
                "lambda_logit": cfg["lambda_logit"],
                "lambda_route": cfg["lambda_route"],
                "purpose": cfg["purpose"],
                "role": "primary",
                "source": "recorded_r52_teacher_anchored_reproducibility",
                "best_epoch": int(r["best_epoch"]),
                "pr_auc": float(r["best_pr_auc"]),
                "f1": float(r["best_f1"]),
                "teacher_pr_auc": float(r["teacher_pr_auc"]),
                "teacher_f1": float(r["teacher_f1"]),
                "delta_pr_auc": float(r["pr_auc_delta"]),
                "delta_f1": float(r["f1_delta"]),
                # RQ2 routing/explanation pack requires checkpoints; filled only on retrain/re-eval.
                "val_logit_consistency": float("nan"),
                "val_route_consistency": float(r.get("routing_divergence", float("nan"))),
                "route_mae": float("nan"),
                "hard_route_agreement": float("nan"),
                "dominant_leaf_agreement": float("nan"),
                "unused_leaves_pct": float(r["unused_leaves_pct"]),
                "unused_leaves_pct_all_layers": float("nan"),
                "tree_contrib_spearman": float("nan"),
                "tree_contrib_top3_jaccard": float("nan"),
                "tree_contrib_top5_jaccard": float("nan"),
                "tree_contrib_top10_jaccard": float("nan"),
                "routing_divergence": float(r.get("routing_divergence", float("nan"))),
                "pooled_cosine": float(r.get("final_pooled_cosine", float("nan"))),
                "best_checkpoint_sha256": r.get("best_checkpoint_sha256"),
                "teacher_checkpoint_sha256": meta["expected_sha256"],
                "note": "predictive_from_recorded_c5; rq2_pack_incomplete_without_ckpt_reeval",
            }
        )
    return rows


def run_one(
    *,
    root: Path,
    out_dir: Path,
    config_id: str,
    cfg: dict[str, Any],
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
    y_val = val_ds.tensors[1].numpy().astype(np.float32)
    print(
        f"[ablation] {config_id} seed={seed} val positives={int(y_val.sum())} "
        f"(expect ~728 for r5.2, ~252 for r4.2)",
        flush=True,
    )

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
    freeze_teacher(teacher)

    init_mode = cfg["init"]
    if init_mode == "teacher":
        load_checkpoint_into(student, frozen_ckpt)
    elif init_mode == "random":
        # Fresh random init under the same seed (set_seed already called).
        pass
    else:
        raise ValueError(f"Unknown init mode: {init_mode}")

    enable_all_student_components(student)
    teacher.to(device)
    student.to(device)

    opt, _ = build_student_optimizer(
        student, {"lr_encoder": LR_ENCODER, "lr_attention": LR_ATTENTION, "lr_odst": LR_ODST}
    )
    assert_teacher_not_in_optimizer(teacher, opt)
    del opt

    parity = parity_check(teacher, student, diag_loader, device, indices)
    if init_mode == "teacher" and not parity["initial_parity_ok"]:
        raise RuntimeError(
            f"blocked_initial_parity config={config_id} seed={seed}: "
            + json.dumps(parity, default=str)
        )
    if init_mode == "random" and parity["initial_parity_ok"]:
        # Extremely unlikely; keep as soft warning in summary rather than hard fail.
        parity["random_init_unexpected_parity"] = True

    teacher_state0 = {k: v.detach().cpu().clone() for k, v in teacher.state_dict().items()}
    student_state0 = {k: v.detach().cpu().clone() for k, v in student.state_dict().items()}

    n_pos = EXPECTED_TRAIN_POS
    n_neg = audits[0].n_neg
    pos_w = pos_weight_from_train(n_pos, n_neg, POS_WEIGHT_MULT)
    pos_weight = torch.tensor([pos_w], dtype=torch.float32)

    w_logit = float(cfg["lambda_logit"])
    w_route = float(cfg["lambda_route"])
    print(
        f"[ablation] {config_id} seed={seed} init={init_mode} "
        f"lambda_logit={w_logit} lambda_route={w_route} device={device}",
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
        w_logit=w_logit,
        w_route=w_route,
    )
    after_hash = sha256_file(frozen_ckpt)
    if after_hash != before_hash:
        raise RuntimeError("Teacher checkpoint file mutated on disk")

    student.eval()
    with torch.no_grad():
        xb0 = val_ds.tensors[0][:8].to(device)
        _ = student_forward_with_routing(student, xb0)

    result["initial_parity_ok"] = parity["initial_parity_ok"]
    result["parity"] = parity
    result["init"] = init_mode
    result["config_id"] = config_id
    _bm = result.get("best_metrics") or result.get("final_metrics")
    _live_pr = float(_bm["teacher"]["pr_auc"])
    _live_f1 = float(_bm["teacher"]["f1"])
    print(
        f"[ablation] {config_id} seed={seed} LIVE teacher r5.2-val "
        f"PR-AUC={_live_pr:.4f} F1={_live_f1:.4f} (stored={float(meta['pr_auc']):.4f})",
        flush=True,
    )
    if _live_pr < 0.85:
        raise RuntimeError(
            f"Teacher r5.2-val PR-AUC={_live_pr:.4f} < 0.85 (seed={seed}); expected ~0.93. "
            f"Wrong teacher checkpoint or partition (r4.2 ~252 pos vs r5.2 ~728 pos). Halting."
        )
    result["teacher_pr_auc"] = _live_pr
    result["teacher_f1"] = _live_f1
    result["teacher_pr_auc_stored"] = float(meta["pr_auc"])
    result["teacher_checkpoint"] = str(frozen_ckpt)
    result["teacher_checkpoint_sha256"] = after_hash

    seed_dir = assert_output_namespace(out_dir / config_id / f"seed{seed}")
    seed_dir.mkdir(parents=True, exist_ok=True)
    if result["best_state"] is not None:
        best_path = seed_dir / "best_student.pt"
        torch.save(
            {
                "model_state_dict": result["best_state"],
                "epoch": result["best_epoch"],
                "seed": seed,
                "config_id": config_id,
                "init": init_mode,
                "lambda_logit": w_logit,
                "lambda_route": w_route,
                "best_val_pr_auc": result["best_pr_auc"],
                "schedule": "teacher_anchoring_ablation",
                "prototype": "r52_teacher_anchoring_ablation_v1",
                "test_evaluated": False,
                "teacher_required_at_inference": False,
                "teacher_checkpoint_sha256": after_hash,
            },
            best_path,
        )
        result["best_checkpoint_path"] = str(best_path)
        result["best_checkpoint_sha256"] = sha256_file(best_path)

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

    (seed_dir / "teacher_student_initial_parity.json").write_text(
        json.dumps(parity, indent=2, default=str), encoding="utf-8"
    )
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
    _write_csv(seed_dir / "epoch_metrics.csv", result["epoch_rows"])
    _write_csv(seed_dir / "routing_summary.csv", result["routing_rows"])

    metric_row = _metric_row_from_result(
        config_id=config_id,
        cfg=cfg,
        seed=seed,
        result=result,
        teacher_meta={"pr_auc": result["teacher_pr_auc"], "f1": result["teacher_f1"]},
        source="trained_ablation",
    )
    result["metric_row"] = metric_row
    return result


@torch.no_grad()
def reeval_existing_student(
    *,
    root: Path,
    out_dir: Path,
    config_id: str,
    cfg: dict[str, Any],
    seed: int,
    ckpt_path: Path,
    device: torch.device,
    val_ds,
) -> dict[str, Any]:
    """Recompute full RQ2 metric pack from an existing student checkpoint."""
    meta = R52_TEACHERS[seed]
    frozen_ckpt = root / meta["relative_dir"] / "best.pt"
    assert_path_allowed_for_read(frozen_ckpt, context="teacher")
    assert_path_allowed_for_read(ckpt_path, context="student_ckpt")

    teacher = build_model()
    student = build_model()
    load_checkpoint_into(teacher, frozen_ckpt)
    load_checkpoint_into(student, ckpt_path)
    freeze_teacher(teacher)
    enable_all_student_components(student)
    teacher.to(device)
    student.to(device)

    from torch.utils.data import DataLoader

    val_loader = DataLoader(val_ds, batch_size=BATCH_SIZE, shuffle=False, num_workers=0)
    y_val = val_ds.tensors[1].numpy().astype(np.float32)
    # pos_weight unused for metrics; dummy criterion for evaluate_pair API
    criterion = nn.BCEWithLogitsLoss()
    val = evaluate_pair(teacher, student, val_loader, y_val, device, criterion)
    s = val["student"]
    result = {
        "best_epoch": None,
        "best_pr_auc": float(s["pr_auc"]),
        "best_f1": float(s["f1"]),
        "unused_leaves_pct": float(s["unused_leaves_pct"]),
        "unused_leaves_pct_all_layers": float(s["unused_leaves_pct_all_layers"]),
        "val_logit_consistency": float(val["val_logit_consistency"]),
        "val_route_consistency": float(val["val_route_consistency"]),
        "route_mae": float(val["route_mae"]),
        "hard_route_agreement": float(val["hard_route_agreement"]),
        "dominant_leaf_agreement": float(val["dominant_leaf_agreement"]),
        "tree_contrib_spearman": float(val["tree_contrib_spearman"]),
        "tree_contrib_top3_jaccard": float(val["tree_contrib_top3_jaccard"]),
        "tree_contrib_top5_jaccard": float(val["tree_contrib_top5_jaccard"]),
        "tree_contrib_top10_jaccard": float(val["tree_contrib_top10_jaccard"]),
        "routing_divergence": float(val["routing_divergence"]),
        "final_pooled_cosine": float(val["pooled_cosine_similarity"]),
        "best_checkpoint_sha256": sha256_file(ckpt_path),
        "teacher_checkpoint_sha256": sha256_file(frozen_ckpt),
    }
    row = _metric_row_from_result(
        config_id=config_id,
        cfg=cfg,
        seed=seed,
        result=result,
        teacher_meta=meta,
        source="reeval_existing_ckpt",
    )
    seed_dir = assert_output_namespace(out_dir / config_id / f"seed{seed}")
    seed_dir.mkdir(parents=True, exist_ok=True)
    (seed_dir / "reeval_summary.json").write_text(json.dumps(row, indent=2, default=str), encoding="utf-8")
    return row


def build_protocol_dict() -> dict[str, Any]:
    return {
        "study": "r52_teacher_anchoring_ablation_v1",
        "output_namespace": str(OUTPUT_REL).replace("\\", "/"),
        "shared_with_c5": {
            "split": "r5.2 train/validation",
            "seeds": list(SEEDS_ORDER),
            "max_epochs": MAX_EPOCHS,
            "patience": PATIENCE,
            "early_stopping_metric": "validation_pr_auc",
            "checkpoint_rule": "maximum_validation_pr_auc",
            "threshold_rule": "maximum_validation_f1",
            "lr_encoder": LR_ENCODER,
            "lr_attention": LR_ATTENTION,
            "lr_odst": LR_ODST,
            "grad_clip_norm": GRAD_CLIP_NORM,
            "batch_size": BATCH_SIZE,
            "pos_weight_mult": POS_WEIGHT_MULT,
            "optimiser": "Adam",
            "weight_decay": 0.0,
            "architecture": ARCHITECTURE,
            "no_retrospective_seed_removal": True,
        },
        "configs": ABLATION_CONFIGS,
        "primary_train_ids": list(PRIMARY_TRAIN_IDS),
        "sensitivity_note": (
            "C5_lam025 / C5_lam075 are pre-specified sensitivity checks only; "
            "not chosen post-hoc and not used for model selection."
        ),
        "c5_reuse": (
            "C5 predictive metrics default to recorded r52_teacher_anchored_seed_summary.csv; "
            "full RQ2 pack requires --train-c5 or --c5-ckpt-root."
        ),
    }


def resolve_config_ids(args: argparse.Namespace) -> list[str]:
    if args.configs:
        ids = [c.strip() for c in args.configs.split(",") if c.strip()]
    else:
        ids = list(PRIMARY_TRAIN_IDS)
        if args.train_c5:
            ids = ["C5"] + ids if "C5" not in ids else ids
        if args.include_sensitivity:
            ids = ids + [c for c in SENSITIVITY_IDS if c not in ids]
    unknown = [c for c in ids if c not in ABLATION_CONFIGS]
    if unknown:
        raise SystemExit(f"Unknown config ids: {unknown}; known={sorted(ABLATION_CONFIGS)}")
    return ids


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--device", choices=["auto", "cuda", "cpu"], default="auto")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--skip-hash-verify", action="store_true")
    parser.add_argument(
        "--configs",
        default="",
        help="Comma-separated config ids (default: C1,C2,C3,C4,C6).",
    )
    parser.add_argument("--seeds", default="42,52,62", help="Comma-separated seeds.")
    parser.add_argument(
        "--train-c5",
        action="store_true",
        help="Also train C5 under this namespace (normally reused from recorded table).",
    )
    parser.add_argument(
        "--include-sensitivity",
        action="store_true",
        help="Include pre-specified C5 λ∈{0.25,0.75} sensitivity runs.",
    )
    parser.add_argument(
        "--c5-ckpt-root",
        type=Path,
        default=None,
        help="Optional root containing seed{N}/best_student.pt for C5 RQ2 re-eval.",
    )
    parser.add_argument("--run-id", default="r52_teacher_anchoring_ablation_v1")
    args = parser.parse_args()

    root = (args.root or Path(__file__).resolve().parents[1]).resolve()
    out_dir = assert_output_namespace(root / OUTPUT_REL)
    out_dir.mkdir(parents=True, exist_ok=True)

    protocol = build_protocol_dict()
    (out_dir / "ablation_protocol.json").write_text(json.dumps(protocol, indent=2), encoding="utf-8")

    config_ids = resolve_config_ids(args)
    seeds = [int(s.strip()) for s in args.seeds.split(",") if s.strip()]
    for s in seeds:
        if s not in R52_TEACHERS:
            raise SystemExit(f"Unknown seed {s}; known={sorted(R52_TEACHERS)}")

    # Partition audit
    try:
        train_ds, val_ds, audits, prep_meta = load_train_validation(
            root, verify_hashes=not args.skip_hash_verify
        )
    except ProtectedDataAccessError as exc:
        manifest = {"status": "blocked_safety", "error": str(exc), "training_executed": False}
        (out_dir / "ablation_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(json.dumps(manifest, indent=2))
        return
    except RuntimeError as exc:
        manifest = {"status": "blocked_data", "error": str(exc), "training_executed": False}
        (out_dir / "ablation_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(json.dumps(manifest, indent=2))
        return

    if args.device == "cpu":
        device = torch.device("cpu")
        gpu_blocked, gpu_reason = False, "cpu_forced"
    else:
        gpu_blocked, gpu_reason = _gpu_blocked()
        if args.device == "cuda" and not torch.cuda.is_available():
            gpu_blocked = True
            gpu_reason = "cuda_requested_unavailable"
        device = torch.device("cuda" if (not gpu_blocked and torch.cuda.is_available()) else "cpu")
        if args.device == "cuda" and device.type != "cuda":
            gpu_blocked = True

    if args.prepare_only or (gpu_blocked and args.device != "cpu"):
        status = "prepared_gpu_blocked" if gpu_blocked else "prepared_only"
        manifest = {
            "status": status,
            "run_id": args.run_id,
            "gpu_blocked": gpu_blocked,
            "gpu_block_reason": gpu_reason,
            "training_executed": False,
            "config_ids": config_ids,
            "seeds": seeds,
            "device": str(device),
        }
        (out_dir / "ablation_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(json.dumps(manifest, indent=2))
        return

    metric_rows: list[dict[str, Any]] = []
    trained_or_reeval_c5 = False
    for config_id in config_ids:
        cfg = ABLATION_CONFIGS[config_id]
        for seed in seeds:
            result = run_one(
                root=root,
                out_dir=out_dir,
                config_id=config_id,
                cfg=cfg,
                seed=seed,
                device=device,
                train_ds=train_ds,
                val_ds=val_ds,
                audits=audits,
            )
            metric_rows.append(result["metric_row"])
            if config_id == "C5":
                trained_or_reeval_c5 = True

    # Optional C5 checkpoint re-eval for RQ2 pack (when C5 was not retrained)
    if args.c5_ckpt_root is not None and not trained_or_reeval_c5:
        ckpt_root = Path(args.c5_ckpt_root)
        for seed in seeds:
            ckpt = ckpt_root / f"seed{seed}" / "best_student.pt"
            if not ckpt.is_file():
                print(f"[ablation] missing C5 ckpt: {ckpt}", flush=True)
                continue
            row = reeval_existing_student(
                root=root,
                out_dir=out_dir,
                config_id="C5",
                cfg=ABLATION_CONFIGS["C5"],
                seed=seed,
                ckpt_path=ckpt,
                device=device,
                val_ds=val_ds,
            )
            metric_rows.append(row)
            trained_or_reeval_c5 = True

    if not trained_or_reeval_c5:
        metric_rows.extend(load_c5_recorded_rows(root))

    # Persist seed-level + mean±SD (no seed dropping)
    _write_csv(out_dir / "ablation_seed_metrics.csv", metric_rows)
    seed_df = pd.DataFrame(metric_rows)
    if not seed_df.empty:
        # Prefer sensitivity after primary when present
        order = list(PRIMARY_ALL_IDS) + [c for c in SENSITIVITY_IDS if c in set(seed_df["config_id"])]
        agg = mean_sd_table(seed_df, config_order=tuple(order))
        agg_path = out_dir / "ablation_mean_sd.csv"
        assert_output_namespace(agg_path)
        agg.to_csv(agg_path, index=False)

    manifest = {
        "status": "completed",
        "run_id": args.run_id,
        "training_executed": True,
        "device": str(device),
        "config_ids_requested": config_ids,
        "seeds": seeds,
        "n_metric_rows": len(metric_rows),
        "c5_source": "trained_or_reeval" if trained_or_reeval_c5 else "recorded_reproducibility_table",
        "no_retrospective_seed_removal": True,
        "sensitivity_included": any(r.get("role") == "sensitivity" for r in metric_rows),
    }
    (out_dir / "ablation_manifest.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    print(json.dumps(manifest, indent=2, default=str))


if __name__ == "__main__":
    main()
