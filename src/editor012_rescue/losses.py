"""EDITOR-012 losses. ET1 ensemble logit MSE is distinct from retired C5 logit MSE."""

from __future__ import annotations

import math

import torch
import torch.nn as nn

ROUTE_EPS = 1e-6
PROB_EPS = 1e-7
LOG2 = math.log(2.0)


def make_task_criterion(pos_weight: float, device: torch.device) -> nn.Module:
    return nn.BCEWithLogitsLoss(
        pos_weight=torch.tensor([pos_weight], device=device, dtype=torch.float32)
    )


def route_consistency_loss(
    student_p: torch.Tensor, teacher_p: torch.Tensor, eps: float = ROUTE_EPS
) -> torch.Tensor:
    p_t = teacher_p.detach().clamp(0.0, 1.0)
    p_s = student_p.clamp(0.0, 1.0)
    term = p_t * torch.log((p_t + eps) / (p_s + eps)) + (1.0 - p_t) * torch.log(
        (1.0 - p_t + eps) / (1.0 - p_s + eps)
    )
    return term.mean()


def et1_ensemble_logit_mse(student_logit: torch.Tensor, ensemble_logit: torch.Tensor) -> torch.Tensor:
    """Exact frozen ET1 distill: unnormalised MSE to equal-weight ensemble logits.

    This is NOT the historical C5 variance-normalised single-teacher logit MSE.
    """
    return torch.mean((student_logit - ensemble_logit.detach()) ** 2)


def per_sample_logit_mse(student_logit: torch.Tensor, ensemble_logit: torch.Tensor) -> torch.Tensor:
    return (student_logit - ensemble_logit.detach()) ** 2


def binary_entropy(p: torch.Tensor) -> torch.Tensor:
    p = p.clamp(PROB_EPS, 1.0 - PROB_EPS)
    return -(p * torch.log(p) + (1.0 - p) * torch.log(1.0 - p))


def confidence_weights(p_bar: torch.Tensor) -> torch.Tensor:
    """A1: w_conf = 1 - H(p_bar) / log(2), clipped to [0, 1]."""
    return (1.0 - binary_entropy(p_bar) / LOG2).clamp(0.0, 1.0)


def agreement_weights(p42: torch.Tensor, p52: torch.Tensor, p62: torch.Tensor) -> torch.Tensor:
    """A2: w_agree = 1 - 4 * Var(p42, p52, p62), clipped to [0, 1]."""
    stacked = torch.stack([p42, p52, p62], dim=0)
    variance = stacked.var(dim=0, unbiased=False)
    return (1.0 - 4.0 * variance).clamp(0.0, 1.0)


def class_balanced_reduction(per_sample: torch.Tensor, labels: torch.Tensor) -> torch.Tensor:
    """A3: 0.5 * mean(loss | y=0) + 0.5 * mean(loss | y=1). Empty class is skipped."""
    pos = labels > 0.5
    neg = ~pos
    terms: list[torch.Tensor] = []
    if bool(pos.any()):
        terms.append(per_sample[pos].mean())
    if bool(neg.any()):
        terms.append(per_sample[neg].mean())
    if not terms:
        return per_sample.new_zeros(())
    if len(terms) == 1:
        return terms[0]
    return 0.5 * terms[0] + 0.5 * terms[1]


def weighted_mean(per_sample: torch.Tensor, weights: torch.Tensor) -> torch.Tensor:
    w = weights.detach()
    denom = w.sum().clamp_min(1e-12)
    return (per_sample * w).sum() / denom


def ensemble_anchor_loss(
    student_logit: torch.Tensor,
    ensemble_logit: torch.Tensor,
    labels: torch.Tensor,
    *,
    confidence_weight: bool = False,
    agreement_weight: bool = False,
    class_balanced_reduction_flag: bool = False,
    p_bar: torch.Tensor | None = None,
    p42: torch.Tensor | None = None,
    p52: torch.Tensor | None = None,
    p62: torch.Tensor | None = None,
) -> torch.Tensor:
    per = per_sample_logit_mse(student_logit, ensemble_logit)
    weights = student_logit.new_ones(student_logit.shape)
    if confidence_weight:
        if p_bar is None:
            raise ValueError("A1/A4 require p_bar")
        weights = weights * confidence_weights(p_bar)
    if agreement_weight:
        if p42 is None or p52 is None or p62 is None:
            raise ValueError("A2/A5 require p42/p52/p62")
        weights = weights * agreement_weights(p42, p52, p62)
    weighted = per * weights
    if class_balanced_reduction_flag:
        return class_balanced_reduction(weighted, labels)
    if confidence_weight or agreement_weight:
        return weighted_mean(per, weights)
    return per.mean()


def historical_c5_logit_consistency(student_logit: torch.Tensor, teacher_logit: torch.Tensor) -> torch.Tensor:
    """Retired C5 term. Present only so tests can prove F10/F11 do not call it."""
    raise Editor012RetiredAnchor("historical static single-teacher logit MSE is retired")


class Editor012RetiredAnchor(RuntimeError):
    """Historical C5 logit anchor must not be used."""
