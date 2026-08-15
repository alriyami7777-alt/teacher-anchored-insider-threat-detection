"""EDITOR-013 heads: new linear, convex tree readout, residual fusion."""

from __future__ import annotations

from typing import Any

import torch
import torch.nn as nn
import torch.nn.functional as F

from editor012_rescue.models import (
    architecture_identity,
    assert_odst046,
    assert_teacher_student_match,
    clone_state,
    freeze_teacher,
    live_odst_forward,
    state_dict_sha256,
    student_forward as historical_student_forward,
)
from editor012_rescue.producing import build_odst046_model, load_state_dict

from .constants import ENCODER_DIM, LR_ALPHA, LR_ATTENTION, LR_ENCODER, LR_LINEAR, LR_ODST, LR_READOUT, N_TREES_TOTAL, WEIGHT_DECAY
from .safety import Editor013ProtocolError


class Editor013LinearHead(nn.Module):
    """Fresh EDITOR-013 linear head. Zero-init; not the stored T-OPT linear_head."""

    def __init__(self, in_dim: int = ENCODER_DIM) -> None:
        super().__init__()
        self.linear = nn.Linear(in_dim, 1)
        nn.init.zeros_(self.linear.weight)
        nn.init.zeros_(self.linear.bias)

    def forward(self, z: torch.Tensor) -> torch.Tensor:
        return self.linear(z).squeeze(-1)


class ConvexTreeReadout(nn.Module):
    """Global softmax tree weights. w=0 ⇒ uniform 1/J. No sample-dependent gates."""

    def __init__(self, n_trees: int = N_TREES_TOTAL) -> None:
        super().__init__()
        self.n_trees = int(n_trees)
        self.w = nn.Parameter(torch.zeros(self.n_trees))

    def tree_weights(self) -> torch.Tensor:
        return F.softmax(self.w, dim=0)

    def forward(self, tree_outputs: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        if tree_outputs.size(-1) != self.n_trees:
            raise Editor013ProtocolError(
                f"tree_outputs last dim {tree_outputs.size(-1)} != {self.n_trees}"
            )
        a = self.tree_weights()
        logit = (tree_outputs * a.unsqueeze(0)).sum(dim=-1)
        return logit, a


class HybridAlpha(nn.Module):
    """Global scalar residual scale. Initialised exactly 0."""

    def __init__(self) -> None:
        super().__init__()
        self.alpha = nn.Parameter(torch.zeros(()))

    def forward(self, linear_logit: torch.Tensor, odst_logit: torch.Tensor) -> torch.Tensor:
        return linear_logit + self.alpha * odst_logit


class Editor013Modules(nn.Module):
    """Detachable EDITOR-013 prediction modules attached to a frozen-schema student."""

    def __init__(
        self,
        *,
        family: str,
        readout: str,
        hybrid: bool,
        in_dim: int = ENCODER_DIM,
        n_trees: int = N_TREES_TOTAL,
    ) -> None:
        super().__init__()
        self.family = family
        self.readout = readout
        self.hybrid = bool(hybrid)
        self.linear_head = Editor013LinearHead(in_dim) if family in {"linear", "hybrid"} else None
        self.tree_readout = ConvexTreeReadout(n_trees) if readout == "weighted" else None
        self.alpha_mod = HybridAlpha() if hybrid else None

    def initial_linear_hash(self) -> str | None:
        if self.linear_head is None:
            return None
        return state_dict_sha256(self.linear_head.state_dict())

    def learned_tree_weights(self) -> list[float] | None:
        if self.tree_readout is None:
            return None
        with torch.no_grad():
            return [float(x) for x in self.tree_readout.tree_weights().detach().cpu().tolist()]

    def learned_alpha(self) -> float | None:
        if self.alpha_mod is None:
            return None
        return float(self.alpha_mod.alpha.detach().cpu().item())


def uniform_tree_logit(tree_outputs: torch.Tensor) -> torch.Tensor:
    return tree_outputs.mean(dim=-1)


def editor013_forward(
    student: nn.Module,
    x: torch.Tensor,
    modules: Editor013Modules,
) -> dict[str, torch.Tensor]:
    z, enc = student.encode_attention_h(x)
    historical_linear = enc["linear_logit"]
    if modules.family == "linear":
        assert modules.linear_head is not None
        linear_logit = modules.linear_head(z)
        zeros = linear_logit.new_zeros(linear_logit.shape)
        return {
            "logit": linear_logit,
            "linear_logit": linear_logit,
            "odst_logit": zeros,
            "historical_linear_logit": historical_linear,
            "z": z,
            "choices": z.new_zeros(z.size(0), N_TREES_TOTAL, 4),
            "leaf_probs": z.new_zeros(z.size(0), 4, 16),
            "leaf_probs_all": z.new_zeros(z.size(0), N_TREES_TOTAL, 16),
            "tree_outputs": z.new_zeros(z.size(0), N_TREES_TOTAL),
            "tree_weights": z.new_full((N_TREES_TOTAL,), 1.0 / N_TREES_TOTAL),
            "alpha": zeros,
            "attention_weights": enc["attention_weights"],
        }
    od = live_odst_forward(student.node_head, z)
    tree_outputs = od["tree_outputs"]

    if modules.readout == "weighted":
        assert modules.tree_readout is not None
        odst_logit, tree_w = modules.tree_readout(tree_outputs)
    else:
        odst_logit = uniform_tree_logit(tree_outputs)
        tree_w = tree_outputs.new_full((tree_outputs.size(-1),), 1.0 / tree_outputs.size(-1))

    if modules.linear_head is not None:
        linear_logit = modules.linear_head(z)
    else:
        linear_logit = historical_linear

    if modules.hybrid:
        assert modules.alpha_mod is not None
        final = modules.alpha_mod(linear_logit, odst_logit)
    else:
        final = odst_logit

    return {
        "logit": final,
        "linear_logit": linear_logit,
        "odst_logit": odst_logit,
        "historical_linear_logit": historical_linear,
        "z": z,
        "choices": od["choices"],
        "leaf_probs": od["leaf_probs"],
        "leaf_probs_all": od["leaf_probs_all"],
        "tree_outputs": tree_outputs,
        "tree_weights": tree_w,
        "alpha": (
            modules.alpha_mod.alpha.expand_as(final)
            if modules.alpha_mod is not None
            else final.new_zeros(final.shape)
        ),
        "attention_weights": enc["attention_weights"],
    }


def editor013_forward_from_z(
    student: nn.Module,
    z: torch.Tensor,
    modules: Editor013Modules,
) -> dict[str, torch.Tensor]:
    """Head-only forward on cached attended representation z."""
    if modules.family == "linear":
        assert modules.linear_head is not None
        linear_logit = modules.linear_head(z)
        zeros = linear_logit.new_zeros(linear_logit.shape)
        return {
            "logit": linear_logit,
            "linear_logit": linear_logit,
            "odst_logit": zeros,
            "z": z,
            "choices": z.new_zeros(z.size(0), N_TREES_TOTAL, 4),
            "leaf_probs": z.new_zeros(z.size(0), 4, 16),
            "leaf_probs_all": z.new_zeros(z.size(0), N_TREES_TOTAL, 16),
            "tree_outputs": z.new_zeros(z.size(0), N_TREES_TOTAL),
            "tree_weights": z.new_full((N_TREES_TOTAL,), 1.0 / N_TREES_TOTAL),
            "alpha": zeros,
        }
    od = live_odst_forward(student.node_head, z)
    tree_outputs = od["tree_outputs"]
    if modules.readout == "weighted":
        assert modules.tree_readout is not None
        odst_logit, tree_w = modules.tree_readout(tree_outputs)
    else:
        odst_logit = uniform_tree_logit(tree_outputs)
        tree_w = tree_outputs.new_full((tree_outputs.size(-1),), 1.0 / tree_outputs.size(-1))
    if modules.linear_head is not None:
        linear_logit = modules.linear_head(z)
    else:
        linear_logit = odst_logit.new_zeros(odst_logit.shape)
    if modules.hybrid:
        assert modules.alpha_mod is not None
        final = modules.alpha_mod(linear_logit, odst_logit)
    else:
        final = odst_logit
    return {
        "logit": final,
        "linear_logit": linear_logit,
        "odst_logit": odst_logit,
        "z": z,
        "choices": od["choices"],
        "leaf_probs": od["leaf_probs"],
        "leaf_probs_all": od["leaf_probs_all"],
        "tree_outputs": tree_outputs,
        "tree_weights": tree_w,
        "alpha": (
            modules.alpha_mod.alpha.expand_as(final)
            if modules.alpha_mod is not None
            else final.new_zeros(final.shape)
        ),
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
    modules: Editor013Modules,
    *,
    encoder_trainable: bool,
) -> None:
    for p in student.lstm.parameters():
        p.requires_grad = bool(encoder_trainable)
    for p in student.attention.parameters():
        p.requires_grad = bool(encoder_trainable)
    train_odst = modules.family in {"odst", "hybrid"}
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
    if modules.tree_readout is not None:
        for p in modules.tree_readout.parameters():
            p.requires_grad = True
    if modules.alpha_mod is not None:
        modules.alpha_mod.alpha.requires_grad = True


def build_editor013_optimizer(
    student: nn.Module,
    modules: Editor013Modules,
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
    if modules.tree_readout is not None:
        groups.append(
            {
                "params": list(modules.tree_readout.parameters()),
                "lr": LR_READOUT,
                "weight_decay": WEIGHT_DECAY,
            }
        )
    if modules.alpha_mod is not None:
        groups.append(
            {"params": [modules.alpha_mod.alpha], "lr": LR_ALPHA, "weight_decay": WEIGHT_DECAY}
        )
    if not groups:
        raise Editor013ProtocolError("no trainable EDITOR-013 parameter groups")
    return torch.optim.Adam(groups)


def make_modules(spec: dict[str, Any]) -> Editor013Modules:
    return Editor013Modules(
        family=str(spec["family"]),
        readout=str(spec.get("readout") or "none"),
        hybrid=bool(spec.get("hybrid", False)),
    )


def tree_contributions(
    tree_outputs: torch.Tensor,
    tree_weights: torch.Tensor,
    *,
    references: torch.Tensor | None = None,
    alpha: torch.Tensor | float = 1.0,
) -> torch.Tensor:
    """c_j = alpha * a_j * (t_j - reference_j). Weights are global, not sample-dependent."""
    if tree_weights.dim() == 1:
        a = tree_weights.unsqueeze(0)
    else:
        a = tree_weights
    centred = tree_outputs if references is None else tree_outputs - references.reshape(1, -1)
    scale = alpha if torch.is_tensor(alpha) else tree_outputs.new_tensor(float(alpha))
    if scale.dim() == 0:
        scale = scale.view(1, 1)
    elif scale.dim() == 1:
        scale = scale.view(-1, 1)
    return scale * a * centred
