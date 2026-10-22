"""Section 22–27 rulings. Thresholds are protocol-frozen. No post-hoc search."""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from .constants import (
    BINARY_RATE_DIFF_MODERATE,
    BINARY_RATE_DIFF_SEVERE,
    HEAD_SURVIVAL_RATIO,
    MEAN_SHIFT_Z_MODERATE,
    MEAN_SHIFT_Z_SEVERE,
    OOS_RATE_MODERATE,
    OOS_RATE_SEVERE,
    PSI_LIMITED_MAX,
    PSI_SEVERE_MIN,
    R61_PREVALENCE,
    REPRESENTATION_NONPORTABILITY_HIGH,
    REPRESENTATION_NONPORTABILITY_LOW,
    STUDENT_MODELS,
)

LABEL_INTEGRITY_VALUES = (
    "PASS",
    "PARTIAL_GROUND_TRUTH_COVERAGE",
    "SEMANTIC_MISMATCH",
    "PARTIAL_COVERAGE_AND_SEMANTIC_MISMATCH",
    "UNRESOLVED",
)
ROOT_CAUSES = (
    "LABEL_PIPELINE_OR_GROUND_TRUTH",
    "RELEASE_LEVEL_REPRESENTATION_SHIFT",
    "PREDICTION_HEAD_NONPORTABILITY",
    "MIXED_LABEL_AND_REPRESENTATION",
    "MIXED_REPRESENTATION_AND_HEAD",
    "UNRESOLVED",
)
REMEDIES = (
    "GROUND_TRUTH_AND_LABEL_PIPELINE_REPAIR",
    "USER_RELATIVE_RELEASE_INVARIANT_REPRESENTATION",
    "MULTI_RELEASE_REPRESENTATION_LEARNING",
    "HEAD_PORTABILITY_REDESIGN",
    "LABEL_REPAIR_THEN_REPRESENTATION_REDESIGN",
    "NO_REMEDY_YET_ROOT_CAUSE_UNRESOLVED",
)

# Diagnostic-label rescore "materially changes collapse" if PR-AUC exceeds 2× prevalence.
MATERIAL_COLLAPSE_CHANGE_PR_AUC_MULTIPLIER = 2.0


def decide_label_integrity(
    *,
    scenario4_available: bool,
    n_official_scenarios: int,
    n_scenarios_with_answers: int,
    semantic_mismatch: bool,
    unresolved: bool = False,
) -> str:
    if unresolved:
        return "UNRESOLVED"
    coverage_partial = (not scenario4_available) or (n_scenarios_with_answers < n_official_scenarios)
    if coverage_partial and semantic_mismatch:
        return "PARTIAL_COVERAGE_AND_SEMANTIC_MISMATCH"
    if coverage_partial:
        return "PARTIAL_GROUND_TRUTH_COVERAGE"
    if semantic_mismatch:
        return "SEMANTIC_MISMATCH"
    return "PASS"


def _ratios(transfer: Mapping[str, float]) -> list[float]:
    return [float(transfer[m]) for m in STUDENT_MODELS if m in transfer]


def decide_representation_nonportability(transfer_ratios: Mapping[str, float]) -> str:
    vals = _ratios(transfer_ratios)
    if len(vals) < 4:
        return "MIXED"
    n_supported = sum(1 for r in vals if (r <= REPRESENTATION_NONPORTABILITY_LOW) or (r < 0.0))
    n_not = sum(1 for r in vals if r > REPRESENTATION_NONPORTABILITY_HIGH)
    if n_supported >= 3:
        return "SUPPORTED"
    if n_not >= 3:
        return "NOT_SUPPORTED"
    return "MIXED"


def ranking_collapses_near_prevalence(pr_auc_values: Mapping[str, float], prevalence: float) -> bool:
    """True when all four models remain approximately at prevalence (PR-AUC < 2× prevalence)."""
    if prevalence <= 0:
        return False
    return all(float(pr_auc_values[m]) < MATERIAL_COLLAPSE_CHANGE_PR_AUC_MULTIPLIER * prevalence for m in STUDENT_MODELS)


def decide_head_specific_failure(
    *,
    transfer_ratios: Mapping[str, float],
    output_pr_auc: Mapping[str, float],
    prevalence: float,
) -> str:
    vals = _ratios(transfer_ratios)
    if len(vals) < 4:
        return "MIXED"
    n_survive = sum(1 for r in vals if r > HEAD_SURVIVAL_RATIO)
    collapsed = ranking_collapses_near_prevalence(output_pr_auc, prevalence)
    if n_survive >= 3 and collapsed:
        return "SUPPORTED"
    if n_survive >= 3 and not collapsed:
        return "NOT_SUPPORTED"
    if n_survive < 2 and collapsed:
        return "NOT_SUPPORTED"
    return "MIXED"


def _max_abs(values: Iterable[float]) -> float:
    seq = [abs(float(v)) for v in values]
    return max(seq) if seq else 0.0


def decide_covariate_shift(
    *,
    psi_values: Iterable[float],
    mean_shift_z: Iterable[float],
    oos_rates: Iterable[float],
    binary_rate_diffs: Iterable[float],
) -> str:
    max_psi = _max_abs(psi_values)
    max_z = _max_abs(mean_shift_z)
    max_oos = _max_abs(oos_rates)
    max_bin = _max_abs(binary_rate_diffs)
    severe = (
        max_psi >= PSI_SEVERE_MIN
        or max_z >= MEAN_SHIFT_Z_SEVERE
        or max_oos >= OOS_RATE_SEVERE
        or max_bin >= BINARY_RATE_DIFF_SEVERE
    )
    limited = (
        max_psi < PSI_LIMITED_MAX
        and max_z < MEAN_SHIFT_Z_MODERATE
        and max_oos < OOS_RATE_MODERATE
        and max_bin < BINARY_RATE_DIFF_MODERATE
    )
    if severe:
        return "SEVERE"
    if limited:
        return "LIMITED"
    return "MODERATE"


def diagnostic_rescore_materially_changes(
    *,
    diagnostic_pr_auc: Mapping[str, float] | None,
    original_pr_auc: Mapping[str, float],
    prevalence: float,
) -> bool:
    if not diagnostic_pr_auc:
        return False
    original_collapsed = ranking_collapses_near_prevalence(original_pr_auc, prevalence)
    diagnostic_collapsed = ranking_collapses_near_prevalence(diagnostic_pr_auc, prevalence)
    if original_collapsed and not diagnostic_collapsed:
        return True
    ta2_orig = float(original_pr_auc.get("TA2", 0.0))
    ta2_diag = float(diagnostic_pr_auc.get("TA2", 0.0))
    return ta2_diag > MATERIAL_COLLAPSE_CHANGE_PR_AUC_MULTIPLIER * max(prevalence, ta2_orig)


def count_activity_shift_dominant(
    *,
    ranked_features: list[str],
    count_features: Iterable[str] = (),
    binary_features: Iterable[str] = (),
    top_k: int = 5,
) -> bool:
    top = list(ranked_features)[:top_k]
    counts = set(count_features)
    n_count = sum(1 for f in top if f in counts)
    return n_count >= 3


def decide_primary_root_cause(
    *,
    label_integrity: str,
    diagnostic_rescore_material: bool,
    representation_nonportability: str,
    head_specific_failure: str,
) -> str:
    label_fail = label_integrity in {
        "SEMANTIC_MISMATCH",
        "PARTIAL_GROUND_TRUTH_COVERAGE",
        "PARTIAL_COVERAGE_AND_SEMANTIC_MISMATCH",
    }
    repr_supported = representation_nonportability == "SUPPORTED"
    head_supported = head_specific_failure == "SUPPORTED"

    # Case 1
    if label_fail and diagnostic_rescore_material:
        if repr_supported:
            return "MIXED_LABEL_AND_REPRESENTATION"
        return "LABEL_PIPELINE_OR_GROUND_TRUTH"

    # Case 2
    if repr_supported:
        if head_supported:
            return "MIXED_REPRESENTATION_AND_HEAD"
        return "RELEASE_LEVEL_REPRESENTATION_SHIFT"

    # Case 3
    if head_supported:
        return "PREDICTION_HEAD_NONPORTABILITY"

    # Partial label failure without material rescore, plus mixed representation
    if label_fail and representation_nonportability == "MIXED":
        return "MIXED_LABEL_AND_REPRESENTATION"

    return "UNRESOLVED"


def decide_recommended_remedy(
    *,
    primary_root_cause: str,
    count_activity_levels_primary_shift: bool,
    broad_generation_shift_remains: bool,
) -> str:
    if primary_root_cause == "LABEL_PIPELINE_OR_GROUND_TRUTH":
        return "GROUND_TRUTH_AND_LABEL_PIPELINE_REPAIR"
    if primary_root_cause == "MIXED_LABEL_AND_REPRESENTATION":
        return "LABEL_REPAIR_THEN_REPRESENTATION_REDESIGN"
    if primary_root_cause == "PREDICTION_HEAD_NONPORTABILITY":
        return "HEAD_PORTABILITY_REDESIGN"
    if primary_root_cause == "MIXED_REPRESENTATION_AND_HEAD":
        return "HEAD_PORTABILITY_REDESIGN" if not count_activity_levels_primary_shift else "USER_RELATIVE_RELEASE_INVARIANT_REPRESENTATION"
    if primary_root_cause == "RELEASE_LEVEL_REPRESENTATION_SHIFT":
        if broad_generation_shift_remains and not count_activity_levels_primary_shift:
            return "MULTI_RELEASE_REPRESENTATION_LEARNING"
        if count_activity_levels_primary_shift:
            return "USER_RELATIVE_RELEASE_INVARIANT_REPRESENTATION"
        return "MULTI_RELEASE_REPRESENTATION_LEARNING"
    return "NO_REMEDY_YET_ROOT_CAUSE_UNRESOLVED"


def apply_rulings(packet: dict[str, Any]) -> dict[str, Any]:
    """Apply Sections 22–27 to a completed diagnostic packet."""
    label_integrity = decide_label_integrity(
        scenario4_available=bool(packet["scenario4_available"]),
        n_official_scenarios=int(packet["n_official_scenarios"]),
        n_scenarios_with_answers=int(packet["n_scenarios_with_answers"]),
        semantic_mismatch=bool(packet["semantic_mismatch"]),
        unresolved=bool(packet.get("label_unresolved", False)),
    )
    transfer = packet["representation_transfer_ratios"]
    pr_auc = packet["original_pr_auc"]
    prevalence = float(packet.get("prevalence", R61_PREVALENCE))
    representation = decide_representation_nonportability(transfer)
    head = decide_head_specific_failure(
        transfer_ratios=transfer,
        output_pr_auc=pr_auc,
        prevalence=prevalence,
    )
    covariate = decide_covariate_shift(
        psi_values=packet["psi_values"],
        mean_shift_z=packet["mean_shift_z"],
        oos_rates=packet["oos_rates"],
        binary_rate_diffs=packet["binary_rate_diffs"],
    )
    material = diagnostic_rescore_materially_changes(
        diagnostic_pr_auc=packet.get("diagnostic_pr_auc"),
        original_pr_auc=pr_auc,
        prevalence=float(packet.get("diagnostic_prevalence", prevalence)),
    )
    root = decide_primary_root_cause(
        label_integrity=label_integrity,
        diagnostic_rescore_material=material,
        representation_nonportability=representation,
        head_specific_failure=head,
    )
    remedy = decide_recommended_remedy(
        primary_root_cause=root,
        count_activity_levels_primary_shift=bool(packet.get("count_activity_levels_primary_shift", False)),
        broad_generation_shift_remains=bool(packet.get("broad_generation_shift_remains", False)),
    )
    return {
        "R61_LABEL_INTEGRITY": label_integrity,
        "REPRESENTATION_NONPORTABILITY": representation,
        "HEAD_SPECIFIC_FAILURE": head,
        "R61_COVARIATE_SHIFT": covariate,
        "EDITOR025_PRIMARY_ROOT_CAUSE": root,
        "EDITOR025_RECOMMENDED_NEXT_REMEDY": remedy,
        "diagnostic_rescore_materially_changes_collapse": material,
    }
