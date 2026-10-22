"""Source-frozen L1-margin uncertainty gate. Thresholds come from TRAIN only."""

from __future__ import annotations

from typing import Any

import numpy as np

from editor012_rescue.metrics import metrics_from_logits

from .constants import ALLOWED_Q, Q_VALUES
from .safety import Editor016Blocked, assert_q_allowed


def l1_margin(l1_logit: np.ndarray) -> np.ndarray:
    """margin(x) = abs(L1_logit(x)). Lower margin means greater uncertainty."""
    return np.abs(np.asarray(l1_logit, dtype=np.float64).reshape(-1))


def tau_from_train(l1_logit_train: np.ndarray, q: float) -> float:
    """q-th quantile of abs(L1_logit) on TRAIN. Validation must never enter here."""
    assert_q_allowed(q)
    margins = l1_margin(l1_logit_train)
    if margins.size == 0:
        raise Editor016Blocked("cannot compute tau_q from an empty TRAIN margin vector")
    return float(np.quantile(margins, float(q)))


def gate_indicator(l1_logit: np.ndarray, tau: float) -> np.ndarray:
    """gate=1 iff abs(L1_logit) <= tau. Uses only the linear model's own score."""
    return (l1_margin(l1_logit) <= float(tau)).astype(np.int8)


def apply_cascade(
    l1_logit: np.ndarray,
    delta: np.ndarray,
    gate: np.ndarray,
) -> np.ndarray:
    """final = L1 + gate * delta. Confident examples remain exactly L1."""
    l1 = np.asarray(l1_logit, dtype=np.float64).reshape(-1)
    d = np.asarray(delta, dtype=np.float64).reshape(-1)
    g = np.asarray(gate, dtype=np.float64).reshape(-1)
    if l1.shape != d.shape or l1.shape != g.shape:
        raise Editor016Blocked("cascade arrays must share a common length")
    return l1 + g * d


def gate_metrics(
    *,
    y: np.ndarray,
    l1_logit: np.ndarray,
    gate: np.ndarray,
    partition: str,
    q: float,
    tau: float,
    seed: int,
    tau_source: str,
) -> dict[str, Any]:
    y = np.asarray(y).astype(int).reshape(-1)
    l1 = np.asarray(l1_logit, dtype=np.float64).reshape(-1)
    g = np.asarray(gate).astype(bool).reshape(-1)
    n = int(len(y))
    n_gate = int(g.sum())
    coverage = float(n_gate / max(n, 1))
    y_g = y[g]
    l1_g = l1[g]
    pos_prev = float(y_g.mean()) if n_gate else float("nan")
    neg_prev = float(1.0 - pos_prev) if n_gate else float("nan")
    if n_gate and y_g.min() != y_g.max():
        met = metrics_from_logits(y_g, l1_g)
        pr = float(met["pr_auc"])
        f1 = float(met["f1"])
    else:
        pr = float("nan")
        f1 = float("nan")
    return {
        "partition": partition,
        "q": float(q),
        "seed": int(seed),
        "tau": float(tau),
        "tau_source": tau_source,
        "n": n,
        "n_gated": n_gate,
        "gate_coverage": coverage,
        "positive_prevalence_inside_gate": pos_prev,
        "negative_prevalence_inside_gate": neg_prev,
        "L1_PR_AUC_inside_gate": pr,
        "L1_F1_inside_gate": f1,
        "labels_used_for_gate": False,
        "validation_used_for_tau": False,
    }


def freeze_thresholds(l1_logit_train: np.ndarray, *, seed: int, source: str) -> dict[float, float]:
    """Compute the five frozen candidate thresholds from TRAIN L1 margins only."""
    if source.lower() in {"validation", "val", "official_validation", "inner_select"}:
        raise Editor016Blocked("validation never determines tau")
    out: dict[float, float] = {}
    for q in Q_VALUES:
        out[float(q)] = tau_from_train(l1_logit_train, q)
    return out


def assert_no_extra_q(q_values) -> None:
    extra = [float(q) for q in q_values if float(q) not in ALLOWED_Q]
    if extra:
        raise Editor016Blocked(f"undeclared gate thresholds introduced: {extra}")
