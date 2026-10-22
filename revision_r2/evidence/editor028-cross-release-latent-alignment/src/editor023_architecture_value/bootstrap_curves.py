"""User-cluster bootstrap for EDITOR-023 curve and stability contrasts.

Sampling unit is the validation user. Windows are never resampled independently.
Three seeds are repeated realisations, not independent experimental units.
"""

from __future__ import annotations

from typing import Any, Callable

import numpy as np
from sklearn.metrics import average_precision_score

from editor012_rescue.metrics import sigmoid
from editor017_robustness.bootstrap_family import user_cluster_stat

from .constants import (
    BOOTSTRAP_RESAMPLES,
    BOOTSTRAP_SEED,
    NOISE_LEVELS,
    PRIMARY_MODELS,
    PRIMARY_SEEDS,
    SOURCE_CHANNELS,
    SOURCE_DEGRADATION_LEVELS,
)
from .curves import noise_aurc, source_channel_aurc


def _pr_auc(y: np.ndarray, logits: np.ndarray) -> float:
    y = np.asarray(y).astype(int).ravel()
    p = sigmoid(np.asarray(logits, dtype=np.float64).ravel())
    if len(np.unique(y)) < 2:
        return float("nan")
    return float(average_precision_score(y, p))


def _ci_record(draws: np.ndarray, contrast: str) -> dict[str, Any]:
    arr = np.asarray(draws, dtype=np.float64)
    lo = float(np.nanpercentile(arr, 2.5))
    hi = float(np.nanpercentile(arr, 97.5))
    return {
        "cluster": "user",
        "n_valid_resamples": int(np.isfinite(arr).sum()),
        "seed": BOOTSTRAP_SEED,
        "sampling_unit": "validation user",
        "statistic": contrast,
        "mean": float(np.nanmean(arr)),
        "ci95": [lo, hi],
        "ci_excludes_zero": bool(hi < 0 or lo > 0),
        "ci_lower_bound_gt_0": bool(lo > 0),
        "windows_not_independent": True,
        "three_seeds_are_not_independent_experimental_units": True,
    }


def bootstrap_metric_bundle(
    users: np.ndarray,
    y: np.ndarray,
    stat_fn: Callable[[np.ndarray, np.ndarray], dict[str, float]],
    *,
    n_valid: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, dict[str, Any]]:
    """One user-resampling loop; ``stat_fn`` returns a dict of scalars per replicate."""
    y = np.asarray(y).astype(int).ravel()
    users = np.asarray(users).astype(str)
    unique = np.unique(users)
    index = {u: np.flatnonzero(users == u) for u in unique}
    rng = np.random.default_rng(seed)
    buckets: dict[str, list[float]] = {}
    attempted = 0
    n_ok = 0
    while n_ok < n_valid:
        attempted += 1
        if attempted > n_valid * 50:
            break
        chosen = rng.choice(unique, size=len(unique), replace=True)
        sl = np.concatenate([index[str(u)] for u in chosen])
        yb = y[sl]
        if len(np.unique(yb)) < 2:
            continue
        rec = stat_fn(sl, yb)
        if not rec or any(not np.isfinite(v) for v in rec.values()):
            continue
        for k, v in rec.items():
            buckets.setdefault(k, []).append(float(v))
        n_ok += 1
    out = {k: _ci_record(np.asarray(vs), k) for k, vs in buckets.items()}
    for rec in out.values():
        rec["n_attempted_draws"] = attempted
        rec["n_users"] = int(len(unique))
    return out


def _source_aurc_from_logits(
    yb: np.ndarray,
    sl: np.ndarray,
    clean_logits: np.ndarray,
    source_logits: dict[str, dict[float, np.ndarray]],
) -> float:
    pr_clean = _pr_auc(yb, clean_logits[sl])
    channel_vals = []
    for src in SOURCE_CHANNELS:
        rets = {0.0: 1.0}
        for d in SOURCE_DEGRADATION_LEVELS:
            if float(d) == 0.0:
                continue
            rets[float(d)] = _pr_auc(yb, source_logits[src][float(d)][sl]) / pr_clean if pr_clean else float("nan")
        channel_vals.append(source_channel_aurc(rets))
    return float(np.mean(channel_vals))


def _noise_aurc_from_logits(
    yb: np.ndarray,
    sl: np.ndarray,
    clean_logits: np.ndarray,
    noise_logits: dict[float, np.ndarray],
) -> float:
    pr_clean = _pr_auc(yb, clean_logits[sl])
    rets = {0.0: 1.0}
    for lvl in NOISE_LEVELS:
        if float(lvl) == 0.0:
            continue
        rets[float(lvl)] = _pr_auc(yb, noise_logits[float(lvl)][sl]) / pr_clean if pr_clean else float("nan")
    return noise_aurc(rets)


def aurc_bootstrap(
    y: np.ndarray,
    users: np.ndarray,
    clean: dict[str, dict[int, np.ndarray]],
    source: dict[str, dict[int, dict[str, dict[float, np.ndarray]]]],
    noise: dict[str, dict[int, dict[float, np.ndarray]]],
) -> dict[str, Any]:
    """Bootstrap SOURCE_AURC and NOISE_AURC contrasts. Mean across seeds inside each replicate."""

    def stat(sl: np.ndarray, yb: np.ndarray) -> dict[str, float]:
        src_vals = {alias: [] for alias in PRIMARY_MODELS}
        noise_vals = {alias: [] for alias in PRIMARY_MODELS}
        clean_pr = {alias: [] for alias in PRIMARY_MODELS}
        for seed in PRIMARY_SEEDS:
            for alias in PRIMARY_MODELS:
                clean_pr[alias].append(_pr_auc(yb, clean[alias][seed][sl]))
                src_vals[alias].append(_source_aurc_from_logits(yb, sl, clean[alias][seed], source[alias][seed]))
                noise_vals[alias].append(_noise_aurc_from_logits(yb, sl, clean[alias][seed], noise[alias][seed]))
        src_mean = {a: float(np.mean(src_vals[a])) for a in PRIMARY_MODELS}
        noise_mean = {a: float(np.mean(noise_vals[a])) for a in PRIMARY_MODELS}
        clean_mean = {a: float(np.mean(clean_pr[a])) for a in PRIMARY_MODELS}
        return {
            "SOURCE_AURC_C2": src_mean["C2-OPT"],
            "SOURCE_AURC_F10": src_mean["F10"],
            "SOURCE_AURC_TA2": src_mean["TA2"],
            "SOURCE_AURC_L1": src_mean["L1"],
            "NOISE_AURC_C2": noise_mean["C2-OPT"],
            "NOISE_AURC_F10": noise_mean["F10"],
            "NOISE_AURC_TA2": noise_mean["TA2"],
            "NOISE_AURC_L1": noise_mean["L1"],
            "F10_minus_C2_SOURCE_AURC": src_mean["F10"] - src_mean["C2-OPT"],
            "TA2_minus_C2_SOURCE_AURC": src_mean["TA2"] - src_mean["C2-OPT"],
            "TA2_minus_F10_SOURCE_AURC": src_mean["TA2"] - src_mean["F10"],
            "TA2_minus_L1_SOURCE_AURC": src_mean["TA2"] - src_mean["L1"],
            "F10_minus_C2_NOISE_AURC": noise_mean["F10"] - noise_mean["C2-OPT"],
            "TA2_minus_C2_NOISE_AURC": noise_mean["TA2"] - noise_mean["C2-OPT"],
            "TA2_minus_F10_NOISE_AURC": noise_mean["TA2"] - noise_mean["F10"],
            "TA2_minus_L1_NOISE_AURC": noise_mean["TA2"] - noise_mean["L1"],
            "TA2_minus_C2_CLEAN_PR_AUC": clean_mean["TA2"] - clean_mean["C2-OPT"],
            "F10_minus_C2_CLEAN_PR_AUC": clean_mean["F10"] - clean_mean["C2-OPT"],
            "TA2_minus_F10_CLEAN_PR_AUC": clean_mean["TA2"] - clean_mean["F10"],
            "TA2_minus_L1_CLEAN_PR_AUC": clean_mean["TA2"] - clean_mean["L1"],
        }

    return bootstrap_metric_bundle(users, y, stat)


def scalar_mean_contrast_bootstrap(
    users: np.ndarray,
    y: np.ndarray,
    values_a: list[np.ndarray],
    values_b: list[np.ndarray],
    *,
    contrast: str,
    higher_is_better: bool,
) -> dict[str, Any]:
    """Mean-across-seeds contrast of a per-sequence scalar (B - A)."""

    def stat(sl: np.ndarray, yb: np.ndarray) -> float:
        seed_stats = []
        for a, b in zip(values_a, values_b):
            seed_stats.append(float(np.nanmean(b[sl]) - np.nanmean(a[sl])))
        return float(np.mean(seed_stats))

    rec = user_cluster_stat(users, y, stat, contrast=contrast)
    lo, hi = rec["ci95"]
    rec["ci_excludes_zero"] = bool(hi < 0 or lo > 0)
    rec["ci_lower_bound_gt_0"] = bool(lo > 0)
    rec["direction_favours_B"] = bool(rec["mean"] > 0) if higher_is_better else bool(rec["mean"] < 0)
    rec["bootstrap_valid"] = True
    rec["note"] = "per-sequence scalar admits the existing user-cluster implementation"
    return rec
