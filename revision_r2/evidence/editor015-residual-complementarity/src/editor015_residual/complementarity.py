"""Frozen L1/TA2 complementarity. No retraining. No validation-tuned blend weights."""

from __future__ import annotations

from typing import Any

import numpy as np
from scipy.stats import pearsonr, spearmanr

from editor012_rescue.losses import confidence_weights
from editor012_rescue.metrics import metrics_from_logits, sigmoid

import torch


def percentile_rank(values: np.ndarray) -> np.ndarray:
    """Deterministic average-rank percentile in [0, 1]. Ties share the mean rank."""
    x = np.asarray(values, dtype=np.float64).reshape(-1)
    order = np.argsort(x, kind="mergesort")
    ranks = np.empty(x.size, dtype=np.float64)
    sorted_x = x[order]
    n = x.size
    i = 0
    while i < n:
        j = i + 1
        while j < n and sorted_x[j] == sorted_x[i]:
            j += 1
        mean_rank = 0.5 * (i + j - 1)
        ranks[order[i:j]] = mean_rank
        i = j
    if n <= 1:
        return np.zeros_like(x)
    return ranks / float(n - 1)


def _corr(a: np.ndarray, b: np.ndarray) -> float:
    a = np.asarray(a, dtype=np.float64).reshape(-1)
    b = np.asarray(b, dtype=np.float64).reshape(-1)
    if a.size < 3 or np.std(a) == 0 or np.std(b) == 0:
        return float("nan")
    return float(pearsonr(a, b)[0])


def _spearman(a: np.ndarray, b: np.ndarray) -> float:
    a = np.asarray(a, dtype=np.float64).reshape(-1)
    b = np.asarray(b, dtype=np.float64).reshape(-1)
    if a.size < 3 or np.std(a) == 0 or np.std(b) == 0:
        return float("nan")
    return float(spearmanr(a, b)[0])


def editor012_confidence(ensemble_logit: np.ndarray) -> np.ndarray:
    """Continuous EDITOR-012 A1 confidence: 1 - H(p_bar)/log(2). Not a searched threshold."""
    p = torch.from_numpy(sigmoid(np.asarray(ensemble_logit, dtype=np.float64)).astype(np.float32))
    return confidence_weights(p).detach().cpu().numpy().astype(np.float64)


def score_relationship(
    y: np.ndarray,
    l1_logit: np.ndarray,
    ta2_logit: np.ndarray,
    *,
    l1_threshold: float,
    ta2_threshold: float,
) -> dict[str, Any]:
    y = np.asarray(y).astype(int).reshape(-1)
    a = np.asarray(l1_logit, dtype=np.float64).reshape(-1)
    b = np.asarray(ta2_logit, dtype=np.float64).reshape(-1)
    pa = sigmoid(a)
    pb = sigmoid(b)
    pred_a = (pa >= l1_threshold).astype(int)
    pred_b = (pb >= ta2_threshold).astype(int)
    disagree = pred_a != pred_b
    pos = y == 1
    neg = y == 0
    return {
        "pearson_score": _corr(a, b),
        "spearman_rank": _spearman(a, b),
        "probability_correlation": _corr(pa, pb),
        "binary_prediction_disagreement": float(disagree.mean()),
        "positive_labelled_disagreement": float(disagree[pos].mean()) if pos.any() else float("nan"),
        "negative_labelled_disagreement": float(disagree[neg].mean()) if neg.any() else float("nan"),
        "n": int(len(y)),
        "n_pos": int(pos.sum()),
        "n_neg": int(neg.sum()),
    }


def error_complementarity(
    y: np.ndarray,
    l1_logit: np.ndarray,
    ta2_logit: np.ndarray,
    *,
    l1_threshold: float,
    ta2_threshold: float,
) -> dict[str, Any]:
    y = np.asarray(y).astype(int).reshape(-1)
    pred_a = (sigmoid(l1_logit) >= l1_threshold).astype(int)
    pred_b = (sigmoid(ta2_logit) >= ta2_threshold).astype(int)
    a_ok = pred_a == y
    b_ok = pred_b == y
    out: dict[str, Any] = {}
    for name, mask in (("all", np.ones(len(y), dtype=bool)), ("positive", y == 1), ("negative", y == 0)):
        m = mask
        out[f"{name}_L1_correct_TA2_wrong"] = int(np.logical_and(a_ok, ~b_ok)[m].sum())
        out[f"{name}_TA2_correct_L1_wrong"] = int(np.logical_and(b_ok, ~a_ok)[m].sum())
        out[f"{name}_both_correct"] = int(np.logical_and(a_ok, b_ok)[m].sum())
        out[f"{name}_both_wrong"] = int(np.logical_and(~a_ok, ~b_ok)[m].sum())
        out[f"{name}_n"] = int(m.sum())
    return out


def user_level_disagreement(
    users: np.ndarray,
    y: np.ndarray,
    l1_logit: np.ndarray,
    ta2_logit: np.ndarray,
    *,
    l1_threshold: float,
    ta2_threshold: float,
) -> dict[str, Any]:
    users = np.asarray(users).astype(str)
    y = np.asarray(y).astype(int).reshape(-1)
    a = np.asarray(l1_logit, dtype=np.float64).reshape(-1)
    b = np.asarray(ta2_logit, dtype=np.float64).reshape(-1)
    pa = sigmoid(a)
    pb = sigmoid(b)
    rows = []
    for u in np.unique(users):
        m = users == u
        rows.append(
            {
                "user": str(u),
                "n_windows": int(m.sum()),
                "n_pos": int(y[m].sum()),
                "mean_L1_score": float(a[m].mean()),
                "mean_TA2_score": float(b[m].mean()),
                "max_L1_score": float(a[m].max()),
                "max_TA2_score": float(b[m].max()),
                "n_flagged_L1": int((pa[m] >= l1_threshold).sum()),
                "n_flagged_TA2": int((pb[m] >= ta2_threshold).sum()),
            }
        )
    mean_l1 = np.asarray([r["mean_L1_score"] for r in rows], dtype=np.float64)
    mean_ta2 = np.asarray([r["mean_TA2_score"] for r in rows], dtype=np.float64)
    max_l1 = np.asarray([r["max_L1_score"] for r in rows], dtype=np.float64)
    max_ta2 = np.asarray([r["max_TA2_score"] for r in rows], dtype=np.float64)
    flag_l1 = np.asarray([r["n_flagged_L1"] for r in rows], dtype=np.float64)
    flag_ta2 = np.asarray([r["n_flagged_TA2"] for r in rows], dtype=np.float64)
    return {
        "rows": rows,
        "user_mean_spearman": _spearman(mean_l1, mean_ta2),
        "user_max_spearman": _spearman(max_l1, max_ta2),
        "user_flag_spearman": _spearman(flag_l1, flag_ta2),
        "user_flag_disagreement_rate": float(np.mean((flag_l1 > 0) != (flag_ta2 > 0))),
        "n_users": int(len(rows)),
        "descriptive_only": True,
    }


def residual_teacher_correlation(
    l1_logit: np.ndarray,
    ta2_logit: np.ndarray,
    ensemble_logit: np.ndarray,
    y: np.ndarray,
) -> dict[str, Any]:
    l1 = np.asarray(l1_logit, dtype=np.float64).reshape(-1)
    ta2 = np.asarray(ta2_logit, dtype=np.float64).reshape(-1)
    ens = np.asarray(ensemble_logit, dtype=np.float64).reshape(-1)
    y = np.asarray(y).astype(int).reshape(-1)
    correction = ta2 - l1
    target = ens - l1
    conf = editor012_confidence(ens)
    median_conf = float(np.median(conf))
    confident = conf >= median_conf
    uncertain = ~confident
    out = {
        "TA2_correction_vs_teacher_residual_all": _corr(correction, target),
        "TA2_correction_vs_teacher_residual_positive": _corr(correction[y == 1], target[y == 1]),
        "TA2_correction_vs_teacher_residual_negative": _corr(correction[y == 0], target[y == 0]),
        "TA2_correction_vs_teacher_residual_teacher_confident": _corr(correction[confident], target[confident]),
        "TA2_correction_vs_teacher_residual_teacher_uncertain": _corr(correction[uncertain], target[uncertain]),
        "confidence_quantity": "EDITOR-012 w_conf = 1 - H(p_bar)/log(2)",
        "confidence_split": "sample median of continuous w_conf; not a searched threshold",
        "confidence_median": median_conf,
        "n_confident": int(confident.sum()),
        "n_uncertain": int(uncertain.sum()),
    }
    return out


def _prob_to_logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(np.asarray(p, dtype=np.float64), 1e-7, 1.0 - 1e-7)
    return np.log(p / (1.0 - p))


def fixed_combinations(
    y: np.ndarray,
    l1_logit: np.ndarray,
    ta2_logit: np.ndarray,
) -> dict[str, dict[str, Any]]:
    l1 = np.asarray(l1_logit, dtype=np.float64).reshape(-1)
    ta2 = np.asarray(ta2_logit, dtype=np.float64).reshape(-1)
    y = np.asarray(y).astype(int).reshape(-1)
    c0 = 0.5 * l1 + 0.5 * ta2
    c1_logit = _prob_to_logit(0.5 * sigmoid(l1) + 0.5 * sigmoid(ta2))
    c2_logit = _prob_to_logit(0.5 * percentile_rank(l1) + 0.5 * percentile_rank(ta2))
    out = {
        "C0": {"logits": c0, "metrics": metrics_from_logits(y, c0), "weights": [0.5, 0.5]},
        "C1": {"logits": c1_logit, "metrics": metrics_from_logits(y, c1_logit), "weights": [0.5, 0.5], "probability_average": True},
        "C2": {"logits": c2_logit, "metrics": metrics_from_logits(y, c2_logit), "weights": [0.5, 0.5], "rank_average": True},
    }
    return out


def classify_predictive_complementarity(
    l1_pr: float,
    ta2_pr: float,
    combo_prs: dict[str, float],
) -> str:
    best_combo = max(combo_prs.values()) if combo_prs else float("-inf")
    if best_combo > l1_pr and best_combo > ta2_pr:
        return "SUPPORTED"
    if best_combo > min(l1_pr, ta2_pr):
        return "PARTIALLY_SUPPORTED"
    return "NOT_SUPPORTED"


def classify_fixed_complementarity(
    *,
    combo_beats_both: bool,
    ci_lo_vs_l1: float | None,
    ci_lo_vs_ta2: float | None,
    mean_vs_l1: float,
    mean_vs_ta2: float,
) -> str:
    if (
        combo_beats_both
        and ci_lo_vs_l1 is not None
        and ci_lo_vs_ta2 is not None
        and ci_lo_vs_l1 > 0
        and ci_lo_vs_ta2 > 0
    ):
        return "STRONG"
    if combo_beats_both and mean_vs_l1 > 0 and mean_vs_ta2 > 0:
        return "CONSISTENT"
    if mean_vs_l1 > 0 or mean_vs_ta2 > 0:
        return "MIXED"
    return "NOT_SUPPORTED"
