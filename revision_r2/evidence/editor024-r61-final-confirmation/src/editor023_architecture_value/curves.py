"""Retention curves, AURC, and descriptive failure profiles. Frozen before results."""

from __future__ import annotations

from typing import Any

import numpy as np

from .constants import (
    NOISE_LEVELS,
    NOISE_SIGMA_MAX,
    NOISE_SIGMA_MIN,
    PRIMARY_MODELS,
    PRIMARY_SEEDS,
    RETENTION_THRESHOLDS,
    SOURCE_CHANNELS,
    SOURCE_DEGRADATION_LEVELS,
)


def trapz(y: np.ndarray, x: np.ndarray) -> float:
    y = np.asarray(y, dtype=np.float64)
    x = np.asarray(x, dtype=np.float64)
    if hasattr(np, "trapezoid"):
        return float(np.trapezoid(y, x))
    return float(np.trapz(y, x))


def retention(pr_auc: float, pr_auc_clean: float) -> float:
    if not np.isfinite(pr_auc_clean) or pr_auc_clean == 0.0:
        return float("nan")
    return float(pr_auc / pr_auc_clean)


def source_channel_aurc(retentions: dict[float, float]) -> float:
    xs = np.asarray(SOURCE_DEGRADATION_LEVELS, dtype=np.float64)
    ys = np.asarray([retentions[float(d)] for d in SOURCE_DEGRADATION_LEVELS], dtype=np.float64)
    return trapz(ys, xs)


def noise_aurc(retentions: dict[float, float]) -> float:
    xs = np.asarray(NOISE_LEVELS, dtype=np.float64)
    ys = np.asarray([retentions[float(s)] for s in NOISE_LEVELS], dtype=np.float64)
    area = trapz(ys, xs)
    width = float(NOISE_SIGMA_MAX - NOISE_SIGMA_MIN)
    if width <= 0:
        return float("nan")
    return float(area / width)


def first_crossing(severities: tuple[float, ...] | list[float], retentions: list[float], threshold: float) -> float | None:
    for sev, ret in zip(severities, retentions):
        if float(sev) == 0.0:
            continue
        if float(ret) < float(threshold):
            return float(sev)
    return None


def mean_across_seeds(values: dict[int, float]) -> float:
    return float(np.mean([values[s] for s in PRIMARY_SEEDS]))


def seed_direction(per_seed_delta: dict[int, float], *, higher_is_better: bool = True) -> dict[str, Any]:
    fav = []
    for seed in PRIMARY_SEEDS:
        d = per_seed_delta[seed]
        fav.append(bool(d > 0) if higher_is_better else bool(d < 0))
    n = int(sum(fav))
    return {
        "favourable_seeds": n,
        "n_primary_seeds": 3,
        "fraction": f"{n}/3",
        "by_seed": {str(s): bool(v) for s, v in zip(PRIMARY_SEEDS, fav)},
        "unfavourable_seeds_retained": True,
    }


def failure_profile(
    source_retention_by_channel: dict[str, dict[float, float]],
    noise_retention: dict[float, float],
) -> dict[str, Any]:
    channel_mean = {
        src: float(np.mean([source_retention_by_channel[src][float(d)] for d in SOURCE_DEGRADATION_LEVELS if d > 0]))
        for src in SOURCE_CHANNELS
    }
    ordered = sorted(channel_mean.items(), key=lambda kv: kv[1])
    src_curve_mean = {
        float(d): float(np.mean([source_retention_by_channel[src][float(d)] for src in SOURCE_CHANNELS]))
        for d in SOURCE_DEGRADATION_LEVELS
    }
    src_rets = [src_curve_mean[float(d)] for d in SOURCE_DEGRADATION_LEVELS]
    noise_rets = [noise_retention[float(s)] for s in NOISE_LEVELS]
    return {
        "worst_source": ordered[0][0],
        "second_worst_source": ordered[1][0],
        "worst_source_mean_retention": ordered[0][1],
        "second_worst_source_mean_retention": ordered[1][1],
        "source_retention_first_below_0.90": first_crossing(SOURCE_DEGRADATION_LEVELS, src_rets, 0.90),
        "source_retention_first_below_0.75": first_crossing(SOURCE_DEGRADATION_LEVELS, src_rets, 0.75),
        "noise_retention_first_below_0.90": first_crossing(NOISE_LEVELS, noise_rets, 0.90),
        "noise_retention_first_below_0.75": first_crossing(NOISE_LEVELS, noise_rets, 0.75),
        "thresholds_created_only_on_crossing": True,
        "descriptive_only": True,
    }


def summarise_source_aurc(source_rows: list[dict[str, Any]], clean_pr: dict[str, dict[int, float]]) -> dict[str, Any]:
    out: dict[str, Any] = {"definition": (
        "trapezoidal AURC of retention vs d in {0.00,0.25,0.50,0.75,1.00}; "
        "SOURCE_AURC = equal mean of five source-channel AURCs; higher is better"
    ), "models": {}}
    for alias in PRIMARY_MODELS:
        per_seed = {}
        per_channel_seed: dict[str, dict[int, float]] = {src: {} for src in SOURCE_CHANNELS}
        for seed in PRIMARY_SEEDS:
            channel_aurc = []
            for src in SOURCE_CHANNELS:
                rets = {0.0: 1.0}
                for d in SOURCE_DEGRADATION_LEVELS:
                    if d == 0.0:
                        continue
                    recs = [
                        r
                        for r in source_rows
                        if r["model"] == alias and int(r["seed"]) == seed and r["source"] == src and abs(float(r["degradation"]) - float(d)) < 1e-12
                    ]
                    rets[float(d)] = float(recs[0]["retention_PR_AUC"])
                aurc = source_channel_aurc(rets)
                per_channel_seed[src][seed] = aurc
                channel_aurc.append(aurc)
            per_seed[seed] = float(np.mean(channel_aurc))
        out["models"][alias] = {
            "SOURCE_AURC": mean_across_seeds(per_seed),
            "SOURCE_AURC_by_seed": {str(s): per_seed[s] for s in PRIMARY_SEEDS},
            "AURC_by_channel": {
                src: mean_across_seeds(per_channel_seed[src]) for src in SOURCE_CHANNELS
            },
        }
    out["F10_minus_C2"] = out["models"]["F10"]["SOURCE_AURC"] - out["models"]["C2-OPT"]["SOURCE_AURC"]
    out["TA2_minus_C2"] = out["models"]["TA2"]["SOURCE_AURC"] - out["models"]["C2-OPT"]["SOURCE_AURC"]
    out["TA2_minus_F10"] = out["models"]["TA2"]["SOURCE_AURC"] - out["models"]["F10"]["SOURCE_AURC"]
    out["TA2_minus_L1"] = out["models"]["TA2"]["SOURCE_AURC"] - out["models"]["L1"]["SOURCE_AURC"]
    out["per_seed_deltas"] = {
        "F10_minus_C2": {str(s): out["models"]["F10"]["SOURCE_AURC_by_seed"][str(s)] - out["models"]["C2-OPT"]["SOURCE_AURC_by_seed"][str(s)] for s in PRIMARY_SEEDS},
        "TA2_minus_C2": {str(s): out["models"]["TA2"]["SOURCE_AURC_by_seed"][str(s)] - out["models"]["C2-OPT"]["SOURCE_AURC_by_seed"][str(s)] for s in PRIMARY_SEEDS},
        "TA2_minus_F10": {str(s): out["models"]["TA2"]["SOURCE_AURC_by_seed"][str(s)] - out["models"]["F10"]["SOURCE_AURC_by_seed"][str(s)] for s in PRIMARY_SEEDS},
        "TA2_minus_L1": {str(s): out["models"]["TA2"]["SOURCE_AURC_by_seed"][str(s)] - out["models"]["L1"]["SOURCE_AURC_by_seed"][str(s)] for s in PRIMARY_SEEDS},
    }
    return out


def summarise_noise_aurc(noise_rows: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {"definition": (
        "trapezoidal AURC of retention vs sigma in "
        "{0.00,0.025,0.05,0.075,0.10,0.15,0.20} normalised by interval width 0.20; higher is better"
    ), "models": {}}
    for alias in PRIMARY_MODELS:
        per_seed = {}
        for seed in PRIMARY_SEEDS:
            rets = {0.0: 1.0}
            for lvl in NOISE_LEVELS:
                if float(lvl) == 0.0:
                    continue
                recs = [
                    r
                    for r in noise_rows
                    if r["model"] == alias and int(r["seed"]) == seed and abs(float(r["noise_level"]) - float(lvl)) < 1e-12
                ]
                rets[float(lvl)] = float(recs[0]["retention_PR_AUC"])
            per_seed[seed] = noise_aurc(rets)
        out["models"][alias] = {
            "NOISE_AURC": mean_across_seeds(per_seed),
            "NOISE_AURC_by_seed": {str(s): per_seed[s] for s in PRIMARY_SEEDS},
        }
    out["F10_minus_C2"] = out["models"]["F10"]["NOISE_AURC"] - out["models"]["C2-OPT"]["NOISE_AURC"]
    out["TA2_minus_C2"] = out["models"]["TA2"]["NOISE_AURC"] - out["models"]["C2-OPT"]["NOISE_AURC"]
    out["TA2_minus_F10"] = out["models"]["TA2"]["NOISE_AURC"] - out["models"]["F10"]["NOISE_AURC"]
    out["TA2_minus_L1"] = out["models"]["TA2"]["NOISE_AURC"] - out["models"]["L1"]["NOISE_AURC"]
    out["per_seed_deltas"] = {
        "F10_minus_C2": {str(s): out["models"]["F10"]["NOISE_AURC_by_seed"][str(s)] - out["models"]["C2-OPT"]["NOISE_AURC_by_seed"][str(s)] for s in PRIMARY_SEEDS},
        "TA2_minus_C2": {str(s): out["models"]["TA2"]["NOISE_AURC_by_seed"][str(s)] - out["models"]["C2-OPT"]["NOISE_AURC_by_seed"][str(s)] for s in PRIMARY_SEEDS},
        "TA2_minus_F10": {str(s): out["models"]["TA2"]["NOISE_AURC_by_seed"][str(s)] - out["models"]["F10"]["NOISE_AURC_by_seed"][str(s)] for s in PRIMARY_SEEDS},
        "TA2_minus_L1": {str(s): out["models"]["TA2"]["NOISE_AURC_by_seed"][str(s)] - out["models"]["L1"]["NOISE_AURC_by_seed"][str(s)] for s in PRIMARY_SEEDS},
    }
    return out
