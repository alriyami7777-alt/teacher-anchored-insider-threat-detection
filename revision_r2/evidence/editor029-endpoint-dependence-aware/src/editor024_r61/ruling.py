"""Predeclared EDITOR-024 claim rules. Do not change after seeing r6.1 results."""

from __future__ import annotations

from typing import Any


def classify_contrast(mean_value: float, ci_lower: float) -> str:
    if mean_value > 0 and ci_lower > 0:
        return "SUPPORTED"
    if mean_value > 0:
        return "CONSISTENT"
    return "NOT_SUPPORTED"


def concern5_status(ta2_ranking_transfer: str) -> str:
    if ta2_ranking_transfer == "SUPPORTED":
        return "RESOLVED_WITH_PROSPECTIVELY_RESERVED_CONFIRMATION"
    if ta2_ranking_transfer == "CONSISTENT":
        return "PARTIALLY_RESOLVED_WITH_PROSPECTIVELY_RESERVED_CONFIRMATION"
    return "PROSPECTIVELY_TESTED_BUT_GENERALISATION_LIMITED"


def paper_wording(ta2_ranking_transfer: str) -> str:
    if ta2_ranking_transfer == "SUPPORTED":
        return (
            "After model development and selection were completed on CERT r5.2, CERT r6.1 was "
            "prospectively reserved for a single final cross-release evaluation. Prior knowledge "
            "was limited to release existence and file metadata; no r6.1 empirical content, labels, "
            "prevalence, feature distributions or predictive results had been inspected. The frozen "
            "r5.2-trained models were then evaluated without target-side training, scaling, "
            "calibration or threshold selection."
        )
    return (
        "The prospectively reserved cross-release evaluation exposed limited transfer to CERT r6.1 "
        "despite strong r5.2 validation performance."
    )


def route_structural_value(
    *,
    ta2_mae: float | None,
    f10_mae: float | None,
    ta2_kl: float | None,
    f10_kl: float | None,
    ta2_hard: float | None,
    f10_hard: float | None,
    ta2_leaf: float | None,
    f10_leaf: float | None,
) -> str:
    vals = (ta2_mae, f10_mae, ta2_kl, f10_kl, ta2_hard, f10_hard, ta2_leaf, f10_leaf)
    if any(v is None for v in vals):
        return "NOT_RUN"
    fav = [
        float(ta2_mae) < float(f10_mae),
        float(ta2_kl) < float(f10_kl),
        float(ta2_hard) > float(f10_hard),
        float(ta2_leaf) > float(f10_leaf),
    ]
    if all(fav):
        return "SUPPORTED"
    if any(fav):
        return "CONSISTENT"
    return "NOT_SUPPORTED"


def claim_payload(
    *,
    ta2_ranking_transfer: str,
    teacher_guidance: str,
    complete_formulation: str,
    route_anchor: str,
    ta2_over_linear: str,
    route_structural: str,
    compatibility_gate: str,
    inference_executed: bool,
) -> dict[str, Any]:
    completed = bool(inference_executed and compatibility_gate == "PASS")
    return {
        "H1": ta2_ranking_transfer,
        "R61_FINAL_TA2_RANKING_TRANSFER": ta2_ranking_transfer,
        "R61_TEACHER_GUIDANCE_VALUE": teacher_guidance,
        "R61_COMPLETE_FORMULATION_VALUE": complete_formulation,
        "R61_ROUTE_ANCHOR_VALUE": route_anchor,
        "R61_TA2_OVER_LINEAR_VALUE": ta2_over_linear,
        "R61_ROUTE_STRUCTURAL_VALUE": route_structural,
        "FINAL_PROSPECTIVELY_RESERVED_EVALUATION_COMPLETED": "YES" if completed else "NO",
        "EDITOR_CONCERN5_STATUS": concern5_status(ta2_ranking_transfer) if completed else "NOT_COMPLETED",
        "CURRENT_PAPER_MODEL": "TA2",
        "paper_wording": paper_wording(ta2_ranking_transfer),
        "designated_final_model_unchanged": True,
    }
