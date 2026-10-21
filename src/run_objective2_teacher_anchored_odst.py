#!/usr/bin/env python
"""Run teacher-anchored end-to-end Bi-LSTM–attention–ODST refinement (seed 42 first)."""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
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

from prototype_v2.data import (  # noqa: E402
    EXPECTED_POS,
    SAFE_FEATURES,
    load_train_validation_datasets,
    make_loader,
    validate_train_val_tensors,
)
from prototype_v2.safety import repo_root, sha256_file  # noqa: E402
from prototype_v3_node.train import set_seed  # noqa: E402
from objective2_end_to_end_refinement.train_micro import make_diagnostic_subset  # noqa: E402
from objective2_teacher_anchored_odst.config import (  # noqa: E402
    BATCH_SIZE,
    FROZEN_COMPARATORS,
    MAX_EPOCHS,
    PARITY_SUBSET_SEED,
    PARITY_SUBSET_SIZE,
    PATIENCE,
    POS_WEIGHT_MULT,
    PRIOR_SEED42_COMPARATORS,
    TEACHER_ANCHORED_CONFIG,
)
from objective2_teacher_anchored_odst.models import (  # noqa: E402
    build_model,
    freeze_teacher,
    load_checkpoint_into,
)
from objective2_teacher_anchored_odst.safety import (  # noqa: E402
    assert_frozen_checkpoint_unchanged,
    assert_no_output_collision,
    assert_output_namespace,
    assert_partition_role_permitted,
    assert_path_not_protected_partition,
)
from objective2_teacher_anchored_odst.train import parity_check, train_teacher_anchored  # noqa: E402
from objective2_teacher_anchored_odst.viability import (  # noqa: E402
    evaluate_multiseed,
    evaluate_seed_viability,
    final_status_label,
)


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


def _objective3_or_busy_gpu() -> tuple[bool, str]:
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
    ignore = ("dwm.exe", "cursor.exe", "explorer.exe", "system", "dwm", "cursor")
    for line in smi.splitlines():
        raw = line.strip()
        if not raw:
            continue
        low = raw.lower()
        if any(tok in low for tok in ignore):
            continue
        if "python" in low or "objective3" in low or "ipython" in low or "jupyter" in low:
            return True, f"gpu_compute_process:{raw}"
    try:
        free, total = torch.cuda.mem_get_info()
        used_frac = 1.0 - free / max(total, 1)
        if used_frac > 0.50:
            return True, f"gpu_memory_fraction:{used_frac:.3f}"
    except Exception:
        pass
    return False, "gpu_clear"


def run_seed(root: Path, out_dir: Path, seed: int, device: torch.device) -> dict[str, Any]:
    assert_partition_role_permitted("r4.2_train")
    assert_partition_role_permitted("r4.2_validation")
    tensor_dir = root / "data/processed/tensors"
    assert_path_not_protected_partition(tensor_dir / "r42_T20_s1_train.npz")
    datasets = load_train_validation_datasets(tensor_dir, materialize_train=False)
    validate_train_val_tensors(datasets, SAFE_FEATURES)
    y_val = np.asarray(datasets["validation"].y)

    set_seed(seed)
    train_loader = make_loader(datasets["train"], BATCH_SIZE, shuffle=True)
    val_loader = make_loader(datasets["validation"], BATCH_SIZE, shuffle=False)
    diag_ds = make_diagnostic_subset(datasets["validation"], PARITY_SUBSET_SIZE, PARITY_SUBSET_SEED)
    indices = list(getattr(diag_ds, "indices", list(range(len(diag_ds)))))
    diag_loader = make_loader(diag_ds, PARITY_SUBSET_SIZE, shuffle=False)

    frozen_meta = FROZEN_COMPARATORS[seed]
    frozen_ckpt = root / frozen_meta["relative_dir"] / "best.pt"
    before_hash = assert_frozen_checkpoint_unchanged(frozen_ckpt, frozen_meta["expected_sha256"])

    teacher = build_model()
    student = build_model()
    load_checkpoint_into(teacher, frozen_ckpt)
    load_checkpoint_into(student, frozen_ckpt)
    freeze_teacher(teacher)
    teacher.to(device)
    student.to(device)

    parity = parity_check(teacher, student, diag_loader, device, indices)
    if not parity["initial_parity_ok"]:
        raise RuntimeError(f"Initial teacher–student parity failed: {parity}")

    teacher_state0 = {k: v.detach().cpu().clone() for k, v in teacher.state_dict().items()}
    student_state0 = {k: v.detach().cpu().clone() for k, v in student.state_dict().items()}
    n_pos = float(EXPECTED_POS["train"])
    n_neg = float(len(datasets["train"]) - EXPECTED_POS["train"])
    pos_weight = torch.tensor([POS_WEIGHT_MULT * n_neg / max(n_pos, 1.0)], dtype=torch.float32)

    print(f"[teacher-anchored] seed={seed} device={device} max_epochs={MAX_EPOCHS} patience={PATIENCE}")
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
    after_hash = assert_frozen_checkpoint_unchanged(frozen_ckpt, before_hash)

    # catastrophic FP/FN relative to teacher comparator
    result["catastrophic_fp_fn"] = bool(
        result["best_fp"] > max(3.0 * frozen_meta["fp"], frozen_meta["fp"] + 100)
        and result["best_fn"] > max(3.0 * frozen_meta["fn"], frozen_meta["fn"] + 100)
    )
    result["initial_parity_ok"] = parity["initial_parity_ok"]
    result["parity"] = parity
    result["teacher_pr_auc"] = frozen_meta["pr_auc"]
    result["teacher_f1"] = frozen_meta["f1"]
    result["teacher_unused_leaves_pct"] = frozen_meta["unused_leaves_pct"]
    result["teacher_checkpoint"] = str(frozen_ckpt)
    result["teacher_checkpoint_sha256"] = after_hash
    result["prior_comparators"] = PRIOR_SEED42_COMPARATORS if seed == 42 else {}
    gate = evaluate_seed_viability(teacher=frozen_meta, run=result)
    result["gate"] = gate

    seed_dir = out_dir / f"seed{seed}"
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
                "prototype": "teacher_anchored_odst",
                "test_evaluated": False,
                "teacher_required_at_inference": False,
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
        ).to_parquet(seed_dir / "validation_predictions.parquet", index=False)

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


def make_figures(out_dir: Path, results: dict[int, dict[str, Any]]) -> None:
    fig, ax = plt.subplots(figsize=(7, 4))
    for seed, r in results.items():
        xs = [row["epoch"] for row in r["epoch_rows"]]
        ax.plot(xs, [row["validation_pr_auc"] for row in r["epoch_rows"]], marker="o", label=f"student s{seed}")
        ax.axhline(r["teacher_pr_auc"], linestyle="--", alpha=0.5, label=f"teacher s{seed}")
    ax.legend(fontsize=7)
    ax.set_title("Teacher-anchored PR-AUC")
    fig.tight_layout()
    fig.savefig(out_dir / "pr_auc_learning_curves.png", dpi=300)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7, 4))
    for seed, r in results.items():
        xs = [row["epoch"] for row in r["epoch_rows"]]
        ax.plot(xs, [row["validation_f1"] for row in r["epoch_rows"]], marker="o", label=f"s{seed}")
        ax.axhline(r["teacher_f1"], linestyle="--", alpha=0.5)
    ax.legend()
    ax.set_title("F1 learning curves")
    fig.tight_layout()
    fig.savefig(out_dir / "f1_learning_curves.png", dpi=300)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7, 4))
    for seed, r in results.items():
        xs = [row["epoch"] for row in r["loss_rows"]]
        ax.plot(xs, [row["train_class_loss"] for row in r["loss_rows"]], label=f"class s{seed}")
        ax.plot(xs, [row["train_logit_consistency_loss"] for row in r["loss_rows"]], linestyle="--", label=f"logit s{seed}")
        ax.plot(xs, [row["train_route_consistency_loss"] for row in r["loss_rows"]], linestyle=":", label=f"route s{seed}")
    ax.legend(fontsize=6)
    ax.set_title("Classification and consistency losses")
    fig.tight_layout()
    fig.savefig(out_dir / "classification_and_consistency_losses.png", dpi=300)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7, 4))
    for seed, r in results.items():
        xs = [row["epoch"] for row in r["grad_rows"]]
        ax.plot(xs, [row["grad_lstm_median"] for row in r["grad_rows"]], label=f"LSTM s{seed}")
        ax.plot(xs, [row["grad_attention_median"] for row in r["grad_rows"]], linestyle="--", label=f"attn s{seed}")
        ax.plot(xs, [row["grad_odst_median"] for row in r["grad_rows"]], linestyle=":", label=f"ODST s{seed}")
    ax.legend(fontsize=6)
    ax.set_title("Component gradient medians")
    fig.tight_layout()
    fig.savefig(out_dir / "component_gradient_norms.png", dpi=300)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7, 4))
    for seed, r in results.items():
        xs = [row["epoch"] for row in r["routing_rows"]]
        ax.plot(xs, [row["student_routing_entropy"] for row in r["routing_rows"]], label=f"student ent s{seed}")
        ax.plot(xs, [row["teacher_routing_entropy"] for row in r["routing_rows"]], linestyle="--", label=f"teacher ent s{seed}")
    ax.legend(fontsize=7)
    ax.set_title("Teacher vs student routing entropy")
    fig.tight_layout()
    fig.savefig(out_dir / "teacher_versus_student_routing.png", dpi=300)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7, 4))
    for seed, r in results.items():
        xs = [row["epoch"] for row in r["routing_rows"]]
        ax.plot(xs, [row["student_unused_leaves_pct"] for row in r["routing_rows"]], label=f"student unused s{seed}")
        ax.plot(xs, [row["teacher_unused_leaves_pct"] for row in r["routing_rows"]], linestyle="--", label=f"teacher unused s{seed}")
    ax.legend(fontsize=7)
    ax.set_title("Leaf utilisation")
    fig.tight_layout()
    fig.savefig(out_dir / "leaf_utilisation.png", dpi=300)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7, 4))
    for seed, r in results.items():
        xs = [row["epoch"] for row in r["param_rows"]]
        ax.plot(xs, [row["pooled_cosine_similarity"] for row in r["param_rows"]], label=f"cos s{seed}")
    ax.axhline(0.98, color="gray", linestyle="--")
    ax.legend()
    ax.set_title("Representation drift (student vs teacher)")
    fig.tight_layout()
    fig.savefig(out_dir / "representation_drift.png", dpi=300)
    plt.close(fig)

    for seed, r in results.items():
        bm = r.get("best_metrics")
        if not bm:
            continue
        fig, ax = plt.subplots(figsize=(7, 4))
        ax.hist(bm["teacher"]["logits"], bins=50, alpha=0.5, label="teacher", density=True)
        ax.hist(bm["student"]["logits"], bins=50, alpha=0.5, label="student", density=True)
        ax.legend()
        ax.set_title(f"Teacher vs student score distributions (seed {seed})")
        fig.tight_layout()
        fig.savefig(out_dir / f"teacher_versus_student_score_distributions_seed{seed}.png", dpi=300)
        plt.close(fig)

        fig, ax = plt.subplots(figsize=(5, 4))
        agree = bm["prediction_agreement"]
        changed = bm["pct_predictions_changed"] / 100.0
        ax.bar(["agreement", "changed"], [agree, changed])
        ax.set_ylim(0, 1)
        ax.set_title(f"Prediction agreement (seed {seed})")
        fig.tight_layout()
        fig.savefig(out_dir / f"prediction_agreement_seed{seed}.png", dpi=300)
        plt.close(fig)


def write_reports(out_dir: Path, results: dict[int, dict], status: str, multi, meta: dict) -> None:
    lines = [
        "# TEACHER_ANCHORED_INTERPRETATION",
        "",
        "## Final status",
        f"`{status}`",
        "",
        "## Repository / provenance",
        f"- worktree: {meta.get('worktree')}",
        f"- branch: {meta.get('branch')}",
        f"- start HEAD: {meta.get('start_head')}",
        f"- final HEAD (pre-commit): {meta.get('final_head')}",
        f"- working-tree status: {meta.get('worktree_status')}",
        f"- partitions: r42_T20_s1_train / r42_T20_s1_validation only",
        f"- protected partitions accessed: {meta.get('protected_accessed')}",
        f"- Objective 3 / locked evidence changed: {meta.get('obj3_changed')}",
        f"- tests: {meta.get('tests')}",
        "",
        "## Completed evidence",
    ]
    for seed, r in sorted(results.items()):
        g = r["gate"]
        bm = r["best_metrics"]
        lines.append(
            f"- Seed {seed}: student PR-AUC={r['best_pr_auc']:.6f} (epoch {r['best_epoch']}) vs teacher {r['teacher_pr_auc']:.6f}; "
            f"Δ={g['pr_auc_delta']:.6f}; viable={g['viable']}; reasons={g['reasons']}; "
            f"unused% student/teacher={r['unused_leaves_pct']:.3f}/{r['teacher_unused_leaves_pct']:.3f}; "
            f"cosine={r['final_pooled_cosine']:.4f}; route_div={r['routing_divergence']:.6f}; "
            f"agreement={bm['prediction_agreement']:.4f}"
        )
    if 42 in results:
        lines.append("")
        lines.append("### Prior failed joint experiments (seed 42, saved summaries only)")
        for name, info in PRIOR_SEED42_COMPARATORS.items():
            lines.append(f"- {name}: {info}")
    lines += [
        "",
        "## Preliminary interpretation",
        "- Teacher remains permanently frozen; student is trained end-to-end with fixed logit and routing consistency weights (0.5, 0.5).",
        "- Representation drift is monitored but not directly penalised.",
        "",
        "## Rejected claims",
        "- No automatic claim of superiority, novelty, deployment readiness, or multi-seed confirmation from seed-42-only evidence.",
        "- No r5.2/r6.2 conclusions.",
        "",
        "## Objective 2 implication",
        "Whether teacher anchoring yields stable genuine end-to-end Bi-LSTM–attention–ODST training is determined by the status label.",
        "",
        "## Chapter 3 implication",
        "If viable, document teacher-anchored training as a candidate final training strategy while inference remains Bi-LSTM–attention–ODST; otherwise record a negative bounded trial.",
        "",
        "## Chapter 4 implication",
        "Compare teacher-anchored student against frozen ODST first, then T2, residual ODST, attention–linear, standalone Bi-LSTM, RF, XGBoost, and fragmented hybrids.",
        "",
        f"Multi-seed: {json.dumps(multi, default=str)}",
    ]
    (out_dir / "TEACHER_ANCHORED_INTERPRETATION.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out_dir / "EXPERIMENTAL_HANDOVER.md").write_text(
        f"""# Experimental handover — teacher-anchored ODST

## Status
`{status}`

## Isolation
- Worktree: {meta.get('worktree')}
- Branch: {meta.get('branch')}
- Start commit: {meta.get('start_head')}
- Outputs: outputs/objective2/teacher_anchored_odst/
- Prior T2 / residual namespaces preserved

## Seeds
{sorted(results.keys())}

## Notes
Frozen ODST teacher remains the protected comparator. Student inference does not require the teacher. Do not merge into main.
""",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--device", choices=["auto", "cuda", "cpu"], default="auto")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--run-id", default="teacher_anchored_v1")
    args = parser.parse_args()
    root = args.root or repo_root()
    out_dir = assert_output_namespace(root / "outputs/objective2/teacher_anchored_odst", root)
    out_dir.mkdir(parents=True, exist_ok=True)
    assert_no_output_collision(out_dir, args.run_id)

    (out_dir / "teacher_anchored_config.json").write_text(
        json.dumps(TEACHER_ANCHORED_CONFIG, indent=2), encoding="utf-8"
    )

    start_head = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    branch = subprocess.check_output(["git", "-C", str(root), "branch", "--show-current"], text=True).strip()
    status_txt = subprocess.check_output(["git", "-C", str(root), "status", "--short"], text=True)

    gpu_blocked = False
    gpu_reason = "n/a"
    if args.device == "cpu":
        device = torch.device("cpu")
    else:
        gpu_blocked, gpu_reason = _objective3_or_busy_gpu()
        if args.device == "cuda" and not torch.cuda.is_available():
            gpu_blocked = True
            gpu_reason = "cuda_requested_unavailable"
        device = torch.device("cuda" if (not gpu_blocked and torch.cuda.is_available()) else "cpu")
        if args.device == "cuda" and device.type != "cuda":
            gpu_blocked = True

    if args.prepare_only or gpu_blocked:
        status = "objective2_teacher_anchored_prepared_gpu_blocked"
        manifest = {
            "status": status,
            "run_id": args.run_id,
            "gpu_blocked": True,
            "gpu_block_reason": gpu_reason,
            "training_executed": False,
            "start_head": start_head,
            "branch": branch,
            "viability_gate_stored": TEACHER_ANCHORED_CONFIG["viability"],
        }
        (out_dir / "teacher_anchored_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(json.dumps(manifest, indent=2))
        return

    results: dict[int, dict[str, Any]] = {}
    r42 = run_seed(root, out_dir, 42, device)
    results[42] = r42
    gate42 = r42["gate"]

    confirmation_run = False
    multi = None
    if gate42["viable"]:
        for seed in (52, 62):
            results[seed] = run_seed(root, out_dir, seed, device)
        confirmation_run = True
        multi = evaluate_multiseed(results)
        status = final_status_label(seed42_gate=gate42, confirmation_run=True, multiseed=multi)
    else:
        status = final_status_label(seed42_gate=gate42, confirmation_run=False)

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
                "viable": g["viable"],
                "improved_vs_teacher": g["improved_vs_teacher"],
                "reasons": ";".join(g["reasons"]),
                "unused_leaves_pct": r["unused_leaves_pct"],
                "teacher_unused_leaves_pct": r["teacher_unused_leaves_pct"],
                "final_pooled_cosine": r["final_pooled_cosine"],
                "routing_divergence": r["routing_divergence"],
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
            {"seed": seed, **{k: v for k, v in p.items() if k != "parity_indices"}, "n_indices": len(p.get("parity_indices", []))}
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

    _write_csv(out_dir / "teacher_anchored_seed_summary.csv", seed_summary)
    _write_csv(out_dir / "teacher_anchored_epoch_metrics.csv", all_epoch)
    _write_csv(out_dir / "teacher_anchored_loss_components.csv", all_loss)
    _write_csv(out_dir / "teacher_anchored_gradient_summary.csv", all_grad)
    _write_csv(out_dir / "teacher_anchored_parameter_updates.csv", all_param)
    _write_csv(out_dir / "teacher_anchored_routing_summary.csv", all_routing)
    _write_csv(out_dir / "teacher_anchored_thresholds.csv", thresholds)
    _write_csv(out_dir / "teacher_student_initial_parity.csv", parity_rows)
    _write_csv(out_dir / "teacher_anchored_prediction_agreement.csv", agreement_rows)

    make_figures(out_dir, results)
    final_head = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    meta = {
        "worktree": str(root),
        "branch": branch,
        "start_head": start_head,
        "final_head": final_head,
        "worktree_status": status_txt.strip() or "clean",
        "protected_accessed": False,
        "obj3_changed": False,
        "tests": "see local pytest invocation in session log",
    }
    write_reports(out_dir, results, status, multi, meta)

    manifest = {
        "status": status,
        "run_id": args.run_id,
        "training_executed": True,
        "gpu_blocked": False,
        "device": str(device),
        "seeds_executed": sorted(results.keys()),
        "seed42_viable": gate42["viable"],
        "multiseed": multi,
        "start_head": start_head,
        "branch": branch,
        "output_dir": str(out_dir),
        "viability_gate_stored": TEACHER_ANCHORED_CONFIG["viability"],
        "consistency_weights": {"logit": 0.5, "route": 0.5},
        "frozen_teacher_checkpoints_unchanged": True,
        "objective3_untouched": True,
        "prior_joint_outputs_untouched": True,
    }
    (out_dir / "teacher_anchored_manifest.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    print(json.dumps(manifest, indent=2, default=str))


if __name__ == "__main__":
    main()
