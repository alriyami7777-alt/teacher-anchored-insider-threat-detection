"""Causal user-relative 13-feature transform. No labels. No future days. No other users."""

from __future__ import annotations

from typing import Sequence

import numpy as np

from .constants import (
    BINARY_FEATURES,
    FEATURE_ORDER,
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


def causal_user_relative_daily(
    raw: np.ndarray,
    dates: np.ndarray | None = None,
    *,
    lookback_days: int = USER_RELATIVE_LOOKBACK_DAYS,
    feature_order: Sequence[str] = FEATURE_ORDER,
) -> np.ndarray:
    """Transform one user's chronological daily matrix.

    Volume (7): log1p(x_t) - median(log1p(x_tau) for t-L <= tau < t)
    Binary (6): x_t - mean(x_tau for t-L <= tau < t)
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
    if dates is None:
        daynum = np.arange(t_len, dtype=np.int64)
    else:
        daynum = _daynum(dates)
        if daynum.shape[0] != t_len:
            raise ValueError("dates length must match daily rows")
        order = np.argsort(daynum, kind="mergesort")
        if not np.all(order == np.arange(t_len)):
            raise ValueError("daily rows must be sorted by calendar date")
        if np.any(np.diff(daynum) <= 0):
            raise ValueError("calendar dates must be strictly increasing")
    for t in range(t_len):
        lo = int(daynum[t] - int(lookback_days))
        left = int(np.searchsorted(daynum, lo, side="left"))
        right = t
        if left >= right:
            continue
        past_log = logx[left:right]
        past_bin = binary[left:right]
        out[t, vol_idx] = logx[t] - np.median(past_log, axis=0)
        out[t, bin_idx] = binary[t] - past_bin.mean(axis=0)
    return out


def causal_user_relative_panel(
    raw: np.ndarray,
    dates: np.ndarray | None = None,
    *,
    lookback_days: int = USER_RELATIVE_LOOKBACK_DAYS,
    feature_order: Sequence[str] = FEATURE_ORDER,
) -> np.ndarray:
    """Transform a (n_users, n_days, 13) dense calendar independently per user."""
    panel = np.asarray(raw, dtype=np.float64)
    if panel.ndim != 3:
        raise ValueError(f"expected (U, T, F), got {panel.shape}")
    out = np.zeros_like(panel, dtype=np.float64)
    for u in range(panel.shape[0]):
        out[u] = causal_user_relative_daily(
            panel[u],
            dates=dates,
            lookback_days=lookback_days,
            feature_order=feature_order,
        )
    return out


def representation_identity() -> dict[str, object]:
    return {
        "name": "causal_user_relative_log_deviations",
        "lookback_calendar_days": USER_RELATIVE_LOOKBACK_DAYS,
        "volume_rule": "log1p(current) - median(log1p(past same-user calendar days))",
        "binary_rule": "current - mean(past same-user calendar days)",
        "cold_start": 0.0,
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
