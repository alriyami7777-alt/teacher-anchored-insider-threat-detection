"""Signed-oblique ODST, node-specific DTE, and function-preserving corrections."""

from __future__ import annotations

import copy
from typing import Any

import torch
import torch.nn as nn
import torch.nn.functional as F

from editor012_rescue.models import live_odst_forward, state_dict_sha256
from editor012_rescue.producing import pin_producing_sources
from editor018_cross_view.models import SummaryBranch as Editor018SummaryBranch
from editor018_cross_view.models import build_odst40, teacher_residual
from objective2_r52_same_information_baselines.models import ShallowMLP
from prototype_v3_node.odst import sparsemax

from .capacity import select_tree_count
from .constants import (
    LAMBDA_TEACHER,
    LR_BRANCH,
    MLP40_DROPOUT,
    MLP40_HIDDEN,
    N_INTERNAL_NODES,
    N_LEAVES,
    N_TREES_TOTAL,
    SIGNED_DIM,
    SO_ODST40_SPEC,
    SUMMARY_DIM,
    TREE_DEPTH,
    WEIGHT_DECAY,
)
from .safety import Editor019Blocked, Editor019ProtocolError


def import_node_class():
    pin_producing_sources()
    from prototype_v3_node.odst import NODE  # noqa: WPS433

    return NODE


def signed_channels(s: torch.Tensor) -> torch.Tensor:
    if s.dim() != 2 or s.size(-1) != SUMMARY_DIM:
        raise Editor019ProtocolError(f"expected (B, {SUMMARY_DIM}); got {tuple(s.shape)}")
    return torch.cat([s, -s], dim=-1)


def signed_coefficients_from_probs(probs: torch.Tensor) -> torch.Tensor:
    """v_i = p_i_positive - p_i_negative for an 80-channel sparsemax selector."""
    if probs.size(-1) != SIGNED_DIM:
        raise Editor019ProtocolError(f"signed selector must be {SIGNED_DIM}-D; got {tuple(probs.shape)}")
    pos, neg = probs[..., :SUMMARY_DIM], probs[..., SUMMARY_DIM:]
    return pos - neg


def build_so_odst40() -> nn.Module:
    node_cls = import_node_class()
    spec = dict(SO_ODST40_SPEC)
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
    if int(model.in_dim) != SIGNED_DIM:
        raise Editor019ProtocolError("SO-ODST40 input dim must be 80 signed channels")
    if int(model.num_layers) != 2 or int(model.n_trees) != 4 or int(model.depth) != 4:
        raise Editor019ProtocolError("SO-ODST40 must retain ODST40 structural settings")
    if str(model.choice_function) != "sparsemax_sigmoid":
        raise Editor019ProtocolError("SO-ODST40 requires the same sparsemax selector")
    if str(model.readout) != "canonical_tree_average":
        raise Editor019ProtocolError("SO-ODST40 requires canonical tree-average readout")
    return model


class SparseObliqueTree(nn.Module):
    """One depth-4 differentiable tree with node-specific signed sparse splits."""

    def __init__(
        self,
        in_dim: int = SUMMARY_DIM,
        depth: int = TREE_DEPTH,
        temperature: float = 0.5,
        leaf_init_std: float = 0.05,
    ) -> None:
        super().__init__()
        if in_dim != SUMMARY_DIM or depth != TREE_DEPTH:
            raise Editor019ProtocolError("SO-DTE trees are frozen at 40 features and depth 4")
        self.in_dim = int(in_dim)
        self.depth = int(depth)
        self.n_internal = N_INTERNAL_NODES
        self.n_leaves = N_LEAVES
        self.signed_dim = SIGNED_DIM
        self.feature_logits = nn.Parameter(torch.empty(self.n_internal, self.signed_dim))
        self.thresholds = nn.Parameter(torch.zeros(self.n_internal))
        self.log_temperatures = nn.Parameter(
            torch.full((self.n_internal,), float(torch.log(torch.tensor(temperature))))
        )
        self.leaf_responses = nn.Parameter(torch.empty(self.n_leaves))
        nn.init.xavier_uniform_(self.feature_logits)
        nn.init.normal_(self.leaf_responses, mean=0.0, std=float(leaf_init_std))

    def temperatures(self) -> torch.Tensor:
        return F.softplus(self.log_temperatures) + 1e-4

    def feature_selection_probs(self) -> torch.Tensor:
        return sparsemax(self.feature_logits, dim=-1)

    def signed_feature_coefficients(self) -> torch.Tensor:
        return signed_coefficients_from_probs(self.feature_selection_probs())

    def forward(self, s: torch.Tensor) -> tuple[torch.Tensor, dict[str, torch.Tensor]]:
        x = signed_channels(s)
        probs = self.feature_selection_probs()
        selected = torch.einsum("bf,nf->bn", x, probs)
        choice = torch.sigmoid((selected - self.thresholds) / self.temperatures())
        route = s.new_ones(s.size(0), 1)
        for d in range(self.depth):
            start = 2**d - 1
            n_nodes = 2**d
            c = choice[:, start : start + n_nodes]
            left = route * (1.0 - c)
            right = route * c
            route = torch.stack((left, right), dim=-1).reshape(s.size(0), n_nodes * 2)
        leaf_probs = route
        response = (leaf_probs * self.leaf_responses.unsqueeze(0)).sum(dim=-1)
        extras = {
            "feature_selection_probs": probs,
            "signed_coefficients": signed_coefficients_from_probs(probs),
            "thresholds": self.thresholds,
            "temperatures": self.temperatures(),
            "choice": choice,
            "leaf_probs": leaf_probs,
            "tree_response": response,
        }
        return response, extras


class SparseObliqueForest(nn.Module):
    """Jointly trained mean ensemble of node-specific signed oblique trees."""

    def __init__(self, n_trees: int, *, combine: str = "mean") -> None:
        super().__init__()
        if n_trees < 1:
            raise Editor019ProtocolError("forest must contain at least one tree")
        self.n_trees = int(n_trees)
        self.combine = combine
        if combine not in {"mean", "sum"}:
            raise Editor019ProtocolError(f"unknown forest combine {combine}")
        self.trees = nn.ModuleList([SparseObliqueTree() for _ in range(self.n_trees)])

    def forward(self, s: torch.Tensor) -> dict[str, torch.Tensor]:
        responses = []
        choices = []
        leaves = []
        coeffs = []
        for tree in self.trees:
            resp, ex = tree(s)
            responses.append(resp)
            choices.append(ex["choice"])
            leaves.append(ex["leaf_probs"])
            coeffs.append(ex["signed_coefficients"])
        trees = torch.stack(responses, dim=-1)
        logit = trees.mean(dim=-1) if self.combine == "mean" else trees.sum(dim=-1)
        return {
            "branch_logit": logit,
            "tree_outputs": trees,
            "choices": torch.stack(choices, dim=1),
            "leaf_probs_all": torch.stack(leaves, dim=1),
            "signed_coefficients": torch.stack(coeffs, dim=0),
        }


def clone_frozen_branch(module: nn.Module) -> nn.Module:
    ref = copy.deepcopy(module)
    ref.eval()
    for p in ref.parameters():
        p.requires_grad = False
    return ref


class SummaryBranch(nn.Module):
    """Live branch plus frozen initial copy. correction = b - stop_grad(b0)."""

    def __init__(self, family: str, *, n_trees: int | None = None) -> None:
        super().__init__()
        self.family = family
        self.n_trees = int(n_trees) if n_trees is not None else 0
        if family == "MLP40":
            self.live = ShallowMLP(in_dim=SUMMARY_DIM, hidden=list(MLP40_HIDDEN), dropout=MLP40_DROPOUT)
        elif family == "ODST40":
            self.live = build_odst40()
            self.n_trees = N_TREES_TOTAL
        elif family == "SO-ODST40":
            self.live = build_so_odst40()
            self.n_trees = N_TREES_TOTAL
        elif family == "SO-DTE40":
            if self.n_trees < 1:
                self.n_trees = int(select_tree_count()["CAPACITY_MATCHED_TREE_COUNT"])
            self.live = SparseObliqueForest(self.n_trees, combine="mean")
        elif family == "BSO-DTE40":
            if self.n_trees < 1:
                self.n_trees = int(select_tree_count()["CAPACITY_MATCHED_TREE_COUNT"])
            self.live = SparseObliqueForest(self.n_trees, combine="sum")
        else:
            raise Editor019ProtocolError(f"unknown family {family}")
        self.reference = clone_frozen_branch(self.live)

    def attach_reference_from_live(self) -> None:
        self.reference = clone_frozen_branch(self.live)

    def live_hash(self) -> str:
        return state_dict_sha256(self.live.state_dict())

    def reference_hash(self) -> str:
        return state_dict_sha256(self.reference.state_dict())


def _empty_tree_extras(s: torch.Tensor, n_trees: int) -> dict[str, torch.Tensor]:
    return {
        "tree_outputs": s.new_zeros(s.size(0), max(n_trees, 1)),
        "choices": s.new_zeros(s.size(0), max(n_trees, 1), N_INTERNAL_NODES if n_trees else 4),
        "leaf_probs_all": s.new_zeros(s.size(0), max(n_trees, 1), N_LEAVES if n_trees else 16),
        "tree_weights": s.new_full((s.size(0), max(n_trees, 1)), 1.0 / max(n_trees, 1)),
        "feature_selection": [],
    }


def _odst_like_forward(module: nn.Module, s: torch.Tensor) -> dict[str, torch.Tensor]:
    od = live_odst_forward(module, s)
    extras = [layer.feature_selection_probs() for layer in module.layers]
    return {
        "branch_logit": od["logit"],
        "tree_outputs": od["tree_outputs"],
        "choices": od["choices"],
        "leaf_probs_all": od["leaf_probs_all"],
        "tree_weights": s.new_full((s.size(0), od["tree_outputs"].size(-1)), 1.0 / od["tree_outputs"].size(-1)),
        "feature_selection": extras,
    }


def _branch_forward(module: nn.Module, family: str, s: torch.Tensor) -> dict[str, torch.Tensor]:
    if family == "MLP40":
        logit = module(s)
        empty = _empty_tree_extras(s, 1)
        empty["branch_logit"] = logit
        return empty
    if family == "ODST40":
        return _odst_like_forward(module, s)
    if family == "SO-ODST40":
        return _odst_like_forward(module, signed_channels(s))
    if family in {"SO-DTE40", "BSO-DTE40"}:
        out = module(s)
        n_trees = out["tree_outputs"].size(-1)
        return {
            "branch_logit": out["branch_logit"],
            "tree_outputs": out["tree_outputs"],
            "choices": out["choices"],
            "leaf_probs_all": out["leaf_probs_all"],
            "tree_weights": s.new_full((s.size(0), n_trees), 1.0 / n_trees),
            "feature_selection": [out["signed_coefficients"]],
        }
    raise Editor019ProtocolError(f"unknown family {family}")


def correction_from_pair(live_logit: torch.Tensor, reference_logit: torch.Tensor) -> torch.Tensor:
    return live_logit - reference_logit.detach()


def branch_forward(
    branch: SummaryBranch,
    s: torch.Tensor,
    l1_logit: torch.Tensor,
) -> dict[str, torch.Tensor]:
    live = _branch_forward(branch.live, branch.family, s)
    with torch.no_grad():
        ref = _branch_forward(branch.reference, branch.family, s)
    corr = correction_from_pair(live["branch_logit"], ref["branch_logit"])
    return {
        "logit": l1_logit + corr,
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


def configure_branch_trainability(branch: SummaryBranch) -> None:
    for p in branch.live.parameters():
        p.requires_grad = True
    freeze_reference(branch)


def build_branch_optimizer(branch: SummaryBranch) -> torch.optim.Optimizer:
    configure_branch_trainability(branch)
    params = [p for p in branch.live.parameters() if p.requires_grad]
    if not params:
        raise Editor019ProtocolError("no trainable summary-branch parameters")
    ref_ids = {id(p) for p in branch.reference.parameters()}
    for p in params:
        if id(p) in ref_ids:
            raise Editor019Blocked("frozen initial branch found in optimiser")
    return torch.optim.Adam(params, lr=LR_BRANCH, weight_decay=WEIGHT_DECAY)


def prove_function_preserving(family: str, *, batch: int = 8, n_trees: int | None = None) -> dict[str, Any]:
    torch.manual_seed(0)
    branch = SummaryBranch(family, n_trees=n_trees)
    configure_branch_trainability(branch)
    branch.eval()
    s = torch.randn(batch, SUMMARY_DIM)
    l1 = torch.randn(batch)
    out = branch_forward(branch, s, l1)
    if not torch.allclose(out["logit"], l1, atol=1e-6, rtol=1e-6):
        raise Editor019Blocked(f"{family} initial final prediction is not exactly L1")
    if not torch.allclose(out["correction"], torch.zeros_like(out["correction"]), atol=1e-6, rtol=1e-6):
        raise Editor019Blocked(f"{family} initial correction is not zero")
    dummy = (out["branch_logit"] * torch.arange(1, batch + 1, dtype=out["branch_logit"].dtype)).sum()
    dummy.backward()
    live_grad = 0.0
    for p in branch.live.parameters():
        if p.grad is not None:
            live_grad += float(p.grad.detach().norm().item())
    ref_grad = 0.0
    for p in branch.reference.parameters():
        if p.grad is not None:
            ref_grad += float(p.grad.detach().norm().item())
        if p.requires_grad:
            raise Editor019Blocked(f"{family} frozen reference still requires grad")
    if live_grad <= 0.0:
        raise Editor019Blocked(f"{family} trainable branch gradient norm is not > 0 at step zero")
    if ref_grad != 0.0:
        raise Editor019Blocked(f"{family} frozen initial branch received gradient")
    return {
        "family": family,
        "initial_final_equals_l1": True,
        "initial_correction_zero": True,
        "live_grad_norm": live_grad,
        "reference_grad_norm": ref_grad,
        "lambda_teacher": LAMBDA_TEACHER,
        "n_trees": branch.n_trees,
    }


def recover_editor018_branch(family: str) -> Editor018SummaryBranch:
    if family not in {"MLP40", "ODST40"}:
        raise Editor019ProtocolError("only MLP40/ODST40 are recovered from EDITOR-018")
    return Editor018SummaryBranch(family)


__all__ = [
    "SummaryBranch",
    "SparseObliqueTree",
    "SparseObliqueForest",
    "signed_channels",
    "signed_coefficients_from_probs",
    "branch_forward",
    "build_branch_optimizer",
    "prove_function_preserving",
    "teacher_residual",
    "build_so_odst40",
    "build_odst40",
]
