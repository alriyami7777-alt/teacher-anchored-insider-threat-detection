"""Live ODST routing, teacher/student helpers, and optimiser construction."""

from __future__ import annotations

import hashlib
from typing import Any

import torch
import torch.nn as nn

from .constants import LR_ATTENTION, LR_ENCODER, LR_ODST, WEIGHT_DECAY
from .safety import Editor012Blocked, Editor012ProtocolError


def live_odst_forward(node_head: nn.Module, h: torch.Tensor) -> dict[str, torch.Tensor]:
    if node_head.readout != "canonical_tree_average":
        raise Editor012ProtocolError("requires canonical_tree_average readout")
    x = h
    live_choices: list[torch.Tensor] = []
    tree_bags: list[torch.Tensor] = []
    leaf_bags: list[torch.Tensor] = []
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
    }


def student_forward(student: nn.Module, x: torch.Tensor) -> dict[str, torch.Tensor]:
    z, enc = student.encode_attention_h(x)
    od = live_odst_forward(student.node_head, z)
    return {
        "logit": od["logit"],
        "linear_logit": enc["linear_logit"],
        "z": z,
        "choices": od["choices"],
        "leaf_probs": od["leaf_probs"],
        "leaf_probs_all": od["leaf_probs_all"],
        "tree_outputs": od["tree_outputs"],
        "attention_weights": enc["attention_weights"],
    }


@torch.no_grad()
def teacher_forward(teacher: nn.Module, x: torch.Tensor) -> dict[str, torch.Tensor]:
    teacher.eval()
    return student_forward(teacher, x)


def freeze_teacher(teacher: nn.Module) -> None:
    teacher.eval()
    for p in teacher.parameters():
        p.requires_grad = False


def enable_student(student: nn.Module) -> None:
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


def build_student_optimizer(student: nn.Module) -> torch.optim.Optimizer:
    groups = []
    mapping = [
        (student.lstm.parameters(), LR_ENCODER),
        (student.attention.parameters(), LR_ATTENTION),
        (student.node_head.parameters(), LR_ODST),
    ]
    for params, lr in mapping:
        plist = [p for p in params if p.requires_grad]
        if plist:
            groups.append({"params": plist, "lr": lr, "weight_decay": WEIGHT_DECAY})
    if not groups:
        raise Editor012ProtocolError("no trainable student parameter groups")
    return torch.optim.Adam(groups)


def assert_teacher_not_in_optimizer(teacher: nn.Module, optimizer: torch.optim.Optimizer) -> None:
    teacher_ids = {id(p) for p in teacher.parameters()}
    for group in optimizer.param_groups:
        for p in group["params"]:
            if id(p) in teacher_ids:
                raise Editor012Blocked("Teacher parameter found in student optimiser")


def architecture_identity(model: nn.Module) -> dict[str, Any]:
    return {
        "n_trees": int(model.node_n_trees),
        "depth": int(model.node_depth),
        "temperature": float(model.node_temperature),
        "num_layers": int(model.node_num_layers),
        "tree_dim": int(model.node_tree_dim),
        "choice_function": str(model.choice_function),
        "readout": str(model.readout),
        "fusion_variant": str(model.fusion_variant),
        "n_trees_total": int(model.node_num_layers) * int(model.node_n_trees),
    }


def assert_odst046(model: nn.Module) -> None:
    ident = architecture_identity(model)
    if ident["n_trees"] != 4 or ident["depth"] != 4 or abs(ident["temperature"] - 0.5) > 1e-12:
        raise Editor012Blocked(f"EDITOR012_BLOCKED ODST-046 mismatch: {ident}")
    if ident["num_layers"] != 2 or ident["choice_function"] != "sparsemax_sigmoid":
        raise Editor012Blocked(f"EDITOR012_BLOCKED inherited ODST mismatch: {ident}")


def assert_teacher_student_match(teacher: nn.Module, student: nn.Module) -> None:
    t = architecture_identity(teacher)
    s = architecture_identity(student)
    if t != s:
        raise Editor012Blocked(f"EDITOR012_BLOCKED architecture mismatch teacher={t} student={s}")


def state_dict_sha256(state: dict[str, torch.Tensor]) -> str:
    digest = hashlib.sha256()
    for key in sorted(state):
        digest.update(key.encode("utf-8"))
        tensor = state[key].detach().cpu().contiguous()
        digest.update(str(tuple(tensor.shape)).encode("utf-8"))
        digest.update(tensor.numpy().tobytes())
    return digest.hexdigest()


def clone_state(model: nn.Module) -> dict[str, torch.Tensor]:
    return {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
