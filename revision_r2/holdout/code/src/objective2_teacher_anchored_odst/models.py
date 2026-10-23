"""Teacher/student helpers and consistency losses with live ODST routing."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import torch
import torch.nn as nn
import torch.nn.functional as F

from prototype_v3_node.architecture import AttentionNodeEnsemble

from .config import ARCHITECTURE, LOGIT_VAR_EPS, ROUTE_EPS


def build_model(**kwargs: Any) -> AttentionNodeEnsemble:
    cfg = dict(ARCHITECTURE)
    cfg.update(kwargs)
    return AttentionNodeEnsemble(**cfg)


def load_checkpoint_into(model: AttentionNodeEnsemble, path: str | Path) -> dict[str, Any]:
    path = Path(path)
    payload = torch.load(path, map_location="cpu", weights_only=False)
    state = payload.get("model_state_dict", payload)
    missing, unexpected = model.load_state_dict(state, strict=False)
    return {
        "checkpoint": str(path),
        "n_state_keys": len(state),
        "missing_keys": list(missing),
        "unexpected_keys": list(unexpected),
    }


def freeze_teacher(teacher: AttentionNodeEnsemble) -> None:
    teacher.eval()
    for p in teacher.parameters():
        p.requires_grad = False


def enable_all_student_components(student: AttentionNodeEnsemble) -> dict[str, bool]:
    """Genuine end-to-end: encoder, attention, ODST all trainable; unused heads frozen."""
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
    return {"lstm": True, "attention": True, "odst": True}


def build_student_optimizer(student: AttentionNodeEnsemble, lrs: dict[str, float]) -> tuple[torch.optim.Optimizer, dict[str, float]]:
    groups = []
    used = {}
    mapping = [
        ("lstm", student.lstm.parameters(), "lr_encoder"),
        ("attention", student.attention.parameters(), "lr_attention"),
        ("odst", student.node_head.parameters(), "lr_odst"),
    ]
    for _name, params, key in mapping:
        plist = [p for p in params if p.requires_grad]
        if plist:
            groups.append({"params": plist, "lr": lrs[key]})
            used[key] = lrs[key]
    if not groups:
        raise RuntimeError("No student trainable groups")
    # Teacher must never appear in optimiser.
    return torch.optim.Adam(groups), used


def assert_teacher_not_in_optimizer(teacher: AttentionNodeEnsemble, optimizer: torch.optim.Optimizer) -> None:
    teacher_ids = {id(p) for p in teacher.parameters()}
    for group in optimizer.param_groups:
        for p in group["params"]:
            if id(p) in teacher_ids:
                raise RuntimeError("Teacher parameter found in optimiser group")


def live_odst_forward(node_head: nn.Module, h: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """Forward ODST with live (non-detached) routing choices for consistency loss.

    Returns:
        logit: (B,)
        choices: (B, n_layers * n_trees, depth) concatenated soft Bernoulli routes
        leaf_probs_first: (B, n_trees, n_leaves) first-layer leaf probs (for diagnostics)
    """
    if node_head.readout != "canonical_tree_average":
        raise ValueError("Teacher-anchored study requires canonical_tree_average readout")
    x = h
    live_choices: list[torch.Tensor] = []
    tree_bags: list[torch.Tensor] = []
    first_leaf = None
    for layer in node_head.layers:
        feature_probs = layer.feature_selection_probs()
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
        if first_leaf is None:
            first_leaf = leaf_probs
        x = torch.cat([x, out], dim=-1)
    logit = torch.cat(tree_bags, dim=-1).mean(dim=-1)
    choices = torch.cat(live_choices, dim=1)  # (B, L*T, D)
    assert first_leaf is not None
    return logit, choices, first_leaf


def student_forward_with_routing(student: AttentionNodeEnsemble, x: torch.Tensor) -> dict[str, torch.Tensor]:
    z, enc = student.encode_attention_h(x)
    logit, choices, leaf = live_odst_forward(student.node_head, z)
    return {
        "logit": logit,
        "z": z,
        "choices": choices,
        "leaf_probs": leaf,
        "attention_weights": enc["attention_weights"],
    }


@torch.no_grad()
def teacher_forward_with_routing(teacher: AttentionNodeEnsemble, x: torch.Tensor) -> dict[str, torch.Tensor]:
    teacher.eval()
    z, enc = teacher.encode_attention_h(x)
    logit, choices, leaf = live_odst_forward(teacher.node_head, z)
    return {
        "logit": logit,
        "z": z,
        "choices": choices,
        "leaf_probs": leaf,
        "attention_weights": enc["attention_weights"],
    }


def logit_consistency_loss(student_logit: torch.Tensor, teacher_logit: torch.Tensor) -> torch.Tensor:
    diff = (student_logit - teacher_logit.detach()).pow(2).mean()
    var = teacher_logit.detach().var(unbiased=False) + LOGIT_VAR_EPS
    return diff / var


def route_consistency_loss(student_p: torch.Tensor, teacher_p: torch.Tensor, eps: float = ROUTE_EPS) -> torch.Tensor:
    """Bernoulli KL mean: p_T log(p_T/p_S) + (1-p_T) log((1-p_T)/(1-p_S))."""
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
    return class_loss + w_logit * logit_loss + w_route * route_loss
