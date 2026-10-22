"""Inner promotion gate. Thresholds are frozen before results and never lowered."""

from __future__ import annotations

from typing import Any

from .constants import MAX_PROMOTED, NON_TREE_TEACHER, PROMOTION_MARGIN, TREE_FAMILIES
from .safety import Editor018ProtocolError


def decide_promotions(
    inner_rows: list[dict[str, Any]],
    *,
    l1_pr_auc: float,
) -> dict[str, Any]:
    by_name = {str(r["condition"]): r for r in inner_rows}
    required = [f"{fam}-{g}" for fam in ("LIN40", "MLP40", "ODST40", "IWODST40") for g in ("T", "D")]
    missing = [n for n in required if n not in by_name]
    if missing:
        raise Editor018ProtocolError(f"inner results missing conditions: {missing}")

    non_tree = [float(by_name[n]["select_PR_AUC"]) for n in NON_TREE_TEACHER if n in by_name]
    best_non_tree_name = max(NON_TREE_TEACHER, key=lambda n: float(by_name[n]["select_PR_AUC"]))
    best_non_tree = float(by_name[best_non_tree_name]["select_PR_AUC"])

    eligible: list[dict[str, Any]] = []
    for fam in TREE_FAMILIES:
        teacher_name = f"{fam}-D"
        task_name = f"{fam}-T"
        teacher_pr = float(by_name[teacher_name]["select_PR_AUC"])
        task_pr = float(by_name[task_name]["select_PR_AUC"])
        vs_l1 = teacher_pr - float(l1_pr_auc)
        vs_non_tree = teacher_pr - best_non_tree
        teacher_helps = teacher_pr > task_pr
        ok = (
            teacher_pr >= float(l1_pr_auc) + PROMOTION_MARGIN
            and teacher_pr >= best_non_tree + PROMOTION_MARGIN
            and teacher_helps
        )
        rec = {
            "family": fam,
            "candidate": teacher_name,
            "task_counterpart": task_name,
            "candidate_PR_AUC": teacher_pr,
            "task_PR_AUC": task_pr,
            "L1_PR_AUC": float(l1_pr_auc),
            "best_non_tree": best_non_tree_name,
            "best_non_tree_PR_AUC": best_non_tree,
            "delta_vs_L1": vs_l1,
            "delta_vs_best_non_tree": vs_non_tree,
            "teacher_gt_task": teacher_helps,
            "eligible": bool(ok),
            "margin": PROMOTION_MARGIN,
        }
        if ok:
            eligible.append(rec)

    eligible.sort(key=lambda r: (-float(r["candidate_PR_AUC"]), r["family"]))
    # Prefer best standard ODST40 and best IW-ODST40 if both qualify.
    promoted: list[dict[str, Any]] = []
    seen_fam: set[str] = set()
    for rec in eligible:
        if rec["family"] in seen_fam:
            continue
        promoted.append(rec)
        seen_fam.add(str(rec["family"]))
        if len(promoted) >= MAX_PROMOTED:
            break

    effects = {
        "A_second_view_helps": {
            "best_branch_minus_L1": max(float(r["select_PR_AUC"]) for r in inner_rows) - float(l1_pr_auc),
        },
        "B_tree_structure": {
            "ODST40-D_minus_LIN40-D": float(by_name["ODST40-D"]["select_PR_AUC"]) - float(by_name["LIN40-D"]["select_PR_AUC"]),
            "ODST40-D_minus_MLP40-D": float(by_name["ODST40-D"]["select_PR_AUC"]) - float(by_name["MLP40-D"]["select_PR_AUC"]),
            "IWODST40-D_minus_LIN40-D": float(by_name["IWODST40-D"]["select_PR_AUC"]) - float(by_name["LIN40-D"]["select_PR_AUC"]),
            "IWODST40-D_minus_MLP40-D": float(by_name["IWODST40-D"]["select_PR_AUC"]) - float(by_name["MLP40-D"]["select_PR_AUC"]),
        },
        "C_teacher_within_tree": {
            "ODST40-D_minus_ODST40-T": float(by_name["ODST40-D"]["select_PR_AUC"]) - float(by_name["ODST40-T"]["select_PR_AUC"]),
            "IWODST40-D_minus_IWODST40-T": float(by_name["IWODST40-D"]["select_PR_AUC"]) - float(by_name["IWODST40-T"]["select_PR_AUC"]),
        },
        "non_tree_available": list(NON_TREE_TEACHER),
        "best_non_tree": best_non_tree_name,
        "best_non_tree_PR_AUC": best_non_tree,
    }
    return {
        "L1_PR_AUC": float(l1_pr_auc),
        "best_non_tree": best_non_tree_name,
        "best_non_tree_PR_AUC": best_non_tree,
        "eligible": eligible,
        "promoted": promoted,
        "promoted_names": [p["candidate"] for p in promoted],
        "margin_frozen": PROMOTION_MARGIN,
        "margin_lowered_after_results": False,
        "effects": effects,
        "non_tree_prs": {n: float(by_name[n]["select_PR_AUC"]) for n in NON_TREE_TEACHER},
    }
