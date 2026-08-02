"""Viability and multi-seed gates for teacher-anchored ODST."""

from __future__ import annotations

from typing import Any

from .config import (
    IMPROVEMENT_PR_AUC_DELTA,
    IMPROVEMENT_RECALL_TOLERANCE,
    VIABILITY_COSINE_MIN,
    VIABILITY_F1_MARGIN,
    VIABILITY_PR_AUC_MARGIN,
    VIABILITY_UNUSED_LEAVES_MAX_WORSE_PP,
)


def evaluate_seed_viability(*, teacher: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    impl_ok = True
    pred_ok = True
    repr_ok = True
    route_ok = True

    for key, label in [
        ("initial_parity_ok", "initial_parity_failed"),
        ("teacher_unchanged", "teacher_parameters_changed"),
        ("encoder_updated", "encoder_not_updated"),
        ("attention_updated", "attention_not_updated"),
        ("odst_updated", "odst_not_updated"),
        ("nonzero_grads_all_components", "missing_component_grads"),
        ("threshold_from_validation_only", "threshold_not_validation_only"),
        ("student_independent_inference", "student_requires_teacher_at_inference"),
    ]:
        if not run.get(key, False):
            impl_ok = False
            reasons.append(label)

    # Genuine joint from epoch 1; best checkpoint must be at least epoch 1 with updates verified.
    if int(run.get("best_epoch", 0)) < 1:
        impl_ok = False
        reasons.append("no_selected_checkpoint")
    if not run.get("joint_training_verified", False):
        impl_ok = False
        reasons.append("joint_optimisation_not_verified")

    if run.get("had_nan_or_inf") or run.get("gradient_explosion") or run.get("protected_access"):
        impl_ok = False
        reasons.append("numerical_or_protection_failure")

    p_t = float(teacher["pr_auc"])
    p_s = float(run["best_pr_auc"])
    f_t = float(teacher["f1"])
    f_s = float(run["best_f1"])
    if p_s < p_t - VIABILITY_PR_AUC_MARGIN:
        pred_ok = False
        reasons.append("pr_auc_below_margin")
    if f_s < f_t - VIABILITY_F1_MARGIN:
        pred_ok = False
        reasons.append("f1_below_margin")
    if run.get("catastrophic_fp_fn"):
        pred_ok = False
        reasons.append("catastrophic_fp_fn")

    cos = float(run.get("final_pooled_cosine", float("nan")))
    if not (cos >= VIABILITY_COSINE_MIN):
        repr_ok = False
        reasons.append("cosine_too_low")
    if run.get("parameter_explosion"):
        repr_ok = False
        reasons.append("parameter_explosion")

    unused_t = float(teacher.get("unused_leaves_pct", 0.0))
    unused_s = float(run.get("unused_leaves_pct", float("nan")))
    if unused_s > unused_t + VIABILITY_UNUSED_LEAVES_MAX_WORSE_PP:
        route_ok = False
        reasons.append("unused_leaves_worse_than_allowed")
    route_div = float(run.get("routing_divergence", float("nan")))
    if not (route_div == route_div) or route_div > 50.0:
        route_ok = False
        reasons.append("routing_divergence_unstable")
    ent_s = float(run.get("routing_entropy_mean", float("nan")))
    if not (ent_s == ent_s) or ent_s < 1e-12:
        # Near-zero entropy may be OK if teacher also near-zero; flag unexplained collapse
        ent_t = float(teacher.get("routing_entropy_mean", 0.0))
        if ent_t > 1e-4 and ent_s < 1e-8:
            route_ok = False
            reasons.append("student_routing_entropy_collapse")
    if unused_s >= 99.0:
        route_ok = False
        reasons.append("odst_routes_not_meaningful")

    improved = (p_s >= p_t + IMPROVEMENT_PR_AUC_DELTA) or (
        abs(float(run.get("best_recall", 0)) - float(teacher.get("recall", 0))) <= IMPROVEMENT_RECALL_TOLERANCE
        and float(run.get("best_fp", 1e9)) < float(teacher.get("fp", 0))
        and abs(p_s - p_t) <= VIABILITY_PR_AUC_MARGIN
    )

    viable = bool(impl_ok and pred_ok and repr_ok and route_ok)
    return {
        "viable": viable,
        "implementation_ok": impl_ok,
        "predictive_ok": pred_ok,
        "representation_ok": repr_ok,
        "routing_ok": route_ok,
        "improved_vs_teacher": bool(improved),
        "pr_auc_delta": p_s - p_t,
        "f1_delta": f_s - f_t,
        "reasons": reasons,
    }


def evaluate_multiseed(seed_results: dict[int, dict[str, Any]]) -> dict[str, Any]:
    completed = {s: r for s, r in seed_results.items() if r.get("completed")}
    viable_seeds = [s for s, r in completed.items() if (r.get("gate") or {}).get("viable")]
    any_collapse = any(r.get("catastrophic_collapse") for r in completed.values())
    if not completed:
        return {"multiseed_viable": False, "viable_seeds": []}
    mean_s = sum(float(r["best_pr_auc"]) for r in completed.values()) / len(completed)
    mean_t = sum(float(r["teacher_pr_auc"]) for r in completed.values()) / len(completed)
    unused_worse = sum(
        1
        for r in completed.values()
        if float(r.get("unused_leaves_pct", 0))
        > float(r.get("teacher_unused_leaves_pct", 0)) + VIABILITY_UNUSED_LEAVES_MAX_WORSE_PP
    )
    updates_ok = all(
        r.get("encoder_updated") and r.get("attention_updated") and r.get("odst_updated") for r in completed.values()
    )
    teachers_ok = all(r.get("teacher_unchanged") for r in completed.values())
    multiseed_viable = (
        len(viable_seeds) >= 2
        and not any_collapse
        and (mean_s - mean_t) >= -VIABILITY_PR_AUC_MARGIN
        and unused_worse == 0
        and updates_ok
        and teachers_ok
    )
    any_improved = any((r.get("gate") or {}).get("improved_vs_teacher") for r in completed.values())
    return {
        "multiseed_viable": multiseed_viable,
        "viable_seeds": viable_seeds,
        "mean_pr_delta": mean_s - mean_t,
        "any_improved": any_improved,
        "updates_verified_all_seeds": updates_ok,
        "teachers_unchanged_all_seeds": teachers_ok,
        "systematic_unused_leaf_deterioration": unused_worse >= 2,
    }


def final_status_label(
    *,
    gpu_blocked: bool = False,
    seed42_gate: dict[str, Any] | None = None,
    confirmation_run: bool = False,
    multiseed: dict[str, Any] | None = None,
) -> str:
    if gpu_blocked or seed42_gate is None:
        return "objective2_teacher_anchored_prepared_gpu_blocked"
    if not seed42_gate.get("viable"):
        return "objective2_teacher_anchored_seed42_failed_viability"
    if not confirmation_run:
        return "objective2_teacher_anchored_seed42_viable_confirmation_not_run"
    assert multiseed is not None
    if not multiseed.get("multiseed_viable"):
        return "objective2_teacher_anchored_multiseed_not_supported"
    if multiseed.get("any_improved"):
        return "objective2_teacher_anchored_multiseed_viable_with_improvement"
    return "objective2_teacher_anchored_multiseed_viable_no_improvement"
