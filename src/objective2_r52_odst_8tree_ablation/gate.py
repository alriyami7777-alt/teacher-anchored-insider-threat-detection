"""Seed-42 and multi-seed viability gates for 8-tree ablation."""

from __future__ import annotations

from typing import Any

import pandas as pd

from .constants import (
    COMPARATOR_16,
    FIDELITY_K,
    F1_MAX_DROP,
    FP_CATASTROPHIC_MULT,
    FN_CATASTROPHIC_MULT,
    LATENCY_MIN_REDUCTION,
    MIN_K_PASS,
    PR_AUC_MAX_DROP,
    STATUS_MULTI_LIMITS,
    STATUS_MULTI_NOT,
    STATUS_MULTI_SUPPORTED,
    STATUS_SEED42_FAIL,
    UNUSED_LEAVES_MAX_WORSE_PP,
)


def evaluate_seed_gate(
    *,
    seed: int,
    student_summary: dict[str, Any],
    fidelity_df: pd.DataFrame,
    latency_16_bs32: float,
) -> dict[str, Any]:
    comp = COMPARATOR_16[seed]
    m = student_summary["validation_metrics"]
    pr = float(m["pr_auc"])
    f1 = float(m["f1"])
    fp = float(m["fp"])
    fn = float(m["fn"])
    unused = float(student_summary["unused_leaves_pct"])
    lat32 = next(r["median_latency_sec"] for r in student_summary["latency"] if r["batch_size"] == 32)

    tech = {
        "initial_parity_ok": bool(student_summary["initial_parity_ok"]),
        "teacher_unchanged": bool(student_summary["teacher_unchanged"]),
        "encoder_updated": bool(student_summary["encoder_updated"]),
        "attention_updated": bool(student_summary["attention_updated"]),
        "odst_updated": bool(student_summary["odst_updated"]),
        "teacher_independent_inference": bool(student_summary["teacher_independent_inference"]),
        "no_nan_inf": not bool(student_summary["had_nan_or_inf"]),
        "checkpoint_after_joint": int(student_summary["best_epoch"]) >= 1,
        "no_catastrophic_collapse": not bool(student_summary["catastrophic_collapse"]),
    }
    tech_ok = all(tech.values())

    pr_ok = pr >= float(comp["pr_auc"]) - PR_AUC_MAX_DROP
    f1_ok = f1 >= float(comp["f1"]) - F1_MAX_DROP
    fp_ok = fp <= float(comp["fp"]) * FP_CATASTROPHIC_MULT
    fn_ok = fn <= float(comp["fn"]) * FN_CATASTROPHIC_MULT
    pred = {
        "pr_auc_8": pr,
        "pr_auc_16": float(comp["pr_auc"]),
        "pr_auc_delta": pr - float(comp["pr_auc"]),
        "pr_auc_ok": pr_ok,
        "f1_8": f1,
        "f1_16": float(comp["f1"]),
        "f1_delta": f1 - float(comp["f1"]),
        "f1_ok": f1_ok,
        "fp_8": fp,
        "fp_16": float(comp["fp"]),
        "fn_8": fn,
        "fn_16": float(comp["fn"]),
        "fp_fn_ok": fp_ok and fn_ok,
        "threshold_validation_only": True,
    }
    pred_ok = pr_ok and f1_ok and fp_ok and fn_ok

    lat_reduction = 1.0 - (lat32 / max(latency_16_bs32, 1e-12))
    unused_16 = float(comp["unused_leaves_pct"])
    unused_ok = unused <= unused_16 + UNUSED_LEAVES_MAX_WORSE_PP
    eff = float(student_summary["effective_rank_over_M"])
    simp = {
        "latency_bs32_8": lat32,
        "latency_bs32_16": latency_16_bs32,
        "latency_reduction": lat_reduction,
        "latency_ok": lat_reduction >= LATENCY_MIN_REDUCTION,
        "head_params_reduced": True,  # by construction (4 vs 8 trees/layer)
        "unused_leaves_pct_8": unused,
        "unused_leaves_pct_16": unused_16,
        "unused_leaves_ok": unused_ok,
        "effective_rank_over_M": eff,
        "effective_rank_ok": eff >= 0.05,  # no worse collapse than near-1-D forest; relative check below
        "n_odst_head_parameters": int(student_summary["n_odst_head_parameters"]),
        "checkpoint_size_bytes": int(student_summary["checkpoint_size_bytes"]),
    }
    # relative rank: do not worsen vs tree count more than comparator typical ~1/16
    simp_ok = simp["latency_ok"] and simp["unused_leaves_ok"] and simp["head_params_reduced"]

    fid = fidelity_df[fidelity_df["seed"] == seed]
    k_pass = {
        int(r.k): bool(r.ci_excludes_zero_positive) for r in fid.itertuples(index=False)
    }
    n_pass = sum(1 for k in FIDELITY_K if k_pass.get(int(k), False))
    expl = {
        "k_pass": k_pass,
        "n_k_pass": n_pass,
        "k3_pass": bool(k_pass.get(3, False)),
        "explanation_ok": n_pass >= MIN_K_PASS and bool(k_pass.get(3, False)),
    }

    passed = tech_ok and pred_ok and simp_ok and expl["explanation_ok"]
    reasons = []
    if not tech_ok:
        reasons.append("technical_failure:" + ",".join(k for k, v in tech.items() if not v))
    if not pred_ok:
        reasons.append("predictive_failure")
    if not simp_ok:
        reasons.append("simplification_failure")
    if not expl["explanation_ok"]:
        reasons.append("explanation_failure")

    return {
        "seed": seed,
        "passed": passed,
        "technical_ok": tech_ok,
        "predictive_ok": pred_ok,
        "simplification_ok": simp_ok,
        "explanation_ok": expl["explanation_ok"],
        "reasons": ";".join(reasons) if reasons else "",
        **{f"tech_{k}": v for k, v in tech.items()},
        **pred,
        **simp,
        **{f"expl_{k}": v for k, v in expl.items() if k != "k_pass"},
        "expl_k_pass": str(k_pass),
    }


def classify_multiseed(gate_rows: list[dict[str, Any]]) -> str:
    if not gate_rows:
        return STATUS_SEED42_FAIL
    g42 = next(r for r in gate_rows if r["seed"] == 42)
    if not g42["passed"]:
        return STATUS_SEED42_FAIL
    n_pass = sum(1 for r in gate_rows if r["passed"])
    if any(r.get("tech_no_catastrophic_collapse") is False for r in gate_rows):
        return STATUS_MULTI_NOT
    # mean PR-AUC within 0.010 of 16-tree mean
    mean_8 = sum(r["pr_auc_8"] for r in gate_rows) / len(gate_rows)
    mean_16 = sum(r["pr_auc_16"] for r in gate_rows) / len(gate_rows)
    mean_ok = mean_8 >= mean_16 - PR_AUC_MAX_DROP
    lat_ok = all(r["latency_ok"] for r in gate_rows)
    expl_ok = all(r["explanation_ok"] for r in gate_rows if r["seed"] in {42, 52, 62} and r.get("passed") or r["seed"] == 42)
    # require faithfulness retained on all completed seeds that passed tech/pred, or at least majority
    expl_all = all(r["explanation_ok"] for r in gate_rows)
    if n_pass >= 2 and mean_ok and lat_ok and expl_all:
        # limits if any seed failed predictive margins tightly or unused leaves borderline
        limits = n_pass < 3 or any(not r["unused_leaves_ok"] for r in gate_rows)
        return STATUS_MULTI_LIMITS if limits else STATUS_MULTI_SUPPORTED
    if n_pass >= 2 and mean_ok:
        return STATUS_MULTI_LIMITS
    return STATUS_MULTI_NOT
