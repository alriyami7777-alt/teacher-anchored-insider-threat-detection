"""Post-primary reduced-capacity ODST 8-tree ablation pipeline."""

from __future__ import annotations

import json
import shutil
import subprocess
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import torch

from objective2_teacher_anchored_odst.models import build_model, load_checkpoint_into
from prototype_v3_node.train import set_seed

from .constants import (
    ARCHITECTURE,
    BASE_COMMIT,
    BRANCH,
    COMPARATOR_16,
    COMPARATOR_M,
    FIDELITY_K,
    M_TREES,
    NODE_DEPTH,
    NODE_N_TREES,
    NODE_NUM_LAYERS,
    OUTPUT_REL,
    PRIMARY_SEED,
    RECORDED_REL,
    SEEDS_ORDER,
    STATUS_GPU,
    STATUS_INCOMPLETE,
    STATUS_PROV,
    STATUS_SAFETY,
    STATUS_SEED42_FAIL,
)
from .fidelity import centred_faithfulness, training_median_refs
from .gate import classify_multiseed, evaluate_seed_gate
from .safety import (
    OpenedFilesRegister,
    ProtectedDataAccessError,
    StudyBlockedError,
    assert_output_namespace,
    environment_metadata,
    refuse_test_loader,
    sha256_file,
    write_json_atomic,
    write_text_atomic,
)
from .student_train import extract_tree_outputs, inference_benchmark, train_8tree_student
from .teacher_stage_b import load_train_val, train_8tree_teacher


def _flush(msg: str) -> None:
    print(msg, flush=True)


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
    ignore = ("dwm.exe", "cursor.exe", "explorer.exe", "system", "shellhost.exe", "whatsapp")
    for line in smi.splitlines():
        raw = line.strip()
        if not raw:
            continue
        low = raw.lower()
        if any(tok in low for tok in ignore):
            continue
        if "python" in low or "objective" in low:
            return True, f"gpu_compute_process:{raw}"
    return False, "gpu_clear"


def _mirror(out_dir: Path, repo: Path) -> None:
    dest = repo / RECORDED_REL
    dest.mkdir(parents=True, exist_ok=True)
    for pattern in ("*.md", "*.csv", "*.json"):
        for p in out_dir.glob(pattern):
            shutil.copy2(p, dest / p.name)
    for sub in ("figures", "figure_sources", "seed42", "seed52", "seed62"):
        s = out_dir / sub
        if not s.exists():
            continue
        d2 = dest / sub
        d2.mkdir(parents=True, exist_ok=True)
        for p in s.rglob("*"):
            if p.is_file():
                rel = p.relative_to(s)
                target = d2 / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, target)


def _measure_16_latency(repo: Path, seed: int, X_val: np.ndarray, device: torch.device, opened: OpenedFilesRegister) -> float:
    meta = COMPARATOR_16[seed]
    if meta.get("latency_bs32_sec") is not None and seed == 42:
        return float(meta["latency_bs32_sec"])
    ckpt = opened.record(repo / meta["ckpt_rel"], f"comparator16_{seed}")
    if sha256_file(ckpt) != meta["expected_sha256"]:
        raise StudyBlockedError(STATUS_PROV, f"16-tree hash mismatch seed={seed}")
    # 16-tree architecture
    arch16 = dict(ARCHITECTURE)
    arch16["node_n_trees"] = 8
    m = build_model(**arch16).to(device)
    load_checkpoint_into(m, ckpt)
    m.eval()
    for p in m.parameters():
        p.requires_grad = False
    rows = inference_benchmark(m, X_val, device)
    return float(next(r["median_latency_sec"] for r in rows if r["batch_size"] == 32))


def _md_table(df: pd.DataFrame, n: int = 40) -> str:
    if df is None or len(df) == 0:
        return "_(empty)_"
    view = df.head(n)
    cols = list(view.columns)
    lines = ["| " + " | ".join(map(str, cols)) + " |", "| " + " | ".join("---" for _ in cols) + " |"]
    for row in view.itertuples(index=False):
        lines.append("| " + " | ".join(str(x) for x in row) + " |")
    return "\n".join(lines)


def run(repo_root: Path | None = None) -> dict[str, Any]:
    repo = Path(repo_root or Path.cwd()).resolve()
    out_dir = assert_output_namespace(repo / OUTPUT_REL)
    out_dir.mkdir(parents=True, exist_ok=True)
    opened = OpenedFilesRegister()
    checks: dict[str, Any] = {}

    try:
        try:
            refuse_test_loader()
            checks["test_refused"] = False
        except ProtectedDataAccessError:
            checks["test_refused"] = True

        blocked, reason = _gpu_blocked()
        checks["gpu_block_reason"] = reason
        if blocked:
            write_json_atomic(
                out_dir / "odst_8tree_manifest.json",
                {"status": STATUS_GPU, "reason": reason, "checks": checks},
            )
            _flush(f"GPU blocked: {reason}")
            return {"status": STATUS_GPU}

        device = torch.device("cuda")
        _flush(f"GPU clear — running 8-tree ablation on {device}")

        config = {
            "study": "r52_odst_8tree_ablation_v1",
            "description": "post-primary reduced-capacity ODST ablation",
            "branch": BRANCH,
            "base_commit": BASE_COMMIT,
            "architecture_change": "node_n_trees 8→4 (M=16→8); depth and layers unchanged",
            "node_num_layers": NODE_NUM_LAYERS,
            "node_n_trees": NODE_N_TREES,
            "node_depth": NODE_DEPTH,
            "M_trees": M_TREES,
            "comparator_M": COMPARATOR_M,
            "architecture": ARCHITECTURE,
            "fidelity_k": list(FIDELITY_K),
            "attribution": "c_m=(o_m-b_m)/8",
            "auto_replace_16tree": False,
            "created_utc": datetime.now(timezone.utc).isoformat(),
        }
        write_json_atomic(out_dir / "odst_8tree_config.json", config)

        _flush("Loading train/validation (test blocked) ...")
        data = load_train_val(repo, opened)

        teacher_rows, parity_rows, seed_rows, epoch_rows = [], [], [], []
        calib_rows, routing_rows, redun_rows, fid_rows, cost_rows = [], [], [], [], []
        cmp_rows, gate_rows = [], []
        completed_seeds: list[int] = []

        for seed in SEEDS_ORDER:
            if seed != PRIMARY_SEED and not gate_rows:
                break
            if seed != PRIMARY_SEED and not gate_rows[0]["passed"]:
                _flush("Seed 42 failed viability — stopping (no 52/62).")
                break

            seed_dir = out_dir / f"seed{seed}"
            teacher_dir = seed_dir / "teacher"
            student_dir = seed_dir / "student"
            seed_dir.mkdir(parents=True, exist_ok=True)

            _flush(f"=== Seed {seed}: train matched 8-tree teacher ===")
            set_seed(seed)
            t_out = train_8tree_teacher(
                repo=repo, seed=seed, out_dir=teacher_dir, device=device, data=data, opened=opened
            )
            tsum = t_out["summary"]
            teacher_rows.append(
                {
                    "seed": seed,
                    "teacher_checkpoint_sha256": tsum["checkpoint_sha256"],
                    "encoder_weight_sha256": tsum["encoder_weight_sha256"],
                    "best_epoch": tsum["best_epoch"],
                    "pr_auc": tsum["validation_metrics"]["pr_auc"],
                    "f1": tsum["validation_metrics"]["f1"],
                    "threshold": tsum["validation_metrics"]["threshold"],
                    "fp": tsum["validation_metrics"]["fp"],
                    "fn": tsum["validation_metrics"]["fn"],
                    "duration_sec": tsum["duration_sec"],
                    "peak_gpu_memory_mb": tsum["peak_gpu_memory_mb"],
                    "n_odst_trainable": tsum["parameter_counts"].get("node_head_trainable"),
                    "M_trees": M_TREES,
                }
            )
            for h in t_out["history"]:
                epoch_rows.append({**h, "model_role": "teacher"})

            _flush(f"=== Seed {seed}: teacher-anchored 8-tree student ===")
            s_out = train_8tree_student(
                seed=seed,
                teacher_ckpt=t_out["best_path"],
                out_dir=student_dir,
                device=device,
                data=data,
            )
            ssum = s_out["summary"]
            parity_rows.append({"seed": seed, **ssum["initial_parity"]})
            met = ssum["validation_metrics"]
            seed_rows.append(
                {
                    "seed": seed,
                    "best_epoch": ssum["best_epoch"],
                    "pr_auc": met["pr_auc"],
                    "precision": met["precision"],
                    "recall": met["recall"],
                    "f1": met["f1"],
                    "fp": met["fp"],
                    "fn": met["fn"],
                    "threshold": ssum["threshold"],
                    "brier_score": ssum["calibration"]["brier_score"],
                    "log_loss": ssum["calibration"]["log_loss"],
                    "ece": ssum["calibration"]["ece"],
                    "training_time_sec": ssum["duration_sec"],
                    "peak_gpu_memory_mb": ssum["peak_gpu_memory_mb"],
                    "checkpoint_size_bytes": ssum["checkpoint_size_bytes"],
                    "n_parameters": ssum["n_parameters"],
                    "n_odst_head_parameters": ssum["n_odst_head_parameters"],
                    "unused_leaves_pct": ssum["unused_leaves_pct"],
                    "routing_entropy_mean": ssum["routing_entropy_mean"],
                    "effective_rank": ssum["effective_rank"],
                    "tree_output_mean_abs_corr": ssum["tree_output_mean_abs_corr"],
                    "checkpoint_sha256": ssum["checkpoint_sha256"],
                    "teacher_unchanged": ssum["teacher_unchanged"],
                    "joint_training_verified": ssum["joint_training_verified"],
                }
            )
            calib_rows.append({"seed": seed, **ssum["calibration"], "threshold": ssum["threshold"]})
            routing_rows.append(
                {
                    "seed": seed,
                    "unused_leaves_pct": ssum["unused_leaves_pct"],
                    "routing_entropy_mean": ssum["routing_entropy_mean"],
                }
            )
            redun_rows.append(
                {
                    "seed": seed,
                    "M": M_TREES,
                    "effective_rank": ssum["effective_rank"],
                    "effective_rank_over_M": ssum["effective_rank_over_M"],
                    "tree_output_mean_abs_corr": ssum["tree_output_mean_abs_corr"],
                    "top_half_contribution_share": ssum["top_half_contribution_share"],
                    "unused_leaves_pct": ssum["unused_leaves_pct"],
                }
            )
            for er in ssum.get("epoch_rows") or []:
                epoch_rows.append({**er, "model_role": "student"})
            for lat in ssum["latency"]:
                cost_rows.append(
                    {
                        "seed": seed,
                        "model": "8tree_student",
                        **lat,
                        "explanation_extraction_latency_bs32_median": ssum[
                            "explanation_extraction_latency_bs32_median"
                        ],
                        "checkpoint_size_bytes": ssum["checkpoint_size_bytes"],
                        "n_odst_head_parameters": ssum["n_odst_head_parameters"],
                    }
                )

            _flush(f"=== Seed {seed}: reference-centred fidelity ===")
            refs = training_median_refs(s_out["student"], data["X_train"], device)
            bundle = extract_tree_outputs(s_out["student"], data["X_val"], device)
            trees = bundle["tree_outputs"]
            recon_err = np.abs(trees.mean(axis=1) - bundle["logit"])
            if float(recon_err.max()) > 1e-5:
                raise RuntimeError(f"readout mismatch seed={seed} max={recon_err.max()}")
            fid = centred_faithfulness(trees, refs, data["users_val"], ssum["threshold"], seed)
            fid_rows.append(fid)

            _flush(f"=== Seed {seed}: compare latency vs 16-tree ===")
            lat16 = _measure_16_latency(repo, seed, data["X_val"], device, opened)
            gate = evaluate_seed_gate(
                seed=seed,
                student_summary=ssum,
                fidelity_df=fid,
                latency_16_bs32=lat16,
            )
            gate_rows.append(gate)
            cmp_rows.append(
                {
                    "seed": seed,
                    "pr_auc_8": gate["pr_auc_8"],
                    "pr_auc_16": gate["pr_auc_16"],
                    "pr_auc_delta": gate["pr_auc_delta"],
                    "f1_8": gate["f1_8"],
                    "f1_16": gate["f1_16"],
                    "f1_delta": gate["f1_delta"],
                    "fp_8": gate["fp_8"],
                    "fp_16": gate["fp_16"],
                    "fn_8": gate["fn_8"],
                    "fn_16": gate["fn_16"],
                    "latency_bs32_8": gate["latency_bs32_8"],
                    "latency_bs32_16": gate["latency_bs32_16"],
                    "latency_reduction": gate["latency_reduction"],
                    "unused_leaves_pct_8": gate["unused_leaves_pct_8"],
                    "unused_leaves_pct_16": gate["unused_leaves_pct_16"],
                    "gate_passed": gate["passed"],
                }
            )
            completed_seeds.append(seed)
            _flush(f"Seed {seed} gate passed={gate['passed']} reasons={gate['reasons'] or 'ok'}")

            if seed == PRIMARY_SEED and not gate["passed"]:
                _flush("Seed-42 viability failed — stop rule.")
                break

        # write tables
        pd.DataFrame(teacher_rows).to_csv(out_dir / "odst_8tree_teacher_provenance.csv", index=False)
        pd.DataFrame(parity_rows).to_csv(out_dir / "odst_8tree_initial_parity.csv", index=False)
        pd.DataFrame(seed_rows).to_csv(out_dir / "odst_8tree_seed_metrics.csv", index=False)
        pd.DataFrame(epoch_rows).to_csv(out_dir / "odst_8tree_epoch_metrics.csv", index=False)
        pd.DataFrame(calib_rows).to_csv(out_dir / "odst_8tree_calibration.csv", index=False)
        pd.DataFrame(routing_rows).to_csv(out_dir / "odst_8tree_routing.csv", index=False)
        pd.DataFrame(redun_rows).to_csv(out_dir / "odst_8tree_redundancy.csv", index=False)
        fid_df = pd.concat(fid_rows, ignore_index=True) if fid_rows else pd.DataFrame()
        fid_df.to_csv(out_dir / "odst_8tree_reference_centred_fidelity.csv", index=False)
        pd.DataFrame(cost_rows).to_csv(out_dir / "odst_8tree_cost.csv", index=False)
        pd.DataFrame(cmp_rows).to_csv(out_dir / "odst_8tree_vs_16tree_comparison.csv", index=False)
        gate_df = pd.DataFrame(gate_rows)
        gate_df.to_csv(out_dir / "odst_8tree_gate_decision.csv", index=False)

        if not gate_rows:
            status = STATUS_INCOMPLETE
        elif not gate_rows[0]["passed"]:
            status = STATUS_SEED42_FAIL
        elif len(completed_seeds) == 1:
            status = STATUS_SEED42_FAIL  # shouldn't happen if passed — actually seed42 alone pass needs multiseed
            # If only seed42 ran and passed, we should have continued — if loop broke early incorrectly
            status = classify_multiseed(gate_rows) if len(gate_rows) >= 1 else STATUS_INCOMPLETE
            # With only seed42 passed, classify as not multi-supported yet — but we always continue if passed
            if len(completed_seeds) < 3 and gate_rows[0]["passed"]:
                # incomplete multi-seed
                status = STATUS_INCOMPLETE
            else:
                status = classify_multiseed(gate_rows)
        else:
            status = classify_multiseed(gate_rows)

        # Fix status logic more cleanly:
        if not gate_rows:
            status = STATUS_INCOMPLETE
        elif not gate_rows[0]["passed"]:
            status = STATUS_SEED42_FAIL
        elif len(gate_rows) < 3:
            status = STATUS_INCOMPLETE
        else:
            status = classify_multiseed(gate_rows)

        # figures
        fig_dir = out_dir / "figures"
        src = out_dir / "figure_sources"
        fig_dir.mkdir(parents=True, exist_ok=True)
        src.mkdir(parents=True, exist_ok=True)

        cmp_df = pd.DataFrame(cmp_rows)
        cmp_df.to_csv(src / "figure1_pr_f1.csv", index=False)
        if len(cmp_df):
            fig, axes = plt.subplots(1, 2, figsize=(7.5, 3.2))
            x = np.arange(len(cmp_df))
            w = 0.35
            axes[0].bar(x - w / 2, cmp_df.pr_auc_16, w, label="16-tree")
            axes[0].bar(x + w / 2, cmp_df.pr_auc_8, w, label="8-tree")
            axes[0].set_xticks(x)
            axes[0].set_xticklabels(cmp_df.seed.astype(str))
            axes[0].set_ylabel("PR-AUC")
            axes[0].legend(fontsize=8)
            axes[1].bar(x - w / 2, cmp_df.f1_16, w, label="16-tree")
            axes[1].bar(x + w / 2, cmp_df.f1_8, w, label="8-tree")
            axes[1].set_xticks(x)
            axes[1].set_xticklabels(cmp_df.seed.astype(str))
            axes[1].set_ylabel("F1")
            axes[1].legend(fontsize=8)
            fig.tight_layout()
            fig.savefig(fig_dir / "figure1_pr_f1_comparison.png", dpi=200, bbox_inches="tight")
            plt.close(fig)

        pd.DataFrame(calib_rows).to_csv(src / "figure2_calibration.csv", index=False)
        if calib_rows:
            fig, ax = plt.subplots(figsize=(4.5, 3.2))
            for r in calib_rows:
                ax.scatter(["Brier", "logloss", "ECE"], [r["brier_score"], r["log_loss"], r["ece"]], label=f"s{r['seed']}")
            ax.legend(fontsize=8)
            ax.set_ylabel("score")
            fig.tight_layout()
            fig.savefig(fig_dir / "figure2_calibration_comparison.png", dpi=200, bbox_inches="tight")
            plt.close(fig)

        pd.DataFrame(cost_rows).to_csv(src / "figure3_latency.csv", index=False)
        if cost_rows:
            fig, ax = plt.subplots(figsize=(5, 3.2))
            for seed in completed_seeds:
                g = [r for r in cost_rows if r["seed"] == seed]
                ax.plot([r["batch_size"] for r in g], [r["median_latency_sec"] for r in g], marker="o", label=f"8tree s{seed}")
            # 16-tree bs32 markers
            for r in cmp_rows:
                ax.scatter([32], [r["latency_bs32_16"]], marker="x", label=f"16tree s{r['seed']}")
            ax.set_xlabel("batch size")
            ax.set_ylabel("median latency (s)")
            ax.legend(fontsize=7)
            fig.tight_layout()
            fig.savefig(fig_dir / "figure3_latency_comparison.png", dpi=200, bbox_inches="tight")
            plt.close(fig)

        pd.DataFrame(redun_rows).to_csv(src / "figure4_redundancy.csv", index=False)
        if redun_rows:
            fig, axes = plt.subplots(1, 2, figsize=(7, 3.2))
            rdf = pd.DataFrame(redun_rows)
            axes[0].bar(rdf.seed.astype(str), rdf.unused_leaves_pct)
            axes[0].set_ylabel("unused leaves %")
            axes[1].bar(rdf.seed.astype(str), rdf.effective_rank_over_M)
            axes[1].set_ylabel("effective rank / M")
            fig.tight_layout()
            fig.savefig(fig_dir / "figure4_active_leaf_redundancy.png", dpi=200, bbox_inches="tight")
            plt.close(fig)

        if len(fid_df):
            fid_df.to_csv(src / "figure5_fidelity.csv", index=False)
            fig, ax = plt.subplots(figsize=(5.5, 3.4))
            for seed in completed_seeds:
                g = fid_df[fid_df.seed == seed].sort_values("k")
                ax.errorbar(
                    g.k + (seed - 52) * 0.05,
                    g.delta_top_minus_random,
                    yerr=[g.delta_top_minus_random - g.ci_low, g.ci_high - g.delta_top_minus_random],
                    fmt="o-",
                    capsize=3,
                    label=f"seed {seed}",
                )
            ax.axhline(0, color="gray", ls=":", lw=1)
            ax.set_xlabel("k")
            ax.set_ylabel("Δ top−random")
            ax.legend(fontsize=8)
            fig.tight_layout()
            fig.savefig(fig_dir / "figure5_explanation_fidelity.png", dpi=200, bbox_inches="tight")
            plt.close(fig)

        # reports
        write_text_atomic(
            out_dir / "ODST_8TREE_INTERPRETATION.md",
            f"""# ODST 8-tree ablation interpretation

## Status

`{status}`

## Experiment type

Post-primary reduced-capacity ODST ablation (16→8 averaged tree units via `node_n_trees` 8→4; depth and layers unchanged).

## Seed-42 gate

{_md_table(gate_df[gate_df.seed==42] if len(gate_df) else gate_df)}

## Comparison vs frozen 16-tree students

{_md_table(cmp_df)}

## Reference-centred fidelity

{_md_table(fid_df)}

## Restrictions

Do not claim automatic replacement of the 16-tree candidate. Do not claim predictive superiority unless directly supported. Requires supervisor review before any candidate change.
""",
        )
        write_text_atomic(
            out_dir / "PAPER_ODST_SIMPLIFICATION_NOTES.md",
            f"""# Paper notes — ODST simplification

Status `{status}`. This is a post-primary reduced-capacity ODST ablation on CERT r5.2 validation only.
""",
        )
        write_text_atomic(
            out_dir / "CHAPTER3_ODST_SIMPLIFICATION_NOTES.md",
            f"""# Chapter 3 notes — ODST simplification (Phase 3)

Controlled architecture refinement: forest capacity M=16→8 with matched 8-tree teacher. Status `{status}`.
""",
        )
        write_text_atomic(
            out_dir / "CHAPTER4_ODST_SIMPLIFICATION_NOTES.md",
            f"""# Chapter 4 notes — ODST simplification

Validation-only 8-tree ablation under Objective 2. Status `{status}`. No automatic candidate replacement.
""",
        )
        write_text_atomic(
            out_dir / "OBJECTIVE2_ODST_SIMPLIFICATION_DEFENCE.md",
            f"""# Defence — ODST 8-tree simplification

Matched 8-tree teachers were trained from the same frozen Bi-LSTM–attention initialisations; students followed the frozen teacher-anchored procedure. The 16-tree model remains the protected comparator. Status `{status}`.
""",
        )
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(repo), text=True).strip()
        write_text_atomic(
            out_dir / "EXPERIMENTAL_HANDOVER.md",
            f"""# Experimental handover — ODST 8-tree ablation

## Final status

`{status}`

## Git

- Branch: `{BRANCH}`
- Final package commit: `{head}`
- Do not merge into main
- Do not create a tag
- Do not automatically replace the 16-tree candidate

## Stop

No 4/6/10/12-tree search; no depth change; supervisor review required before candidate change.
""",
        )

        opened_df = pd.DataFrame(opened.rows)
        opened_df.to_csv(out_dir / "opened_files_register.csv", index=False)
        write_json_atomic(out_dir / "environment_metadata.json", environment_metadata())
        manifest = {
            "status": status,
            "completed_seeds": completed_seeds,
            "checks": checks,
            "auto_replace_16tree": False,
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "git_head_at_run": head,
        }
        write_json_atomic(out_dir / "odst_8tree_manifest.json", manifest)
        _mirror(out_dir, repo)
        _flush(f"COMPLETE: {status}")
        return manifest

    except StudyBlockedError as e:
        write_json_atomic(out_dir / "odst_8tree_manifest.json", {"status": e.status, "error": str(e), "checks": checks})
        raise
    except ProtectedDataAccessError as e:
        write_json_atomic(out_dir / "odst_8tree_manifest.json", {"status": STATUS_SAFETY, "error": str(e), "checks": checks})
        raise
    except Exception as e:
        write_json_atomic(
            out_dir / "odst_8tree_manifest.json",
            {"status": STATUS_INCOMPLETE, "error": str(e), "traceback": traceback.format_exc(), "checks": checks},
        )
        _flush(f"INCOMPLETE: {e}")
        raise


def main() -> None:
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--repo-root", type=Path, default=None)
    args = p.parse_args()
    run(repo_root=args.repo_root)


if __name__ == "__main__":
    main()
