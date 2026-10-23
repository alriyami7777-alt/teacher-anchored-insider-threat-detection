"""Differentiable sequence–ensemble model: Bi-LSTM + attention/last + soft forest/linear.

Independent implementation for Objective 2 Stage 1 / 1.1. Does not import from
standalone Bi-LSTM or Soft Decision Forest training scripts.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import torch
import torch.nn as nn
import torch.nn.functional as F


class TemporalAttention(nn.Module):
    """Trainable attention over all Bi-LSTM timesteps.

    Attention weights are non-negative and sum to 1 along the time axis
    for each sequence (softmax).
    """

    def __init__(self, hidden_dim: int, attention_dim: int) -> None:
        super().__init__()
        if attention_dim < 1:
            raise ValueError("attention_dim must be >= 1")
        self.projection = nn.Linear(hidden_dim, attention_dim)
        self.score = nn.Linear(attention_dim, 1, bias=False)

    def forward(self, h: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        """
        Args:
            h: (B, T, H) Bi-LSTM hidden states for all timesteps.
        Returns:
            z: (B, H) attention-aggregated representation.
            attn: (B, T) attention weights (non-negative, row-sum ~= 1).
        """
        energies = self.score(torch.tanh(self.projection(h))).squeeze(-1)
        attn = torch.softmax(energies, dim=1)
        z = torch.bmm(attn.unsqueeze(1), h).squeeze(1)
        return z, attn


class SoftDecisionTree(nn.Module):
    """Differentiable soft binary decision tree with sigmoid routing."""

    def __init__(self, in_dim: int, depth: int) -> None:
        super().__init__()
        if depth < 1:
            raise ValueError("depth must be >= 1")
        self.depth = depth
        self.n_internal = (2**depth) - 1
        self.n_leaves = 2**depth
        self.node_weight = nn.Parameter(torch.empty(self.n_internal, in_dim))
        self.node_bias = nn.Parameter(torch.zeros(self.n_internal))
        self.leaf_logit = nn.Parameter(torch.empty(self.n_leaves))
        nn.init.xavier_uniform_(self.node_weight)
        nn.init.zeros_(self.node_bias)
        with torch.no_grad():
            self.leaf_logit.uniform_(-0.5, 0.5)

        paths: list[list[tuple[int, int]]] = []
        for leaf in range(self.n_leaves):
            node = 0
            path: list[tuple[int, int]] = []
            for d in range(self.depth):
                go_right = (leaf >> (self.depth - 1 - d)) & 1
                path.append((node, go_right))
                node = 2 * node + (2 if go_right else 1)
            paths.append(path)
        self._paths = paths

    def routing(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        logits = F.linear(x, self.node_weight, self.node_bias)
        p_left = torch.sigmoid(logits)
        p_right = 1.0 - p_left
        batch = x.size(0)
        leaf_probs = x.new_ones(batch, self.n_leaves)
        for leaf, path in enumerate(self._paths):
            prob = x.new_ones(batch)
            for node, go_right in path:
                prob = prob * (p_right[:, node] if go_right else p_left[:, node])
            leaf_probs[:, leaf] = prob
        return p_left, p_right, leaf_probs

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, dict[str, torch.Tensor]]:
        p_left, p_right, leaf_probs = self.routing(x)
        tree_logit = (leaf_probs * self.leaf_logit.unsqueeze(0)).sum(dim=1)
        extras = {
            "p_left": p_left,
            "p_right": p_right,
            "leaf_probs": leaf_probs,
            "tree_logit": tree_logit,
        }
        return tree_logit, extras


class SoftDecisionForest(nn.Module):
    """Mean of soft-tree logits -> sequence-level malicious logit."""

    def __init__(self, in_dim: int, n_trees: int = 5, depth: int = 4) -> None:
        super().__init__()
        if n_trees < 1:
            raise ValueError("n_trees must be >= 1")
        self.trees = nn.ModuleList([SoftDecisionTree(in_dim, depth) for _ in range(n_trees)])
        self.n_trees = n_trees
        self.depth = depth
        self.in_dim = in_dim

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, list[dict[str, torch.Tensor]]]:
        tree_logits = []
        extras_list = []
        for tree in self.trees:
            logit, extras = tree(x)
            tree_logits.append(logit)
            extras_list.append(extras)
        forest_logit = torch.stack(tree_logits, dim=1).mean(dim=1)
        return forest_logit, extras_list


class SequenceEnsembleModel(nn.Module):
    """End-to-end Bi-LSTM encoder + temporal aggregation + classification head.

    Input:  (B, T=20, F=13)
    Output: sequence-level malicious logit (B,), plus explainability extras.

    Ablations (Stage 1.1):
      temporal_aggregation: attention | last
      classification_head: soft_forest | linear
    """

    def __init__(
        self,
        input_dim: int = 13,
        hidden_size: int = 64,
        dropout: float = 0.2,
        attention_dim: int = 64,
        n_trees: int = 5,
        tree_depth: int = 4,
        classification_head: str = "soft_forest",
        temporal_aggregation: str = "attention",
    ) -> None:
        super().__init__()
        if classification_head not in {"soft_forest", "linear"}:
            raise ValueError(f"Unknown classification_head: {classification_head}")
        if temporal_aggregation not in {"attention", "last"}:
            raise ValueError(f"Unknown temporal_aggregation: {temporal_aggregation}")

        self.input_dim = input_dim
        self.hidden_size = hidden_size
        self.dropout_p = dropout
        self.attention_dim = attention_dim
        self.n_trees = n_trees
        self.tree_depth = tree_depth
        self.classification_head = classification_head
        self.temporal_aggregation = temporal_aggregation
        self.encoder_dim = hidden_size * 2

        self.lstm = nn.LSTM(
            input_size=input_dim,
            hidden_size=hidden_size,
            num_layers=1,
            batch_first=True,
            bidirectional=True,
        )
        self.dropout = nn.Dropout(dropout)

        # Attention module is always constructed so checkpoint schemas stay stable;
        # it is unused when temporal_aggregation == "last".
        self.attention = TemporalAttention(self.encoder_dim, attention_dim)

        if classification_head == "soft_forest":
            self.forest = SoftDecisionForest(
                in_dim=self.encoder_dim, n_trees=n_trees, depth=tree_depth
            )
            self.linear_head = None
        else:
            self.forest = None
            self.linear_head = nn.Linear(self.encoder_dim, 1)

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, dict]:
        if x.dim() != 3:
            raise ValueError(f"Expected (B, T, F); got shape {tuple(x.shape)}")
        h, _ = self.lstm(x)  # (B, T, 2H)
        h = self.dropout(h)

        if self.temporal_aggregation == "attention":
            z, attn = self.attention(h)
        else:
            z = h[:, -1, :]
            attn = torch.zeros(h.size(0), h.size(1), device=h.device, dtype=h.dtype)
            attn[:, -1] = 1.0

        routing: list[dict[str, torch.Tensor]] = []
        if self.classification_head == "soft_forest":
            assert self.forest is not None
            logit, routing = self.forest(z)
        else:
            assert self.linear_head is not None
            logit = self.linear_head(z).squeeze(-1)

        extras = {
            "hidden_states": h,
            "aggregated": z,
            "attention_weights": attn,
            "routing": routing,
            "temporal_aggregation": self.temporal_aggregation,
            "classification_head": self.classification_head,
        }
        return logit, extras

    def component_parameter_counts(self) -> dict[str, int]:
        counts = {
            "bilstm_encoder": count_parameters(self.lstm) + count_parameters(self.dropout),
            "attention": count_parameters(self.attention),
            "total": count_parameters(self),
        }
        if self.forest is not None:
            counts["soft_forest"] = count_parameters(self.forest)
        if self.linear_head is not None:
            counts["linear_head"] = count_parameters(self.linear_head)
        return counts

    def trainable_component_params(self) -> dict[str, list[nn.Parameter]]:
        """Active components that should receive gradients under current ablation."""
        comps: dict[str, list[nn.Parameter]] = {
            "bilstm": list(self.lstm.parameters()),
        }
        if self.temporal_aggregation == "attention":
            comps["attention"] = list(self.attention.parameters())
        if self.classification_head == "soft_forest" and self.forest is not None:
            comps["soft_forest"] = list(self.forest.parameters())
        if self.classification_head == "linear" and self.linear_head is not None:
            comps["linear_head"] = list(self.linear_head.parameters())
        return comps


def count_parameters(module: nn.Module) -> int:
    return sum(p.numel() for p in module.parameters() if p.requires_grad)


def load_encoder_checkpoint(
    model: SequenceEnsembleModel,
    checkpoint_path: str | Path,
) -> dict[str, Any]:
    """Load compatible Bi-LSTM encoder weights from a standalone Bi-LSTM checkpoint.

    Copies only ``lstm.*`` tensors with matching shapes. Ignores the standalone
    classification head (``fc.*``). Does not freeze the encoder.
    """
    path = Path(checkpoint_path)
    payload = torch.load(path, map_location="cpu", weights_only=False)
    src = payload.get("model_state_dict", payload)
    if not isinstance(src, dict):
        raise ValueError(f"Unexpected checkpoint format in {path}")

    dst = model.state_dict()
    loaded: list[str] = []
    incompatible: list[str] = []
    skipped_head: list[str] = []
    to_load: dict[str, torch.Tensor] = {}

    for key, tensor in src.items():
        if key.startswith("fc."):
            skipped_head.append(key)
            continue
        if not key.startswith("lstm."):
            incompatible.append(f"{key} (not an encoder key)")
            continue
        if key not in dst:
            incompatible.append(f"{key} (absent in sequence-ensemble model)")
            continue
        if tuple(tensor.shape) != tuple(dst[key].shape):
            incompatible.append(
                f"{key} (shape {tuple(tensor.shape)} != {tuple(dst[key].shape)})"
            )
            continue
        to_load[key] = tensor
        loaded.append(key)

    missing = [k for k in dst if k.startswith("lstm.") and k not in to_load]
    model.load_state_dict(to_load, strict=False)

    report = {
        "checkpoint": str(path),
        "loaded": loaded,
        "missing": missing,
        "incompatible": incompatible,
        "skipped_standalone_head": skipped_head,
        "n_loaded": len(loaded),
        "encoder_frozen": False,
    }
    return report


def _entropy(p: torch.Tensor, dim: int = -1, eps: float = 1e-8) -> torch.Tensor:
    p = p.clamp_min(eps)
    return -(p * p.log()).sum(dim=dim)


def component_grad_norms(model: SequenceEnsembleModel) -> dict[str, float]:
    norms: dict[str, float] = {}
    for name, params in model.trainable_component_params().items():
        total = 0.0
        for p in params:
            if p.grad is not None:
                total += float(p.grad.detach().pow(2).sum().item())
        norms[f"grad_norm_{name}"] = total**0.5
    return norms


@torch.no_grad()
def compute_validation_diagnostics(
    model: SequenceEnsembleModel,
    logits: torch.Tensor,
    extras: dict,
    y_true: torch.Tensor,
    grad_norms: dict[str, float] | None = None,
    unused_leaf_threshold: float = 1e-3,
) -> dict[str, Any]:
    """Finite validation diagnostics for attention, routing, logits, and class probs."""
    attn = extras["attention_weights"]
    probs = torch.sigmoid(logits)
    y = y_true.float()

    attn_entropy = _entropy(attn, dim=1)
    diag: dict[str, Any] = {
        "attention_mean_entropy": float(attn_entropy.mean().item()),
        "attention_mean_max_weight": float(attn.max(dim=1).values.mean().item()),
        "logit_mean": float(logits.mean().item()),
        "logit_std": float(logits.std(unbiased=False).item()) if logits.numel() > 1 else 0.0,
        "mean_prob_positive": float(probs[y > 0.5].mean().item()) if (y > 0.5).any() else float("nan"),
        "mean_prob_negative": float(probs[y <= 0.5].mean().item()) if (y <= 0.5).any() else float("nan"),
    }

    pos_mean = attn.mean(dim=0)
    pos_std = attn.std(dim=0, unbiased=False)
    for t in range(attn.size(1)):
        diag[f"attention_pos{t:02d}_mean"] = float(pos_mean[t].item())
        diag[f"attention_pos{t:02d}_std"] = float(pos_std[t].item())

    routing = extras.get("routing") or []
    unused_total = 0
    routing_entropies: list[float] = []
    for i, route in enumerate(routing):
        leaf = route["leaf_probs"]  # (B, L)
        util = leaf.mean(dim=0)
        ent = _entropy(leaf, dim=1).mean()
        unused = int((util < unused_leaf_threshold).sum().item())
        unused_total += unused
        routing_entropies.append(float(ent.item()))
        diag[f"tree{i}_routing_entropy"] = float(ent.item())
        diag[f"tree{i}_mean_leaf_utilisation"] = float(util.mean().item())
        diag[f"tree{i}_unused_leaves"] = unused
        for j in range(util.numel()):
            diag[f"tree{i}_leaf{j:02d}_util"] = float(util[j].item())

    diag["mean_routing_entropy"] = (
        float(sum(routing_entropies) / len(routing_entropies)) if routing_entropies else float("nan")
    )
    diag["n_unused_leaves_total"] = unused_total
    diag["n_trees_reported"] = len(routing)

    if grad_norms:
        diag.update(grad_norms)

    for k, v in diag.items():
        if isinstance(v, float):
            if math.isnan(v):
                continue  # empty positive/negative subsets
            if not math.isfinite(v):
                raise AssertionError(f"Non-finite diagnostic: {k}={v}")
    return diag


def assert_model_outputs(
    logits: torch.Tensor,
    extras: dict,
    batch_size: int,
    seq_len: int = 20,
) -> list[str]:
    """Numerical validity checks for Stage 1 smoke / pre-training validation."""
    messages: list[str] = []
    if logits.shape != (batch_size,):
        raise AssertionError(f"logit shape {tuple(logits.shape)} != ({batch_size},)")
    messages.append(f"PASS: output-logit shape={tuple(logits.shape)}")

    attn = extras["attention_weights"]
    if attn.shape != (batch_size, seq_len):
        raise AssertionError(f"attention shape {tuple(attn.shape)} != ({batch_size}, {seq_len})")
    messages.append(f"PASS: attention-weight shape={tuple(attn.shape)}")

    if (attn < 0).any():
        raise AssertionError("Attention weights must be non-negative")
    row_sums = attn.sum(dim=1)
    if not torch.allclose(row_sums, torch.ones_like(row_sums), atol=1e-5):
        raise AssertionError(
            f"Attention rows must sum to 1; min={float(row_sums.min()):.6f} "
            f"max={float(row_sums.max()):.6f}"
        )
    messages.append("PASS: each attention row sums approximately to 1")

    if not torch.isfinite(logits).all():
        raise AssertionError("Non-finite output logits")
    messages.append("PASS: output logits are finite")

    routing = extras.get("routing") or []
    head = extras.get("classification_head", "soft_forest")
    if head == "soft_forest" and not routing:
        raise AssertionError("soft_forest head produced empty routing extras")
    for i, route in enumerate(routing):
        for key in ("p_left", "p_right", "leaf_probs", "tree_logit"):
            t = route[key]
            if not torch.isfinite(t).all():
                raise AssertionError(f"Non-finite {key} in tree {i}")
        p_left, p_right = route["p_left"], route["p_right"]
        if (p_left < 0).any() or (p_left > 1).any() or (p_right < 0).any() or (p_right > 1).any():
            raise AssertionError(f"Routing probabilities outside [0,1] in tree {i}")
        if not torch.allclose(p_left + p_right, torch.ones_like(p_left), atol=1e-5):
            raise AssertionError(f"p_left + p_right != 1 in tree {i}")
        leaf_sum = route["leaf_probs"].sum(dim=1)
        if not torch.allclose(leaf_sum, torch.ones_like(leaf_sum), atol=1e-4):
            raise AssertionError(f"Leaf-path probabilities do not sum to 1 in tree {i}")
    if routing:
        messages.append("PASS: routing probabilities and logits are finite and valid")
    else:
        messages.append("PASS: linear head (no soft-routing extras)")
    return messages


def assert_component_gradients(model: SequenceEnsembleModel) -> list[str]:
    """Verify active components received finite non-zero gradients."""
    messages: list[str] = []

    def _check(params: list[nn.Parameter], name: str) -> None:
        grads = [p.grad for p in params if p.requires_grad]
        if not grads or any(g is None for g in grads):
            raise AssertionError(f"Missing gradients for {name}")
        if not all(torch.isfinite(g).all() for g in grads):
            raise AssertionError(f"Non-finite gradients for {name}")
        if not any(float(g.abs().sum()) > 0 for g in grads):
            raise AssertionError(f"All-zero gradients for {name}")
        messages.append(f"PASS: {name} received finite non-zero gradients")

    for name, params in model.trainable_component_params().items():
        _check(params, name)
    return messages
