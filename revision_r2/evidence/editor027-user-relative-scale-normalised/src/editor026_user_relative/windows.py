"""Rebuild frozen 20-day windows on the user-relative representation. Split rules unchanged."""

from __future__ import annotations

from typing import Any

import numpy as np

from .constants import FEATURE_ORDER, SEQUENCE_LENGTH_LOCKED
from .safety import Editor026Blocked


def gather_windows(
    *,
    scaled_by_user: dict[str, np.ndarray],
    dates_by_user: dict[str, np.ndarray],
    users: np.ndarray,
    start_dates: np.ndarray,
    sequence_length: int = SEQUENCE_LENGTH_LOCKED,
) -> np.ndarray:
    """Gather frozen start-date windows. No cross-boundary window construction."""
    n = int(len(users))
    f = len(FEATURE_ORDER)
    x = np.empty((n, sequence_length, f), dtype=np.float32)
    users = np.asarray(users).astype(str)
    starts = np.asarray(start_dates).astype(str)
    off = np.arange(sequence_length, dtype=np.int64)
    order = np.argsort(users, kind="mergesort")
    i = 0
    while i < n:
        u = users[order[i]]
        j = i
        while j < n and users[order[j]] == u:
            j += 1
        idx_rows = order[i:j]
        feats = scaled_by_user[u]
        d = np.asarray(dates_by_user[u]).astype(str)
        daynum = np.array([np.datetime64(t[:10], "D").astype(np.int64) for t in d], dtype=np.int64)
        start_nums = np.array(
            [np.datetime64(starts[k][:10], "D").astype(np.int64) for k in idx_rows],
            dtype=np.int64,
        )
        start_idx = np.searchsorted(daynum, start_nums, side="left")
        if np.any(start_idx >= len(feats)) or np.any(
            daynum[np.clip(start_idx, 0, max(len(feats) - 1, 0))] != start_nums
        ):
            raise Editor026Blocked(f"window start not on calendar for user {u}")
        if np.any(start_idx + sequence_length > len(feats)):
            raise Editor026Blocked(f"incomplete window for user {u}")
        gather = start_idx[:, None] + off[None, :]
        x[idx_rows] = feats[gather]
        i = j
    return x


def r61_gather_windows(
    *,
    scaled_panel: np.ndarray,
    user_index: np.ndarray,
    start_index: np.ndarray,
    sequence_length: int = SEQUENCE_LENGTH_LOCKED,
) -> np.ndarray:
    """Reuse frozen r6.1 completed-window indices. No new window search."""
    panel = np.asarray(scaled_panel)
    ui = np.asarray(user_index).astype(np.int64)
    si = np.asarray(start_index).astype(np.int64)
    off = np.arange(sequence_length, dtype=np.int64)
    if np.any(si + sequence_length > panel.shape[1]):
        raise Editor026Blocked("r6.1 window exceeds calendar")
    idx_t = si[:, None] + off[None, :]
    return np.asarray(panel[ui[:, None], idx_t], dtype=np.float32)


def flatten_windows(x: np.ndarray) -> np.ndarray:
    arr = np.asarray(x, dtype=np.float64)
    if arr.ndim != 3:
        raise ValueError(f"expected (N, T, F), got {arr.shape}")
    return arr.reshape(arr.shape[0], -1)


def split_notes() -> dict[str, Any]:
    return {
        "r52_chronological_split": "FROZEN",
        "validation_day_may_use_earlier_same_user_calendar_history": True,
        "future_validation_day_may_not_affect_earlier_day": True,
        "sequence_windows_retain_no_cross_boundary_split_rules": True,
        "labels_never_enter_baseline": True,
        "user_relative_baseline_is_causal_historical_behaviour": True,
        "not_target_wide_scaler_fitting": True,
    }
