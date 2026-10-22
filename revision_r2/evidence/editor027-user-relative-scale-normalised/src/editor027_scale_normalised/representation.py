"""Causal user-relative scale-normalised 13-feature transform.

No labels. No future days. No other users. No target-wide fitting.
"""

from __future__ import annotations

from typing import Sequence

import numpy as np

from .constants import (
    BINARY_FEATURES,
    FEATURE_ORDER,
    FLOOR_FALLBACK,
    MAD_SCALE_CONSTANT,
    USER_RELATIVE_LOOKBACK_DAYS,
    VOLUME_FEATURES,
)

N_VOLUME = len(VOLUME_FEATURES)
N_BINARY = len(BINARY_FEATURES)


def _daynum(dates: np.ndarray) -> np.ndarray:
    d = np.asarray(dates)
    if np.issubdtype(d.dtype, np.datetime64):
        return d.astype("datetime64[D]").astype(np.int64)
    text = d.astype(str)
    return np.array([np.datetime64(t[:10], "D").astype(np.int64) for t in text], dtype=np.int64)


def _calendar(dates: np.ndarray | None, t_len: int) -> np.ndarray:
    if dates is None:
        return np.arange(t_len, dtype=np.int64)
    daynum = _daynum(dates)
    if daynum.shape[0] != t_len:
        raise ValueError("dates length must match daily rows")
    order = np.argsort(daynum, kind="mergesort")
    if not np.all(order == np.arange(t_len)):
        raise ValueError("daily rows must be sorted by calendar date")
    if t_len > 1 and np.any(np.diff(daynum) <= 0):
        raise ValueError("calendar dates must be strictly increasing")
    return daynum


def robust_centre_and_scale(past_log: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Causal median and 1.4826 × MAD on log1p volume history."""
    centre = np.median(past_log, axis=0)
    mad = np.median(np.abs(past_log - centre), axis=0)
    return centre, MAD_SCALE_CONSTANT * mad


def jeffreys_bernoulli_residual(current: np.ndarray, past_bin: np.ndarray) -> np.ndarray:
    """Standardised causal Bernoulli residual with Jeffreys smoothing."""
    n = float(past_bin.shape[0])
    k = past_bin.sum(axis=0)
    p_hat = (k + 0.5) / (n + 1.0)
    denom = np.sqrt(p_hat * (1.0 - p_hat))
    return (current - p_hat) / denom


def causal_volume_scales_daily(
    raw: np.ndarray,
    dates: np.ndarray | None = None,
    *,
    lookback_days: int = USER_RELATIVE_LOOKBACK_DAYS,
    feature_order: Sequence[str] = FEATURE_ORDER,
) -> np.ndarray:
    """Return (T, 7) causal MAD scales. NaN when there is no previous history."""
    x = np.asarray(raw, dtype=np.float64)
    if x.ndim != 2 or x.shape[1] != len(feature_order):
        raise ValueError(f"expected (T, {len(feature_order)}), got {x.shape}")
    t_len = int(x.shape[0])
    scales = np.full((t_len, N_VOLUME), np.nan, dtype=np.float64)
    if t_len == 0:
        return scales
    names = list(feature_order)
    vol_idx = [names.index(f) for f in VOLUME_FEATURES]
    logx = np.log1p(np.clip(x[:, vol_idx], 0.0, None))
    daynum = _calendar(dates, t_len)
    for t in range(t_len):
        lo = int(daynum[t] - int(lookback_days))
        left = int(np.searchsorted(daynum, lo, side="left"))
        right = t
        if left >= right:
            continue
        _, scale = robust_centre_and_scale(logx[left:right])
        scales[t] = scale
    return scales


def causal_scale_normalised_daily(
    raw: np.ndarray,
    dates: np.ndarray | None = None,
    *,
    lookback_days: int = USER_RELATIVE_LOOKBACK_DAYS,
    feature_order: Sequence[str] = FEATURE_ORDER,
    scale_floors: np.ndarray | Sequence[float] | None = None,
) -> np.ndarray:
    """Transform one user's chronological daily matrix.

    Volume (7): (log1p(x_t) - median(log1p past)) / max(1.4826 * MAD, floor)
    Binary (6): (x_t - Jeffreys p_hat) / sqrt(p_hat * (1 - p_hat))
    No past days -> 0. Labels never enter. Other users never enter.
    """
    x = np.asarray(raw, dtype=np.float64)
    if x.ndim != 2:
        raise ValueError(f"expected (T, F) daily matrix, got {x.shape}")
    if x.shape[1] != len(feature_order):
        raise ValueError(f"expected F={len(feature_order)}, got {x.shape[1]}")
    t_len = int(x.shape[0])
    out = np.zeros((t_len, x.shape[1]), dtype=np.float64)
    if t_len == 0:
        return out
    names = list(feature_order)
    vol_idx = [names.index(f) for f in VOLUME_FEATURES]
    bin_idx = [names.index(f) for f in BINARY_FEATURES]
    vol = np.clip(x[:, vol_idx], 0.0, None)
    logx = np.log1p(vol)
    binary = x[:, bin_idx]
    floors = np.asarray(
        scale_floors if scale_floors is not None else np.full(N_VOLUME, FLOOR_FALLBACK),
        dtype=np.float64,
    )
    if floors.shape != (N_VOLUME,):
        raise ValueError(f"scale_floors must have shape ({N_VOLUME},)")
    daynum = _calendar(dates, t_len)
    for t in range(t_len):
        lo = int(daynum[t] - int(lookback_days))
        left = int(np.searchsorted(daynum, lo, side="left"))
        right = t
        if left >= right:
            continue
        past_log = logx[left:right]
        centre, scale = robust_centre_and_scale(past_log)
        denom = np.maximum(scale, floors)
        out[t, vol_idx] = (logx[t] - centre) / denom
        out[t, bin_idx] = jeffreys_bernoulli_residual(binary[t], binary[left:right])
    return out


def causal_scale_normalised_panel(
    raw: np.ndarray,
    dates: np.ndarray | None = None,
    *,
    lookback_days: int = USER_RELATIVE_LOOKBACK_DAYS,
    feature_order: Sequence[str] = FEATURE_ORDER,
    scale_floors: np.ndarray | Sequence[float] | None = None,
) -> np.ndarray:
    """Transform a (n_users, n_days, 13) dense calendar independently per user."""
    panel = np.asarray(raw, dtype=np.float64)
    if panel.ndim != 3:
        raise ValueError(f"expected (U, T, F), got {panel.shape}")
    out = np.zeros_like(panel, dtype=np.float64)
    for u in range(panel.shape[0]):
        out[u] = causal_scale_normalised_daily(
            panel[u],
            dates=dates,
            lookback_days=lookback_days,
            feature_order=feature_order,
            scale_floors=scale_floors,
        )
    return out


def representation_identity() -> dict[str, object]:
    return {
        "name": "causal_user_relative_scale_normalised",
        "SCALE": "causal user-relative scale-normalised representation",
        "lookback_calendar_days": USER_RELATIVE_LOOKBACK_DAYS,
        "volume_rule": (
            "(log1p(current) - causal median(log1p past)) / "
            "max(1.4826 * causal MAD, source-only 25th-percentile floor)"
        ),
        "binary_rule": (
            "(current - Jeffreys p_hat) / sqrt(p_hat * (1 - p_hat)), "
            "p_hat = (k + 0.5) / (n + 1)"
        ),
        "MAD_definition": "median(|y - median(y)|) over causal same-user history",
        "MAD_SCALE_CONSTANT": MAD_SCALE_CONSTANT,
        "SCALE_FLOOR_PERCENTILE": 0.25,
        "SCALE_FLOOR_SOURCE": "CERT r5.2 TRAIN ONLY",
        "FLOOR_FALLBACK": FLOOR_FALLBACK,
        "cold_start": 0.0,
        "clipping": "NO",
        "target_quantile_mapping": "NO",
        "target_mean_alignment": "NO",
        "target_variance_alignment": "NO",
        "future_days": "PROHIBITED",
        "other_users": "PROHIBITED",
        "labels": "PROHIBITED",
        "release_level_target_statistic": "PROHIBITED",
        "output_dim": 13,
        "no_appended_baseline_statistics": True,
        "volume_features": list(VOLUME_FEATURES),
        "binary_features": list(BINARY_FEATURES),
        "feature_order": list(FEATURE_ORDER),
        "inactive_days_in_calendar_history": True,
    }
