"""Producing C2 / R2 losses. No annealed, focal, ranking, or class-balanced variants."""

from __future__ import annotations

import torch
import torch.nn as nn

LOGIT_VAR_EPS = 1e-6
ROUTE_EPS = 1e-6


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


def total_loss(
    *,
    class_loss: torch.Tensor,
    logit_loss: torch.Tensor,
    route_loss: torch.Tensor,
    w_logit: float,
    w_route: float,
) -> torch.Tensor:
    return class_loss + float(w_logit) * logit_loss + float(w_route) * route_loss


def make_task_criterion(pos_weight: float, device: torch.device) -> nn.Module:
    return nn.BCEWithLogitsLoss(
        pos_weight=torch.tensor([pos_weight], device=device, dtype=torch.float32)
    )
