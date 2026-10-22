"""INNER_SELECT residual promotion. Official VALIDATION is unused."""

from __future__ import annotations

from typing import Any

from .constants import MAX_PROMOTED_RESIDUAL, PROMOTION_MARGIN, SIMPLICITY_RANK


def decide_promotions(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Promote at most two residual candidates that beat L1 by >= 0.001 PR-AUC.

    After optional E2E, each family keeps only the better of frozen-base vs E2E.
    Official VALIDATION is unused. No candidate can be invented after results.
    """
    by = {r["condition"]: r for r in rows}
    l1 = by.get("L1")
    if l1 is None:
        raise ValueError("L1 missing from inner screen")
    l1_pr = float(l1["select_PR_AUC"])

    residual_names = [n for n in ("R0", "R1", "R2", "R3") if n in by and by[n].get("executed", True)]
    eligible: list[dict[str, Any]] = []
    for name in residual_names:
        rec = by[name]
        pr = float(rec["select_PR_AUC"])
        if pr >= l1_pr + PROMOTION_MARGIN:
            e2e_name = f"E2E_{name}"
            e2e = by.get(e2e_name)
            chosen = name
            chosen_pr = pr
            chosen_f1 = float(rec.get("select_F1") or 0.0)
            stage = "frozen_base"
            if e2e is not None:
                e2e_pr = float(e2e["select_PR_AUC"])
                e2e_f1 = float(e2e.get("select_F1") or 0.0)
                if (e2e_pr, e2e_f1) > (chosen_pr, chosen_f1):
                    chosen = e2e_name
                    chosen_pr = e2e_pr
                    chosen_f1 = e2e_f1
                    stage = "e2e"
            eligible.append(
                {
                    "inner_condition": name,
                    "promoted_condition": chosen,
                    "validation_name": chosen,
                    "stage": stage,
                    "category": "function_preserving_residual",
                    "inner_select_pr_auc": chosen_pr,
                    "inner_select_f1": chosen_f1,
                    "frozen_base_pr_auc": pr,
                    "e2e_pr_auc": float(e2e["select_PR_AUC"]) if e2e is not None else None,
                    "delta_vs_L1": chosen_pr - l1_pr,
                    "simplicity": SIMPLICITY_RANK.get(name, 9),
                    "spec": {
                        "family": "residual",
                        "final_distill": rec.get("final_distill"),
                        "residual_teacher": rec.get("residual_teacher"),
                        "route": rec.get("route"),
                        "encoder_trainable": stage == "e2e",
                    },
                }
            )

    eligible.sort(
        key=lambda r: (-float(r["inner_select_pr_auc"]), -float(r["inner_select_f1"]), r["simplicity"])
    )
    # At most one promoted architecture per residual family, then cap at 2 families.
    seen_family = set()
    unique: list[dict[str, Any]] = []
    for rec in eligible:
        fam = rec["inner_condition"]
        if fam in seen_family:
            continue
        seen_family.add(fam)
        unique.append(rec)
    promoted = unique[:MAX_PROMOTED_RESIDUAL]
    return {
        "official_r52_validation_not_used_for_selection": True,
        "INNER_SELECT_only": True,
        "L1_PR_AUC": l1_pr,
        "TA2_PR_AUC": float(by["TA2"]["select_PR_AUC"]) if "TA2" in by else None,
        "promotion_margin": PROMOTION_MARGIN,
        "promoted": promoted,
        "n_promoted": len(promoted),
        "eligible_before_cap": [e["inner_condition"] for e in unique],
        "R3": by.get("R3", {}).get("status", "absent"),
        "frozen_before_official_validation_evaluation_of_candidates": True,
        "no_candidate_invented_after_results": True,
    }
