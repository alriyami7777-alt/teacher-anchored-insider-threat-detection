"""Phase I — exactly one non-trained input counterfactual: R52_SUPPORT_CLIP."""

from __future__ import annotations

from typing import Any, Sequence

import numpy as np

from .constants import COUNT_FEATURES, FEATURE_ORDER, SUPPORT_CLIP_HIGH_QUANTILE, SUPPORT_CLIP_LOW_QUANTILE, SUPPORT_CLIP_VIEW_NAME
from .feature_shift import apply_scale, clip_raw_count_features, inverse_scale, support_bounds_from_train


def r52_train_support_bounds(train_raw: np.ndarray, feature_order: Sequence[str] = FEATURE_ORDER) -> dict[str, tuple[float, float]]:
    """Bounds fitted from r5.2 TRAIN only. Quantiles are protocol-frozen."""
    names = list(feature_order)
    bounds: dict[str, tuple[float, float]] = {}
    for name in COUNT_FEATURES:
        j = names.index(name)
        bounds[name] = support_bounds_from_train(train_raw[:, j])
    return bounds


def apply_r52_support_clip(
    *,
    r61_scaled: np.ndarray,
    mean: np.ndarray,
    scale: np.ndarray,
    bounds: dict[str, tuple[float, float]],
) -> np.ndarray:
    """Clip raw count features to r5.2 TRAIN bounds, then apply frozen scaler. No trainable parameters."""
    raw = inverse_scale(r61_scaled, mean, scale)
    clipped = clip_raw_count_features(raw, bounds, FEATURE_ORDER)
    return apply_scale(clipped, mean, scale)


def clip_view_identity() -> dict[str, Any]:
    return {
        "view": SUPPORT_CLIP_VIEW_NAME,
        "low_quantile": SUPPORT_CLIP_LOW_QUANTILE,
        "high_quantile": SUPPORT_CLIP_HIGH_QUANTILE,
        "n_clip_levels": 1,
        "trainable_parameters": 0,
        "bounds_source": "R52_TRAIN",
        "binary_indicators_unchanged": True,
        "additional_clipping_levels": [],
    }
