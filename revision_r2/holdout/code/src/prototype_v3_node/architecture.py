"""Bi-LSTM → temporal attention → NODE/ODST head (Prototype V3).

Variants
--------
* ``attention_linear_reference`` — frozen pretrained linear head only.
* ``canonical_entmax15_node`` — canonical NODE (entmax15 + entmoid15 + tree average).
* ``sparsemax_sigmoid_odst`` — non-canonical choice-function ablation + tree average.
* ``canonical_node_with_linear_residual`` — linear + α·tanh(canonical NODE).
* ``canonical_node_with_learned_gate`` — linear + α·gate·tanh(canonical NODE).
* ``dense_linear_readout_node`` — entmax15/entmoid15 Dense stack + Linear(h_L) ablation.

Primary first experiment: ``canonical_entmax15_node``.
First seed-42 comparison set excludes residual/gated variants.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import torch
import torch.nn as nn

from models.sequence_ensemble import TemporalAttention

from .odst import (
    ABLATION_EQUATIONS,
    CANONICAL_NODE_EQUATIONS,
    NODE,
    NODE_EQUATIONS,
    ChoiceFunction,
    ReadoutMode,
    summarize_odst_shapes,
)

MAX_RESIDUAL_SCALE = 1.0
DEFAULT_RESIDUAL_SCALE_LOGIT_INIT = -5.0

FUSION_VARIANTS = (
    "attention_linear_reference",
    "canonical_entmax15_node",
    "sparsemax_sigmoid_odst",
    "canonical_node_with_linear_residual",
    "canonical_node_with_learned_gate",
    "dense_linear_readout_node",
)

# First seed-42 comparison (do not auto-train residual/gated).
SEED42_COMPARISON_VARIANTS = (
    "attention_linear_reference",
    "canonical_entmax15_node",
    "sparsemax_sigmoid_odst",
    "dense_linear_readout_node",
)

VARIANT_EQUATIONS = {
    "attention_linear_reference": "final_logit = linear_logit",
    "canonical_entmax15_node": (
        "final_logit = mean_{l,t} f_tree^{(l,t)}  "
        "[entmax15 + entmoid15 + canonical_tree_average]"
    ),
    "sparsemax_sigmoid_odst": (
        "final_logit = mean_{l,t} f_tree^{(l,t)}  "
        "[sparsemax + sigmoid + tree_average; NON-CANONICAL ABLATION]"
    ),
    "canonical_node_with_linear_residual": (
        "final_logit = linear_logit + alpha * tanh(canonical_node_logit)"
    ),
    "canonical_node_with_learned_gate": (
        "final_logit = linear_logit + alpha * sigmoid(MLP(h)) * tanh(canonical_node_logit)"
    ),
    "dense_linear_readout_node": (
        "final_logit = Linear(h_L)  [entmax15 + entmoid15 + dense_linear_readout ABLATION]"
    ),
}

VARIANT_NODE_CONFIG: dict[str, dict[str, str]] = {
    "attention_linear_reference": {
        "choice_function": "entmax15",
        "readout": "canonical_tree_average",
    },
    "canonical_entmax15_node": {
        "choice_function": "entmax15",
        "readout": "canonical_tree_average",
    },
    "sparsemax_sigmoid_odst": {
        "choice_function": "sparsemax_sigmoid",
        "readout": "canonical_tree_average",
    },
    "canonical_node_with_linear_residual": {
        "choice_function": "entmax15",
        "readout": "canonical_tree_average",
    },
    "canonical_node_with_learned_gate": {
        "choice_function": "entmax15",
        "readout": "canonical_tree_average",
    },
    "dense_linear_readout_node": {
        "choice_function": "entmax15",
        "readout": "dense_linear_readout",
    },
}

BOUNDED_RESIDUAL_SEMANTICS = (
    "For residual/gated NODE variants, the additive correction is "
    "alpha * gate * tanh(node_logit) with alpha ∈ (0, MAX_RESIDUAL_SCALE]. "
    "residual_scale_logit is initialised strongly negative so predictions "
    "start near the pretrained attention-linear reference. "
    "Residual/gated variants are deferred until the primary NODE head is competitive."
)


def count_parameters(module: nn.Module, trainable_only: bool = False) -> int:
    if trainable_only:
        return sum(p.numel() for p in module.parameters() if p.requires_grad)
    return sum(p.numel() for p in module.parameters())


def resolve_node_config(fusion_variant: str) -> tuple[ChoiceFunction, ReadoutMode]:
    if fusion_variant not in VARIANT_NODE_CONFIG:
        raise ValueError(f"Unknown fusion_variant={fusion_variant!r}")
    cfg = VARIANT_NODE_CONFIG[fusion_variant]
    return cfg["choice_function"], cfg["readout"]  # type: ignore[return-value]


class AttentionNodeEnsemble(nn.Module):
    """Bi-LSTM + temporal attention encoder with NODE/ODST classification head."""

    def __init__(
        self,
        input_dim: int = 13,
        hidden_size: int = 64,
        dropout: float = 0.2,
        attention_dim: int = 64,
        fusion_variant: str = "canonical_entmax15_node",
        node_num_layers: int = 2,
        node_n_trees: int = 8,
        node_depth: int = 4,
        node_tree_dim: int = 1,
        node_temperature: float = 1.0,
        node_dropout: float = 0.0,
        leaf_init_std: float = 0.05,
        gate_hidden_dim: int = 32,
        max_residual_scale: float = MAX_RESIDUAL_SCALE,
        residual_scale_logit_init: float = DEFAULT_RESIDUAL_SCALE_LOGIT_INIT,
    ) -> None:
        super().__init__()
        if fusion_variant not in FUSION_VARIANTS:
            raise ValueError(
                f"Unknown fusion_variant={fusion_variant!r}; "
                f"expected one of {FUSION_VARIANTS}"
            )
        if max_residual_scale <= 0:
            raise ValueError("max_residual_scale must be positive")

        choice_function, readout = resolve_node_config(fusion_variant)

        self.input_dim = input_dim
        self.hidden_size = hidden_size
        self.dropout_p = dropout
        self.attention_dim = attention_dim
        self.fusion_variant = fusion_variant
        self.encoder_dim = hidden_size * 2
        self.node_num_layers = int(node_num_layers)
        self.node_n_trees = int(node_n_trees)
        self.node_depth = int(node_depth)
        self.node_tree_dim = int(node_tree_dim)
        self.node_temperature = float(node_temperature)
        self.choice_function = choice_function
        self.readout = readout
        self.gate_hidden_dim = gate_hidden_dim
        self.max_residual_scale = float(max_residual_scale)
        self.leaf_init_std = float(leaf_init_std)
        self.bounded_residual_semantics = BOUNDED_RESIDUAL_SEMANTICS
        self.node_equations = dict(CANONICAL_NODE_EQUATIONS)
        self.ablation_equations = dict(ABLATION_EQUATIONS)
        self.node_shape_summary = summarize_odst_shapes(
            in_dim=self.encoder_dim,
            num_layers=self.node_num_layers,
            n_trees=self.node_n_trees,
            depth=self.node_depth,
            tree_dim=self.node_tree_dim,
            choice_function=choice_function,
            readout=readout,
        )

        self.lstm = nn.LSTM(
            input_size=input_dim,
            hidden_size=hidden_size,
            num_layers=1,
            batch_first=True,
            bidirectional=True,
        )
        self.dropout = nn.Dropout(dropout)
        self.attention = TemporalAttention(self.encoder_dim, attention_dim)
        self.linear_head = nn.Linear(self.encoder_dim, 1)
        self.node_head = NODE(
            in_dim=self.encoder_dim,
            num_layers=self.node_num_layers,
            n_trees=self.node_n_trees,
            depth=self.node_depth,
            tree_dim=self.node_tree_dim,
            temperature=self.node_temperature,
            dropout=node_dropout,
            choice_function=choice_function,
            readout=readout,
            leaf_init_std=leaf_init_std,
        )

        self.residual_scale_logit = nn.Parameter(
            torch.tensor(float(residual_scale_logit_init))
        )
        self.sample_gate = nn.Sequential(
            nn.Linear(self.encoder_dim, gate_hidden_dim),
            nn.Tanh(),
            nn.Linear(gate_hidden_dim, 1),
        )
        nn.init.zeros_(self.sample_gate[-1].weight)
        nn.init.zeros_(self.sample_gate[-1].bias)

    def effective_alpha(self) -> torch.Tensor:
        return self.max_residual_scale * torch.sigmoid(self.residual_scale_logit)

    def _gate_values(self, h: torch.Tensor) -> torch.Tensor:
        batch = h.size(0)
        if self.fusion_variant == "attention_linear_reference":
            return h.new_zeros(batch)
        if self.fusion_variant in {
            "canonical_entmax15_node",
            "sparsemax_sigmoid_odst",
            "dense_linear_readout_node",
        }:
            return h.new_ones(batch)
        if self.fusion_variant == "canonical_node_with_linear_residual":
            return h.new_ones(batch)
        return torch.sigmoid(self.sample_gate(h).squeeze(-1))

    def encode_attention_h(self, x: torch.Tensor) -> tuple[torch.Tensor, dict[str, Any]]:
        """Return attention-aggregated ``h`` and encoder extras (no NODE)."""
        if x.dim() != 3:
            raise ValueError(f"Expected (B, T, F); got shape {tuple(x.shape)}")
        hidden, _ = self.lstm(x)
        hidden = self.dropout(hidden)
        aggregated, attn = self.attention(hidden)
        extras = {
            "hidden_states": hidden,
            "aggregated": aggregated,
            "attention_weights": attn,
            "linear_logit": self.linear_head(aggregated).squeeze(-1),
        }
        return aggregated, extras

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, dict[str, Any]]:
        aggregated, enc = self.encode_attention_h(x)
        linear_logit = enc["linear_logit"]
        node_logit, node_extras = self.node_head(aggregated)
        node_bounded = torch.tanh(node_logit)
        gate = self._gate_values(aggregated)
        alpha = self.effective_alpha()

        if self.fusion_variant == "attention_linear_reference":
            effective_residual = linear_logit.new_zeros(linear_logit.shape)
            final_logit = linear_logit
            alpha_value = linear_logit.new_zeros(())
        elif self.fusion_variant in {
            "canonical_entmax15_node",
            "sparsemax_sigmoid_odst",
            "dense_linear_readout_node",
        }:
            effective_residual = node_logit
            final_logit = node_logit
            alpha_value = linear_logit.new_ones(())
        else:
            effective_residual = alpha * gate * node_bounded
            final_logit = linear_logit + effective_residual
            alpha_value = alpha

        extras: dict[str, Any] = {
            **enc,
            "linear_logit": linear_logit,
            "node_logit": node_logit,
            "node_bounded": node_bounded,
            "effective_residual": effective_residual,
            "alpha": alpha_value.expand_as(linear_logit)
            if alpha_value.ndim == 0
            else alpha_value,
            "alpha_scalar": float(alpha_value.detach().item())
            if alpha_value.numel() == 1
            else float("nan"),
            "max_residual_scale": self.max_residual_scale,
            "final_logit": final_logit,
            "gate": gate,
            "fusion_variant": self.fusion_variant,
            "variant_equation": VARIANT_EQUATIONS[self.fusion_variant],
            "bounded_residual_semantics": BOUNDED_RESIDUAL_SEMANTICS,
            "temporal_aggregation": "attention",
            "node_num_layers": self.node_num_layers,
            "node_n_trees": self.node_n_trees,
            "node_depth": self.node_depth,
            "choice_function": self.choice_function,
            "readout": self.readout,
            "node_equations": self.node_equations,
            "ablation_equations": self.ablation_equations,
            "node_shape_summary": self.node_shape_summary,
            "is_canonical_node": bool(node_extras.get("is_canonical_node", False)),
            "mechanism": node_extras.get("mechanism"),
        }
        extras["feature_selection_probs"] = node_extras.get("feature_selection_probs")
        extras["thresholds"] = node_extras.get("thresholds")
        extras["temperatures"] = node_extras.get("temperatures")
        extras["leaf_probs"] = node_extras.get("leaf_probs")
        extras["choice"] = node_extras.get("choice")
        extras["odst_layers"] = node_extras.get("odst_layers")
        extras["layer_tree_logits"] = node_extras.get("layer_tree_logits")
        return final_logit, extras

    @torch.no_grad()
    def data_aware_initialize_from_batch(
        self, x_batch: torch.Tensor, **kwargs: Any
    ) -> dict[str, Any]:
        """Initialize NODE from a training batch of sequences (labels unused)."""
        self.eval()
        h, _ = self.encode_attention_h(x_batch)
        report = self.node_head.data_aware_initialize(h, **kwargs)
        report["h_batch_shape"] = list(h.shape)
        report["labels_used"] = False
        return report

    def freeze_encoder(self) -> None:
        for p in self.lstm.parameters():
            p.requires_grad = False
        for p in self.attention.parameters():
            p.requires_grad = False

    def freeze_backbone(self) -> None:
        self.freeze_encoder()
        for p in self.linear_head.parameters():
            p.requires_grad = False

    def apply_frozen_node_trainability(self) -> None:
        """Initial protocol: freeze encoder+linear; train NODE (+ residual/gate)."""
        self.freeze_backbone()
        train_node = self.fusion_variant != "attention_linear_reference"
        for p in self.node_head.parameters():
            p.requires_grad = train_node
        # Canonical tree-average: output_head must stay frozen even if train_node.
        if self.readout == "canonical_tree_average":
            for p in self.node_head.output_head.parameters():
                p.requires_grad = False
        elif train_node:
            for p in self.node_head.output_head.parameters():
                p.requires_grad = True

        use_alpha = self.fusion_variant in {
            "canonical_node_with_linear_residual",
            "canonical_node_with_learned_gate",
        }
        self.residual_scale_logit.requires_grad = use_alpha
        use_sample = self.fusion_variant == "canonical_node_with_learned_gate"
        for p in self.sample_gate.parameters():
            p.requires_grad = use_sample
        if self.fusion_variant == "attention_linear_reference":
            self.residual_scale_logit.requires_grad = False

    def trainable_parameter_groups(self) -> dict[str, list[nn.Parameter]]:
        groups: dict[str, list[nn.Parameter]] = {
            "encoder": [p for p in self.lstm.parameters() if p.requires_grad],
            "attention": [p for p in self.attention.parameters() if p.requires_grad],
            "linear_head": [p for p in self.linear_head.parameters() if p.requires_grad],
            "node_head": [p for p in self.node_head.parameters() if p.requires_grad],
            "residual_scale": (
                [self.residual_scale_logit]
                if self.residual_scale_logit.requires_grad
                else []
            ),
            "gate": [p for p in self.sample_gate.parameters() if p.requires_grad],
        }
        return {k: v for k, v in groups.items() if v}

    def component_parameter_counts(self) -> dict[str, int]:
        # Count NODE trainable excluding frozen unused linear head when tree-average.
        node_trainable = sum(
            p.numel() for p in self.node_head.parameters() if p.requires_grad
        )
        return {
            "bilstm_encoder": count_parameters(self.lstm) + count_parameters(self.dropout),
            "attention": count_parameters(self.attention),
            "linear_head": count_parameters(self.linear_head),
            "node_head": count_parameters(self.node_head),
            "node_head_trainable": node_trainable,
            "residual_scale": int(self.residual_scale_logit.numel()),
            "sample_gate": count_parameters(self.sample_gate),
            "total": count_parameters(self),
            "trainable": count_parameters(self, trainable_only=True),
            "node_num_layers": self.node_num_layers,
            "node_n_trees": self.node_n_trees,
            "node_depth": self.node_depth,
            "node_n_leaves_per_tree": 2**self.node_depth,
        }


def load_v1_attention_linear_checkpoint(
    model: AttentionNodeEnsemble,
    checkpoint_path: str | Path,
) -> dict[str, Any]:
    """Load Bi-LSTM + attention + linear weights from V1 attention-linear ckpt."""
    path = Path(checkpoint_path)
    payload = torch.load(path, map_location="cpu", weights_only=False)
    src = payload.get("model_state_dict", payload)
    if not isinstance(src, dict):
        raise ValueError(f"Unexpected checkpoint format in {path}")

    dst = model.state_dict()
    to_load: dict[str, torch.Tensor] = {}
    loaded: list[str] = []
    skipped: list[str] = []
    incompatible: list[str] = []
    for key, tensor in src.items():
        if key not in dst:
            skipped.append(key)
            continue
        if tuple(tensor.shape) != tuple(dst[key].shape):
            incompatible.append(
                f"{key} (shape {tuple(tensor.shape)} != {tuple(dst[key].shape)})"
            )
            continue
        if key.startswith(("lstm.", "attention.", "linear_head.")):
            to_load[key] = tensor
            loaded.append(key)
        else:
            skipped.append(key)
    model.load_state_dict(to_load, strict=False)
    return {
        "checkpoint": str(path),
        "n_loaded": len(loaded),
        "loaded": loaded,
        "skipped": skipped,
        "incompatible": incompatible,
        "mechanism": "BiLSTM→Attention→NODE/ODST",
        "choice_function": model.choice_function,
        "readout": model.readout,
    }
