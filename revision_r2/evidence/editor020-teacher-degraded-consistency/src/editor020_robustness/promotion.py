"""Inner promotion freeze. Thresholds and objectives cannot change after this file is written."""

from __future__ import annotations

from typing import Any

from .constants import ARCH_SPECS, CLEAN_PRESERVATION_MARGIN, OBJECTIVES
from .safety import Editor020ProtocolError


def _row(rows: list[dict[str, Any]], arch: str, objective: str) -> dict[str, Any]:
    key = f"{arch}-{objective}"
    for row in rows:
        if str(row["condition"]) == key:
            return row
    raise Editor020ProtocolError(f"missing inner row {key}")


def _eligible(cand: dict[str, Any], clean: dict[str, Any]) -> bool:
    clean_ok = float(cand["clean_PR_AUC"]) >= float(clean["clean_PR_AUC"]) - CLEAN_PRESERVATION_MARGIN
    src_ok = float(cand["MEAN_SOURCE_DELTA"]) > float(clean["MEAN_SOURCE_DELTA"])
    noise_ok = float(cand["MEAN_NOISE_RETENTION"]) > float(clean["MEAN_NOISE_RETENTION"])
    return bool(clean_ok and src_ok and noise_ok)


def _better(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Prefer greater source improvement, then noise, then simpler objective."""
    da = float(a["source_improvement"])
    db = float(b["source_improvement"])
    if da != db:
        return da > db
    na = float(a["noise_improvement"])
    nb = float(b["noise_improvement"])
    if na != nb:
        return na > nb
    return int(OBJECTIVES[a["objective"]]["simplicity_rank"]) < int(OBJECTIVES[b["objective"]]["simplicity_rank"])


def decide_promotions(inner_rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_arch: dict[str, dict[str, Any]] = {}
    promoted: dict[str, Any] = {}
    for arch, spec in ARCH_SPECS.items():
        clean = _row(inner_rows, arch, "R0")
        cands = []
        for obj in spec["objectives"]:
            if obj == "R0":
                continue
            row = _row(inner_rows, arch, obj)
            rec = {
                "arch": arch,
                "objective": obj,
                "condition": f"{arch}-{obj}",
                "clean_PR_AUC": float(row["clean_PR_AUC"]),
                "MEAN_SOURCE_DELTA": float(row["MEAN_SOURCE_DELTA"]),
                "WORST_SOURCE_DELTA": float(row["WORST_SOURCE_DELTA"]),
                "MEAN_NOISE_RETENTION": float(row["MEAN_NOISE_RETENTION"]),
                "matched_clean_PR_AUC": float(clean["clean_PR_AUC"]),
                "source_improvement": float(row["MEAN_SOURCE_DELTA"]) - float(clean["MEAN_SOURCE_DELTA"]),
                "noise_improvement": float(row["MEAN_NOISE_RETENTION"]) - float(clean["MEAN_NOISE_RETENTION"]),
                "clean_delta": float(row["clean_PR_AUC"]) - float(clean["clean_PR_AUC"]),
                "eligible": _eligible(row, clean),
            }
            cands.append(rec)
        chosen = None
        eligible = [c for c in cands if c["eligible"]]
        if arch == "TA2":
            r3 = next((c for c in eligible if c["objective"] == "R3"), None)
            r4 = next((c for c in eligible if c["objective"] == "R4"), None)
            if r3 is not None and r4 is not None:
                r4_beats_r3_both = (
                    float(r4["MEAN_SOURCE_DELTA"]) > float(r3["MEAN_SOURCE_DELTA"])
                    and float(r4["MEAN_NOISE_RETENTION"]) > float(r3["MEAN_NOISE_RETENTION"])
                )
                chosen = r4 if r4_beats_r3_both else r3
                remaining = [c for c in eligible if c["objective"] not in {"R3", "R4"}]
                pool = remaining + [chosen]
            else:
                pool = eligible
                chosen = None
            if chosen is None and pool:
                chosen = pool[0]
                for cand in pool[1:]:
                    if _better(cand, chosen):
                        chosen = cand
        else:
            if eligible:
                chosen = eligible[0]
                for cand in eligible[1:]:
                    if _better(cand, chosen):
                        chosen = cand
        by_arch[arch] = {
            "clean": {
                "condition": f"{arch}-R0",
                "clean_PR_AUC": float(clean["clean_PR_AUC"]),
                "MEAN_SOURCE_DELTA": float(clean["MEAN_SOURCE_DELTA"]),
                "MEAN_NOISE_RETENTION": float(clean["MEAN_NOISE_RETENTION"]),
            },
            "candidates": cands,
            "promoted": chosen,
        }
        promoted[arch] = None if chosen is None else chosen["condition"]

    return {
        "promoted": promoted,
        "promoted_names": [v for v in promoted.values() if v is not None],
        "by_arch": by_arch,
        "clean_preservation_margin": CLEAN_PRESERVATION_MARGIN,
        "weighted_robustness_score_invented": False,
        "max_one_strategy_per_architecture": True,
        "ta2_r4_requires_both_families_over_r3": True,
        "selection_order": ["source_improvement", "noise_improvement", "simpler_objective"],
        "objectives_and_weights_frozen": True,
    }
