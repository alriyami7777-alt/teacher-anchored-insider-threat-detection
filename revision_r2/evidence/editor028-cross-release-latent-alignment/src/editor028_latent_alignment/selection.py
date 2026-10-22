"""Label-blind candidate eligibility. r6.1 labels never enter this module."""

from __future__ import annotations

from typing import Any, Mapping

from .constants import (
    ALIGNED_CANDIDATES,
    CANDIDATE_LAMBDAS,
    S1_R52_MEAN_MIN,
    S2_N_SEEDS_MIN,
    S2_SEED_MIN,
    S3_ALIGN0_DELTA_MIN,
    S4_ALIGNMENT_REDUCTION_MIN,
    S5_N_SEEDS_MIN,
    S6_SEPARATION_RETENTION_MIN,
    SEEDS,
    TIE_REDUCTION_ABS,
)
from .safety import Editor028Blocked


def alignment_reduction(d_candidate: float, d_align0: float) -> float:
    if d_align0 == 0.0:
        return float("nan")
    return 1.0 - float(d_candidate) / float(d_align0)


def evaluate_gates(
    *,
    r52_pr: Mapping[str, Mapping[int, float]],
    coral_d: Mapping[str, Mapping[int, float]],
    r52_separation: Mapping[str, Mapping[int, float]],
) -> dict[str, Any]:
    align0_prs = [float(r52_pr["ALIGN0"][s]) for s in SEEDS]
    align0_mean = sum(align0_prs) / len(align0_prs)
    align0_ds = [float(coral_d["ALIGN0"][s]) for s in SEEDS]
    align0_d_mean = sum(align0_ds) / len(align0_ds)
    align0_seps = [float(r52_separation["ALIGN0"][s]) for s in SEEDS]
    align0_sep_mean = sum(align0_seps) / len(align0_seps)

    rows = {}
    for name in ALIGNED_CANDIDATES:
        prs = [float(r52_pr[name][s]) for s in SEEDS]
        mean_pr = sum(prs) / len(prs)
        ds = [float(coral_d[name][s]) for s in SEEDS]
        d_mean = sum(ds) / len(ds)
        a = alignment_reduction(d_mean, align0_d_mean)
        seps = [float(r52_separation[name][s]) for s in SEEDS]
        retention = [(s / align0_sep_mean) if align0_sep_mean != 0.0 else float("nan") for s in seps]
        mean_ret = sum(retention) / len(retention)
        s1 = bool(mean_pr >= S1_R52_MEAN_MIN)
        s2 = bool(sum(1 for p in prs if p >= S2_SEED_MIN) >= S2_N_SEEDS_MIN)
        s3 = bool((mean_pr - align0_mean) >= S3_ALIGN0_DELTA_MIN)
        s4 = bool(a >= S4_ALIGNMENT_REDUCTION_MIN)
        s5 = bool(sum(1 for d, d0 in zip(ds, align0_ds) if d < d0) >= S5_N_SEEDS_MIN)
        s6 = bool(mean_ret >= S6_SEPARATION_RETENTION_MIN)
        rows[name] = {
            "lambda_CORAL": float(CANDIDATE_LAMBDAS[name]),
            "mean_r52_pr_auc": mean_pr,
            "seed_r52_pr_auc": {str(s): p for s, p in zip(SEEDS, prs)},
            "LATENT_CORAL_DISCREPANCY": d_mean,
            "seed_coral": {str(s): d for s, d in zip(SEEDS, ds)},
            "ALIGNMENT_REDUCTION": a,
            "R52_LATENT_SEPARATION_RETENTION": mean_ret,
            "seed_retention": {str(s): r for s, r in zip(SEEDS, retention)},
            "S1": s1,
            "S2": s2,
            "S3": s3,
            "S4": s4,
            "S5": s5,
            "S6": s6,
            "label_blind_gate": bool(s1 and s2 and s3 and s4 and s5 and s6),
            "alignment_gate": bool(s4 and s5),
            "clean_gate": bool(s1 and s2 and s3),
        }
    eligible = [n for n in ALIGNED_CANDIDATES if rows[n]["label_blind_gate"]]
    selected = select_eligible(eligible, rows) if eligible else "NONE"
    alignment_pass = any(rows[n]["alignment_gate"] for n in ALIGNED_CANDIDATES)
    clean_pass_any_aligned = any(rows[n]["clean_gate"] for n in ALIGNED_CANDIDATES)
    if eligible:
        ruling = "ELIGIBLE"
    elif alignment_pass and not all(rows[n]["clean_gate"] for n in ALIGNED_CANDIDATES if rows[n]["alignment_gate"]):
        ruling = "ALIGNMENT_GAIN_WITH_CLEAN_TRADEOFF"
    else:
        ruling = "LATENT_ALIGNMENT_NOT_SUPPORTED"
    return {
        "ALIGN0_mean_r52_pr_auc": align0_mean,
        "ALIGN0_LATENT_CORAL_DISCREPANCY": align0_d_mean,
        "ALIGN0_mean_r52_separation": align0_sep_mean,
        "candidates": rows,
        "eligible": eligible,
        "EDITOR028_SELECTED_CANDIDATE": selected,
        "ruling": ruling,
        "alignment_pass_any": alignment_pass,
        "clean_pass_any_aligned": clean_pass_any_aligned,
    }


def select_eligible(eligible: list[str], rows: Mapping[str, Mapping[str, Any]]) -> str:
    if not eligible:
        return "NONE"
    best_a = max(float(rows[n]["ALIGNMENT_REDUCTION"]) for n in eligible)
    close = [n for n in eligible if abs(float(rows[n]["ALIGNMENT_REDUCTION"]) - best_a) <= TIE_REDUCTION_ABS]
    return min(close, key=lambda n: float(CANDIDATE_LAMBDAS[n]))


def refuse_r61_label_use_in_selection() -> None:
    raise Editor028Blocked("r6.1 labels are prohibited during candidate selection")
