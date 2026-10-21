"""Freeze/unfreeze schedules and differential optimizers for micro-runs."""

from __future__ import annotations

from typing import Any

import torch
import torch.nn as nn

from prototype_v3_node.architecture import AttentionNodeEnsemble

from .protocol import LR_ATTENTION, LR_ENCODER, LR_ODST, T2_SCHEDULE


def set_component_trainable(
    model: AttentionNodeEnsemble,
    *,
    lstm: bool,
    attention: bool,
    odst: bool,
) -> dict[str, bool]:
    for p in model.lstm.parameters():
        p.requires_grad = bool(lstm)
    for p in model.attention.parameters():
        p.requires_grad = bool(attention)
    for p in model.linear_head.parameters():
        p.requires_grad = False
    for p in model.node_head.parameters():
        p.requires_grad = bool(odst)
    # sparsemax sigmoid readout trains output_head with ODST
    if model.readout == "canonical_tree_average":
        for p in model.node_head.output_head.parameters():
            p.requires_grad = False
    model.residual_scale_logit.requires_grad = False
    for p in model.sample_gate.parameters():
        p.requires_grad = False
    model.dropout.requires_grad_(False)
    return {"lstm": bool(lstm), "attention": bool(attention), "odst": bool(odst)}


def flags_for_condition(condition: str, epoch: int) -> dict[str, bool]:
    if condition == "T0":
        return {"lstm": False, "attention": False, "odst": True}
    if condition in {"T1", "T3"}:
        return {"lstm": True, "attention": True, "odst": True}
    if condition == "T2":
        if epoch not in T2_SCHEDULE:
            raise KeyError(f"T2 schedule missing epoch {epoch}")
        return dict(T2_SCHEDULE[epoch])
    raise ValueError(f"Unknown condition {condition!r}")


def apply_schedule(model: AttentionNodeEnsemble, condition: str, epoch: int) -> dict[str, bool]:
    flags = flags_for_condition(condition, epoch)
    return set_component_trainable(model, **flags)


def build_optimizer(
    model: AttentionNodeEnsemble,
    condition: str,
    *,
    lr_lstm: float = LR_ENCODER,
    lr_attention: float = LR_ATTENTION,
    lr_odst: float = LR_ODST,
) -> tuple[torch.optim.Optimizer, dict[str, float]]:
    groups: list[dict[str, Any]] = []
    lrs: dict[str, float] = {}
    lstm_params = [p for p in model.lstm.parameters() if p.requires_grad]
    attn_params = [p for p in model.attention.parameters() if p.requires_grad]
    odst_params = [p for p in model.node_head.parameters() if p.requires_grad]
    if lstm_params:
        groups.append({"params": lstm_params, "lr": lr_lstm})
        lrs["lr_lstm"] = lr_lstm
    if attn_params:
        groups.append({"params": attn_params, "lr": lr_attention})
        lrs["lr_attention"] = lr_attention
    if odst_params:
        groups.append({"params": odst_params, "lr": lr_odst})
        lrs["lr_odst"] = lr_odst
    if not groups:
        raise RuntimeError(f"No trainable parameters for condition {condition}")
    return torch.optim.Adam(groups), lrs


def snapshot_requires_grad(model: AttentionNodeEnsemble) -> dict[str, bool]:
    return {
        "lstm_any": any(p.requires_grad for p in model.lstm.parameters()),
        "attention_any": any(p.requires_grad for p in model.attention.parameters()),
        "odst_any": any(p.requires_grad for p in model.node_head.parameters()),
        "linear_any": any(p.requires_grad for p in model.linear_head.parameters()),
    }


def assert_frozen_have_no_grad(model: AttentionNodeEnsemble) -> None:
    for name, p in model.named_parameters():
        if not p.requires_grad and p.grad is not None:
            raise RuntimeError(f"Unexpected gradient on frozen parameter {name}")
