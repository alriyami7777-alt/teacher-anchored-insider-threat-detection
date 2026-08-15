"""Shared temporal ODST placement and matched linear residual heads."""

from __future__ import annotations

from typing import Any

import torch
import torch.nn as nn

from editor012_rescue.models import live_odst_forward, state_dict_sha256
from editor013_odst_value.models import Editor013LinearHead, uniform_tree_logit

from .constants import ENCODER_DIM, LR_ATTENTION, LR_BETA, LR_ENCODER, LR_LINEAR, LR_ODST, N_TREES_TOTAL, WEIGHT_DECAY
from .safety import Editor014ProtocolError


class ResidualBeta(nn.Module):
    """Global scalar residual scale. Initialised exactly 0."""

    def __init__(self) -> None:
        super().__init__()
        self.beta = nn.Parameter(torch.zeros(()))

    def forward(self, linear_logit: torch.Tensor, odst_logit: torch.Tensor) -> torch.Tensor:
        return linear_logit + self.beta * odst_logit


class TrainMeanCenter(nn.Module):
    """Frozen TRAIN/INNER_TRAIN mean of the temporal ODST logit. Never validation."""

    def __init__(self) -> None:
        super().__init__()
        self.register_buffer("train_mean", torch.zeros(()))
        self.register_buffer("frozen", torch.zeros((), dtype=torch.bool))

    def freeze_from(self, mean_value: float) -> None:
        self.train_mean.fill_(float(mean_value))
        self.frozen.fill_(True)

    def center(self, o: torch.Tensor) -> torch.Tensor:
        if not bool(self.frozen.item()):
            raise Editor014ProtocolError("T2 centering mean is not frozen from TRAIN/INNER_TRAIN")
        return o - self.train_mean


class Editor014Modules(nn.Module):
    def __init__(
        self,
        *,
        family: str,
        placement: str,
        hybrid: bool,
        center: bool,
        in_dim: int = ENCODER_DIM,
    ) -> None:
        super().__init__()
        self.family = family
        self.placement = placement
        self.hybrid = bool(hybrid)
        self.center = bool(center)
        needs_linear = family in {"linear", "temporal_hybrid"}
        self.linear_head = Editor013LinearHead(in_dim) if needs_linear else None
        self.beta_mod = ResidualBeta() if hybrid else None
        self.center_mod = TrainMeanCenter() if center else None

    def initial_linear_hash(self) -> str | None:
        if self.linear_head is None:
            return None
        return state_dict_sha256(self.linear_head.state_dict())

    def learned_beta(self) -> float | None:
        if self.beta_mod is None:
            return None
        return float(self.beta_mod.beta.detach().cpu().item())

    def frozen_train_mean(self) -> float | None:
        if self.center_mod is None:
            return None
        return float(self.center_mod.train_mean.detach().cpu().item())


def apply_shared_odst(node_head: nn.Module, h: torch.Tensor) -> dict[str, torch.Tensor]:
    """Apply one shared ODST-046 to every time step. h: (B, T, H) or (B, H)."""
    if h.dim() == 2:
        od = live_odst_forward(node_head, h)
        return {
            **od,
            "tree_outputs_btj": od["tree_outputs"].unsqueeze(1),
            "q_t": od["logit"].unsqueeze(1),
        }
    if h.dim() != 3:
        raise Editor014ProtocolError(f"expected (B,T,H) or (B,H); got {tuple(h.shape)}")
    batch, steps, hidden = h.shape
    flat = h.reshape(batch * steps, hidden)
    od = live_odst_forward(node_head, flat)
    trees = od["tree_outputs"].reshape(batch, steps, -1)
    q_t = trees.mean(dim=-1)
    choices = od["choices"].reshape(batch, steps, *od["choices"].shape[1:])
    leaves = od["leaf_probs_all"].reshape(batch, steps, *od["leaf_probs_all"].shape[1:])
    return {
        "logit": (q_t.mean(dim=-1) if steps else q_t.squeeze(-1)),
        "tree_outputs": trees.mean(dim=1),
        "tree_outputs_btj": trees,
        "q_t": q_t,
        "choices": choices.mean(dim=1),
        "leaf_probs": od["leaf_probs"].reshape(batch, steps, *od["leaf_probs"].shape[1:]).mean(dim=1),
        "leaf_probs_all": leaves,
    }


def temporal_aggregate(alpha: torch.Tensor, q_t: torch.Tensor) -> torch.Tensor:
    """Σ_t alpha_t q_t. Attention weights are unchanged by this placement."""
    if alpha.shape != q_t.shape:
        raise Editor014ProtocolError(f"alpha {tuple(alpha.shape)} != q_t {tuple(q_t.shape)}")
    return (alpha * q_t).sum(dim=-1)


def editor014_forward(
    student: nn.Module,
    x: torch.Tensor,
    modules: Editor014Modules,
) -> dict[str, torch.Tensor]:
    z, enc = student.encode_attention_h(x)
    h_t = enc["hidden_states"]
    alpha = enc["attention_weights"]
    historical_linear = enc["linear_logit"]

    if modules.family == "linear":
        assert modules.linear_head is not None
        linear_logit = modules.linear_head(z)
        zeros = linear_logit.new_zeros(linear_logit.shape)
        return {
            "logit": linear_logit,
            "linear_logit": linear_logit,
            "odst_logit": zeros,
            "odst_logit_raw": zeros,
            "historical_linear_logit": historical_linear,
            "z": z,
            "hidden_states": h_t,
            "attention_weights": alpha,
            "tree_outputs": z.new_zeros(z.size(0), N_TREES_TOTAL),
            "tree_outputs_btj": z.new_zeros(z.size(0), h_t.size(1), N_TREES_TOTAL),
            "q_t": z.new_zeros(z.size(0), h_t.size(1)),
            "choices": z.new_zeros(z.size(0), N_TREES_TOTAL, 4),
            "leaf_probs_all": z.new_zeros(z.size(0), N_TREES_TOTAL, 16),
            "beta": zeros,
        }

    if modules.placement == "post_attention":
        od = live_odst_forward(student.node_head, z)
        odst_raw = uniform_tree_logit(od["tree_outputs"])
        trees_btj = od["tree_outputs"].unsqueeze(1).expand(-1, h_t.size(1), -1)
        q_t = odst_raw.unsqueeze(1).expand(-1, h_t.size(1))
        choices = od["choices"]
        leaves = od["leaf_probs_all"]
        trees = od["tree_outputs"]
    elif modules.placement == "pre_pooling":
        od = apply_shared_odst(student.node_head, h_t)
        trees_btj = od["tree_outputs_btj"]
        q_t = od["q_t"]
        odst_raw = temporal_aggregate(alpha, q_t)
        choices = od["choices"]
        leaves = od["leaf_probs_all"]
        trees = od["tree_outputs"]
    else:
        raise Editor014ProtocolError(f"unknown placement {modules.placement!r}")

    if modules.center_mod is not None and bool(modules.center_mod.frozen.item()):
        odst_logit = modules.center_mod.center(odst_raw)
    else:
        odst_logit = odst_raw

    if modules.linear_head is not None:
        linear_logit = modules.linear_head(z)
    else:
        linear_logit = historical_linear

    if modules.hybrid:
        assert modules.beta_mod is not None
        final = modules.beta_mod(linear_logit, odst_logit)
        beta = modules.beta_mod.beta.expand_as(final)
    else:
        final = odst_logit
        beta = final.new_zeros(final.shape)

    return {
        "logit": final,
        "linear_logit": linear_logit,
        "odst_logit": odst_logit,
        "odst_logit_raw": odst_raw,
        "historical_linear_logit": historical_linear,
        "z": z,
        "hidden_states": h_t,
        "attention_weights": alpha,
        "tree_outputs": trees,
        "tree_outputs_btj": trees_btj,
        "q_t": q_t,
        "choices": choices,
        "leaf_probs_all": leaves,
        "beta": beta,
    }


def freeze_encoder_attention(student: nn.Module) -> None:
    student.lstm.eval()
    student.attention.eval()
    student.dropout.eval()
    for p in student.lstm.parameters():
        p.requires_grad = False
    for p in student.attention.parameters():
        p.requires_grad = False
    for p in student.linear_head.parameters():
        p.requires_grad = False
    student.residual_scale_logit.requires_grad = False
    for p in student.sample_gate.parameters():
        p.requires_grad = False


def configure_trainability(
    student: nn.Module,
    modules: Editor014Modules,
    *,
    encoder_trainable: bool,
) -> None:
    for p in student.lstm.parameters():
        p.requires_grad = bool(encoder_trainable)
    for p in student.attention.parameters():
        p.requires_grad = bool(encoder_trainable)
    train_odst = modules.family in {"odst", "temporal_odst", "temporal_hybrid"}
    for p in student.node_head.parameters():
        p.requires_grad = train_odst
    for p in student.linear_head.parameters():
        p.requires_grad = False
    student.residual_scale_logit.requires_grad = False
    for p in student.sample_gate.parameters():
        p.requires_grad = False
    if modules.linear_head is not None:
        for p in modules.linear_head.parameters():
            p.requires_grad = True
    if modules.beta_mod is not None:
        modules.beta_mod.beta.requires_grad = True
    if modules.center_mod is not None:
        modules.center_mod.train_mean.requires_grad = False


def build_editor014_optimizer(
    student: nn.Module,
    modules: Editor014Modules,
    *,
    encoder_trainable: bool,
) -> torch.optim.Optimizer:
    configure_trainability(student, modules, encoder_trainable=encoder_trainable)
    groups = []
    if encoder_trainable:
        enc = [p for p in student.lstm.parameters() if p.requires_grad]
        att = [p for p in student.attention.parameters() if p.requires_grad]
        if enc:
            groups.append({"params": enc, "lr": LR_ENCODER, "weight_decay": WEIGHT_DECAY})
        if att:
            groups.append({"params": att, "lr": LR_ATTENTION, "weight_decay": WEIGHT_DECAY})
    odst = [p for p in student.node_head.parameters() if p.requires_grad]
    if odst:
        groups.append({"params": odst, "lr": LR_ODST, "weight_decay": WEIGHT_DECAY})
    if modules.linear_head is not None:
        groups.append(
            {
                "params": list(modules.linear_head.parameters()),
                "lr": LR_LINEAR,
                "weight_decay": WEIGHT_DECAY,
            }
        )
    if modules.beta_mod is not None:
        groups.append({"params": [modules.beta_mod.beta], "lr": LR_BETA, "weight_decay": WEIGHT_DECAY})
    if not groups:
        raise Editor014ProtocolError("no trainable EDITOR-014 parameter groups")
    return torch.optim.Adam(groups)


def make_modules(spec: dict[str, Any]) -> Editor014Modules:
    return Editor014Modules(
        family=str(spec["family"]),
        placement=str(spec.get("placement") or "none"),
        hybrid=bool(spec.get("hybrid", False)),
        center=bool(spec.get("center", False)),
    )


def linear_attention_equivalence(
    z: torch.Tensor,
    h_t: torch.Tensor,
    alpha: torch.Tensor,
    weight: torch.Tensor,
    bias: torch.Tensor,
) -> torch.Tensor:
    """w^T Σ_t α_t h_t + b  vs  Σ_t α_t (w^T h_t) + b."""
    pooled = (alpha.unsqueeze(-1) * h_t).sum(dim=1)
    left = (pooled * weight.view(1, -1)).sum(dim=-1) + bias
    per_t = (h_t * weight.view(1, 1, -1)).sum(dim=-1)
    right = (alpha * per_t).sum(dim=-1) + bias
    if not torch.allclose(left, right, atol=1e-5, rtol=1e-5):
        raise Editor014ProtocolError("linear attention equivalence failed")
    if not torch.allclose(pooled, z, atol=1e-5, rtol=1e-5):
        raise Editor014ProtocolError("attended z is not Σ_t α_t h_t")
    return left
