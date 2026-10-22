"""Heads and encoder wrappers for EDITOR-010 (linear, diagnostic MLP, ODST)."""

from __future__ import annotations

from typing import Any

import torch
import torch.nn as nn

from models.sequence_ensemble import SequenceEnsembleModel
from prototype_v3_node.architecture import AttentionNodeEnsemble
from prototype_v3_node.odst import NODE

from .constants import ENCODER_ARCH, MLP_HIDDEN, PRODUCING_ODST


class LinearHead(nn.Module):
    def __init__(self, in_dim: int = 128) -> None:
        super().__init__()
        self.fc = nn.Linear(in_dim, 1)

    def forward(self, h: torch.Tensor) -> tuple[torch.Tensor, dict[str, Any]]:
        logit = self.fc(h).squeeze(-1)
        return logit, {}


class DiagnosticMLPHead(nn.Module):
    """Diagnostic only: representation -> one hidden layer -> nonlinearity -> output."""

    def __init__(self, in_dim: int = 128, hidden: int = MLP_HIDDEN) -> None:
        super().__init__()
        self.net = nn.Sequential(nn.Linear(in_dim, hidden), nn.ReLU(), nn.Linear(hidden, 1))

    def forward(self, h: torch.Tensor) -> tuple[torch.Tensor, dict[str, Any]]:
        logit = self.net(h).squeeze(-1)
        return logit, {}


class ODSTHead(nn.Module):
    def __init__(self, cfg: dict[str, Any] | None = None, in_dim: int = 128) -> None:
        super().__init__()
        c = dict(PRODUCING_ODST if cfg is None else cfg)
        self.cfg = c
        self.node = NODE(
            in_dim=in_dim,
            num_layers=int(c["num_layers"]),
            n_trees=int(c["n_trees"]),
            depth=int(c["depth"]),
            tree_dim=1,
            temperature=float(c["temperature"]),
            dropout=float(c["dropout"]),
            choice_function=str(c["choice_function"]),
            readout=str(c["readout"]),
            leaf_init_std=float(c["leaf_init_std"]),
        )

    def forward(self, h: torch.Tensor) -> tuple[torch.Tensor, dict[str, Any]]:
        return self.node(h)


def build_encoder() -> SequenceEnsembleModel:
    return SequenceEnsembleModel(
        input_dim=int(ENCODER_ARCH["input_dim"]),
        hidden_size=int(ENCODER_ARCH["hidden_size"]),
        dropout=float(ENCODER_ARCH["dropout"]),
        attention_dim=int(ENCODER_ARCH["attention_dim"]),
        classification_head="linear",
        temporal_aggregation="attention",
    )


def build_attention_node(cfg: dict[str, Any] | None = None) -> AttentionNodeEnsemble:
    c = dict(PRODUCING_ODST if cfg is None else cfg)
    return AttentionNodeEnsemble(
        input_dim=13,
        hidden_size=64,
        dropout=0.2,
        attention_dim=64,
        fusion_variant="sparsemax_sigmoid_odst",
        node_num_layers=int(c["num_layers"]),
        node_n_trees=int(c["n_trees"]),
        node_depth=int(c["depth"]),
        node_tree_dim=1,
        node_temperature=float(c["temperature"]),
        node_dropout=float(c["dropout"]),
        leaf_init_std=float(c["leaf_init_std"]),
    )


def build_head(kind: str, cfg: dict[str, Any] | None = None) -> nn.Module:
    kind = kind.upper()
    if kind in {"H-LIN", "LIN", "LINEAR"}:
        return LinearHead()
    if kind in {"H-MLP", "MLP"}:
        return DiagnosticMLPHead()
    if kind in {"H-ODST", "ODST"}:
        return ODSTHead(cfg)
    raise ValueError(f"Unknown head {kind!r}")


@torch.no_grad()
def extract_attended(model: SequenceEnsembleModel, x: torch.Tensor) -> torch.Tensor:
    model.eval()
    h, _ = model.lstm(x)
    z, _attn = model.attention(h)
    return z
