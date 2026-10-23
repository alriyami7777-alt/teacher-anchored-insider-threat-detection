"""Loss components for Prototype V3 NODE training."""

from __future__ import annotations

from typing import Any

import torch
import torch.nn as nn


def binary_entropy(p: torch.Tensor, eps: float = 1e-6) -> torch.Tensor:
    p = p.clamp(eps, 1.0 - eps)
    return -(p * p.log() + (1.0 - p) * (1.0 - p).log())


def gate_anti_collapse_penalty(gate: torch.Tensor, eps: float = 1e-6) -> torch.Tensor:
    return -binary_entropy(gate, eps=eps).mean()


def residual_magnitude_penalty(effective_residual: torch.Tensor) -> torch.Tensor:
    return (effective_residual**2).mean()


def v3_total_loss(
    logits: torch.Tensor,
    y: torch.Tensor,
    extras: dict[str, Any],
    criterion: nn.Module,
    *,
    node_aux_weight: float = 0.0,
    linear_aux_weight: float = 0.0,
    residual_penalty_weight: float = 1e-3,
    anti_collapse_weight: float = 1e-3,
) -> tuple[torch.Tensor, dict[str, float]]:
    """Primary BCE on final logit + optional tiny aux/penalties."""
    primary = criterion(logits, y)
    parts: dict[str, float] = {"loss_primary": float(primary.detach().item())}
    total = primary

    if linear_aux_weight > 0:
        aux_lin = criterion(extras["linear_logit"], y)
        total = total + linear_aux_weight * aux_lin
        parts["loss_aux_linear"] = float(aux_lin.detach().item())
    else:
        parts["loss_aux_linear"] = 0.0

    if node_aux_weight > 0:
        aux_node = criterion(extras["node_logit"], y)
        total = total + node_aux_weight * aux_node
        parts["loss_aux_node"] = float(aux_node.detach().item())
    else:
        parts["loss_aux_node"] = 0.0

    variant = extras.get("fusion_variant")
    if (
        residual_penalty_weight > 0
        and variant
        in {
            "canonical_node_with_linear_residual",
            "canonical_node_with_learned_gate",
        }
        and "effective_residual" in extras
    ):
        mag = residual_magnitude_penalty(extras["effective_residual"])
        total = total + residual_penalty_weight * mag
        parts["loss_residual_magnitude"] = float(mag.detach().item())
    else:
        parts["loss_residual_magnitude"] = 0.0

    if anti_collapse_weight > 0 and variant == "canonical_node_with_learned_gate":
        ac = gate_anti_collapse_penalty(extras["gate"])
        total = total + anti_collapse_weight * ac
        parts["loss_gate_anti_collapse"] = float(ac.detach().item())
    else:
        parts["loss_gate_anti_collapse"] = 0.0

    parts["loss_total"] = float(total.detach().item())
    parts["node_aux_weight"] = float(node_aux_weight)
    parts["linear_aux_weight"] = float(linear_aux_weight)
    parts["residual_penalty_weight"] = float(residual_penalty_weight)
    parts["anti_collapse_weight"] = float(anti_collapse_weight)
    return total, parts
