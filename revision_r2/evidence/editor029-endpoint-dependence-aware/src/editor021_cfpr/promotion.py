"""EDITOR-021 INNER_SELECT G1–G5 and official O1–O6 gates. No manual override."""

from __future__ import annotations

from typing import Any

import numpy as np

from .constants import (
    CLEAN_MEAN_MARGIN,
    CLEAN_SEED_MARGIN,
    PRIMARY_SEEDS,
    ROBUSTNESS_CANDIDATES,
    ROBUSTNESS_GAIN,
)


def _mean(xs: list[float]) -> float:
    return float(np.mean(xs)) if xs else float("nan")


def rows_for(rows: list[dict[str, Any]], candidate: str) -> list[dict[str, Any]]:
    found = [r for r in rows if str(r["candidate"]) == candidate]
    return sorted(found, key=lambda r: int(r["seed"]))


def mean_metric(rows: list[dict[str, Any]], candidate: str, key: str) -> float:
    return _mean([float(r[key]) for r in rows_for(rows, candidate)])


def seed_delta(rows: list[dict[str, Any]], cand: str, base: str, seed: int, key: str) -> float:
    a = next(r for r in rows if r["candidate"] == cand and int(r["seed"]) == seed)
    b = next(r for r in rows if r["candidate"] == base and int(r["seed"]) == seed)
    return float(a[key]) - float(b[key])


def evaluate_inner_gates(rows: list[dict[str, Any]], candidate: str) -> dict[str, Any]:
    cfp0 = rows_for(rows, "CFP0")
    cand = rows_for(rows, candidate)
    if len(cfp0) != len(PRIMARY_SEEDS) or len(cand) != len(PRIMARY_SEEDS):
        return {
            "candidate": candidate,
            "eligible": False,
            "reason": "incomplete_three_seed_rows",
            "G1": False,
            "G2": False,
            "G3": False,
            "G4": False,
            "G5": False,
        }
    clean_delta = mean_metric(rows, candidate, "clean_PR_AUC") - mean_metric(rows, "CFP0", "clean_PR_AUC")
    seed_clean = [seed_delta(rows, candidate, "CFP0", s, "clean_PR_AUC") for s in PRIMARY_SEEDS]
    d_source = mean_metric(rows, candidate, "S_source") - mean_metric(rows, "CFP0", "S_source")
    d_noise = mean_metric(rows, candidate, "S_noise") - mean_metric(rows, "CFP0", "S_noise")
    d_comp = mean_metric(rows, candidate, "S_composite") - mean_metric(rows, "CFP0", "S_composite")
    seed_comp = [seed_delta(rows, candidate, "CFP0", s, "S_composite") for s in PRIMARY_SEEDS]
    g1 = clean_delta >= -CLEAN_MEAN_MARGIN
    g2 = all(d >= -CLEAN_SEED_MARGIN for d in seed_clean)
    g3 = d_comp >= ROBUSTNESS_GAIN
    g4 = d_source >= 0.0 and d_noise >= 0.0
    g5 = sum(d > 0.0 for d in seed_comp) >= 2
    return {
        "candidate": candidate,
        "clean_delta": clean_delta,
        "seed_clean_deltas": seed_clean,
        "source_gain": d_source,
        "noise_gain": d_noise,
        "composite_delta": d_comp,
        "seed_composite_deltas": seed_comp,
        "G1": bool(g1),
        "G2": bool(g2),
        "G3": bool(g3),
        "G4": bool(g4),
        "G5": bool(g5),
        "eligible": bool(g1 and g2 and g3 and g4 and g5),
        "mean_S_composite": mean_metric(rows, candidate, "S_composite"),
        "rho": float(next(r for r in cand)["rho"]),
    }


def select_inner_candidate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    packs = [evaluate_inner_gates(rows, name) for name in ROBUSTNESS_CANDIDATES]
    eligible = [p for p in packs if p["eligible"]]
    selected = None
    rule = "none_passed"
    if len(eligible) == 1:
        selected = eligible[0]["candidate"]
        rule = "single_eligible"
    elif len(eligible) > 1:
        eligible_sorted = sorted(eligible, key=lambda p: (-float(p["mean_S_composite"]), float(p["rho"])))
        top = eligible_sorted[0]
        if len(eligible_sorted) > 1:
            second = eligible_sorted[1]
            if abs(float(top["mean_S_composite"]) - float(second["mean_S_composite"])) <= 0.001:
                selected = min(eligible, key=lambda p: float(p["rho"]))["candidate"]
                rule = "tie_smaller_rho"
            else:
                selected = top["candidate"]
                rule = "greatest_S_composite"
        else:
            selected = top["candidate"]
            rule = "greatest_S_composite"
    return {
        "candidates": packs,
        "EDITOR021_SELECTED_CANDIDATE": selected,
        "EDITOR021_INNER_PROMOTION": selected if selected else "NONE",
        "selection_rule": rule,
        "weighted_robustness_score_invented": False,
        "manual_override": False,
    }


def evaluate_cfp0_scaffold(
    cfp0_rows: list[dict[str, Any]],
    starting_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    if len(cfp0_rows) != len(PRIMARY_SEEDS) or len(starting_rows) != len(PRIMARY_SEEDS):
        return {"pass": False, "reason": "incomplete_three_seed_rows"}
    deltas = []
    for seed in PRIMARY_SEEDS:
        a = next(r for r in cfp0_rows if int(r["seed"]) == seed)
        b = next(r for r in starting_rows if int(r["seed"]) == seed)
        deltas.append(float(a["clean_PR_AUC"]) - float(b["clean_PR_AUC"]))
    mean_delta = _mean(deltas)
    ok = mean_delta >= -CLEAN_MEAN_MARGIN and all(d >= -CLEAN_SEED_MARGIN for d in deltas)
    return {
        "pass": bool(ok),
        "mean_clean_delta_vs_starting_ta2": mean_delta,
        "seed_clean_deltas_vs_starting_ta2": deltas,
        "G_mean": mean_delta >= -CLEAN_MEAN_MARGIN,
        "G_seed": all(d >= -CLEAN_SEED_MARGIN for d in deltas),
        "reference": "starting TA2 (F11) scored on INNER_SELECT; EDITOR-020 TA2-R0 not rerun",
    }


def evaluate_official_gates(
    *,
    clean_delta: float,
    clean_ci_lo: float,
    composite_delta: float,
    source_gain: float,
    noise_gain: float,
    composite_ci_lo: float,
    n_seeds_positive_composite: int,
) -> dict[str, Any]:
    o1 = clean_delta >= -CLEAN_MEAN_MARGIN
    o2 = clean_ci_lo >= -CLEAN_SEED_MARGIN
    o3 = composite_delta >= ROBUSTNESS_GAIN
    o4 = source_gain > 0.0 and noise_gain > 0.0
    o5 = composite_ci_lo > 0.0
    o6 = n_seeds_positive_composite >= 2
    promoted = bool(o1 and o2 and o3 and o4 and o5 and o6)
    clean_ok = bool(o1 and o2)
    robust_ok = bool(o3 and o4 and o5 and o6)
    if promoted:
        ruling = {
            "EDITOR021_TRAINING_TIME_ROBUSTNESS_HARDENING": "SUPPORTED",
            "EDITOR021_CLEAN_FUNCTION_PRESERVATION": "SUPPORTED",
            "EDITOR021_PROMOTION": "SUPPORTED",
            "CURRENT_PAPER_MODEL": "TA2-RP",
        }
    elif robust_ok and not clean_ok:
        ruling = {
            "EDITOR021_TRAINING_TIME_ROBUSTNESS_HARDENING": "ROBUSTNESS_GAIN_WITH_CLEAN_TRADEOFF",
            "EDITOR021_CLEAN_FUNCTION_PRESERVATION": "NOT_SUPPORTED",
            "EDITOR021_PROMOTION": "NO",
            "CURRENT_PAPER_MODEL": "TA2",
        }
    elif clean_ok and not robust_ok:
        ruling = {
            "EDITOR021_TRAINING_TIME_ROBUSTNESS_HARDENING": "NOT_SUPPORTED",
            "EDITOR021_CLEAN_FUNCTION_PRESERVATION": "SUPPORTED",
            "EDITOR021_PROMOTION": "NO",
            "CURRENT_PAPER_MODEL": "TA2",
        }
    else:
        ruling = {
            "EDITOR021_TRAINING_TIME_ROBUSTNESS_HARDENING": "NOT_SUPPORTED",
            "EDITOR021_CLEAN_FUNCTION_PRESERVATION": "NOT_SUPPORTED",
            "EDITOR021_PROMOTION": "NO",
            "CURRENT_PAPER_MODEL": "TA2",
        }
    return {
        "O1": bool(o1),
        "O2": bool(o2),
        "O3": bool(o3),
        "O4": bool(o4),
        "O5": bool(o5),
        "O6": bool(o6),
        "promoted": promoted,
        **ruling,
        "clean_delta": clean_delta,
        "clean_ci_lo": clean_ci_lo,
        "composite_delta": composite_delta,
        "source_gain": source_gain,
        "noise_gain": noise_gain,
        "composite_ci_lo": composite_ci_lo,
        "n_seeds_positive_composite": n_seeds_positive_composite,
    }
