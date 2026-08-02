"""Prototype V2: Adaptive Residual-Gated Differentiable Sequence–Ensemble.

Reuses V1 Bi-LSTM + temporal attention building blocks without modifying
``sequence_ensemble.py`` or any locked Objective 2 / 3 artefacts.

Fusion (residual-gated)::

    final_logit = linear_logit + sigmoid(gate(h)) * forest_logit

Controlled variants: linear_only, forest_only_v1, fixed_residual_0_5
(alias: fixed_average), learned_global_residual_gate (alias: learned_global_gate),
sample_specific_residual_gate.
"""

from __future__ import annotations

import math
from typing import Any

import torch
import torch.nn as nn
import torch.nn.functional as F

from models.sequence_ensemble import (
    SoftDecisionForest,
    TemporalAttention,
    count_parameters,
)

FUSION_VARIANTS = (
    "linear_only",
    "forest_only_v1",
    "fixed_residual_0_5",
    "learned_global_residual_gate",
    "sample_specific_residual_gate",
)

# Backward-compatible aliases used by early V2 scaffolding / manifests.
FUSION_VARIANT_ALIASES = {
    "learned_global_gate": "learned_global_residual_gate",
    "fixed_average": "fixed_residual_0_5",
}


def normalize_fusion_variant(variant: str) -> str:
    return FUSION_VARIANT_ALIASES.get(variant, variant)


def _entropy(p: torch.Tensor, dim: int = -1, eps: float = 1e-8) -> torch.Tensor:
    p = p.clamp_min(eps)
    return -(p * p.log()).sum(dim=dim)


class ResidualGate(nn.Module):
    """Produce a gate in (0, 1) for residual forest contribution.

    * learned_global_residual_gate: single scalar logit (broadcast over batch)
    * sample_specific_residual_gate: Linear(h) -> scalar logit per sample
    """

    def __init__(self, variant: str, encoder_dim: int) -> None:
        super().__init__()
        self.variant = normalize_fusion_variant(variant)
        if self.variant == "learned_global_residual_gate":
            self.global_logit = nn.Parameter(torch.zeros(()))
            self.proj = None
        elif self.variant == "sample_specific_residual_gate":
            self.global_logit = None
            self.proj = nn.Linear(encoder_dim, 1)
            nn.init.zeros_(self.proj.weight)
            nn.init.zeros_(self.proj.bias)
        else:
            self.global_logit = None
            self.proj = None

    def forward(self, h: torch.Tensor) -> torch.Tensor:
        """
        Args:
            h: (B, H) aggregated representation.
        Returns:
            gate: (B,) values in (0, 1).
        """
        b = h.size(0)
        if self.variant == "learned_global_residual_gate":
            assert self.global_logit is not None
            g = torch.sigmoid(self.global_logit).expand(b)
            return g
        if self.variant == "sample_specific_residual_gate":
            assert self.proj is not None
            return torch.sigmoid(self.proj(h).squeeze(-1))
        if self.variant == "fixed_residual_0_5":
            return h.new_full((b,), 0.5)
        if self.variant == "linear_only":
            return h.new_zeros((b,))
        if self.variant == "forest_only_v1":
            return h.new_ones((b,))
        raise ValueError(f"Unknown gate variant: {self.variant}")


class SequenceEnsembleV2(nn.Module):
    """Bi-LSTM + attention encoder with dual heads and residual-gated fusion.

    Input:  (B, T=20, F=13)
    Output: final fused malicious logit (B,), plus explainability extras.
    """

    def __init__(
        self,
        input_dim: int = 13,
        hidden_size: int = 64,
        dropout: float = 0.2,
        attention_dim: int = 64,
        n_trees: int = 5,
        tree_depth: int = 4,
        fusion_variant: str = "sample_specific_residual_gate",
        temporal_aggregation: str = "attention",
    ) -> None:
        super().__init__()
        fusion_variant = normalize_fusion_variant(fusion_variant)
        if fusion_variant not in FUSION_VARIANTS:
            raise ValueError(
                f"Unknown fusion_variant={fusion_variant!r}; "
                f"expected one of {FUSION_VARIANTS} "
                f"(aliases: {sorted(FUSION_VARIANT_ALIASES)})"
            )
        if temporal_aggregation not in {"attention", "last"}:
            raise ValueError(f"Unknown temporal_aggregation: {temporal_aggregation}")

        self.input_dim = input_dim
        self.hidden_size = hidden_size
        self.dropout_p = dropout
        self.attention_dim = attention_dim
        self.n_trees = n_trees
        self.tree_depth = tree_depth
        self.fusion_variant = fusion_variant
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
        self.attention = TemporalAttention(self.encoder_dim, attention_dim)

        # Always construct both heads (V2 dual-head design).
        self.linear_head = nn.Linear(self.encoder_dim, 1)
        self.forest = SoftDecisionForest(
            in_dim=self.encoder_dim, n_trees=n_trees, depth=tree_depth
        )
        self.gate = ResidualGate(fusion_variant, self.encoder_dim)

    def encode(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """Return hidden states, aggregated z, attention weights."""
        if x.dim() != 3:
            raise ValueError(f"Expected (B, T, F); got shape {tuple(x.shape)}")
        h, _ = self.lstm(x)
        h = self.dropout(h)
        if self.temporal_aggregation == "attention":
            z, attn = self.attention(h)
        else:
            z = h[:, -1, :]
            attn = torch.zeros(h.size(0), h.size(1), device=h.device, dtype=h.dtype)
            attn[:, -1] = 1.0
        return h, z, attn

    def fuse(
        self,
        linear_logit: torch.Tensor,
        forest_logit: torch.Tensor,
        gate: torch.Tensor,
    ) -> torch.Tensor:
        """Apply controlled fusion variant."""
        v = self.fusion_variant
        if v == "linear_only":
            return linear_logit
        if v == "forest_only_v1":
            return forest_logit
        # Residual family (incl. fixed_residual_0_5 with gate≡0.5):
        # final = linear + σ(gate) * forest_correction
        return linear_logit + gate * forest_logit

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, dict[str, Any]]:
        h, z, attn = self.encode(x)
        linear_logit = self.linear_head(z).squeeze(-1)
        forest_logit, routing = self.forest(z)
        forest_correction = forest_logit
        gate = self.gate(z)
        final_logit = self.fuse(linear_logit, forest_correction, gate)

        extras: dict[str, Any] = {
            "hidden_states": h,
            "aggregated": z,
            "attention_weights": attn,
            "routing": routing,
            "linear_logit": linear_logit,
            "forest_logit": forest_logit,
            "forest_correction": forest_correction,
            "gate": gate,
            "final_logit": final_logit,
            "fusion_variant": self.fusion_variant,
            "temporal_aggregation": self.temporal_aggregation,
        }
        return final_logit, extras

    def component_parameter_counts(self) -> dict[str, int]:
        return {
            "bilstm_encoder": count_parameters(self.lstm) + count_parameters(self.dropout),
            "attention": count_parameters(self.attention),
            "linear_head": count_parameters(self.linear_head),
            "soft_forest": count_parameters(self.forest),
            "gate": count_parameters(self.gate),
            "total": count_parameters(self),
        }

    def trainable_component_params(self) -> dict[str, list[nn.Parameter]]:
        """Active components that should receive gradients under current variant."""
        comps: dict[str, list[nn.Parameter]] = {
            "bilstm": list(self.lstm.parameters()),
        }
        if self.temporal_aggregation == "attention":
            comps["attention"] = list(self.attention.parameters())

        v = self.fusion_variant
        if v == "linear_only":
            comps["linear_head"] = list(self.linear_head.parameters())
        elif v == "forest_only_v1":
            comps["soft_forest"] = list(self.forest.parameters())
        elif v == "fixed_residual_0_5":
            comps["linear_head"] = list(self.linear_head.parameters())
            comps["soft_forest"] = list(self.forest.parameters())
        else:
            # Residual-gated variants: both heads + gate
            comps["linear_head"] = list(self.linear_head.parameters())
            comps["soft_forest"] = list(self.forest.parameters())
            gate_params = list(self.gate.parameters())
            if gate_params:
                comps["gate"] = gate_params
        return comps


def compute_v2_loss(
    extras: dict[str, Any],
    y: torch.Tensor,
    criterion: nn.Module,
    *,
    aux_linear_weight: float = 0.5,
    aux_forest_weight: float = 0.5,
    gate_collapse_weight: float = 0.01,
    gate_min: float = 0.05,
    gate_max: float = 0.95,
    unused_leaf_weight: float = 0.01,
    unused_leaf_threshold: float = 1e-3,
) -> tuple[torch.Tensor, dict[str, float]]:
    """Final BCE + auxiliary head BCEs + gate / leaf safeguards.

    Auxiliary losses keep both heads supervised so neither becomes inactive.
    Gate-collapse penalty encourages mean gate away from {0, 1} for residual
    variants. Leaf-utilization penalty discourages massively unused leaves.
    """
    final_logit = extras["final_logit"]
    linear_logit = extras["linear_logit"]
    forest_logit = extras["forest_logit"]
    gate = extras["gate"]
    variant = extras["fusion_variant"]

    loss_final = criterion(final_logit, y)
    loss_linear = criterion(linear_logit, y)
    loss_forest = criterion(forest_logit, y)

    total = loss_final
    # Always apply aux when both heads exist (all V2 variants construct both).
    if aux_linear_weight > 0 and variant != "forest_only_v1":
        total = total + aux_linear_weight * loss_linear
    if aux_forest_weight > 0 and variant != "linear_only":
        total = total + aux_forest_weight * loss_forest

    stats: dict[str, float] = {
        "loss_final": float(loss_final.detach().item()),
        "loss_linear": float(loss_linear.detach().item()),
        "loss_forest": float(loss_forest.detach().item()),
        "gate_mean": float(gate.detach().mean().item()),
        "gate_std": float(gate.detach().std(unbiased=False).item()) if gate.numel() > 1 else 0.0,
        "gate_min": float(gate.detach().min().item()),
        "gate_max": float(gate.detach().max().item()),
    }

    # Gate-collapse safeguard (residual-gated variants only).
    gate_pen = final_logit.new_zeros(())
    if (
        gate_collapse_weight > 0
        and variant in {"learned_global_residual_gate", "sample_specific_residual_gate"}
    ):
        g_mean = gate.mean()
        # Soft hinge away from [gate_min, gate_max]
        below = F.relu(gate_min - g_mean)
        above = F.relu(g_mean - gate_max)
        gate_pen = below + above
        # Also penalize near-zero variance for sample-specific (all gates identical)
        if variant == "sample_specific_residual_gate" and gate.numel() > 1:
            gate_pen = gate_pen + F.relu(0.01 - gate.var(unbiased=False))
        total = total + gate_collapse_weight * gate_pen
    stats["gate_collapse_penalty"] = float(gate_pen.detach().item())

    # Unused-leaf safeguard
    leaf_pen = final_logit.new_zeros(())
    unused_total = 0
    n_leaves_total = 0
    routing = extras.get("routing") or []
    if unused_leaf_weight > 0 and routing and variant != "linear_only":
        for route in routing:
            leaf = route["leaf_probs"]  # (B, L)
            util = leaf.mean(dim=0)
            n_leaves_total += util.numel()
            unused = (util < unused_leaf_threshold).float()
            unused_total += int(unused.sum().item())
            # Encourage utilization: -mean(log(util + eps)) soft push
            leaf_pen = leaf_pen + (-(util.clamp_min(1e-6).log()).mean())
        leaf_pen = leaf_pen / max(len(routing), 1)
        total = total + unused_leaf_weight * leaf_pen
    stats["unused_leaf_penalty"] = float(leaf_pen.detach().item())
    stats["n_unused_leaves"] = float(unused_total)
    stats["n_leaves_total"] = float(n_leaves_total)
    stats["unused_leaf_pct"] = (
        100.0 * unused_total / n_leaves_total if n_leaves_total else float("nan")
    )
    stats["loss_total"] = float(total.detach().item())
    return total, stats


@torch.no_grad()
def compute_v2_diagnostics(
    extras: dict[str, Any],
    y_true: torch.Tensor,
    unused_leaf_threshold: float = 1e-3,
) -> dict[str, Any]:
    """Finite validation diagnostics for gate, heads, attention, routing."""
    attn = extras["attention_weights"]
    gate = extras["gate"]
    linear_logit = extras["linear_logit"]
    forest_logit = extras["forest_logit"]
    final_logit = extras["final_logit"]
    y = y_true.float()

    attn_entropy = _entropy(attn, dim=1)
    diag: dict[str, Any] = {
        "fusion_variant": extras.get("fusion_variant"),
        "attention_mean_entropy": float(attn_entropy.mean().item()),
        "attention_mean_max_weight": float(attn.max(dim=1).values.mean().item()),
        "gate_mean": float(gate.mean().item()),
        "gate_std": float(gate.std(unbiased=False).item()) if gate.numel() > 1 else 0.0,
        "gate_min": float(gate.min().item()),
        "gate_max": float(gate.max().item()),
        "linear_logit_mean": float(linear_logit.mean().item()),
        "forest_logit_mean": float(forest_logit.mean().item()),
        "final_logit_mean": float(final_logit.mean().item()),
        "mean_final_prob_positive": (
            float(torch.sigmoid(final_logit)[y > 0.5].mean().item())
            if (y > 0.5).any()
            else float("nan")
        ),
        "mean_final_prob_negative": (
            float(torch.sigmoid(final_logit)[y <= 0.5].mean().item())
            if (y <= 0.5).any()
            else float("nan")
        ),
    }

    routing = extras.get("routing") or []
    unused_total = 0
    routing_ents: list[float] = []
    for i, route in enumerate(routing):
        leaf = route["leaf_probs"]
        util = leaf.mean(dim=0)
        ent = _entropy(leaf, dim=1).mean()
        unused = int((util < unused_leaf_threshold).sum().item())
        unused_total += unused
        routing_ents.append(float(ent.item()))
        diag[f"tree{i}_routing_entropy"] = float(ent.item())
        diag[f"tree{i}_unused_leaves"] = unused
    diag["mean_routing_entropy"] = (
        float(sum(routing_ents) / len(routing_ents)) if routing_ents else float("nan")
    )
    diag["n_unused_leaves_total"] = unused_total
    diag["n_trees_reported"] = len(routing)
    n_leaves = routing[0]["leaf_probs"].size(1) * len(routing) if routing else 0
    diag["unused_leaf_pct"] = (
        100.0 * unused_total / n_leaves if n_leaves else float("nan")
    )

    # Soft gate-collapse flag for locking criteria
    g_mean = float(gate.mean().item())
    diag["gate_collapsed"] = bool(g_mean < 0.05 or g_mean > 0.95)

    for k, v in diag.items():
        if isinstance(v, float) and math.isnan(v):
            continue
        if isinstance(v, float) and not math.isfinite(v):
            raise AssertionError(f"Non-finite diagnostic: {k}={v}")
    return diag


def assert_v2_outputs(
    logits: torch.Tensor,
    extras: dict[str, Any],
    batch_size: int,
    seq_len: int = 20,
) -> list[str]:
    messages: list[str] = []
    if logits.shape != (batch_size,):
        raise AssertionError(f"final logit shape {tuple(logits.shape)} != ({batch_size},)")
    messages.append(f"PASS: final-logit shape={tuple(logits.shape)}")

    for key in ("linear_logit", "forest_logit", "gate", "attention_weights"):
        if key not in extras:
            raise AssertionError(f"Missing extras[{key}]")
    if extras["gate"].shape != (batch_size,):
        raise AssertionError(f"gate shape {tuple(extras['gate'].shape)} != ({batch_size},)")
    if (extras["gate"] < 0).any() or (extras["gate"] > 1).any():
        raise AssertionError("Gate values must lie in [0, 1]")
    messages.append("PASS: gate in [0, 1]")

    attn = extras["attention_weights"]
    if attn.shape != (batch_size, seq_len):
        raise AssertionError(f"attention shape {tuple(attn.shape)} != ({batch_size}, {seq_len})")
    if (attn < 0).any():
        raise AssertionError("Attention weights must be non-negative")
    row_sums = attn.sum(dim=1)
    if not torch.allclose(row_sums, torch.ones_like(row_sums), atol=1e-5):
        raise AssertionError("Attention rows must sum to 1")
    messages.append("PASS: attention valid")

    if not torch.isfinite(logits).all():
        raise AssertionError("Non-finite final logits")
    for key in ("linear_logit", "forest_logit"):
        if not torch.isfinite(extras[key]).all():
            raise AssertionError(f"Non-finite {key}")
    messages.append("PASS: head logits finite")

    routing = extras.get("routing") or []
    if not routing:
        raise AssertionError("V2 always constructs soft forest; routing must be non-empty")
    for i, route in enumerate(routing):
        leaf_sum = route["leaf_probs"].sum(dim=1)
        if not torch.allclose(leaf_sum, torch.ones_like(leaf_sum), atol=1e-4):
            raise AssertionError(f"Leaf probs do not sum to 1 in tree {i}")
    messages.append("PASS: soft-forest routing valid")
    return messages


def assert_v2_component_gradients(model: SequenceEnsembleV2) -> list[str]:
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


def component_grad_norms_v2(model: SequenceEnsembleV2) -> dict[str, float]:
    norms: dict[str, float] = {}
    for name, params in model.trainable_component_params().items():
        total = 0.0
        for p in params:
            if p.grad is not None:
                total += float(p.grad.detach().pow(2).sum().item())
        norms[f"grad_norm_{name}"] = total**0.5
    return norms
