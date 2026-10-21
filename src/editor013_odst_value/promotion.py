"""INNER_SELECT promotion. Official VALIDATION is unused."""

from __future__ import annotations

from typing import Any

from .constants import PROMOTION_MARGIN


def decide_promotions(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Promote at most one learned-readout ODST and one residual/hybrid.

    A candidate must beat matched teacher-guided linear H1-LIN-D by >= 0.001 PR-AUC.
    Official VALIDATION is unused.
    """
    by = {r["condition"]: r for r in rows}
    h1 = by.get("H1-LIN-D")
    if h1 is None:
        raise ValueError("H1-LIN-D missing from inner screen")
    h1_pr = float(h1["select_PR_AUC"])

    def _ok(name: str) -> bool:
        rec = by.get(name)
        return rec is not None and float(rec["select_PR_AUC"]) >= h1_pr + PROMOTION_MARGIN

    learned = [n for n in ("H5-ODST-W-D", "H4-ODST-W") if _ok(n)]
    hybrids = [n for n in ("H9-HYB-W-D", "H7-HYB-U-D", "H8-HYB-W", "H6-HYB-U") if _ok(n)]

    promoted: list[dict[str, Any]] = []
    if learned:
        best_l = max(learned, key=lambda n: (float(by[n]["select_PR_AUC"]), n.endswith("-D")))
        val_name = "W1" if best_l.endswith("-D") else "W0"
        promoted.append(
            {
                "inner_condition": best_l,
                "validation_name": val_name,
                "category": "learned_readout_odst",
                "inner_select_pr_auc": float(by[best_l]["select_PR_AUC"]),
                "delta_vs_H1": float(by[best_l]["select_PR_AUC"]) - h1_pr,
                "spec": {
                    "family": "odst",
                    "readout": "weighted",
                    "hybrid": False,
                    "distill": best_l.endswith("-D"),
                    "teacher": "ensemble" if best_l.endswith("-D") else "none",
                    "route": False,
                },
            }
        )
    if hybrids:
        best_h = max(hybrids, key=lambda n: (float(by[n]["select_PR_AUC"]), n.endswith("-D")))
        weighted = "W" in best_h
        val_name = "HW1" if weighted and best_h.endswith("-D") else ("HYB1" if best_h.endswith("-D") else "HYB0")
        promoted.append(
            {
                "inner_condition": best_h,
                "validation_name": val_name,
                "category": "residual_hybrid",
                "inner_select_pr_auc": float(by[best_h]["select_PR_AUC"]),
                "delta_vs_H1": float(by[best_h]["select_PR_AUC"]) - h1_pr,
                "spec": {
                    "family": "hybrid",
                    "readout": "weighted" if weighted else "uniform",
                    "hybrid": True,
                    "distill": best_h.endswith("-D"),
                    "teacher": "ensemble" if best_h.endswith("-D") else "none",
                    "route": False,
                },
            }
        )

    odst_guided = [n for n in ("H3-ODST-U-D", "H5-ODST-W-D", "H7-HYB-U-D", "H9-HYB-W-D") if n in by]
    best_odst = max(odst_guided, key=lambda n: float(by[n]["select_PR_AUC"])) if odst_guided else None
    headroom = "SUPPORTED" if promoted else "NOT_SUPPORTED"
    return {
        "official_r52_validation_not_used_for_selection": True,
        "INNER_SELECT_only": True,
        "H1_LIN_D_pr_auc": h1_pr,
        "promotion_margin": PROMOTION_MARGIN,
        "ODST_INCREMENTAL_HEADROOM_INNER": headroom,
        "promoted": promoted,
        "best_teacher_guided_odst_inner": best_odst,
        "best_inner_odst_delta_vs_H1": (
            float(by[best_odst]["select_PR_AUC"]) - h1_pr if best_odst else float("nan")
        ),
        "n_promoted": len(promoted),
        "frozen_before_official_validation_evaluation_of_candidates": True,
    }
