"""Write figures and interpretation reports for r5.2 teacher-anchored reproducibility."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def make_figures(out_dir: Path, results: dict[int, dict[str, Any]], r42_context: list[dict[str, Any]] | None = None) -> None:
    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    for seed, r in results.items():
        xs = [row["epoch"] for row in r["epoch_rows"]]
        ax.plot(xs, [row["validation_pr_auc"] for row in r["epoch_rows"]], marker="o", label=f"student s{seed}")
        ax.axhline(r["teacher_pr_auc"], linestyle="--", alpha=0.45, label=f"teacher s{seed}")
    ax.set_xlabel("Epoch")
    ax.set_ylabel("Validation PR-AUC")
    ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(out_dir / "r52_validation_pr_auc_learning_curves.png", dpi=300)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    for seed, r in results.items():
        xs = [row["epoch"] for row in r["epoch_rows"]]
        ax.plot(xs, [row["validation_f1"] for row in r["epoch_rows"]], marker="o", label=f"student s{seed}")
        ax.axhline(r["teacher_f1"], linestyle="--", alpha=0.45, label=f"teacher s{seed}")
    ax.set_xlabel("Epoch")
    ax.set_ylabel("Validation F1")
    ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(out_dir / "r52_validation_f1_learning_curves.png", dpi=300)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    seeds = sorted(results)
    t_pr = [results[s]["teacher_pr_auc"] for s in seeds]
    s_pr = [results[s]["best_pr_auc"] for s in seeds]
    x = list(range(len(seeds)))
    ax.plot(x, t_pr, "o--", label="r5.2 frozen teacher")
    ax.plot(x, s_pr, "s-", label="r5.2 teacher-anchored student")
    ax.set_xticks(x)
    ax.set_xticklabels([str(s) for s in seeds])
    ax.set_xlabel("Seed")
    ax.set_ylabel("Validation PR-AUC")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_dir / "r52_teacher_versus_student_seed_comparison.png", dpi=300)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    for seed, r in results.items():
        xs = [row["epoch"] for row in r["routing_rows"]]
        ax.plot(xs, [row["student_unused_leaves_pct"] for row in r["routing_rows"]], label=f"student unused s{seed}")
        ax.plot(
            xs,
            [row["teacher_unused_leaves_pct"] for row in r["routing_rows"]],
            linestyle="--",
            label=f"teacher unused s{seed}",
        )
    ax.set_xlabel("Epoch")
    ax.set_ylabel("Unused leaves (%)")
    ax.legend(fontsize=6)
    fig.tight_layout()
    fig.savefig(out_dir / "r52_routing_and_leaf_utilisation.png", dpi=300)
    plt.close(fig)

    if r42_context:
        fig, ax = plt.subplots(figsize=(7.5, 4.4))
        # ΔPR-AUC student-teacher for r4.2 vs r5.2
        r42_by_seed = {int(r["seed"]): r for r in r42_context if "seed" in r}
        xs, d42, d52 = [], [], []
        for seed in sorted(set(r42_by_seed) | set(results)):
            xs.append(str(seed))
            if seed in r42_by_seed:
                d42.append(float(r42_by_seed[seed].get("pr_auc_delta", float("nan"))))
            else:
                d42.append(float("nan"))
            if seed in results:
                d52.append(float(results[seed]["gate"]["pr_auc_delta"]))
            else:
                d52.append(float("nan"))
        ax.plot(xs, d42, "o--", label="r4.2 ΔPR-AUC (student−teacher)")
        ax.plot(xs, d52, "s-", label="r5.2 ΔPR-AUC (student−teacher)")
        ax.axhline(0.0, color="gray", linewidth=0.8)
        ax.axhline(-0.02, color="gray", linestyle=":", linewidth=0.8)
        ax.set_xlabel("Seed")
        ax.set_ylabel("PR-AUC delta")
        ax.legend(fontsize=8)
        fig.tight_layout()
        fig.savefig(out_dir / "r42_versus_r52_reproducibility.png", dpi=300)
        plt.close(fig)


def write_reports(
    out_dir: Path,
    *,
    results: dict[int, dict[str, Any]],
    status: str,
    multi: dict[str, Any] | None,
    meta: dict[str, Any],
) -> None:
    seed_lines = []
    for seed, r in sorted(results.items()):
        g = r.get("gate") or {}
        seed_lines.append(
            f"- Seed {seed}: student PR-AUC={r.get('best_pr_auc')} (epoch {r.get('best_epoch')}) vs teacher "
            f"{r.get('teacher_pr_auc')}; Δ={g.get('pr_auc_delta')}; viable={g.get('viable')}; "
            f"reasons={g.get('reasons')}; cosine={r.get('final_pooled_cosine')}; "
            f"unused% s/t={r.get('unused_leaves_pct')}/{r.get('teacher_unused_leaves_pct')}"
        )

    interp = f"""# R52_TEACHER_ANCHORED_INTERPRETATION

## Final status
`{status}`

## Completed r5.2 validation evidence
Results below are measured on CERT r5.2 training and validation partitions only.
{chr(10).join(seed_lines) if seed_lines else '- No completed seed runs.'}

## Seed variability
All predefined seeds (42, 52, 62) are reported without conditional exclusion for predictive failure.
Predictive viability and multi-seed reproducibility are classified separately from successful implementation.

## Cross-version reproducibility interpretation
The frozen r4.2 teacher-anchored procedure (architecture, loss coefficients, optimiser groups, gates) was transferred without modification.
Whether the procedure reproduces on r5.2 is summarised by the final status label and `r42_vs_r52_reproducibility_summary.csv`.

## Retained historical test evidence
Earlier locked r5.2 test results remain evidence only for the original frozen architecture and baselines.
They are not teacher-anchored student test results.

## Deferred independent confirmation
The teacher-anchored student has not received untouched independent r5.2 test confirmation in this study.

## Unsupported claims
Do not claim: independent r5.2 test confirmation; superiority over RF/XGBoost; state-of-the-art results;
uniform seed stability; generalisation to r6.2 or real organisations; that teacher-anchored training must work on every dataset.

## Provenance
- worktree: {meta.get('worktree')}
- branch: {meta.get('branch')}
- HEAD: {meta.get('start_head')}
- multi-seed: {json.dumps(multi, default=str)}
"""
    (out_dir / "R52_TEACHER_ANCHORED_INTERPRETATION.md").write_text(interp, encoding="utf-8")

    (out_dir / "R52_CROSS_VERSION_REPRODUCIBILITY.md").write_text(
        f"""# R52_CROSS_VERSION_REPRODUCIBILITY

## Question
Does the teacher-anchored end-to-end training procedure reproduce on CERT r5.2 when architecture, loss,
optimiser, seeds, gates, and model-selection rules are transferred without modification from the frozen r4.2 candidate?

## Locked transfer
- Candidate tag: objective2-teacher-anchored-candidate-v1
- Audit commit: b8272df572b50aa6d153f898a8a51e33366ef869
- Source commit: 965f1477e3eee920e6a6eef406ec24247429c5c7
- λ_logit = λ_route = 0.5
- lr_encoder = lr_attention = 3e-5; lr_odst = 3e-4; Adam; batch 1024; epochs 15; patience 4; grad_clip 1.0
- Seed-level and multi-seed gates unchanged from r4.2 reconstruction

## Outcome
Final status: `{status}`

## Separations
- Successful implementation ≠ predictive viability ≠ multi-seed reproducibility ≠ routing preservation ≠ predictive improvement ≠ baseline superiority
""",
        encoding="utf-8",
    )

    (out_dir / "R52_TEST_USE_DECISION_NOTE.md").write_text(
        """# R52_TEST_USE_DECISION_NOTE

This study stops after train/validation evaluation. The r5.2 test partition was not opened and no
teacher-anchored test predictions were generated.

## Options for later supervisor review (not executed here)

1. **Reserve r5.2 test** from further use and use r6.2 for later stress testing / independent confirmation.
2. **Perform one disclosed post-hoc r5.2 test analysis** after explicit supervisor approval, with full disclosure
   that r5.2 test has already been used for earlier locked baseline confirmation.

Do not execute either option automatically from this package.
""",
        encoding="utf-8",
    )

    (out_dir / "PAPER_R52_RESULTS_NOTES.md").write_text(
        f"""# PAPER_R52_RESULTS_NOTES

Draft-only notes. Do not paste into the manuscript without human review.

- Study: locked teacher-anchored transfer to CERT r5.2 train/validation.
- Status: `{status}`
- Primary comparator: r5.2 frozen Bi-LSTM–attention–ODST teacher vs teacher-anchored student (same seed).
- Seeds: 42, 52, 62 (all run unless safety/parity/interface/teacher-provenance failure).
- Independent r5.2 test confirmation: **not performed** in this study.
""",
        encoding="utf-8",
    )

    (out_dir / "PAPER_R52_DISCUSSION_NOTES.md").write_text(
        f"""# PAPER_R52_DISCUSSION_NOTES

Draft-only discussion cues.

- Frame as cross-version **procedure reproducibility**, not architecture search.
- Emphasise seed variability measurement rather than conditional seed exclusion.
- Keep historical locked test panels labelled as prior frozen/baseline evidence only.
- Avoid superiority claims over RF/XGBoost from validation-only teacher-anchored results.
- Status reference: `{status}`
""",
        encoding="utf-8",
    )

    (out_dir / "OBJECTIVE2_R52_DEFENCE_EXPLANATION.md").write_text(
        f"""# OBJECTIVE2_R52_DEFENCE_EXPLANATION

## What was locked
The Objective 2 teacher-anchored candidate (architecture + loss + optimiser + gates) was frozen on r4.2
and transferred unchanged to r5.2 train/validation.

## What was tested
Whether that fixed procedure remains implementable and multi-seed viable on the larger CERT release,
using seed-specific r5.2 frozen teachers as anchors.

## What was not tested
r5.2 test performance of the teacher-anchored student; hyperparameter retuning; architecture redesign.

## Status
`{status}`
""",
        encoding="utf-8",
    )

    (out_dir / "EXPERIMENTAL_HANDOVER.md").write_text(
        f"""# EXPERIMENTAL_HANDOVER — r5.2 teacher-anchored reproducibility

## Status
`{status}`

## Isolation
- Worktree: {meta.get('worktree')}
- Branch: {meta.get('branch')}
- Start HEAD: {meta.get('start_head')}
- Output namespace: outputs/objective2/r52_teacher_anchored_reproducibility_v1/

## Protections verified
- Existing r5.2 locked-baselines worktree not modified by this runner
- r5.2 test not opened
- Objective 3 outputs not written
- Frozen r4.2 candidate evidence not overwritten

## Next review stop
Review validation evidence and decide test-use policy using `R52_TEST_USE_DECISION_NOTE.md`.
Do not merge into main or create a final cross-version tag automatically.
""",
        encoding="utf-8",
    )
