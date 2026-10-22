"""Pure feature-shift, PSI, and support-bound statistics. Bins/bounds from r5.2 TRAIN only."""

from __future__ import annotations

from typing import Any, Sequence

import numpy as np

from .constants import (
    BINARY_FEATURES,
    COUNT_FEATURES,
    FEATURE_ORDER,
    PSI_FLOOR,
    QUANTILES,
    SUPPORT_CLIP_HIGH_QUANTILE,
    SUPPORT_CLIP_LOW_QUANTILE,
)


def column_stats(x: np.ndarray) -> dict[str, float]:
    v = np.asarray(x, dtype=np.float64).ravel()
    v = v[np.isfinite(v)]
    if v.size == 0:
        return {"n": 0.0, "mean": float("nan"), "std": float("nan"), "median": float("nan")}
    rec = {
        "n": float(v.size),
        "mean": float(v.mean()),
        "std": float(v.std(ddof=0)),
        "median": float(np.median(v)),
    }
    qs = np.quantile(v, QUANTILES)
    for q, val in zip(QUANTILES, qs):
        rec[f"q{int(round(q * 100)):02d}"] = float(val)
    return rec


def mean_shift_z(mean_target: float, mean_train: float) -> float:
    """Difference of means already expressed in r5.2 TRAIN scaler units."""
    return float(mean_target - mean_train)


def train_decile_edges(train_col: np.ndarray) -> np.ndarray:
    v = np.asarray(train_col, dtype=np.float64).ravel()
    v = v[np.isfinite(v)]
    return np.unique(np.quantile(v, np.linspace(0.0, 1.0, 11)))


def digitize_deciles(values: np.ndarray, edges: np.ndarray) -> np.ndarray:
    v = np.asarray(values, dtype=np.float64).ravel()
    if len(edges) < 2:
        return np.zeros(v.shape[0], dtype=np.int64)
    return np.digitize(v, edges[1:-1], right=True)


def population_stability_index(train_col: np.ndarray, target_col: np.ndarray) -> float:
    edges = train_decile_edges(train_col)
    n_bins = max(len(edges) - 1, 1)
    t_idx = digitize_deciles(train_col, edges)
    a_idx = digitize_deciles(target_col, edges)
    expected = np.bincount(t_idx, minlength=n_bins).astype(np.float64)
    actual = np.bincount(a_idx, minlength=n_bins).astype(np.float64)
    expected = np.clip(expected / max(expected.sum(), 1.0), PSI_FLOOR, 1.0)
    actual = np.clip(actual / max(actual.sum(), 1.0), PSI_FLOOR, 1.0)
    return float(np.sum((actual - expected) * np.log(actual / expected)))


def support_bounds_from_train(train_col: np.ndarray) -> tuple[float, float]:
    v = np.asarray(train_col, dtype=np.float64).ravel()
    v = v[np.isfinite(v)]
    lo = float(np.quantile(v, SUPPORT_CLIP_LOW_QUANTILE))
    hi = float(np.quantile(v, SUPPORT_CLIP_HIGH_QUANTILE))
    return lo, hi


def out_of_support_rate(target_col: np.ndarray, lo: float, hi: float) -> float:
    v = np.asarray(target_col, dtype=np.float64).ravel()
    v = v[np.isfinite(v)]
    if v.size == 0:
        return float("nan")
    return float(np.mean((v < lo) | (v > hi)))


def clip_raw_count_features(
    raw: np.ndarray,
    bounds: dict[str, tuple[float, float]],
    feature_order: Sequence[str] = FEATURE_ORDER,
) -> np.ndarray:
    """Clip count/continuous features only. Binary indicators unchanged. No trainable parameters."""
    out = np.array(raw, dtype=np.float64, copy=True)
    names = list(feature_order)
    for name in COUNT_FEATURES:
        if name not in bounds:
            continue
        j = names.index(name)
        lo, hi = bounds[name]
        out[..., j] = np.clip(out[..., j], lo, hi)
    return out


def binary_rate(raw_col: np.ndarray) -> float:
    v = np.asarray(raw_col, dtype=np.float64).ravel()
    return float(np.mean(v > 0.5))


def inverse_scale(scaled: np.ndarray, mean: np.ndarray, scale: np.ndarray) -> np.ndarray:
    m = np.asarray(mean, dtype=np.float64).reshape((1,) * (scaled.ndim - 1) + (-1,))
    s = np.asarray(scale, dtype=np.float64).reshape(m.shape)
    s = np.where(s == 0.0, 1.0, s)
    return np.asarray(scaled, dtype=np.float64) * s + m


def apply_scale(raw: np.ndarray, mean: np.ndarray, scale: np.ndarray) -> np.ndarray:
    m = np.asarray(mean, dtype=np.float64).reshape((1,) * (raw.ndim - 1) + (-1,))
    s = np.asarray(scale, dtype=np.float64).reshape(m.shape)
    s = np.where(s == 0.0, 1.0, s)
    return ((np.asarray(raw, dtype=np.float64) - m) / s).astype(np.float32)


def shift_rows(
    *,
    r52_train_scaled: np.ndarray,
    r52_all_scaled: np.ndarray | None,
    r61_scaled: np.ndarray,
    r52_train_raw: np.ndarray,
    r61_raw: np.ndarray,
    feature_order: Sequence[str] = FEATURE_ORDER,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    names = list(feature_order)
    for j, name in enumerate(names):
        tr_s = r52_train_scaled[:, j]
        tg_s = r61_scaled[:, j]
        tr_stats = column_stats(tr_s)
        tg_stats = column_stats(tg_s)
        lo, hi = support_bounds_from_train(r52_train_raw[:, j])
        rec: dict[str, Any] = {
            "feature": name,
            "r52_mean": tr_stats["mean"],
            "r61_mean": tg_stats["mean"],
            "r52_standard_deviation": tr_stats["std"],
            "r61_standard_deviation": tg_stats["std"],
            "r52_median": tr_stats["median"],
            "r61_median": tg_stats["median"],
            "MEAN_SHIFT_Z": mean_shift_z(tg_stats["mean"], tr_stats["mean"]),
            "PSI_R61_VS_R52": population_stability_index(tr_s, tg_s),
            "support_lo_raw": lo,
            "support_hi_raw": hi,
            "out_of_support_rate": out_of_support_rate(r61_raw[:, j], lo, hi),
            "is_binary": name in BINARY_FEATURES,
            "is_count": name in COUNT_FEATURES,
            "bins_fitted_from": "R52_TRAIN",
            "oos_bounds_fitted_from": "R52_TRAIN",
        }
        for q in (1, 5, 25, 75, 95, 99):
            rec[f"r52_q{q:02d}"] = tr_stats[f"q{q:02d}"]
            rec[f"r61_q{q:02d}"] = tg_stats[f"q{q:02d}"]
        if r52_all_scaled is not None:
            all_stats = column_stats(r52_all_scaled[:, j])
            rec["r52_all_userdays_mean"] = all_stats["mean"]
        if name in BINARY_FEATURES:
            rec["r52_binary_rate"] = binary_rate(r52_train_raw[:, j])
            rec["r61_binary_rate"] = binary_rate(r61_raw[:, j])
            rec["binary_rate_abs_diff"] = abs(rec["r61_binary_rate"] - rec["r52_binary_rate"])
        else:
            rec["binary_rate_abs_diff"] = 0.0
        rows.append(rec)
    severity = []
    for rec in rows:
        severity.append(
            max(
                abs(float(rec["MEAN_SHIFT_Z"])),
                float(rec["PSI_R61_VS_R52"]),
                float(rec["out_of_support_rate"]),
                float(rec.get("binary_rate_abs_diff") or 0.0),
            )
        )
    order = np.argsort(-np.asarray(severity))
    for rank, i in enumerate(order, start=1):
        rows[int(i)]["shift_severity_rank"] = int(rank)
    return rows


def pearson_corr(a: Sequence[float], b: Sequence[float]) -> float:
    x = np.asarray(a, dtype=np.float64)
    y = np.asarray(b, dtype=np.float64)
    if x.size < 2 or y.size < 2:
        return float("nan")
    if np.std(x) == 0 or np.std(y) == 0:
        return float("nan")
    return float(np.corrcoef(x, y)[0, 1])
