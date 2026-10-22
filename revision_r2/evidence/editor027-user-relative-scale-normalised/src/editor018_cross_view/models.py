"""Cross-view summary branches with function-preserving correction."""

from __future__ import annotations

import copy
from typing import Any

import torch
import torch.nn as nn
import torch.nn.functional as F

from editor012_rescue.models import live_odst_forward, state_dict_sha256
from editor012_rescue.producing import pin_producing_sources
from objective2_r52_same_information_baselines.models import ShallowMLP

from .constants import (
    LAMBDA_TEACHER,
    LR_ATTENTION,
    LR_BRANCH,
    LR_ENCODER,
    MLP40_DROPOUT,
    MLP40_HIDDEN,
    N_TREES_TOTAL,
    ODST40_SPEC,
    SUMMARY_DIM,
    WEIGHT_DECAY,
)
from .safety import Editor018Blocked, Editor018ProtocolError


def import_node_class():
    pin_producing_sources()
    from prototype_v3_node.odst import NODE  # noqa: WPS433

    return NODE


def build_odst40() -> nn.Module:
    node_cls = import_node_class()
    spec = dict(ODST40_SPEC)
    model = node_cls(
        in_dim=int(spec["in_dim"]),
        num_layers=int(spec["num_layers"]),
        n_trees=int(spec["n_trees"]),
        depth=int(spec["depth"]),
        tree_dim=int(spec["tree_dim"]),
        temperature=float(spec["temperature"]),
        dropout=float(spec["dropout"]),
        choice_function=str(spec["choice_function"]),
        readout=str(spec["readout"]),
        leaf_init_std=float(spec["leaf_init_std"]),
    )
    if int(model.in_dim) != SUMMARY_DIM:
        raise Editor018ProtocolError("ODST40 input dim must be 40")
    if int(model.num_layers) != 2 or int(model.n_trees) != 4 or int(model.depth) != 4:
        raise Editor018ProtocolError("ODST40 must match ODST-046 structural settings")
    if str(model.choice_function) != "sparsemax_sigmoid":
        raise Editor018ProtocolError("ODST40 requires sparsemax feature selection")
    if str(model.readout) != "canonical_tree_average":
        raise Editor018ProtocolError("ODST40 requires canonical tree-average readout")
    return model


class Linear40(nn.Module):
    def __init__(self, in_dim: int = SUMMARY_DIM) -> None:
        super().__init__()
        if in_dim != SUMMARY_DIM:
            raise Editor018ProtocolError("LIN40 input dim must be 40")
        self.linear = nn.Linear(in_dim, 1)
        nn.init.zeros_(self.linear.weight)
        nn.init.zeros_(self.linear.bias)

    def forward(self, s: torch.Tensor) -> torch.Tensor:
        return self.linear(s).squeeze(-1)


class InstanceWiseTreeGate(nn.Module):
    """a(s) = softmax(W_g s + b_g). Zero init ⇒ uniform 1/8. No hidden layer."""

    def __init__(self, in_dim: int = SUMMARY_DIM, n_trees: int = N_TREES_TOTAL) -> None:
        super().__init__()
        self.n_trees = int(n_trees)
        self.proj = nn.Linear(in_dim, self.n_trees)
        nn.init.zeros_(self.proj.weight)
        nn.init.zeros_(self.proj.bias)

    def forward(self, s: torch.Tensor) -> torch.Tensor:
        return F.softmax(self.proj(s), dim=-1)


def clone_frozen_branch(module: nn.Module) -> nn.Module:
    ref = copy.deepcopy(module)
    ref.eval()
    for p in ref.parameters():
        p.requires_grad = False
    return ref


class SummaryBranch(nn.Module):
    """Live branch plus frozen initial copy. correction = b - stop_grad(b0)."""

    def __init__(self, family: str) -> None:
        super().__init__()
        self.family = family
        if family == "LIN40":
            self.live = Linear40()
        elif family == "MLP40":
            self.live = ShallowMLP(in_dim=SUMMARY_DIM, hidden=list(MLP40_HIDDEN), dropout=MLP40_DROPOUT)
        elif family == "ODST40":
            self.live = build_odst40()
        elif family == "IWODST40":
            self.live = build_odst40()
            self.gate = InstanceWiseTreeGate()
        else:
            raise Editor018ProtocolError(f"unknown family {family}")
        if family != "IWODST40":
            self.gate = None  # type: ignore[assignment]
        self.reference = clone_frozen_branch(self.live)
        self.reference_gate = clone_frozen_branch(self.gate) if self.gate is not None else None

    def attach_reference_from_live(self) -> None:
        self.reference = clone_frozen_branch(self.live)
        if self.gate is not None:
            self.reference_gate = clone_frozen_branch(self.gate)

    def live_hash(self) -> str:
        return state_dict_sha256(self.live.state_dict())

    def reference_hash(self) -> str:
        return state_dict_sha256(self.reference.state_dict())


def _branch_forward(module: nn.Module, family: str, s: torch.Tensor, gate: nn.Module | None) -> dict[str, torch.Tensor]:
    zeros_trees = s.new_zeros(s.size(0), N_TREES_TOTAL)
    zeros_choices = s.new_zeros(s.size(0), N_TREES_TOTAL, 4)
    zeros_leaves = s.new_zeros(s.size(0), N_TREES_TOTAL, 16)
    uniform = s.new_full((s.size(0), N_TREES_TOTAL), 1.0 / N_TREES_TOTAL)
    if family == "LIN40":
        logit = module(s)
        return {
            "branch_logit": logit,
            "tree_outputs": zeros_trees,
            "choices": zeros_choices,
            "leaf_probs_all": zeros_leaves,
            "tree_weights": uniform,
            "feature_selection": [],
        }
    if family == "MLP40":
        logit = module(s)
        return {
            "branch_logit": logit,
            "tree_outputs": zeros_trees,
            "choices": zeros_choices,
            "leaf_probs_all": zeros_leaves,
            "tree_weights": uniform,
            "feature_selection": [],
        }
    od = live_odst_forward(module, s)
    trees = od["tree_outputs"]
    if family == "IWODST40":
        if gate is None:
            raise Editor018ProtocolError("IW-ODST40 requires an instance-wise gate")
        weights = gate(s)
        logit = (weights * trees).sum(dim=-1)
    else:
        weights = uniform
        logit = trees.mean(dim=-1)
    extras = []
    for layer in module.layers:
        extras.append(layer.feature_selection_probs())
    return {
        "branch_logit": logit,
        "tree_outputs": trees,
        "choices": od["choices"],
        "leaf_probs_all": od["leaf_probs_all"],
        "tree_weights": weights,
        "feature_selection": extras,
    }


def correction_from_pair(live_logit: torch.Tensor, reference_logit: torch.Tensor) -> torch.Tensor:
    return live_logit - reference_logit.detach()


def teacher_residual(ensemble_logit: torch.Tensor, l1_logit: torch.Tensor) -> torch.Tensor:
    return ensemble_logit.detach() - l1_logit.detach()


def cross_view_forward(
    branch: SummaryBranch,
    s: torch.Tensor,
    l1_logit: torch.Tensor,
) -> dict[str, torch.Tensor]:
    live = _branch_forward(branch.live, branch.family, s, branch.gate)
    with torch.no_grad():
        ref = _branch_forward(branch.reference, branch.family, s, branch.reference_gate)
    corr = correction_from_pair(live["branch_logit"], ref["branch_logit"])
    final = l1_logit + corr
    return {
        "logit": final,
        "l1_logit": l1_logit,
        "branch_logit": live["branch_logit"],
        "reference_logit": ref["branch_logit"].detach(),
        "correction": corr,
        "tree_outputs": live["tree_outputs"],
        "reference_tree_outputs": ref["tree_outputs"].detach(),
        "choices": live["choices"],
        "leaf_probs_all": live["leaf_probs_all"],
        "tree_weights": live["tree_weights"],
        "feature_selection": live["feature_selection"],
    }


def freeze_reference(branch: SummaryBranch) -> None:
    branch.reference.eval()
    for p in branch.reference.parameters():
        p.requires_grad = False
    if branch.reference_gate is not None:
        branch.reference_gate.eval()
        for p in branch.reference_gate.parameters():
            p.requires_grad = False


def configure_branch_trainability(branch: SummaryBranch) -> None:
    for p in branch.live.parameters():
        p.requires_grad = True
    if branch.gate is not None:
        for p in branch.gate.parameters():
            p.requires_grad = True
    freeze_reference(branch)


def build_branch_optimizer(branch: SummaryBranch) -> torch.optim.Optimizer:
    configure_branch_trainability(branch)
    params = [p for p in branch.live.parameters() if p.requires_grad]
    if branch.gate is not None:
        params.extend([p for p in branch.gate.parameters() if p.requires_grad])
    if not params:
        raise Editor018ProtocolError("no trainable summary-branch parameters")
    ref_ids = {id(p) for p in branch.reference.parameters()}
    if branch.reference_gate is not None:
        ref_ids.update(id(p) for p in branch.reference_gate.parameters())
    for p in params:
        if id(p) in ref_ids:
            raise Editor018Blocked("frozen initial branch found in optimiser")
    return torch.optim.Adam(params, lr=LR_BRANCH, weight_decay=WEIGHT_DECAY)


def build_e2e_optimizer(student: nn.Module, l1_modules: nn.Module, branch: SummaryBranch) -> torch.optim.Optimizer:
    configure_branch_trainability(branch)
    groups = []
    enc = [p for p in student.lstm.parameters() if True]
    att = [p for p in student.attention.parameters() if True]
    for p in student.lstm.parameters():
        p.requires_grad = True
    for p in student.attention.parameters():
        p.requires_grad = True
    for p in student.linear_head.parameters():
        p.requires_grad = False
    student.residual_scale_logit.requires_grad = False
    for p in student.sample_gate.parameters():
        p.requires_grad = False
    for p in student.node_head.parameters():
        p.requires_grad = False
    for p in l1_modules.parameters():
        p.requires_grad = True
    groups.append({"params": enc, "lr": LR_ENCODER, "weight_decay": WEIGHT_DECAY})
    groups.append({"params": att, "lr": LR_ATTENTION, "weight_decay": WEIGHT_DECAY})
    groups.append({"params": list(l1_modules.parameters()), "lr": LR_BRANCH, "weight_decay": WEIGHT_DECAY})
    branch_params = [p for p in branch.live.parameters() if p.requires_grad]
    if branch.gate is not None:
        branch_params.extend(p for p in branch.gate.parameters() if p.requires_grad)
    groups.append({"params": branch_params, "lr": LR_BRANCH, "weight_decay": WEIGHT_DECAY})
    return torch.optim.Adam(groups)


def prove_function_preserving(family: str, *, batch: int = 8) -> dict[str, Any]:
    torch.manual_seed(0)
    branch = SummaryBranch(family)
    configure_branch_trainability(branch)
    branch.eval()
    s = torch.randn(batch, SUMMARY_DIM)
    l1 = torch.randn(batch)
    s.requires_grad_(True)
    out = cross_view_forward(branch, s, l1)
    if not torch.allclose(out["logit"], l1, atol=1e-6, rtol=1e-6):
        raise Editor018Blocked(f"{family} initial final prediction is not exactly L1")
    if not torch.allclose(out["correction"], torch.zeros_like(out["correction"]), atol=1e-6, rtol=1e-6):
        raise Editor018Blocked(f"{family} initial correction is not zero")
    dummy = (out["branch_logit"] * torch.arange(1, batch + 1, dtype=out["branch_logit"].dtype)).sum()
    dummy.backward()
    live_grad = 0.0
    for p in branch.live.parameters():
        if p.grad is not None:
            live_grad += float(p.grad.detach().norm().item())
    if branch.gate is not None:
        for p in branch.gate.parameters():
            if p.grad is not None:
                live_grad += float(p.grad.detach().norm().item())
    ref_grad = 0.0
    for p in branch.reference.parameters():
        if p.grad is not None:
            ref_grad += float(p.grad.detach().norm().item())
        if p.requires_grad:
            raise Editor018Blocked(f"{family} frozen reference still requires grad")
    if branch.reference_gate is not None:
        for p in branch.reference_gate.parameters():
            if p.grad is not None:
                ref_grad += float(p.grad.detach().norm().item())
    if live_grad <= 0.0:
        raise Editor018Blocked(f"{family} trainable branch gradient norm is not > 0 at step zero")
    if ref_grad != 0.0:
        raise Editor018Blocked(f"{family} frozen initial branch received gradient")
    iw = None
    if family == "IWODST40":
        with torch.no_grad():
            w = branch.gate(s).detach()
        if not torch.allclose(w, torch.full_like(w, 1.0 / N_TREES_TOTAL), atol=1e-6):
            raise Editor018Blocked("IW-ODST initial tree weights are not exactly 1/8")
        if not torch.allclose(w.sum(dim=-1), torch.ones(batch), atol=1e-6):
            raise Editor018Blocked("IW weights do not sum to 1 per sequence")
        iw = [float(x) for x in w[0].tolist()]
    return {
        "family": family,
        "initial_final_equals_l1": True,
        "initial_correction_zero": True,
        "live_grad_norm": live_grad,
        "reference_grad_norm": ref_grad,
        "lambda_teacher": LAMBDA_TEACHER,
        "iw_initial_weights": iw,
    }
