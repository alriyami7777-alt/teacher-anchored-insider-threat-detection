"""Adaptive Residual-Gated Differentiable Sequence–Ensemble (Prototype V2).

Reuses TemporalAttention / SoftDecisionForest implementations from the V1
package without modifying V1 behaviour. Parallel linear + soft-forest heads
with controlled fusion variants.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import torch
import torch.nn as nn

# Import V1 building blocks without altering them.
from models.sequence_ensemble import SoftDecisionForest, TemporalAttention

FUSION_VARIANTS = (
    "linear_only",
    "forest_only_v1",
    "fixed_residual_0_5",
    "learned_global_residual_gate",
    "sample_specific_residual_gate",
)

# Backward-compatible aliases (deprecated names → canonical).
FUSION_VARIANT_ALIASES = {
    "fixed_average": "fixed_residual_0_5",
}

FOREST_CORRECTION_SEMANTICS = (
    "forest_correction is the raw soft-forest logit "
    "(mean of soft-tree logits over the forest). "
    "It is used as an additive residual on the pretrained linear logit: "
    "final_logit = linear_logit + gate * forest_correction. "
    "It is neither a centred forest logit nor a separately learned delta head. "
    "Leaf logits are zero-initialised so forest_correction ≈ 0 at construction, "
    "keeping residual variants near the stable attention-linear prediction."
)

VARIANT_EQUATIONS = {
    "linear_only": "final_logit = linear_logit",
    "forest_only_v1": "final_logit = forest_logit  # linear head fully bypassed",
    "fixed_residual_0_5": "final_logit = linear_logit + 0.5 * forest_correction",
    "learned_global_residual_gate": (
        "final_logit = linear_logit + sigmoid(g) * forest_correction  "
        "# g is one shared scalar"
    ),
    "sample_specific_residual_gate": (
        "final_logit = linear_logit + sigmoid(MLP(h)) * forest_correction"
    ),
}


def normalize_fusion_variant(variant: str) -> str:
    return FUSION_VARIANT_ALIASES.get(variant, variant)


def count_parameters(module: nn.Module, trainable_only: bool = False) -> int:
    if trainable_only:
        return sum(p.numel() for p in module.parameters() if p.requires_grad)
    return sum(p.numel() for p in module.parameters())


class ResidualGatedSequenceEnsemble(nn.Module):
    """Bi-LSTM + temporal attention with parallel heads and residual gating.

    Fusion (residual variants)::

        final_logit = linear_logit + gate * forest_correction

    where ``forest_correction`` is the **raw soft-forest logit** (see
    ``FOREST_CORRECTION_SEMANTICS``). Controlled variants:

    - linear_only: final = linear; forest not fused (aux only)
    - forest_only_v1: final = forest_logit only (linear fully bypassed;
      identical to V1 soft-forest head formulation on the shared encoder)
    - fixed_residual_0_5: final = linear + 0.5 * forest_correction
      (fixed residual weight; **not** a mathematical average).
      Alias: ``fixed_average`` (deprecated).
    - learned_global_residual_gate: one scalar gate shared by all sequences
    - sample_specific_residual_gate: gate MLP from aggregated representation h
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
        gate_hidden_dim: int = 32,
        fixed_gate_prob: float = 0.5,
        zero_init_forest_leaves: bool = True,
    ) -> None:
        super().__init__()
        fusion_variant = normalize_fusion_variant(fusion_variant)
        if fusion_variant not in FUSION_VARIANTS:
            raise ValueError(
                f"Unknown fusion_variant={fusion_variant!r}; "
                f"expected one of {FUSION_VARIANTS} "
                f"(aliases: {sorted(FUSION_VARIANT_ALIASES)})"
            )
        if not (0.0 < fixed_gate_prob < 1.0):
            raise ValueError("fixed_gate_prob must be in (0, 1)")

        self.input_dim = input_dim
        self.hidden_size = hidden_size
        self.dropout_p = dropout
        self.attention_dim = attention_dim
        self.n_trees = n_trees
        self.tree_depth = tree_depth
        self.fusion_variant = fusion_variant
        self.gate_hidden_dim = gate_hidden_dim
        self.fixed_gate_prob = float(fixed_gate_prob)
        self.encoder_dim = hidden_size * 2
        self.zero_init_forest_leaves = bool(zero_init_forest_leaves)
        self.forest_correction_semantics = FOREST_CORRECTION_SEMANTICS

        self.lstm = nn.LSTM(
            input_size=input_dim,
            hidden_size=hidden_size,
            num_layers=1,
            batch_first=True,
            bidirectional=True,
        )
        self.dropout = nn.Dropout(dropout)
        self.attention = TemporalAttention(self.encoder_dim, attention_dim)

        # Parallel heads (always constructed for stable schemas / aux losses).
        self.linear_head = nn.Linear(self.encoder_dim, 1)
        self.forest = SoftDecisionForest(
            in_dim=self.encoder_dim, n_trees=n_trees, depth=tree_depth
        )
        if zero_init_forest_leaves:
            self._zero_init_forest_leaf_logits()

        # Gate modules: only active parameters used by gated variants.
        # global_gate_logit = 0 → sigmoid = 0.5 (unsaturated).
        self.global_gate_logit = nn.Parameter(torch.zeros(()))
        self.sample_gate = nn.Sequential(
            nn.Linear(self.encoder_dim, gate_hidden_dim),
            nn.Tanh(),
            nn.Linear(gate_hidden_dim, 1),
        )
        # Last layer zeros → sample gate logits ≈ 0 → sigmoid ≈ 0.5 (unsaturated).
        nn.init.zeros_(self.sample_gate[-1].weight)
        nn.init.zeros_(self.sample_gate[-1].bias)

    def _zero_init_forest_leaf_logits(self) -> None:
        """Make forest_correction ≈ 0 so residual V2 starts near attention-linear."""
        with torch.no_grad():
            for tree in self.forest.trees:
                tree.leaf_logit.zero_()

    def _gate_values(self, h: torch.Tensor) -> torch.Tensor:
        """Return per-sample gate probabilities in (0, 1), shape (B,)."""
        batch = h.size(0)
        variant = self.fusion_variant
        if variant == "linear_only":
            return h.new_zeros(batch)
        if variant == "forest_only_v1":
            # Diagnostic gate only; final logits ignore linear entirely.
            return h.new_ones(batch)
        if variant == "fixed_residual_0_5":
            return h.new_full((batch,), self.fixed_gate_prob)
        if variant == "learned_global_residual_gate":
            g = torch.sigmoid(self.global_gate_logit)
            return g.expand(batch)
        # sample_specific_residual_gate
        return torch.sigmoid(self.sample_gate(h).squeeze(-1))

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, dict[str, Any]]:
        if x.dim() != 3:
            raise ValueError(f"Expected (B, T, F); got shape {tuple(x.shape)}")

        hidden, _ = self.lstm(x)
        hidden = self.dropout(hidden)
        aggregated, attn = self.attention(hidden)

        linear_logit = self.linear_head(aggregated).squeeze(-1)
        forest_logit, routing = self.forest(aggregated)
        # Raw forest logit used as residual correction (see FOREST_CORRECTION_SEMANTICS).
        forest_correction = forest_logit
        gate = self._gate_values(aggregated)

        if self.fusion_variant == "linear_only":
            final_logit = linear_logit
        elif self.fusion_variant == "forest_only_v1":
            # Exact V1 forest-only formulation: linear head does not contribute.
            final_logit = forest_logit
        else:
            final_logit = linear_logit + gate * forest_correction

        extras: dict[str, Any] = {
            "hidden_states": hidden,
            "aggregated": aggregated,
            "attention_weights": attn,
            "linear_logit": linear_logit,
            "forest_logit": forest_logit,
            "forest_correction": forest_correction,
            "forest_correction_semantics": FOREST_CORRECTION_SEMANTICS,
            "final_logit": final_logit,
            "gate": gate,
            "routing": routing,
            "fusion_variant": self.fusion_variant,
            "variant_equation": VARIANT_EQUATIONS[self.fusion_variant],
            "temporal_aggregation": "attention",
        }
        return final_logit, extras

    def component_parameter_counts(self) -> dict[str, int]:
        counts = {
            "bilstm_encoder": count_parameters(self.lstm) + count_parameters(self.dropout),
            "attention": count_parameters(self.attention),
            "linear_head": count_parameters(self.linear_head),
            "soft_forest": count_parameters(self.forest),
            "global_gate": int(self.global_gate_logit.numel())
            if self.global_gate_logit.requires_grad
            else 0,
            "sample_gate": count_parameters(self.sample_gate),
            "total": count_parameters(self),
            "fusion_variant": self.fusion_variant,  # type: ignore[dict-item]
        }
        return counts

    def active_parameter_counts(self) -> dict[str, int]:
        comps = self.trainable_component_params()
        return {name: sum(p.numel() for p in params) for name, params in comps.items()}

    def trainable_component_params(self) -> dict[str, list[nn.Parameter]]:
        comps: dict[str, list[nn.Parameter]] = {
            "bilstm": list(self.lstm.parameters()),
            "attention": list(self.attention.parameters()),
        }
        variant = self.fusion_variant
        if variant == "linear_only":
            comps["linear_head"] = list(self.linear_head.parameters())
            comps["soft_forest"] = list(self.forest.parameters())
        elif variant == "forest_only_v1":
            comps["soft_forest"] = list(self.forest.parameters())
            # linear_head is bypassed in the forward fusion; still listed for aux
            # training if enabled, but does not affect final_logit.
            comps["linear_head"] = list(self.linear_head.parameters())
        else:
            comps["linear_head"] = list(self.linear_head.parameters())
            comps["soft_forest"] = list(self.forest.parameters())
            if variant == "learned_global_residual_gate":
                comps["gate"] = [self.global_gate_logit]
            elif variant == "sample_specific_residual_gate":
                comps["gate"] = list(self.sample_gate.parameters())
            # fixed_residual_0_5: no trainable gate parameters
        return comps

    def freeze_inactive_heads(self, freeze_unused_gate: bool = True) -> None:
        if not freeze_unused_gate:
            return
        variant = self.fusion_variant
        use_global = variant == "learned_global_residual_gate"
        use_sample = variant == "sample_specific_residual_gate"
        self.global_gate_logit.requires_grad = use_global
        for p in self.sample_gate.parameters():
            p.requires_grad = use_sample

    def set_encoder_trainable(self, trainable: bool) -> None:
        for p in self.lstm.parameters():
            p.requires_grad = bool(trainable)

    def set_attention_trainable(self, trainable: bool) -> None:
        for p in self.attention.parameters():
            p.requires_grad = bool(trainable)

    def set_linear_head_trainable(self, trainable: bool) -> None:
        for p in self.linear_head.parameters():
            p.requires_grad = bool(trainable)

    def apply_warmup_freeze(self) -> None:
        """Warm-up: freeze pretrained encoder + linear; train forest/gate."""
        self.set_encoder_trainable(False)
        self.set_attention_trainable(False)
        self.set_linear_head_trainable(False)
        for p in self.forest.parameters():
            p.requires_grad = True
        self.freeze_inactive_heads(freeze_unused_gate=True)

    def apply_joint_finetune(self) -> None:
        """Joint fine-tune: unfreeze encoder, attention, and linear head."""
        self.set_encoder_trainable(True)
        self.set_attention_trainable(True)
        self.set_linear_head_trainable(True)
        for p in self.forest.parameters():
            p.requires_grad = True
        self.freeze_inactive_heads(freeze_unused_gate=True)

    def trainable_parameter_groups(self) -> list[nn.Parameter]:
        return [p for p in self.parameters() if p.requires_grad]


def load_v1_attention_linear_checkpoint(
    model: ResidualGatedSequenceEnsemble,
    checkpoint_path: str | Path,
) -> dict[str, Any]:
    """Load compatible Bi-LSTM + attention (+ linear) weights from a V1 checkpoint.

    Does not modify the source file. Soft-forest leaf logits remain at their
    V2 zero-init (near-zero correction) unless matching keys exist and are
    deliberately loaded (they are not — forest/gate stay V2-initialised).
    """
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
    # Re-assert near-zero forest correction after any partial load.
    if model.zero_init_forest_leaves:
        model._zero_init_forest_leaf_logits()
    return {
        "checkpoint": str(path),
        "n_loaded": len(loaded),
        "loaded": loaded,
        "skipped": skipped,
        "incompatible": incompatible,
        "forest_correction_semantics": FOREST_CORRECTION_SEMANTICS,
        "forest_leaves_zero_reasserted": bool(model.zero_init_forest_leaves),
    }


def auxiliary_losses(
    extras: dict[str, Any],
    y: torch.Tensor,
    criterion: nn.Module,
    linear_aux_weight: float = 0.0,
    forest_aux_weight: float = 0.0,
) -> tuple[torch.Tensor, dict[str, float]]:
    """Optional auxiliary BCE losses on linear and forest heads."""
    device = y.device
    zero = torch.zeros((), device=device)
    parts: dict[str, float] = {}
    total = zero
    if linear_aux_weight > 0:
        loss_lin = criterion(extras["linear_logit"], y)
        total = total + linear_aux_weight * loss_lin
        parts["aux_linear"] = float(loss_lin.detach().item())
    if forest_aux_weight > 0:
        loss_for = criterion(extras["forest_logit"], y)
        total = total + forest_aux_weight * loss_for
        parts["aux_forest"] = float(loss_for.detach().item())
    parts["aux_total"] = float(total.detach().item()) if total.numel() else 0.0
    return total, parts


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

    for key in (
        "linear_logit",
        "forest_logit",
        "forest_correction",
        "final_logit",
        "gate",
        "attention_weights",
    ):
        if key not in extras:
            raise AssertionError(f"Missing extras[{key!r}]")
        t = extras[key]
        if not torch.isfinite(t).all():
            raise AssertionError(f"Non-finite extras[{key}]")
    messages.append("PASS: recorded logits/gate/attention are finite")

    attn = extras["attention_weights"]
    if attn.shape != (batch_size, seq_len):
        raise AssertionError(f"attention shape {tuple(attn.shape)} != ({batch_size}, {seq_len})")
    if (attn < 0).any():
        raise AssertionError("Attention weights must be non-negative")
    row_sums = attn.sum(dim=1)
    if not torch.allclose(row_sums, torch.ones_like(row_sums), atol=1e-5):
        raise AssertionError("Attention rows must sum to 1")
    messages.append("PASS: attention weights valid")

    gate = extras["gate"]
    if gate.shape != (batch_size,):
        raise AssertionError(f"gate shape {tuple(gate.shape)} != ({batch_size},)")
    if ((gate < 0) | (gate > 1)).any():
        raise AssertionError("Gate values must be in [0, 1]")
    messages.append("PASS: gate values in [0, 1]")

    if not torch.allclose(extras["final_logit"], logits, atol=1e-6):
        raise AssertionError("extras['final_logit'] != returned logits")
    messages.append("PASS: extras['final_logit'] matches returned logits")

    variant = extras.get("fusion_variant", "")
    if variant == "forest_only_v1":
        if not torch.allclose(logits, extras["forest_logit"], atol=1e-6):
            raise AssertionError("forest_only_v1 must equal forest_logit exactly")
        messages.append("PASS: forest_only_v1 bypasses linear (final == forest_logit)")
    if variant == "fixed_residual_0_5":
        expected = extras["linear_logit"] + 0.5 * extras["forest_correction"]
        if not torch.allclose(logits, expected, atol=1e-5):
            raise AssertionError("fixed_residual_0_5 arithmetic failed")
        messages.append("PASS: fixed_residual_0_5 = linear + 0.5 * correction")

    routing = extras.get("routing") or []
    for i, route in enumerate(routing):
        leaf_sum = route["leaf_probs"].sum(dim=1)
        if not torch.allclose(leaf_sum, torch.ones_like(leaf_sum), atol=1e-4):
            raise AssertionError(f"Leaf-path probabilities do not sum to 1 in tree {i}")
        if not torch.isfinite(route["tree_logit"]).all():
            raise AssertionError(f"Non-finite tree_logit in tree {i}")
    if routing:
        messages.append("PASS: soft-forest routing valid")
    return messages


def assert_v2_component_gradients(
    model: ResidualGatedSequenceEnsemble,
    require_gate: bool | None = None,
) -> list[str]:
    messages: list[str] = []
    if require_gate is None:
        require_gate = model.fusion_variant in {
            "learned_global_residual_gate",
            "sample_specific_residual_gate",
        }

    def _check(params: list[nn.Parameter], name: str, allow_zero: bool = False) -> None:
        grads = [p.grad for p in params if p.requires_grad]
        if not grads or any(g is None for g in grads):
            raise AssertionError(f"Missing gradients for {name}")
        if not all(torch.isfinite(g).all() for g in grads):
            raise AssertionError(f"Non-finite gradients for {name}")
        if not allow_zero and not any(float(g.abs().sum()) > 0 for g in grads):
            raise AssertionError(f"All-zero gradients for {name}")
        messages.append(f"PASS: {name} received finite non-zero gradients")

    comps = model.trainable_component_params()
    for name, params in comps.items():
        if name == "gate" and not require_gate:
            continue
        if name == "gate" and model.fusion_variant == "fixed_residual_0_5":
            continue
        _check(params, name)
    return messages


def component_grad_norms(model: ResidualGatedSequenceEnsemble) -> dict[str, float]:
    norms: dict[str, float] = {}
    for name, params in model.trainable_component_params().items():
        total = 0.0
        for p in params:
            if p.grad is not None:
                total += float(p.grad.detach().pow(2).sum().item())
        norms[f"grad_norm_{name}"] = total**0.5
    return norms


def summarize_gate_distribution(gate: torch.Tensor) -> dict[str, float]:
    g = gate.detach().float().view(-1)
    return {
        "gate_mean": float(g.mean().item()),
        "gate_std": float(g.std(unbiased=False).item()) if g.numel() > 1 else 0.0,
        "gate_min": float(g.min().item()),
        "gate_max": float(g.max().item()),
        "pct_near_0": float((g < 0.05).float().mean().item() * 100.0),
        "pct_near_1": float((g > 0.95).float().mean().item() * 100.0),
    }


def summarize_correction_distribution(correction: torch.Tensor) -> dict[str, float]:
    c = correction.detach().float().view(-1)
    return {
        "correction_mean": float(c.mean().item()),
        "correction_std": float(c.std(unbiased=False).item()) if c.numel() > 1 else 0.0,
        "correction_min": float(c.min().item()),
        "correction_max": float(c.max().item()),
        "correction_abs_mean": float(c.abs().mean().item()),
    }
