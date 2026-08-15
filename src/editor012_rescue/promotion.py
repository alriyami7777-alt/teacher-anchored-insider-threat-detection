"""Frozen inner-search ranking and promotion rules. Official VALIDATION is unused."""

from __future__ import annotations

from typing import Any

from .constants import ANCHOR_FORMULATIONS, PROMOTION_MARGIN


def decide_promotions(
    rows: list[dict[str, Any]],
    *,
    max_n: int = 2,
    margin: float = PROMOTION_MARGIN,
) -> dict[str, Any]:
    """Promote at most two teacher-anchor formulations from INNER_SELECT only."""
    if not rows:
        return {"promoted": [], "a0_pr_auc": None, "reason": "no_inner_rows"}
    a0 = [r for r in rows if r["anchor_id"] == "A0" and not r.get("route_on")]
    if not a0:
        raise ValueError("A0 route-off is required as the inner-search reference")
    a0_pr = float(a0[0]["inner_select_pr_auc"])
    a0_f1 = float(a0[0].get("inner_select_f1", 0.0))

    def _key(r: dict[str, Any]) -> tuple:
        return (
            -float(r["inner_select_pr_auc"]),
            -float(r.get("inner_select_f1", 0.0)),
            int(ANCHOR_FORMULATIONS[r["anchor_id"]]["simplicity_rank"]),
            int(bool(r.get("route_on"))),
        )

    ranked = sorted(rows, key=_key)
    promoted: list[dict[str, Any]] = []
    for r in ranked:
        if r["anchor_id"] == "A0" and not r.get("route_on"):
            continue
        pr = float(r["inner_select_pr_auc"])
        simpler = int(ANCHOR_FORMULATIONS[r["anchor_id"]]["simplicity_rank"]) < 0
        beats = pr > a0_pr
        near_and_simpler = (a0_pr - pr) <= margin and simpler
        if not (beats or near_and_simpler):
            continue
        promoted.append(
            {
                "anchor_id": r["anchor_id"],
                "route_on": bool(r.get("route_on")),
                "inner_select_pr_auc": pr,
                "inner_select_f1": float(r.get("inner_select_f1", 0.0)),
                "beats_A0": beats,
                "within_margin_and_simpler": near_and_simpler,
                "condition": f"PROM_{r['anchor_id']}{'_R' if r.get('route_on') else ''}",
            }
        )
        if len(promoted) >= max_n:
            break
    return {
        "a0_pr_auc": a0_pr,
        "a0_f1": a0_f1,
        "ranked": [
            {
                "anchor_id": r["anchor_id"],
                "route_on": bool(r.get("route_on")),
                "inner_select_pr_auc": float(r["inner_select_pr_auc"]),
                "inner_select_f1": float(r.get("inner_select_f1", 0.0)),
            }
            for r in ranked
        ],
        "promoted": promoted,
        "promotion_source": "INNER_SELECT",
        "official_r52_validation_not_used_for_selection": True,
        "max_n": max_n,
        "margin": margin,
    }
