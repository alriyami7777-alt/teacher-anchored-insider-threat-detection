"""Live ODST routing forwards, residual head, and trainability helpers."""

from __future__ import annotations

from typing import Any

import torch
import torch.nn as nn

from .safety import Editor009ProtocolError


def live_odst_forward(node_head: nn.Module, h: torch.Tensor) -> dict[str, torch.Tensor]:
    if node_head.readout != "canonical_tree_average":
        raise Editor009ProtocolError("requires canonical_tree_average readout")
    x = h
    live_choices: list[torch.Tensor] = []
    tree_bags: list[torch.Tensor] = []
    leaf_bags: list[torch.Tensor] = []
    feature_ents: list[torch.Tensor] = []
    first_leaf = None
    for layer in node_head.layers:
        feature_probs = layer.feature_selection_probs()
        feat_ent = -(feature_probs.clamp_min(1e-8) * feature_probs.clamp_min(1e-8).log()).sum(dim=-1)
        feature_ents.append(feat_ent)
        selected = torch.einsum("bf,tdf->btd", x, feature_probs)
        choice = layer.split_choice(selected)
        batch = x.size(0)
        c = choice.unsqueeze(2).expand(batch, layer.n_trees, layer.n_leaves, layer.depth)
        codes = layer.leaf_codes.view(1, 1, layer.n_leaves, layer.depth)
        log_c = torch.log(c.clamp(1e-8, 1.0 - 1e-8))
        log_1mc = torch.log((1.0 - c).clamp(1e-8, 1.0))
        leaf_probs = torch.exp((codes * log_c + (1.0 - codes) * log_1mc).sum(dim=-1))
        response = torch.einsum("btl,tlu->btu", leaf_probs, layer.leaf_responses)
        out = response.reshape(batch, layer.n_trees * layer.tree_dim)
        live_choices.append(choice)
        tree_bags.append(out)
        leaf_bags.append(leaf_probs)
        if first_leaf is None:
            first_leaf = leaf_probs
        x = torch.cat([x, out], dim=-1)
    tree_cat = torch.cat(tree_bags, dim=-1)
    logit = tree_cat.mean(dim=-1)
    assert first_leaf is not None
    return {
        "logit": logit,
        "choices": torch.cat(live_choices, dim=1),
        "leaf_probs": first_leaf,
        "leaf_probs_all": torch.cat(leaf_bags, dim=1),
        "tree_outputs": tree_cat,
        "feature_selector_entropy": torch.stack(feature_ents).mean(),
    }


def student_forward(student: nn.Module, x: torch.Tensor, *, residual: bool = False) -> dict[str, torch.Tensor]:
    z, enc = student.encode_attention_h(x)
    od = live_odst_forward(student.node_head, z)
    linear_logit = enc["linear_logit"]
    if residual:
        final = linear_logit + od["logit"]
    else:
        final = od["logit"]
    return {
        "logit": final,
        "odst_logit": od["logit"],
        "linear_logit": linear_logit,
        "z": z,
        "choices": od["choices"],
        "leaf_probs": od["leaf_probs"],
        "leaf_probs_all": od["leaf_probs_all"],
        "tree_outputs": od["tree_outputs"],
        "attention_weights": enc["attention_weights"],
        "feature_selector_entropy": od["feature_selector_entropy"],
    }


@torch.no_grad()
def teacher_forward(teacher: nn.Module, x: torch.Tensor) -> dict[str, torch.Tensor]:
    teacher.eval()
    return student_forward(teacher, x, residual=False)


def freeze_teacher(teacher: nn.Module) -> None:
    teacher.eval()
    for p in teacher.parameters():
        p.requires_grad = False


def enable_c5_student(student: nn.Module) -> None:
    for p in student.lstm.parameters():
        p.requires_grad = True
    for p in student.attention.parameters():
        p.requires_grad = True
    for p in student.node_head.parameters():
        p.requires_grad = True
    for p in student.linear_head.parameters():
        p.requires_grad = False
    student.residual_scale_logit.requires_grad = False
    for p in student.sample_gate.parameters():
        p.requires_grad = False


def enable_residual_head_only(student: nn.Module) -> None:
    for p in student.lstm.parameters():
        p.requires_grad = False
    for p in student.attention.parameters():
        p.requires_grad = False
    for p in student.linear_head.parameters():
        p.requires_grad = False
    for p in student.node_head.parameters():
        p.requires_grad = True
    student.residual_scale_logit.requires_grad = False
    for p in student.sample_gate.parameters():
        p.requires_grad = False


def enable_residual_e2e(student: nn.Module) -> None:
    for p in student.lstm.parameters():
        p.requires_grad = True
    for p in student.attention.parameters():
        p.requires_grad = True
    for p in student.linear_head.parameters():
        p.requires_grad = True
    for p in student.node_head.parameters():
        p.requires_grad = True
    student.residual_scale_logit.requires_grad = False
    for p in student.sample_gate.parameters():
        p.requires_grad = False


def zero_odst_leaves(student: nn.Module) -> None:
    with torch.no_grad():
        for layer in student.node_head.layers:
            layer.leaf_responses.zero_()


def transfer_attention_linear(student: nn.Module, al_state: dict[str, torch.Tensor]) -> dict[str, int]:
    own = student.state_dict()
    mapped = {}
    n_lstm = n_attn = n_lin = 0
    for k, v in al_state.items():
        if k.startswith("lstm.") and k in own and own[k].shape == v.shape:
            mapped[k] = v
            n_lstm += 1
        elif k.startswith("attention.") and k in own and own[k].shape == v.shape:
            mapped[k] = v
            n_attn += 1
        elif k.startswith("linear_head.") and k in own and own[k].shape == v.shape:
            mapped[k] = v
            n_lin += 1
    missing, unexpected = student.load_state_dict(mapped, strict=False)
    if n_lstm == 0 or n_attn == 0 or n_lin == 0:
        raise Editor009ProtocolError(
            f"attention-linear transfer incomplete lstm={n_lstm} attn={n_attn} linear={n_lin}"
        )
    return {
        "n_lstm": n_lstm,
        "n_attention": n_attn,
        "n_linear": n_lin,
        "n_missing": len(missing),
        "n_unexpected": len(unexpected),
    }


def build_optimizer(student: nn.Module, lrs: dict[str, float]) -> torch.optim.Optimizer:
    groups = []
    mapping = [
        (student.lstm.parameters(), "lr_encoder"),
        (student.attention.parameters(), "lr_attention"),
        (student.node_head.parameters(), "lr_odst"),
        (student.linear_head.parameters(), "lr_attention"),
    ]
    for params, key in mapping:
        plist = [p for p in params if p.requires_grad]
        if plist:
            groups.append({"params": plist, "lr": lrs[key]})
    if not groups:
        raise Editor009ProtocolError("no trainable parameter groups")
    return torch.optim.Adam(groups)


def permute_tree_choices(choices: torch.Tensor, perm: torch.Tensor) -> torch.Tensor:
    """Permute tree index on dim=1. choices: (B, L*T, D)."""
    return choices.index_select(1, perm)
