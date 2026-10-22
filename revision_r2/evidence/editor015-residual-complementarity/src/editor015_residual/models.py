"""Function-preserving residual ODST. Initial output is exactly L1; ODST grads are not."""

from __future__ import annotations

import copy
from typing import Any

import torch
import torch.nn as nn

from editor012_rescue.models import live_odst_forward, state_dict_sha256
from editor013_odst_value.models import Editor013LinearHead, uniform_tree_logit

from .constants import ENCODER_DIM, LR_ATTENTION, LR_ENCODER, LR_LINEAR, LR_ODST, N_TREES_TOTAL, WEIGHT_DECAY
from .safety import Editor015Blocked, Editor015ProtocolError


def clone_frozen_odst(node_head: nn.Module) -> nn.Module:
    """Frozen reference copy g_theta0. requires_grad = FALSE for the entire campaign."""
    ref = copy.deepcopy(node_head)
    ref.eval()
    for p in ref.parameters():
        p.requires_grad = False
    return ref


def residual_odst_logit(live_logit: torch.Tensor, reference_logit: torch.Tensor) -> torch.Tensor:
    """r_theta(z) = g_theta(z) - stop_gradient(g_theta0(z))."""
    return live_logit - reference_logit.detach()


class Editor015Modules(nn.Module):
    """Matched L1 linear head plus a frozen ODST reference copy."""

    def __init__(self, in_dim: int = ENCODER_DIM) -> None:
        super().__init__()
        self.linear_head = Editor013LinearHead(in_dim)
        self.reference_odst: nn.Module | None = None

    def attach_reference(self, node_head: nn.Module) -> None:
        self.reference_odst = clone_frozen_odst(node_head)

    def initial_linear_hash(self) -> str:
        return state_dict_sha256(self.linear_head.state_dict())

    def reference_hash(self) -> str | None:
        if self.reference_odst is None:
            return None
        return state_dict_sha256(self.reference_odst.state_dict())


def editor015_forward(
    student: nn.Module,
    x: torch.Tensor,
    modules: Editor015Modules,
) -> dict[str, torch.Tensor]:
    z, enc = student.encode_attention_h(x)
    return editor015_forward_from_z(student, z, modules, historical_linear=enc["linear_logit"], enc=enc)


def editor015_forward_from_z(
    student: nn.Module,
    z: torch.Tensor,
    modules: Editor015Modules,
    *,
    historical_linear: torch.Tensor | None = None,
    enc: dict[str, torch.Tensor] | None = None,
) -> dict[str, torch.Tensor]:
    if modules.reference_odst is None:
        raise Editor015ProtocolError("frozen reference ODST is not attached")
    linear_logit = modules.linear_head(z)
    live = live_odst_forward(student.node_head, z)
    ref = live_odst_forward(modules.reference_odst, z)
    residual = residual_odst_logit(live["logit"], ref["logit"])
    final = linear_logit + residual
    zeros = final.new_zeros(final.shape)
    out = {
        "logit": final,
        "linear_logit": linear_logit,
        "odst_logit": live["logit"],
        "reference_odst_logit": ref["logit"].detach(),
        "residual_logit": residual,
        "historical_linear_logit": historical_linear if historical_linear is not None else zeros,
        "z": z,
        "choices": live["choices"],
        "leaf_probs": live["leaf_probs"],
        "leaf_probs_all": live["leaf_probs_all"],
        "tree_outputs": live["tree_outputs"],
        "reference_tree_outputs": ref["tree_outputs"].detach(),
        "tree_weights": z.new_full((N_TREES_TOTAL,), 1.0 / N_TREES_TOTAL),
    }
    if enc is not None:
        out["attention_weights"] = enc["attention_weights"]
        out["hidden_states"] = enc["hidden_states"]
    return out


def freeze_encoder_attention_linear(student: nn.Module, modules: Editor015Modules) -> None:
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
    for p in modules.linear_head.parameters():
        p.requires_grad = False
    if modules.reference_odst is not None:
        for p in modules.reference_odst.parameters():
            p.requires_grad = False


def configure_trainability(
    student: nn.Module,
    modules: Editor015Modules,
    *,
    encoder_trainable: bool,
    linear_trainable: bool,
) -> None:
    for p in student.lstm.parameters():
        p.requires_grad = bool(encoder_trainable)
    for p in student.attention.parameters():
        p.requires_grad = bool(encoder_trainable)
    for p in student.node_head.parameters():
        p.requires_grad = True
    for p in student.linear_head.parameters():
        p.requires_grad = False
    student.residual_scale_logit.requires_grad = False
    for p in student.sample_gate.parameters():
        p.requires_grad = False
    for p in modules.linear_head.parameters():
        p.requires_grad = bool(linear_trainable)
    if modules.reference_odst is not None:
        modules.reference_odst.eval()
        for p in modules.reference_odst.parameters():
            p.requires_grad = False


def build_editor015_optimizer(
    student: nn.Module,
    modules: Editor015Modules,
    *,
    encoder_trainable: bool,
    linear_trainable: bool,
) -> torch.optim.Optimizer:
    configure_trainability(
        student, modules, encoder_trainable=encoder_trainable, linear_trainable=linear_trainable
    )
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
    if linear_trainable:
        groups.append(
            {
                "params": list(modules.linear_head.parameters()),
                "lr": LR_LINEAR,
                "weight_decay": WEIGHT_DECAY,
            }
        )
    if not groups:
        raise Editor015ProtocolError("no trainable EDITOR-015 parameter groups")
    if modules.reference_odst is not None:
        ref_ids = {id(p) for p in modules.reference_odst.parameters()}
        for group in groups:
            for p in group["params"]:
                if id(p) in ref_ids:
                    raise Editor015Blocked("frozen reference ODST found in optimiser")
    return torch.optim.Adam(groups)


def make_modules() -> Editor015Modules:
    return Editor015Modules()


def r3_equivalent_to_r1_if_l1_frozen(l1_logit: torch.Tensor, residual: torch.Tensor, ensemble: torch.Tensor) -> bool:
    """MSE(L1+r, ens) == MSE(r, ens-L1) when L1 is the same tensor in both."""
    left = torch.mean((l1_logit + residual - ensemble) ** 2)
    right = torch.mean((residual - (ensemble - l1_logit)) ** 2)
    return bool(torch.allclose(left, right, atol=1e-8, rtol=1e-8))
