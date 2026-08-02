"""Advancement gate and final decision helpers."""

from __future__ import annotations

from typing import Any

from .protocol import ADVANCEMENT, MAX_TOTAL_RUNS


def evaluate_seed42_gate(
    t0: dict[str, Any],
    candidate: dict[str, Any],
) -> dict[str, Any]:
    """Return gate evaluation for one candidate versus T0."""
    reasons: list[str] = []
    mandatory_ok = True

    if candidate.get("had_nan_or_inf"):
        mandatory_ok = False
        reasons.append("nan_or_inf")
    if candidate.get("gradient_explosion"):
        mandatory_ok = False
        reasons.append("gradient_explosion")
    if candidate.get("routing_collapse"):
        mandatory_ok = False
        reasons.append("routing_collapse")
    if candidate.get("protected_access"):
        mandatory_ok = False
        reasons.append("protected_access")

    unused_t0 = float(t0.get("unused_leaves_pct", 100.0))
    unused_c = float(candidate.get("unused_leaves_pct", 100.0))
    if unused_c > unused_t0 + ADVANCEMENT["unused_leaf_max_worse_than_t0_pp"]:
        mandatory_ok = False
        reasons.append("unused_leaves_worse_than_t0")

    # Improvement not solely by threshold movement: require PR-AUC evidence or structural.
    pr_t0 = float(t0["best_pr_auc"])
    pr_c = float(candidate["best_pr_auc"])
    final_pr_c = float(candidate["final_pr_auc"])
    if final_pr_c < candidate.get("best_pr_auc", final_pr_c) - 0.02:
        # temporary best then collapse
        if final_pr_c + 1e-12 < pr_t0:
            reasons.append("collapsed_after_best_epoch")

    gate_a = (
        mandatory_ok
        and (pr_c >= pr_t0 + ADVANCEMENT["pr_auc_gate_a_delta"])
        and not candidate.get("major_calibration_deterioration", False)
        and (final_pr_c >= pr_c - 0.02)
    )
    unused_improved = (unused_t0 - unused_c) >= ADVANCEMENT["unused_leaf_improvement_pp"]
    gate_b = (
        mandatory_ok
        and abs(pr_c - pr_t0) <= ADVANCEMENT["pr_auc_gate_b_tolerance"]
        and unused_improved
        and candidate.get("routing_diversity_improved", False)
        and candidate.get("fp_improved_at_comparable_recall", False)
        and candidate.get("stable_gradients", True)
    )

    passed = bool(gate_a or gate_b)
    return {
        "mandatory_ok": mandatory_ok,
        "gate_a": gate_a,
        "gate_b": gate_b,
        "passed": passed,
        "reasons": reasons,
        "pr_auc_delta": pr_c - pr_t0,
        "unused_leaves_delta_pp": unused_t0 - unused_c,
    }


def choose_one_candidate(results: dict[str, dict[str, Any]]) -> str | None:
    """Select at most one advancing condition among those that passed the gate."""
    passed = []
    for name, row in results.items():
        if name == "T0":
            continue
        gate = row.get("gate") or {}
        if gate.get("passed"):
            passed.append((name, row))
    if not passed:
        return None

    def sort_key(item: tuple[str, dict[str, Any]]):
        name, row = item
        return (
            -float(row["best_pr_auc"]),
            float(row.get("unused_leaves_pct", 100.0)),
            float(row.get("fp_at_best", 1e9)),
            float(row.get("brier_best", 1e9)),
            float(row.get("grad_instability", 1e9)),
            name,
        )

    passed.sort(key=sort_key)
    return passed[0][0]


def assert_run_budget(n_completed: int, max_runs: int = MAX_TOTAL_RUNS) -> None:
    if n_completed > max_runs:
        raise RuntimeError(f"Exceeded maximum run budget {max_runs}; got {n_completed}")


def final_decision_status(
    *,
    seed42_selected: str | None,
    confirmation_ok: bool | None,
    inconclusive_evidence: bool = False,
) -> str:
    if inconclusive_evidence:
        return "objective2_end_to_end_refinement_inconclusive"
    if seed42_selected is None:
        return "objective2_frozen_odst_retained_by_bounded_refinement"
    if confirmation_ok:
        return "objective2_end_to_end_refinement_candidate_identified"
    return "objective2_frozen_odst_retained_by_bounded_refinement"
