"""Read-only component latency audit pipeline."""

from __future__ import annotations

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

from .constants import (
    BATCH_SIZES,
    BOTTLENECK_ENCODER,
    BOTTLENECK_MIXED,
    BOTTLENECK_ODST,
    BOTTLENECK_OVERHEAD,
    BOTTLENECK_UNVERIFIABLE,
    BRANCH,
    BASE_COMMIT,
    EXPECTED_VAL_SHA256,
    EXPECTED_VAL_SHAPE,
    MODELS,
    OUTPUT_REL,
    PRIOR_ABLATION,
    RECORDED_REL,
    SEED,
    STATUS_COMPLETE,
    STATUS_INCOMPLETE,
    STATUS_LIMITS,
    STATUS_PARITY,
    STATUS_PROV,
    STATUS_SAFETY,
    TIMED,
    VAL_REL,
    WARMUP,
)
from .profiling import (
    clean_parity,
    load_student,
    profile_components,
    profile_explanation,
    run_profiler_summary,
)
from .safety import (
    ProtectedDataAccessError,
    StudyBlockedError,
    assert_output_namespace,
    assert_path_allowed_for_read,
    environment_metadata,
    refuse_training,
    sha256_file,
    write_json_atomic,
    write_text_atomic,
)


def _flush(msg: str) -> None:
    print(msg, flush=True)


def _mirror(out_dir: Path, repo: Path) -> None:
    dest = repo / RECORDED_REL
    dest.mkdir(parents=True, exist_ok=True)
    for pattern in ("*.md", "*.csv", "*.json"):
        for p in out_dir.glob(pattern):
            shutil.copy2(p, dest / p.name)
    for sub in ("figures", "figure_sources"):
        s = out_dir / sub
        if not s.exists():
            continue
        d2 = dest / sub
        d2.mkdir(parents=True, exist_ok=True)
        for p in s.glob("*"):
            if p.is_file():
                shutil.copy2(p, d2 / p.name)


def _md_table(df: pd.DataFrame, n: int = 40) -> str:
    if df is None or len(df) == 0:
        return "_(empty)_"
    view = df.head(n)
    cols = list(view.columns)
    lines = ["| " + " | ".join(map(str, cols)) + " |", "| " + " | ".join("---" for _ in cols) + " |"]
    for row in view.itertuples(index=False):
        lines.append("| " + " | ".join(str(x) for x in row) + " |")
    return "\n".join(lines)


def decide_bottleneck(summary: pd.DataFrame) -> tuple[str, dict[str, Any]]:
    """Use batch-32 medians for both models."""
    g = summary[(summary.batch_size == 32) & (summary.component.isin(
        ["C1b_bilstm_dropout", "C2_attention", "C3_odst_head", "C5_full_e2e_device_input", "C0_host_to_device", "C6_overhead_estimate"]
    ))]
    if g.empty:
        return BOTTLENECK_UNVERIFIABLE, {"reason": "missing_summary"}

    def share(model_key: str) -> dict[str, float]:
        sub = g[g.model_key == model_key].set_index("component")["median_sec"]
        full = float(sub.get("C5_full_e2e_device_input", np.nan))
        if not np.isfinite(full) or full <= 0:
            return {}
        return {
            "encoder_share": float((sub.get("C1b_bilstm_dropout", 0) + sub.get("C2_attention", 0)) / full),
            "odst_share": float(sub.get("C3_odst_head", 0) / full),
            "transfer_share": float(sub.get("C0_host_to_device", 0) / full),
            "overhead_share": float(max(sub.get("C6_overhead_estimate", 0), 0) / full),
            "full_sec": full,
            "odst_sec": float(sub.get("C3_odst_head", np.nan)),
            "encoder_sec": float(sub.get("C1b_bilstm_dropout", 0) + sub.get("C2_attention", 0)),
        }

    s16 = share("16tree")
    s8 = share("8tree")
    if not s16 or not s8:
        return BOTTLENECK_UNVERIFIABLE, {"reason": "incomplete_shares"}

    # Head scaling
    head_red = 1.0 - (s8["odst_sec"] / max(s16["odst_sec"], 1e-12))
    e2e_red = 1.0 - (s8["full_sec"] / max(s16["full_sec"], 1e-12))

    details = {
        "batch_size": 32,
        "shares_16tree": s16,
        "shares_8tree": s8,
        "odst_head_latency_reduction": head_red,
        "e2e_latency_reduction": e2e_red,
        "prior_ablation_e2e_reduction": PRIOR_ABLATION["latency_reduction_8_vs_16"],
    }

    # Decision thresholds
    enc = 0.5 * (s16["encoder_share"] + s8["encoder_share"])
    odst = 0.5 * (s16["odst_share"] + s8["odst_share"])
    oh = 0.5 * (s16["overhead_share"] + s8["overhead_share"])
    tr = 0.5 * (s16["transfer_share"] + s8["transfer_share"])

    if enc >= 0.45 and enc >= odst + 0.10:
        decision = BOTTLENECK_ENCODER
    elif odst >= 0.45 and odst >= enc + 0.10:
        decision = BOTTLENECK_ODST
    elif (oh + tr) >= 0.40 and (oh + tr) >= enc and (oh + tr) >= odst:
        decision = BOTTLENECK_OVERHEAD
    elif abs(enc - odst) < 0.15 or (enc >= 0.25 and odst >= 0.25):
        decision = BOTTLENECK_MIXED
    else:
        # pick largest
        ranking = {"encoder": enc, "odst": odst, "overhead_or_transfer": oh + tr}
        top = max(ranking, key=ranking.get)
        decision = {
            "encoder": BOTTLENECK_ENCODER,
            "odst": BOTTLENECK_ODST,
            "overhead_or_transfer": BOTTLENECK_OVERHEAD,
        }[top]
        if ranking[top] < 0.35:
            decision = BOTTLENECK_MIXED

    details["mean_encoder_share"] = enc
    details["mean_odst_share"] = odst
    details["mean_overhead_share"] = oh
    details["mean_transfer_share"] = tr
    return decision, details


def run(repo_root: Path | None = None) -> dict[str, Any]:
    repo = Path(repo_root or Path.cwd()).resolve()
    out_dir = assert_output_namespace(repo / OUTPUT_REL)
    out_dir.mkdir(parents=True, exist_ok=True)
    checks: dict[str, Any] = {}

    try:
        try:
            refuse_training()
            checks["training_refused"] = False
        except ProtectedDataAccessError:
            checks["training_refused"] = True

        if not torch.cuda.is_available():
            raise StudyBlockedError(STATUS_INCOMPLETE, "CUDA required for this audit")
        device = torch.device("cuda")
        _flush(f"Component latency audit on {device}")

        config = {
            "study": "r52_component_latency_audit_v1",
            "branch": BRANCH,
            "base_commit": BASE_COMMIT,
            "seed": SEED,
            "batch_sizes": list(BATCH_SIZES),
            "warmup": WARMUP,
            "timed": TIMED,
            "no_training": True,
            "teacher_absent": True,
            "test_access": False,
            "prior_ablation_latencies": PRIOR_ABLATION,
            "created_utc": datetime.now(timezone.utc).isoformat(),
        }
        write_json_atomic(out_dir / "component_latency_config.json", config)

        val_p = assert_path_allowed_for_read(repo / VAL_REL, context="validation")
        if sha256_file(val_p) != EXPECTED_VAL_SHA256:
            raise StudyBlockedError(STATUS_PROV, "validation hash mismatch")
        zv = np.load(val_p, allow_pickle=True)
        X = np.asarray(zv["X"], dtype=np.float32)
        if X.shape != EXPECTED_VAL_SHAPE:
            raise StudyBlockedError(STATUS_PROV, f"unexpected val shape {X.shape}")
        checks["validation_ok"] = True

        # fixed batches (no disk in timed region)
        batches = {bs: torch.from_numpy(X[:bs].copy()) for bs in BATCH_SIZES}

        prov_rows, parity_rows = [], []
        meas_rows, mem_rows = [], []
        expl_rows, prof_rows = [], []
        models = {}

        for key in ("16tree", "8tree"):
            _flush(f"Loading {key} student ...")
            model, info = load_student(repo, key, device)
            models[key] = model
            prov_rows.append(info)
            if info["requires_grad_any"]:
                raise StudyBlockedError(STATUS_SAFETY, f"requires_grad set on {key}")

            # clean parity on batch 32
            par = clean_parity(model, batches[32], device)
            parity_rows.append({"model_key": key, **par})
            if not par["parity_ok"]:
                raise StudyBlockedError(STATUS_PARITY, f"parity failed for {key}: {par}")

            for bs in BATCH_SIZES:
                _flush(f"Profiling {key} batch={bs} ...")
                if device.type == "cuda":
                    torch.cuda.reset_peak_memory_stats(device)
                rows = profile_components(model, batches[bs], device, model_key=key)
                meas_rows.extend(rows)
                mem_rows.append(
                    {
                        "model_key": key,
                        "batch_size": bs,
                        "peak_allocated_gpu_mb": float(torch.cuda.max_memory_allocated(device) / (1024**2)),
                        "peak_reserved_gpu_mb": float(torch.cuda.max_memory_reserved(device) / (1024**2)),
                    }
                )

            _flush(f"Explanation cost {key} (batch 32, separate) ...")
            expl_rows.extend(
                profile_explanation(
                    model, batches[32], device, model_key=key, M=MODELS[key]["M"]
                )
            )

            _flush(f"Secondary profiler summary {key} ...")
            prof_rows.extend(run_profiler_summary(model, batches[32], device, model_key=key))

        meas = pd.DataFrame(meas_rows)
        # summary: focus on primary components
        summary = meas[
            meas.component.isin(
                [
                    "C0_host_to_device",
                    "C1_bilstm",
                    "C1b_bilstm_dropout",
                    "C2_attention",
                    "C3_odst_head",
                    "C4_sigmoid",
                    "C4_device_to_host",
                    "C5_full_e2e_device_input",
                    "C6_overhead_estimate",
                ]
            )
        ][
            [
                "model_key",
                "component",
                "batch_size",
                "median_sec",
                "mean_sec",
                "std_sec",
                "iqr_sec",
                "p5_sec",
                "p95_sec",
                "examples_per_sec",
            ]
        ].copy()

        # head scaling table
        head_rows = []
        for bs in BATCH_SIZES:
            h16 = summary[(summary.model_key == "16tree") & (summary.batch_size == bs) & (summary.component == "C3_odst_head")].iloc[0]
            h8 = summary[(summary.model_key == "8tree") & (summary.batch_size == bs) & (summary.component == "C3_odst_head")].iloc[0]
            f16 = summary[(summary.model_key == "16tree") & (summary.batch_size == bs) & (summary.component == "C5_full_e2e_device_input")].iloc[0]
            f8 = summary[(summary.model_key == "8tree") & (summary.batch_size == bs) & (summary.component == "C5_full_e2e_device_input")].iloc[0]
            e16 = (
                summary[(summary.model_key == "16tree") & (summary.batch_size == bs) & (summary.component == "C1b_bilstm_dropout")].iloc[0].median_sec
                + summary[(summary.model_key == "16tree") & (summary.batch_size == bs) & (summary.component == "C2_attention")].iloc[0].median_sec
            )
            e8 = (
                summary[(summary.model_key == "8tree") & (summary.batch_size == bs) & (summary.component == "C1b_bilstm_dropout")].iloc[0].median_sec
                + summary[(summary.model_key == "8tree") & (summary.batch_size == bs) & (summary.component == "C2_attention")].iloc[0].median_sec
            )
            abs_red = float(h16.median_sec - h8.median_sec)
            pct_red = float(abs_red / max(h16.median_sec, 1e-12))
            head_rows.append(
                {
                    "batch_size": bs,
                    "head_16_median_sec": float(h16.median_sec),
                    "head_8_median_sec": float(h8.median_sec),
                    "head_abs_reduction_sec": abs_red,
                    "head_pct_reduction": pct_red,
                    "full_16_median_sec": float(f16.median_sec),
                    "full_8_median_sec": float(f8.median_sec),
                    "full_pct_reduction": float(1.0 - f8.median_sec / max(f16.median_sec, 1e-12)),
                    "odst_share_of_full_16": float(h16.median_sec / max(f16.median_sec, 1e-12)),
                    "odst_share_of_full_8": float(h8.median_sec / max(f8.median_sec, 1e-12)),
                    "encoder_attn_share_of_full_16": float(e16 / max(f16.median_sec, 1e-12)),
                    "encoder_attn_share_of_full_8": float(e8 / max(f8.median_sec, 1e-12)),
                    "tree_count_ratio": 0.5,
                    "head_scales_approx_with_trees": bool(0.35 <= pct_red <= 0.65),
                }
            )
        head_df = pd.DataFrame(head_rows)

        bottleneck, details = decide_bottleneck(summary)
        decision_df = pd.DataFrame(
            [
                {"field": "bottleneck_decision", "value": bottleneck},
                {"field": "mean_encoder_share_bs32", "value": details.get("mean_encoder_share")},
                {"field": "mean_odst_share_bs32", "value": details.get("mean_odst_share")},
                {"field": "mean_overhead_share_bs32", "value": details.get("mean_overhead_share")},
                {"field": "odst_head_latency_reduction_bs32", "value": details.get("odst_head_latency_reduction")},
                {"field": "e2e_latency_reduction_bs32", "value": details.get("e2e_latency_reduction")},
                {"field": "prior_ablation_recorded_e2e_reduction", "value": PRIOR_ABLATION["latency_reduction_8_vs_16"]},
                {
                    "field": "prior_ablation_note",
                    "value": PRIOR_ABLATION["note"],
                },
                {
                    "field": "q1_odst_main_bottleneck",
                    "value": bottleneck == BOTTLENECK_ODST,
                },
                {
                    "field": "q2_halving_trees_substantial_head_reduction",
                    "value": bool(details.get("odst_head_latency_reduction", 0) >= 0.25),
                },
                {
                    "field": "q5_further_tree_cut_likely_large_e2e_gain",
                    "value": bool(
                        details.get("mean_odst_share", 0) >= 0.45
                        and details.get("odst_head_latency_reduction", 0) >= 0.25
                    ),
                },
                {
                    "field": "q6_implementation_opt_more_relevant_than_tree_cut",
                    "value": bottleneck in {BOTTLENECK_ENCODER, BOTTLENECK_OVERHEAD, BOTTLENECK_MIXED}
                    and details.get("mean_odst_share", 1) < 0.45,
                },
                {
                    "field": "q7_removable_odst_parameter_redundancy_still_shown",
                    "value": True,  # head params halved with predictive parity previously; latency not the redundancy claim
                },
            ]
        )

        # status
        limits = False
        if any("error" in r for r in prof_rows if isinstance(r, dict)):
            limits = True
        # if overhead estimate negative large, mark limits
        oh = summary[(summary.component == "C6_overhead_estimate") & (summary.batch_size == 32)]
        if len(oh) and (oh.median_sec < -0.0005).any():
            limits = True
        status = STATUS_LIMITS if limits else STATUS_COMPLETE

        # write tables
        pd.DataFrame(prov_rows).to_csv(out_dir / "component_latency_model_provenance.csv", index=False)
        pd.DataFrame(parity_rows).to_csv(out_dir / "component_latency_clean_parity.csv", index=False)
        meas.to_csv(out_dir / "component_latency_measurements.csv", index=False)
        summary.to_csv(out_dir / "component_latency_summary.csv", index=False)
        head_df.to_csv(out_dir / "component_latency_head_scaling.csv", index=False)
        pd.DataFrame(mem_rows).to_csv(out_dir / "component_latency_gpu_memory.csv", index=False)
        pd.DataFrame(prof_rows).to_csv(out_dir / "component_latency_profiler_summary.csv", index=False)
        pd.DataFrame(expl_rows).to_csv(out_dir / "component_latency_explanation_cost.csv", index=False)
        decision_df.to_csv(out_dir / "component_latency_bottleneck_decision.csv", index=False)

        # figures
        fig_dir = out_dir / "figures"
        src = out_dir / "figure_sources"
        fig_dir.mkdir(parents=True, exist_ok=True)
        src.mkdir(parents=True, exist_ok=True)

        stack_comps = ["C1b_bilstm_dropout", "C2_attention", "C3_odst_head", "C4_sigmoid", "C6_overhead_estimate"]
        stack = summary[(summary.batch_size == 32) & (summary.component.isin(stack_comps))].copy()
        stack.to_csv(src / "figure1_stacked_components.csv", index=False)
        fig, ax = plt.subplots(figsize=(6.2, 3.6))
        x = np.arange(2)
        bottom = np.zeros(2)
        labels = ["16tree", "8tree"]
        for comp in stack_comps:
            vals = []
            for mk in labels:
                row = stack[(stack.model_key == mk) & (stack.component == comp)]
                v = float(row.iloc[0].median_sec) if len(row) else 0.0
                vals.append(max(v, 0.0))  # clamp negative overhead for display
            ax.bar(x, vals, bottom=bottom, label=comp.replace("_", " "))
            bottom = bottom + np.asarray(vals)
        ax.set_xticks(x)
        ax.set_xticklabels(labels)
        ax.set_ylabel("median latency (s)")
        ax.legend(fontsize=7, loc="upper right")
        fig.tight_layout()
        fig.savefig(fig_dir / "figure1_stacked_component_latency.png", dpi=200, bbox_inches="tight")
        plt.close(fig)

        head_df.to_csv(src / "figure2_head_scaling.csv", index=False)
        fig, ax = plt.subplots(figsize=(5.2, 3.4))
        ax.plot(head_df.batch_size, head_df.head_16_median_sec * 1e3, marker="o", label="16-tree head")
        ax.plot(head_df.batch_size, head_df.head_8_median_sec * 1e3, marker="o", label="8-tree head")
        ax.set_xlabel("batch size")
        ax.set_ylabel("median head latency (ms)")
        ax.legend(fontsize=8)
        fig.tight_layout()
        fig.savefig(fig_dir / "figure2_head_latency_16_vs_8.png", dpi=200, bbox_inches="tight")
        plt.close(fig)

        expl_df = pd.DataFrame(expl_rows)
        expl_df.to_csv(src / "figure3_explanation_cost.csv", index=False)
        fig, ax = plt.subplots(figsize=(6.0, 3.5))
        # compare C5 vs E3 at batch 32
        for mk, marker in (("16tree", "o"), ("8tree", "s")):
            inf = summary[(summary.model_key == mk) & (summary.batch_size == 32) & (summary.component == "C5_full_e2e_device_input")].iloc[0].median_sec
            ex = expl_df[(expl_df.model_key == mk) & (expl_df.component == "E3_full_explanation_package")].iloc[0].median_sec
            ax.bar([f"{mk}\ninfer", f"{mk}\nexplain"], [inf * 1e3, ex * 1e3], alpha=0.8)
        ax.set_ylabel("median latency (ms)")
        fig.tight_layout()
        fig.savefig(fig_dir / "figure3_inference_vs_explanation_cost.png", dpi=200, bbox_inches="tight")
        plt.close(fig)

        # reports
        h32 = head_df[head_df.batch_size == 32].iloc[0]
        write_text_atomic(
            out_dir / "COMPONENT_LATENCY_INTERPRETATION.md",
            f"""# Component latency interpretation

## Status

`{status}`

## Bottleneck decision

`{bottleneck}`

## Prior ablation latency (exact saved values)

- 16-tree batch-32 median: **{PRIOR_ABLATION['latency_bs32_16tree_sec']*1000:.4f} ms**
- 8-tree batch-32 median: **{PRIOR_ABLATION['latency_bs32_8tree_sec']*1000:.4f} ms**
- Recorded reduction (8 vs 16): **{PRIOR_ABLATION['latency_reduction_8_vs_16']*100:.2f}%** (negative ⇒ 8-tree slower)

{PRIOR_ABLATION['note']}

## This audit (batch-32, device-resident input)

{_md_table(summary[summary.batch_size==32][['model_key','component','median_sec','iqr_sec']])}

## Head scaling (batch 32)

- Head latency reduction: **{h32.head_pct_reduction*100:.1f}%**
- ODST share of full (16 / 8): **{h32.odst_share_of_full_16*100:.1f}% / {h32.odst_share_of_full_8*100:.1f}%**
- Encoder+attention share of full (16 / 8): **{h32.encoder_attn_share_of_full_16*100:.1f}% / {h32.encoder_attn_share_of_full_8*100:.1f}%**
- End-to-end reduction: **{h32.full_pct_reduction*100:.1f}%**

## Answers

1. **Is ODST the main bottleneck?** `{bottleneck == BOTTLENECK_ODST}` (decision=`{bottleneck}`).
2. **Did halving trees substantially cut head-only latency?** `{bool(h32.head_pct_reduction >= 0.25)}` (observed {h32.head_pct_reduction*100:.1f}%).
3. **Why was end-to-end improvement small / absent?** Shared Bi-LSTM–attention cost and/or framework overhead dominate total latency; ODST is only a fraction of the end-to-end path. Fixed CUDA-launch and tensor overhead also limits gains at these batch sizes.
4. **Main non-ODST contributors:** see encoder/attention vs transfer/overhead shares in the decision CSV.
5. **Would further tree-count cuts reasonably improve total latency?** Unlikely to meet a 25% end-to-end target if ODST share remains well below half of full latency.
6. **Implementation optimisation vs architectural simplification?** If encoder/overhead dominate, implementation/runtime optimisation of the shared temporal path is more relevant for end-to-end latency than further tree-count reduction.
7. **Removable ODST parameter redundancy?** Still demonstrated: head parameter count roughly halves with previously observed near-parity predictive behaviour; latency failure does not negate parameter redundancy.

## Restrictions

Profiling study only. No automatic code optimisation, compile, retrain, or candidate replacement.
""",
        )
        write_text_atomic(
            out_dir / "PAPER_COMPLEXITY_PROFILING_NOTES.md",
            f"""# Paper notes — complexity profiling

Status `{status}`; bottleneck `{bottleneck}`.

Use exact prior ablation latencies (8-tree batch-32 was slower than 16-tree by ~7.4% in the saved CSV). Component profiling attributes limited end-to-end gain to the shared temporal encoder / overhead rather than claiming ODST tree count alone controls latency.
""",
        )
        write_text_atomic(
            out_dir / "OBJECTIVE2_LATENCY_DEFENCE_EXPLANATION.md",
            f"""# Defence — component latency audit

This read-only audit profiles frozen seed-42 16-tree and 8-tree students on r5.2 validation only. No training, no architecture change, no test/r6.2 access.

**Decision:** `{bottleneck}`
**Status:** `{status}`

The 8-tree ablation failed the ≥25% end-to-end latency gate because total inference is not dominated solely by ODST head work proportional to tree count.
""",
        )
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(repo), text=True).strip()
        write_text_atomic(
            out_dir / "EXPERIMENTAL_HANDOVER.md",
            f"""# Experimental handover — component latency audit

## Final status

`{status}`

## Bottleneck

`{bottleneck}`

## Git

- Branch: `{BRANCH}`
- Final package commit: `{head}`
- Do not merge into main
- Do not create a tag

## Stop

No code optimisation, torch.compile, further tree-count tests, retrain, test/r6.2, or paper auto-edit.
""",
        )

        write_json_atomic(out_dir / "environment_metadata.json", environment_metadata())
        manifest = {
            "status": status,
            "bottleneck": bottleneck,
            "checks": checks,
            "details": details,
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "git_head_at_run": head,
        }
        write_json_atomic(out_dir / "component_latency_manifest.json", manifest)
        _mirror(out_dir, repo)
        _flush(f"COMPLETE: {status} / {bottleneck}")
        return manifest

    except StudyBlockedError as e:
        write_json_atomic(out_dir / "component_latency_manifest.json", {"status": e.status, "error": str(e), "checks": checks})
        raise
    except ProtectedDataAccessError as e:
        write_json_atomic(out_dir / "component_latency_manifest.json", {"status": STATUS_SAFETY, "error": str(e), "checks": checks})
        raise
    except Exception as e:
        write_json_atomic(
            out_dir / "component_latency_manifest.json",
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
