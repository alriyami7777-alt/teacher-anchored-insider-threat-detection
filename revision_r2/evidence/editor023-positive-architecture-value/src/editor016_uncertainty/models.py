"""Function-preserving linear and ODST residual specialists. Initial delta is exactly 0."""

from __future__ import annotations

from typing import Any

import torch
import torch.nn as nn

from editor012_rescue.models import live_odst_forward, state_dict_sha256
from editor013_odst_value.models import Editor013LinearHead
from editor015_residual.models import clone_frozen_odst, residual_odst_logit

from .constants import ENCODER_DIM, LR_ATTENTION, LR_ENCODER, LR_LINEAR, LR_ODST, N_TREES_TOTAL, WEIGHT_DECAY
from .safety import Editor016Blocked, Editor016ProtocolError


class Editor016Modules(nn.Module):
    """Matched L1 linear base plus a zero-init linear residual and optional frozen ODST reference."""

    def __init__(self, *, head: str, in_dim: int = ENCODER_DIM) -> None:
        super().__init__()
        if head not in {"linear", "odst"}:
            raise Editor016ProtocolError(f"unknown specialist head {head!r}")
        self.head = head
        self.linear_base = Editor013LinearHead(in_dim)
        self.linear_residual = Editor013LinearHead(in_dim)
        self.reference_odst: nn.Module | None = None

    def attach_reference(self, node_head: nn.Module) -> None:
        self.reference_odst = clone_frozen_odst(node_head)

    def initial_linear_hash(self) -> str:
        return state_dict_sha256(self.linear_head_state())

    def linear_head_state(self) -> dict[str, torch.Tensor]:
        return self.linear_base.state_dict()

    def reference_hash(self) -> str | None:
        if self.reference_odst is None:
            return None
        return state_dict_sha256(self.reference_odst.state_dict())


def make_modules(head: str) -> Editor016Modules:
    return Editor016Modules(head=head)


def editor016_forward(
    student: nn.Module,
    x: torch.Tensor,
    modules: Editor016Modules,
    *,
    gate: torch.Tensor,
    source_l1: torch.Tensor | None = None,
    use_source_l1: bool = False,
) -> dict[str, torch.Tensor]:
    z, enc = student.encode_attention_h(x)
    return editor016_forward_from_z(
        student,
        z,
        modules,
        gate=gate,
        source_l1=source_l1,
        use_source_l1=use_source_l1,
        historical_linear=enc["linear_logit"],
        enc=enc,
    )


def editor016_forward_from_z(
    student: nn.Module,
    z: torch.Tensor,
    modules: Editor016Modules,
    *,
    gate: torch.Tensor,
    source_l1: torch.Tensor | None = None,
    use_source_l1: bool = False,
    historical_linear: torch.Tensor | None = None,
    enc: dict[str, torch.Tensor] | None = None,
    teacher_choices: torch.Tensor | None = None,
) -> dict[str, torch.Tensor]:
    g = gate.reshape(-1).to(dtype=z.dtype)
    live_l1 = modules.linear_base(z)
    if use_source_l1:
        if source_l1 is None:
            raise Editor016ProtocolError("source L1 logits required when use_source_l1=True")
        l1_logit = source_l1.reshape(-1).to(dtype=z.dtype)
    else:
        l1_logit = live_l1
    zeros = l1_logit.new_zeros(l1_logit.shape)
    if modules.head == "linear":
        delta = modules.linear_residual(z)
        live = {
            "logit": zeros,
            "choices": z.new_zeros((z.size(0), 1, 1)),
            "leaf_probs": z.new_zeros((z.size(0), 1, 1)),
            "leaf_probs_all": z.new_zeros((z.size(0), 1, 1)),
            "tree_outputs": z.new_zeros((z.size(0), N_TREES_TOTAL)),
        }
        ref_logit = zeros
        ref_trees = live["tree_outputs"]
    else:
        if modules.reference_odst is None:
            raise Editor016ProtocolError("frozen reference ODST is not attached")
        live = live_odst_forward(student.node_head, z)
        ref = live_odst_forward(modules.reference_odst, z)
        delta = residual_odst_logit(live["logit"], ref["logit"])
        ref_logit = ref["logit"].detach()
        ref_trees = ref["tree_outputs"].detach()
    final = l1_logit + g * delta
    out = {
        "logit": final,
        "linear_logit": l1_logit,
        "live_l1_logit": live_l1,
        "source_l1_logit": source_l1.reshape(-1) if source_l1 is not None else l1_logit.detach(),
        "delta": delta,
        "gate": g,
        "odst_logit": live["logit"],
        "reference_odst_logit": ref_logit,
        "residual_logit": delta,
        "historical_linear_logit": historical_linear if historical_linear is not None else zeros,
        "z": z,
        "choices": live["choices"],
        "leaf_probs": live["leaf_probs"],
        "leaf_probs_all": live["leaf_probs_all"],
        "tree_outputs": live["tree_outputs"],
        "reference_tree_outputs": ref_trees,
        "tree_weights": z.new_full((N_TREES_TOTAL,), 1.0 / N_TREES_TOTAL),
        "teacher_choices": teacher_choices,
    }
    if enc is not None:
        out["attention_weights"] = enc["attention_weights"]
        out["hidden_states"] = enc["hidden_states"]
    return out


def configure_trainability(
    student: nn.Module,
    modules: Editor016Modules,
    *,
    encoder_trainable: bool,
    linear_base_trainable: bool,
) -> None:
    for p in student.lstm.parameters():
        p.requires_grad = bool(encoder_trainable)
    for p in student.attention.parameters():
        p.requires_grad = bool(encoder_trainable)
    for p in student.linear_head.parameters():
        p.requires_grad = False
    student.residual_scale_logit.requires_grad = False
    for p in student.sample_gate.parameters():
        p.requires_grad = False
    for p in modules.linear_base.parameters():
        p.requires_grad = bool(linear_base_trainable)
    if modules.head == "linear":
        for p in student.node_head.parameters():
            p.requires_grad = False
        for p in modules.linear_residual.parameters():
            p.requires_grad = True
    else:
        for p in student.node_head.parameters():
            p.requires_grad = True
        for p in modules.linear_residual.parameters():
            p.requires_grad = False
    if modules.reference_odst is not None:
        modules.reference_odst.eval()
        for p in modules.reference_odst.parameters():
            p.requires_grad = False


def build_editor016_optimizer(
    student: nn.Module,
    modules: Editor016Modules,
    *,
    encoder_trainable: bool,
    linear_base_trainable: bool,
) -> torch.optim.Optimizer:
    configure_trainability(
        student,
        modules,
        encoder_trainable=encoder_trainable,
        linear_base_trainable=linear_base_trainable,
    )
    groups = []
    if encoder_trainable:
        enc = [p for p in student.lstm.parameters() if p.requires_grad]
        att = [p for p in student.attention.parameters() if p.requires_grad]
        if enc:
            groups.append({"params": enc, "lr": LR_ENCODER, "weight_decay": WEIGHT_DECAY})
        if att:
            groups.append({"params": att, "lr": LR_ATTENTION, "weight_decay": WEIGHT_DECAY})
    if modules.head == "odst":
        odst = [p for p in student.node_head.parameters() if p.requires_grad]
        if odst:
            groups.append({"params": odst, "lr": LR_ODST, "weight_decay": WEIGHT_DECAY})
    if modules.head == "linear":
        groups.append(
            {
                "params": list(modules.linear_residual.parameters()),
                "lr": LR_LINEAR,
                "weight_decay": WEIGHT_DECAY,
            }
        )
    if linear_base_trainable:
        groups.append(
            {
                "params": list(modules.linear_base.parameters()),
                "lr": LR_LINEAR,
                "weight_decay": WEIGHT_DECAY,
            }
        )
    if not groups:
        raise Editor016ProtocolError("no trainable EDITOR-016 parameter groups")
    if modules.reference_odst is not None:
        ref_ids = {id(p) for p in modules.reference_odst.parameters()}
        for group in groups:
            for p in group["params"]:
                if id(p) in ref_ids:
                    raise Editor016Blocked("frozen reference ODST found in optimiser")
    return torch.optim.Adam(groups)


def specialist_param_grad_norm(student: nn.Module, modules: Editor016Modules) -> float:
    params = (
        list(modules.linear_residual.parameters())
        if modules.head == "linear"
        else list(student.node_head.parameters())
    )
    total = 0.0
    for p in params:
        if p.grad is not None:
            total += float(p.grad.detach().pow(2).sum().item())
    return total ** 0.5


def reference_grad_l1(modules: Editor016Modules) -> float:
    if modules.reference_odst is None:
        return 0.0
    total = 0.0
    for p in modules.reference_odst.parameters():
        if p.grad is not None:
            total += float(p.grad.detach().abs().sum().item())
    return total
