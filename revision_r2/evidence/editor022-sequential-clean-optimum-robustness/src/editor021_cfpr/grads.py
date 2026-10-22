"""One-sided conflict projection and rho-bounded robustness gradient budget."""

from __future__ import annotations

from typing import Iterable, Sequence

import torch
import torch.nn as nn

from .constants import COSINE_EPS, EPS_GRAD


def encoder_attention_params(student: nn.Module) -> list[nn.Parameter]:
    return [p for p in student.lstm.parameters()] + [p for p in student.attention.parameters()]


def odst_head_params(student: nn.Module) -> list[nn.Parameter]:
    return [p for p in student.node_head.parameters()]


def trainable_params(student: nn.Module) -> list[nn.Parameter]:
    return [p for p in student.parameters() if p.requires_grad]


def flatten_grads(grads: Sequence[torch.Tensor | None], likes: Sequence[torch.Tensor]) -> torch.Tensor:
    pieces = []
    for g, like in zip(grads, likes):
        if g is None:
            pieces.append(like.detach().new_zeros(like.numel()))
        else:
            pieces.append(g.reshape(-1))
    if not pieces:
        raise ValueError("no gradients to flatten")
    return torch.cat(pieces)


def unflatten_grads(flat: torch.Tensor, likes: Sequence[torch.Tensor]) -> list[torch.Tensor]:
    out: list[torch.Tensor] = []
    offset = 0
    for like in likes:
        n = int(like.numel())
        out.append(flat[offset : offset + n].view_as(like))
        offset += n
    return out


def cosine_repr_loss(h_student: torch.Tensor, h_ref: torch.Tensor, *, eps: float = COSINE_EPS) -> torch.Tensor:
    """L_repr = 1 - cos(h_S(x_tilde), stopgrad(h_Fref(x)))."""
    a = h_student
    b = h_ref.detach()
    a_n = a / a.norm(dim=-1, keepdim=True).clamp_min(eps)
    b_n = b / b.norm(dim=-1, keepdim=True).clamp_min(eps)
    return (1.0 - (a_n * b_n).sum(dim=-1)).mean()


def project_robustness(
    g_c: torch.Tensor,
    g_r: torch.Tensor,
    *,
    eps: float = EPS_GRAD,
) -> tuple[torch.Tensor, bool]:
    """One-sided PCGrad-style projection of g_r onto the non-conflicting half-space of g_c."""
    d = torch.dot(g_c, g_r)
    if d < 0:
        denom = torch.dot(g_c, g_c) + eps
        return g_r - (d / denom) * g_c, True
    return g_r, False


def rho_scale(
    g_c: torch.Tensor,
    g_r_perp: torch.Tensor,
    rho: float,
    *,
    eps: float = EPS_GRAD,
) -> tuple[torch.Tensor, float]:
    gc_norm = torch.linalg.vector_norm(g_c)
    if float(gc_norm) < eps:
        return g_r_perp.new_zeros(g_r_perp.shape), 0.0
    gr_norm = torch.linalg.vector_norm(g_r_perp)
    alpha = min(1.0, float(rho) * float(gc_norm) / (float(gr_norm) + eps))
    return g_r_perp * alpha, float(alpha)


def combine_encoder_grads(
    g_c_enc: torch.Tensor,
    g_r_enc: torch.Tensor,
    rho: float,
    *,
    eps: float = EPS_GRAD,
) -> dict[str, torch.Tensor | float | bool]:
    g_r_perp, projected = project_robustness(g_c_enc, g_r_enc, eps=eps)
    scaled, alpha = rho_scale(g_c_enc, g_r_perp, rho, eps=eps)
    combined = g_c_enc + scaled
    return {
        "g_c": g_c_enc,
        "g_r": g_r_enc,
        "g_r_perp": g_r_perp,
        "scaled": scaled,
        "combined": combined,
        "alpha": float(alpha),
        "projected": bool(projected),
        "dot_before": float(torch.dot(g_c_enc, g_r_enc)),
        "dot_after": float(torch.dot(g_c_enc, g_r_perp)),
        "gc_norm": float(torch.linalg.vector_norm(g_c_enc)),
        "gr_perp_norm": float(torch.linalg.vector_norm(g_r_perp)),
        "scaled_norm": float(torch.linalg.vector_norm(scaled)),
    }


def assign_grad_(params: Iterable[nn.Parameter], grads: Sequence[torch.Tensor | None]) -> None:
    for p, g in zip(params, grads):
        if g is None:
            p.grad = None
        else:
            p.grad = g
