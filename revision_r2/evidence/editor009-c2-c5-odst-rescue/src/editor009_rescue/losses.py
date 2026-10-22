"""Implementation-derived C2/C5 losses and EDITOR-009 rescue variants.

Producing equations (feasibility models.py / reproducibility models.py):

    L_logit = mean((s - stopgrad(t))^2) / (var_unbiasedFalse(stopgrad(t)) + 1e-6)
    L_route = mean( p_t log((p_t+eps)/(p_s+eps)) + (1-p_t) log((1-p_t+eps)/(1-p_s+eps)) )
    L_task  = BCEWithLogits(s, y; pos_weight = (n_neg/n_pos)*0.25 )
    L_total = L_task + w_logit * L_logit + w_route * L_route

Weights are static in producing C5: w_logit = w_route = 0.5.
C2 uses w_logit = w_route = 0 (terms may still be computed for logging).
"""

from __future__ import annotations

import torch
import torch.nn as nn

LOGIT_VAR_EPS = 1e-6
ROUTE_EPS = 1e-6
PRODUCING_W_LOGIT = 0.5
PRODUCING_W_ROUTE = 0.5
MAX_EPOCHS = 15


def annealed_weight(w0: float, epoch: int, max_epochs: int = MAX_EPOCHS) -> float:
    """EDITOR009_LINEAR_EPOCH_DECAY_TO_ZERO: w(e)=w0*(MAX_EPOCHS-e)/(MAX_EPOCHS-1)."""
    if max_epochs <= 1:
        return 0.0 if epoch >= max_epochs else float(w0)
    e = int(epoch)
    if e < 1:
        e = 1
    if e > max_epochs:
        e = max_epochs
    return float(w0) * float(max_epochs - e) / float(max_epochs - 1)


def logit_consistency_loss(student_logit: torch.Tensor, teacher_logit: torch.Tensor) -> torch.Tensor:
    diff = (student_logit - teacher_logit.detach()).pow(2).mean()
    var = teacher_logit.detach().var(unbiased=False) + LOGIT_VAR_EPS
    return diff / var


def route_consistency_loss(
    student_p: torch.Tensor, teacher_p: torch.Tensor, eps: float = ROUTE_EPS
) -> torch.Tensor:
    p_t = teacher_p.detach().clamp(0.0, 1.0)
    p_s = student_p.clamp(0.0, 1.0)
    term = p_t * torch.log((p_t + eps) / (p_s + eps)) + (1.0 - p_t) * torch.log(
        (1.0 - p_t + eps) / (1.0 - p_s + eps)
    )
    return term.mean()


def route_kl_elements(
    student_p: torch.Tensor, teacher_p: torch.Tensor, eps: float = ROUTE_EPS
) -> torch.Tensor:
    p_t = teacher_p.detach().clamp(0.0, 1.0)
    p_s = student_p.clamp(0.0, 1.0)
    return p_t * torch.log((p_t + eps) / (p_s + eps)) + (1.0 - p_t) * torch.log(
        (1.0 - p_t + eps) / (1.0 - p_s + eps)
    )


def total_loss(
    *,
    class_loss: torch.Tensor,
    logit_loss: torch.Tensor,
    route_loss: torch.Tensor,
    w_logit: float,
    w_route: float,
) -> torch.Tensor:
    return class_loss + w_logit * logit_loss + w_route * route_loss


def masked_mean(values: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    w = mask.to(dtype=values.dtype)
    denom = w.sum().clamp_min(1.0)
    return (values * w).sum() / denom


def class_balanced_logit_loss(
    student_logit: torch.Tensor, teacher_logit: torch.Tensor, y: torch.Tensor
) -> torch.Tensor:
    """Equal mean of positive-window and negative-window producing logit terms."""
    sq = (student_logit - teacher_logit.detach()).pow(2)
    var = teacher_logit.detach().var(unbiased=False) + LOGIT_VAR_EPS
    yb = y.reshape(-1)
    pos = yb > 0.5
    neg = ~pos
    if bool(pos.any()) and bool(neg.any()):
        return 0.5 * (sq[pos].mean() + sq[neg].mean()) / var
    return sq.mean() / var


def class_balanced_route_loss(
    student_p: torch.Tensor, teacher_p: torch.Tensor, y: torch.Tensor
) -> torch.Tensor:
    """Equal mean of positive-window and negative-window producing route KL."""
    elem = route_kl_elements(student_p, teacher_p)
    per = elem.reshape(elem.size(0), -1).mean(dim=1)
    yb = y.reshape(-1)
    pos = yb > 0.5
    neg = ~pos
    if bool(pos.any()) and bool(neg.any()):
        return 0.5 * (per[pos].mean() + per[neg].mean())
    return per.mean()


def selective_logit_loss(
    student_logit: torch.Tensor,
    teacher_logit: torch.Tensor,
    mask: torch.Tensor,
) -> torch.Tensor:
    if not bool(mask.any()):
        return student_logit.new_zeros(())
    diff = (student_logit - teacher_logit.detach()).pow(2)
    var = teacher_logit.detach().var(unbiased=False) + LOGIT_VAR_EPS
    return masked_mean(diff, mask) / var


def selective_route_loss(
    student_p: torch.Tensor,
    teacher_p: torch.Tensor,
    mask: torch.Tensor,
) -> torch.Tensor:
    if not bool(mask.any()):
        return student_p.new_zeros(())
    per = route_kl_elements(student_p, teacher_p).reshape(student_p.size(0), -1).mean(dim=1)
    return masked_mean(per, mask)


def teacher_correct_mask(
    teacher_logit: torch.Tensor, y: torch.Tensor, threshold: float
) -> torch.Tensor:
    """Producing inference rule on TRAIN: sigmoid(logit) >= frozen teacher threshold."""
    pred = torch.sigmoid(teacher_logit.detach()) >= float(threshold)
    return pred.eq(y.reshape(-1) > 0.5)


def make_task_criterion(pos_weight: float, device: torch.device) -> nn.Module:
    return nn.BCEWithLogitsLoss(pos_weight=torch.tensor([pos_weight], device=device, dtype=torch.float32))
