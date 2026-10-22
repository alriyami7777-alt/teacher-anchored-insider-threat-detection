"""Source-only causal MAD scale floors. r6.1 never enters the estimate."""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np

from .constants import (
    FLOOR_FALLBACK,
    SCALE_FLOOR_PERCENTILE,
    VOLUME_FEATURES,
)
from .representation import causal_volume_scales_daily
from .safety import Editor027Blocked


def train_calendar_mask(dates: np.ndarray, train_start: str, train_end: str) -> np.ndarray:
    d = np.asarray(dates).astype(str)
    return (d >= train_start[:10]) & (d <= train_end[:10])


def collect_positive_train_scales(
    raw_by_user: Mapping[str, np.ndarray],
    dates_by_user: Mapping[str, np.ndarray],
    train_start: str,
    train_end: str,
) -> dict[str, np.ndarray]:
    """Strictly positive finite causal MAD scales on r5.2 TRAIN user-days."""
    buckets: dict[str, list[float]] = {f: [] for f in VOLUME_FEATURES}
    for user, raw in raw_by_user.items():
        dates = dates_by_user[user]
        mask = train_calendar_mask(dates, train_start, train_end)
        if not np.any(mask):
            continue
        scales = causal_volume_scales_daily(raw, dates)
        for j, name in enumerate(VOLUME_FEATURES):
            vals = scales[mask, j]
            keep = np.isfinite(vals) & (vals > 0.0)
            if np.any(keep):
                buckets[name].extend(vals[keep].tolist())
    return {name: np.asarray(vals, dtype=np.float64) for name, vals in buckets.items()}


def floors_from_positive_scales(positive: Mapping[str, np.ndarray]) -> dict[str, Any]:
    floors: dict[str, float] = {}
    fallback_used: dict[str, bool] = {}
    n_positive: dict[str, int] = {}
    for name in VOLUME_FEATURES:
        arr = np.asarray(positive.get(name, []), dtype=np.float64)
        arr = arr[np.isfinite(arr) & (arr > 0.0)]
        n_positive[name] = int(arr.size)
        if arr.size == 0:
            floors[name] = float(FLOOR_FALLBACK)
            fallback_used[name] = True
        else:
            floors[name] = float(np.quantile(arr, SCALE_FLOOR_PERCENTILE))
            fallback_used[name] = False
    return {
        "floors": floors,
        "fallback_used": fallback_used,
        "n_positive_source_scales": n_positive,
        "SCALE_FLOOR_PERCENTILE": SCALE_FLOOR_PERCENTILE,
        "FLOOR_FALLBACK": FLOOR_FALLBACK,
        "SCALE_FLOOR_SOURCE": "CERT r5.2 TRAIN ONLY",
        "R61_TARGET_SCALE_FLOOR": "NO",
        "strictly_positive_finite_only": True,
    }


def fit_scale_floors(
    raw_by_user: Mapping[str, np.ndarray],
    dates_by_user: Mapping[str, np.ndarray],
    train_start: str,
    train_end: str,
) -> dict[str, Any]:
    if "r61" in train_start.lower() or "r6.1" in train_start.lower():
        raise Editor027Blocked("r6.1 statistic refused for volume scale floor")
    positive = collect_positive_train_scales(raw_by_user, dates_by_user, train_start, train_end)
    rec = floors_from_positive_scales(positive)
    rec["train_calendar_start"] = train_start[:10]
    rec["train_calendar_end"] = train_end[:10]
    rec["floor_vector"] = [float(rec["floors"][f]) for f in VOLUME_FEATURES]
    return rec
