"""Predeclared EDITOR-029 rulings. Thresholds are frozen before scores are examined."""

from __future__ import annotations

from typing import Any

from .constants import SUPPORTED_OFFSETS_CONSISTENT, SUPPORTED_OFFSETS_STRONG


def _ci_lo(ci: list[float] | None) -> float:
    if not ci:
        return float("nan")
    return float(ci[0])


def ranking_signal(
    *,
    mean_pr_auc: float,
    prevalence: float,
    ci_lo: float | None,
    n_offsets_above: int | None = None,
    median_pr_auc: float | None = None,
    median_prevalence: float | None = None,
    require_offsets: bool,
) -> str:
    excess = float(mean_pr_auc) - float(prevalence)
    if median_pr_auc is not None and median_prevalence is not None:
        if float(median_pr_auc) <= float(median_prevalence):
            return "NOT_SUPPORTED"
    if mean_pr_auc <= prevalence:
        return "NOT_SUPPORTED"
    strong = excess > 0 and (ci_lo is not None and ci_lo > 0)
    if require_offsets:
        strong = strong and (n_offsets_above is not None and int(n_offsets_above) >= SUPPORTED_OFFSETS_STRONG)
    if strong and mean_pr_auc > prevalence:
        return "SUPPORTED"
    if excess > 0:
        return "CONSISTENT"
    return "NOT_SUPPORTED"


def part_a_ranking_signal(
    *,
    ta2_offset0_mean_pr_auc: float,
    offset0_prevalence: float,
    ta2_excess_ci_lo: float,
    n_offsets_above: int,
    median_pr_auc: float,
    median_prevalence: float,
) -> str:
    """A1+A2+A3 for R52_DEOVERLAP_RANKING_SIGNAL."""
    if median_pr_auc <= median_prevalence:
        return "NOT_SUPPORTED"
    a1 = ta2_offset0_mean_pr_auc > offset0_prevalence
    a2 = ta2_excess_ci_lo > 0
    a3 = int(n_offsets_above) >= SUPPORTED_OFFSETS_STRONG
    if a1 and a2 and a3:
        return "SUPPORTED"
    if ta2_offset0_mean_pr_auc > offset0_prevalence or median_pr_auc > median_prevalence:
        return "CONSISTENT"
    return "NOT_SUPPORTED"


def contrast_signal(
    *,
    offset0_ci_lo: float,
    median_difference: float,
    n_favourable: int,
) -> str:
    n_fav = int(n_favourable)
    if median_difference <= 0 or n_fav <= 10:
        return "NOT_SUPPORTED"
    if offset0_ci_lo > 0 and n_fav >= SUPPORTED_OFFSETS_STRONG:
        return "SUPPORTED"
    if median_difference > 0 and n_fav >= SUPPORTED_OFFSETS_CONSISTENT:
        return "CONSISTENT"
    return "NOT_SUPPORTED"


def endpoint_ranking_signal(
    *,
    mean_pr_auc: float,
    prevalence: float,
    excess_ci_lo: float,
) -> str:
    if mean_pr_auc <= prevalence:
        return "NOT_SUPPORTED"
    if excess_ci_lo > 0:
        return "SUPPORTED"
    if (mean_pr_auc - prevalence) > 0:
        return "CONSISTENT"
    return "NOT_SUPPORTED"


def endpoint_deoverlap_signal(
    *,
    offset0_pr_auc: float,
    offset0_prevalence: float,
    excess_ci_lo: float,
    n_offsets_above: int,
    median_pr_auc: float,
    median_prevalence: float,
) -> str:
    if median_pr_auc <= median_prevalence:
        return "NOT_SUPPORTED"
    b3 = offset0_pr_auc > offset0_prevalence
    b4 = excess_ci_lo > 0
    b5 = int(n_offsets_above) >= SUPPORTED_OFFSETS_STRONG
    if b3 and b4 and b5:
        return "SUPPORTED"
    if (offset0_pr_auc > offset0_prevalence) or (median_pr_auc > median_prevalence):
        return "CONSISTENT"
    return "NOT_SUPPORTED"


def endpoint_component_value(
    *,
    stride1_ci_lo: float,
    offset0_ci_lo: float,
    median_difference: float,
    n_favourable: int,
) -> str:
    n_fav = int(n_favourable)
    if median_difference <= 0 or n_fav <= 10:
        return "NOT_SUPPORTED"
    if stride1_ci_lo > 0 and offset0_ci_lo > 0 and n_fav >= SUPPORTED_OFFSETS_STRONG:
        return "SUPPORTED"
    if median_difference > 0 and n_fav >= SUPPORTED_OFFSETS_CONSISTENT:
        return "CONSISTENT"
    return "NOT_SUPPORTED"


def route_structural_value(
    *,
    ep_final_mae: float,
    ep_f10_mae: float,
    mae_diff_ci: list[float] | None,
) -> str:
    """SUPPORTED if EP_FINAL has lower mean route MAE than EP_F10 and CI agrees."""
    lower = float(ep_final_mae) < float(ep_f10_mae)
    if not lower:
        if float(ep_final_mae) == float(ep_f10_mae):
            return "CONSISTENT"
        return "NOT_SUPPORTED"
    if mae_diff_ci is None:
        return "CONSISTENT"
    # Favourable direction: F10_MAE - FINAL_MAE > 0, so CI lower bound > 0.
    if _ci_lo(mae_diff_ci) > 0:
        return "SUPPORTED"
    return "CONSISTENT"


def dependence_concern(ranking: str, ta2_minus_c2: str) -> str:
    if ranking == "NOT_SUPPORTED":
        return "NOT_RESOLVED"
    if ranking == "SUPPORTED" and ta2_minus_c2 != "NOT_SUPPORTED":
        if ta2_minus_c2 == "SUPPORTED":
            return "RESOLVED"
        return "RESOLVED_WITH_QUALIFICATION"
    if ranking == "CONSISTENT":
        return "RESOLVED_WITH_QUALIFICATION"
    return "NOT_RESOLVED"


def endpoint_causality_concern(ranking: str, deoverlap: str) -> str:
    if ranking == "NOT_SUPPORTED" or deoverlap == "NOT_SUPPORTED":
        return "NOT_RESOLVED"
    if ranking == "SUPPORTED" and deoverlap == "SUPPORTED":
        return "RESOLVED_FOR_END_OF_DAY_DETECTION"
    if ranking in {"SUPPORTED", "CONSISTENT"} and deoverlap in {"SUPPORTED", "CONSISTENT"}:
        return "RESOLVED_WITH_QUALIFICATION"
    return "NOT_RESOLVED"


def editor_response_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "concern": "window_dependence",
            "question": "Do r5.2 conclusions remain under non-overlapping windows?",
            "ruling": payload.get("R52_DEOVERLAP_RANKING_SIGNAL"),
            "editor_closure": payload.get("EDITOR029_DEPENDENCE_CONCERN"),
        },
        {
            "concern": "endpoint_semantics",
            "question": "Does ranking remain under an endpoint-defined past-and-current-day task?",
            "ruling": payload.get("ENDPOINT_RANKING_SIGNAL"),
            "editor_closure": payload.get("EDITOR029_ENDPOINT_CAUSALITY_CONCERN"),
        },
        {
            "concern": "teacher_guidance",
            "question": "Does ensemble-teacher predictive guidance retain value at the endpoint?",
            "ruling": payload.get("ENDPOINT_TEACHER_GUIDANCE_VALUE"),
            "editor_closure": payload.get("ENDPOINT_TEACHER_GUIDANCE_VALUE"),
        },
        {
            "concern": "same_user_partitions",
            "question": "Did EDITOR-029 test unseen-user generalisation?",
            "ruling": "NO",
            "editor_closure": "UNSEEN_USER_GENERALISATION_TESTED=NO",
        },
        {
            "concern": "cross_release",
            "question": "Did EDITOR-029 change the frozen r6.1 conclusion?",
            "ruling": "NO",
            "editor_closure": "EDITOR024_R61_GENERALISATION_RESULT_CHANGED=NO",
        },
    ]
