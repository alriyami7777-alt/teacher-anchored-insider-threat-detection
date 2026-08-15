"""INNER_SELECT promotion. Official VALIDATION is unused."""

from __future__ import annotations

from typing import Any

from .constants import MAX_PROMOTED_TEMPORAL, PROMOTION_MARGIN, TEMPORAL_CANDIDATES


def decide_promotions(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Promote at most two temporal ODST candidates that beat B0 by >= 0.001 PR-AUC.

    Official VALIDATION is unused. No candidate can be invented after results.
    Tie-break: higher F1, then simpler architecture (T0 < T1 < T2).
    """
    by = {r["condition"]: r for r in rows}
    b0 = by.get("B0")
    if b0 is None:
        raise ValueError("B0 missing from inner screen")
    b0_pr = float(b0["select_PR_AUC"])
    simplicity = {"T0": 0, "T1": 1, "T2": 2}

    eligible: list[dict[str, Any]] = []
    for name in TEMPORAL_CANDIDATES:
        rec = by.get(name)
        if rec is None:
            continue
        pr = float(rec["select_PR_AUC"])
        if pr >= b0_pr + PROMOTION_MARGIN:
            eligible.append(
                {
                    "inner_condition": name,
                    "validation_name": name,
                    "category": "temporal_odst",
                    "inner_select_pr_auc": pr,
                    "inner_select_f1": float(rec.get("select_F1") or 0.0),
                    "delta_vs_B0": pr - b0_pr,
                    "simplicity": simplicity[name],
                    "spec": {
                        "family": rec.get("family"),
                        "placement": rec.get("placement"),
                        "hybrid": rec.get("hybrid"),
                        "center": rec.get("center"),
                        "distill": True,
                        "teacher": "ensemble",
                        "route": False,
                    },
                }
            )

    eligible.sort(
        key=lambda r: (-float(r["inner_select_pr_auc"]), -float(r["inner_select_f1"]), r["simplicity"])
    )
    promoted = eligible[:MAX_PROMOTED_TEMPORAL]
    best = max(TEMPORAL_CANDIDATES, key=lambda n: float(by[n]["select_PR_AUC"])) if all(n in by for n in TEMPORAL_CANDIDATES) else None
    return {
        "official_r52_validation_not_used_for_selection": True,
        "INNER_SELECT_only": True,
        "B0_LINEAR_DISTILL_PR_AUC": b0_pr,
        "B1_TA2_PR_AUC": float(by["B1"]["select_PR_AUC"]) if "B1" in by else None,
        "promotion_margin": PROMOTION_MARGIN,
        "promoted": promoted,
        "n_promoted": len(promoted),
        "best_temporal_candidate": best,
        "best_inner_delta_vs_linear": (
            float(by[best]["select_PR_AUC"]) - b0_pr if best is not None else float("nan")
        ),
        "eligible_before_cap": [e["inner_condition"] for e in eligible],
        "frozen_before_official_validation_evaluation_of_candidates": True,
        "no_candidate_invented_after_results": True,
    }
