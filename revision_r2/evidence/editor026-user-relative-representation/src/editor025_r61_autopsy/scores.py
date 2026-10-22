"""Phase D/E/F score, ranking, and capture statistics. No training."""

from __future__ import annotations

from typing import Any, Sequence

import numpy as np

from editor012_rescue.metrics import sigmoid

from .constants import SCORE_QUANTILES, TOPK_FRACTIONS, TOPK_MULTIPLIERS


def score_quantiles(values: np.ndarray) -> dict[str, float]:
    v = np.asarray(values, dtype=np.float64).ravel()
    v = v[np.isfinite(v)]
    rec = {
        "n": float(v.size),
        "mean": float(v.mean()) if v.size else float("nan"),
        "std": float(v.std(ddof=0)) if v.size else float("nan"),
    }
    if v.size == 0:
        for q in SCORE_QUANTILES:
            rec[_qname(q)] = float("nan")
        return rec
    qs = np.quantile(v, SCORE_QUANTILES)
    for q, val in zip(SCORE_QUANTILES, qs):
        rec[_qname(q)] = float(val)
    return rec


def _qname(q: float) -> str:
    if q == 0.001:
        return "q001"
    if q == 0.999:
        return "q999"
    return f"q{int(round(q * 100)):02d}"


def distribution_block(logits: np.ndarray, threshold: float) -> dict[str, Any]:
    logits = np.asarray(logits, dtype=np.float64).ravel()
    probs = sigmoid(logits)
    rec = {
        "logit": score_quantiles(logits),
        "probability": score_quantiles(probs),
        "fraction_gt_frozen_r52_threshold": float(np.mean(probs > float(threshold))) if logits.size else float("nan"),
        "fraction_gt_0.5": float(np.mean(probs > 0.5)) if logits.size else float("nan"),
        "fraction_lt_0.01": float(np.mean(probs < 0.01)) if logits.size else float("nan"),
        "fraction_gt_0.99": float(np.mean(probs > 0.99)) if logits.size else float("nan"),
    }
    return rec


def percentile_ranks(scores: np.ndarray, query: np.ndarray) -> np.ndarray:
    s = np.asarray(scores, dtype=np.float64).ravel()
    q = np.asarray(query, dtype=np.float64).ravel()
    order = np.sort(s)
    # percent of all windows with score <= query
    idx = np.searchsorted(order, q, side="right")
    return (idx / max(len(order), 1)) * 100.0


def ranking_profile(y: np.ndarray, scores: np.ndarray) -> dict[str, Any]:
    y = np.asarray(y).astype(int).ravel()
    s = np.asarray(scores, dtype=np.float64).ravel()
    pos = s[y == 1]
    n = int(y.size)
    n_pos = int(y.sum())
    if n_pos == 0:
        return {"n_pos": 0, "NOT_EVALUABLE": True}
    pct = percentile_ranks(s, pos)
    order = np.argsort(-s, kind="mergesort")
    ranked_y = y[order]
    capture: dict[str, float] = {}
    for m in TOPK_MULTIPLIERS:
        k = min(n, n_pos * int(m))
        capture[f"top_{m}N"] = float(ranked_y[:k].sum() / n_pos)
    for frac in TOPK_FRACTIONS:
        k = max(1, int(round(frac * n)))
        k = min(n, k)
        pct_label = "0.1pct" if abs(frac - 0.001) < 1e-12 else "1pct"
        capture[f"top_{pct_label}"] = float(ranked_y[:k].sum() / n_pos)
    return {
        "n": n,
        "n_pos": n_pos,
        "median_positive_percentile": float(np.median(pct)),
        "mean_positive_percentile": float(np.mean(pct)),
        "min_positive_percentile": float(np.min(pct)),
        "max_positive_percentile": float(np.max(pct)),
        "q25_positive_percentile": float(np.quantile(pct, 0.25)),
        "q75_positive_percentile": float(np.quantile(pct, 0.75)),
        "capture": capture,
        "positive_percentiles": pct,
        "frozen_topk_multipliers": list(TOPK_MULTIPLIERS),
        "frozen_topk_fractions": list(TOPK_FRACTIONS),
    }


def user_positive_windows(y: np.ndarray, users: np.ndarray) -> dict[str, np.ndarray]:
    y = np.asarray(y).astype(int).ravel()
    users = np.asarray(users).astype(str)
    out: dict[str, np.ndarray] = {}
    for u in np.unique(users):
        sl = np.flatnonzero((users == u) & (y == 1))
        if sl.size:
            out[str(u)] = sl
    return out
