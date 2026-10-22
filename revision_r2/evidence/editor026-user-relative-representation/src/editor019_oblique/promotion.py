"""Inner promotion and conditional XGB-teacher trigger. Thresholds never relax."""

from __future__ import annotations

from typing import Any

from .constants import (
    DTE_FAMILIES,
    MAX_PROMOTED,
    NEW_TREE_FAMILIES,
    PROMOTION_MARGIN,
    XGB_TRIGGER_MLP_BAND,
    XGB_TRIGGER_ODST_MARGIN,
)
from .safety import Editor019ProtocolError


def _pr(rows: dict[str, dict[str, Any]], name: str) -> float:
    if name not in rows:
        raise Editor019ProtocolError(f"inner results missing {name}")
    return float(rows[name]["select_PR_AUC"])


def factorial_effects(rows: dict[str, dict[str, Any]]) -> dict[str, Any]:
    teacher_effects = {
        fam: _pr(rows, f"{fam}-D") - _pr(rows, f"{fam}-T") for fam in NEW_TREE_FAMILIES
    }
    tree_d = {fam: _pr(rows, f"{fam}-D") for fam in NEW_TREE_FAMILIES}
    best_tree = max(tree_d, key=tree_d.get)
    return {
        "SIGNED_SPLIT_EFFECT": _pr(rows, "SO-ODST40-D") - _pr(rows, "ODST40-D"),
        "NON_OBLIVIOUS_EFFECT": _pr(rows, "SO-DTE40-D") - _pr(rows, "SO-ODST40-D"),
        "BOOSTING_EFFECT": _pr(rows, "BSO-DTE40-D") - _pr(rows, "SO-DTE40-D"),
        "TEACHER_EFFECT": teacher_effects,
        "BEST_TREE": f"{best_tree}-D",
        "BEST_TREE_PR_AUC": tree_d[best_tree],
        "BEST_TREE_MINUS_L1": tree_d[best_tree] - _pr(rows, "L1"),
        "BEST_TREE_MINUS_MLP40": tree_d[best_tree] - _pr(rows, "MLP40-D"),
        "tree_D": tree_d,
    }


def decide_promotions(inner_rows: list[dict[str, Any]], *, l1_pr_auc: float) -> dict[str, Any]:
    by_name = {str(r["condition"]): r for r in inner_rows}
    by_name["L1"] = {"condition": "L1", "select_PR_AUC": float(l1_pr_auc)}
    required = ["MLP40-D", "ODST40-D"] + [f"{fam}-{g}" for fam in NEW_TREE_FAMILIES for g in ("T", "D")]
    missing = [n for n in required if n not in by_name]
    if missing:
        raise Editor019ProtocolError(f"inner results missing conditions: {missing}")

    mlp = _pr(by_name, "MLP40-D")
    odst = _pr(by_name, "ODST40-D")
    effects = factorial_effects(by_name)

    eligible: list[dict[str, Any]] = []
    for fam in NEW_TREE_FAMILIES:
        teacher_pr = _pr(by_name, f"{fam}-D")
        task_pr = _pr(by_name, f"{fam}-T")
        ok = (
            teacher_pr >= float(l1_pr_auc) + PROMOTION_MARGIN
            and teacher_pr >= mlp + PROMOTION_MARGIN
            and teacher_pr > task_pr
        )
        rec = {
            "family": fam,
            "candidate": f"{fam}-D",
            "task_counterpart": f"{fam}-T",
            "candidate_PR_AUC": teacher_pr,
            "task_PR_AUC": task_pr,
            "L1_PR_AUC": float(l1_pr_auc),
            "MLP40_D_PR_AUC": mlp,
            "delta_vs_L1": teacher_pr - float(l1_pr_auc),
            "delta_vs_MLP40": teacher_pr - mlp,
            "teacher_gt_task": teacher_pr > task_pr,
            "eligible": bool(ok),
            "margin": PROMOTION_MARGIN,
            "margin_relaxed_after_results": False,
        }
        if ok:
            eligible.append(rec)
    eligible.sort(key=lambda r: (-float(r["candidate_PR_AUC"]), r["family"]))
    promoted = eligible[:MAX_PROMOTED]

    dte_best_name = max(DTE_FAMILIES, key=lambda fam: _pr(by_name, f"{fam}-D"))
    dte_best = _pr(by_name, f"{dte_best_name}-D")
    xgb_trigger = (
        len(promoted) == 0
        and (dte_best - odst) >= XGB_TRIGGER_ODST_MARGIN
        and abs(dte_best - mlp) <= XGB_TRIGGER_MLP_BAND
    )
    return {
        "L1_PR_AUC": float(l1_pr_auc),
        "MLP40_D_PR_AUC": mlp,
        "ODST40_D_PR_AUC": odst,
        "eligible": eligible,
        "promoted": promoted,
        "promoted_names": [p["candidate"] for p in promoted],
        "margin_frozen": PROMOTION_MARGIN,
        "margin_lowered_after_results": False,
        "effects": effects,
        "XGB_TEACHER_BRANCH": "TRIGGERED" if xgb_trigger else "NOT_TRIGGERED",
        "xgb_trigger_detail": {
            "no_tree_passed_section_16": len(promoted) == 0,
            "best_so_dte_or_bso": f"{dte_best_name}-D",
            "best_dte_PR_AUC": dte_best,
            "delta_vs_ODST40_D": dte_best - odst,
            "abs_delta_vs_MLP40_D": abs(dte_best - mlp),
            "odst_margin": XGB_TRIGGER_ODST_MARGIN,
            "mlp_band": XGB_TRIGGER_MLP_BAND,
        },
    }


def decide_xgb_promotion(
    *,
    l1_pr_auc: float,
    mlp_xd: float,
    tree_xd: float,
    tree_name: str,
) -> dict[str, Any]:
    ok = tree_xd >= float(l1_pr_auc) + PROMOTION_MARGIN and tree_xd >= float(mlp_xd) + PROMOTION_MARGIN
    promoted = [{"candidate": f"{tree_name}-XD", "family": tree_name, "candidate_PR_AUC": tree_xd}] if ok else []
    return {
        "eligible": ok,
        "promoted": promoted,
        "promoted_names": [p["candidate"] for p in promoted],
        "MLP40_XD": mlp_xd,
        "BEST_TREE_XD": tree_xd,
        "TREE_MINUS_MLP_XGB_TEACHER": tree_xd - mlp_xd,
        "margin_frozen": PROMOTION_MARGIN,
    }
