"""INNER_SELECT specialist promotion. Official VALIDATION is unused."""

from __future__ import annotations

from typing import Any

from .constants import MAX_PROMOTED, PROMOTION_MARGIN, Q_VALUES, SPECIALIST_CONDITIONS


def _key(condition: str, q: float) -> str:
    return f"{condition}@q{q:.2f}"


def decide_promotions(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Promote at most two ODST specialist systems with ODST-specific value.

    A candidate may be promoted only if whole-system PR-AUC >= L1 + 0.001
    and (S3 >= S1 + 0.001 or S4 >= S1 + 0.001) at the same q.
    Teacher-guided ODST must also beat task-only ODST at that q.
    Prefer one route-OFF and one route-ON if both qualify.
    """
    by = {r["condition"]: r for r in rows}
    l1 = by.get("L1")
    if l1 is None:
        raise ValueError("L1 missing from inner screen")
    l1_pr = float(l1["select_PR_AUC"])

    factorial: dict[str, Any] = {}
    eligible: list[dict[str, Any]] = []
    for q in Q_VALUES:
        s0 = by.get(_key("S0", q))
        s1 = by.get(_key("S1", q))
        s2 = by.get(_key("S2", q))
        s3 = by.get(_key("S3", q))
        s4 = by.get(_key("S4", q))
        if not all(r is not None for r in (s0, s1, s2, s3, s4)):
            continue
        s0_pr = float(s0["select_PR_AUC"])
        s1_pr = float(s1["select_PR_AUC"])
        s2_pr = float(s2["select_PR_AUC"])
        s3_pr = float(s3["select_PR_AUC"])
        s4_pr = float(s4["select_PR_AUC"])
        effects = {
            "q": float(q),
            "S0": s0_pr,
            "S1": s1_pr,
            "S2": s2_pr,
            "S3": s3_pr,
            "S4": s4_pr,
            "S2_minus_S0": s2_pr - s0_pr,
            "S3_minus_S1": s3_pr - s1_pr,
            "S3_minus_S2": s3_pr - s2_pr,
            "S4_minus_S3": s4_pr - s3_pr,
            "S4_minus_S1": s4_pr - s1_pr,
            "coverage": s3.get("gate_coverage", s1.get("gate_coverage")),
        }
        factorial[f"{q:.2f}"] = effects
        for name, rec, matched_linear, task_odst, odst_vs_linear in (
            ("S3", s3, s1_pr, s2_pr, s3_pr - s1_pr),
            ("S4", s4, s1_pr, s2_pr, s4_pr - s1_pr),
        ):
            pr = float(rec["select_PR_AUC"])
            whole_ok = pr >= l1_pr + PROMOTION_MARGIN
            odst_ok = pr >= matched_linear + PROMOTION_MARGIN
            teacher_ok = pr > task_odst
            if whole_ok and odst_ok and teacher_ok:
                e2e_name = f"E2E_{_key(name, q)}"
                e2e = by.get(e2e_name)
                chosen = rec["condition"]
                chosen_pr = pr
                stage = "head_only"
                if e2e is not None:
                    e2e_pr = float(e2e["select_PR_AUC"])
                    if e2e_pr > chosen_pr:
                        chosen = e2e_name
                        chosen_pr = e2e_pr
                        stage = "e2e"
                eligible.append(
                    {
                        "inner_condition": name,
                        "q": float(q),
                        "promoted_condition": chosen,
                        "stage": stage,
                        "inner_select_pr_auc": chosen_pr,
                        "head_only_pr_auc": pr,
                        "e2e_pr_auc": float(e2e["select_PR_AUC"]) if e2e is not None else None,
                        "delta_vs_L1": chosen_pr - l1_pr,
                        "odst_minus_matched_linear": odst_vs_linear,
                        "teacher_guidance_effect": pr - task_odst,
                        "gate_coverage": float(rec.get("gate_coverage") or 0.0),
                        "route": bool(SPECIALIST_CONDITIONS[name]["route"]),
                        "spec": {
                            **SPECIALIST_CONDITIONS[name],
                            "q": float(q),
                            "encoder_trainable": stage == "e2e",
                        },
                    }
                )

    def _sort_key(r: dict[str, Any]) -> tuple:
        return (
            -float(r["delta_vs_L1"]),
            -float(r["odst_minus_matched_linear"]),
            float(r["gate_coverage"]),
        )

    eligible.sort(key=_sort_key)
    route_off = [e for e in eligible if not e["route"]]
    route_on = [e for e in eligible if e["route"]]
    promoted: list[dict[str, Any]] = []
    if route_off and route_on:
        promoted = [route_off[0], route_on[0]]
        promoted.sort(key=_sort_key)
        promoted = promoted[:MAX_PROMOTED]
    else:
        promoted = eligible[:MAX_PROMOTED]

    return {
        "official_r52_validation_not_used_for_selection": True,
        "INNER_SELECT_only": True,
        "L1_PR_AUC": l1_pr,
        "promotion_margin": PROMOTION_MARGIN,
        "q_values": list(Q_VALUES),
        "factorial_effects": factorial,
        "promoted": promoted,
        "n_promoted": len(promoted),
        "eligible_before_cap": [
            {"condition": e["inner_condition"], "q": e["q"], "pr_auc": e["inner_select_pr_auc"]}
            for e in eligible
        ],
        "prefer_one_route_off_one_route_on": True,
        "frozen_before_official_validation_evaluation_of_candidates": True,
        "no_candidate_invented_after_results": True,
        "no_additional_q_or_architecture_after_this_commit": True,
    }
