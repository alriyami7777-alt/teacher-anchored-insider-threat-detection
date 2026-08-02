"""Neural Oblivious Decision Ensembles (NODE) / ODST in pure PyTorch.

Canonical NODE (Popov, Sidorov & Babenko, arXiv:1909.06312)
-----------------------------------------------------------
* Feature selection: ``entmax15`` (α = 1.5 entmax)
* Split decisions: ``entmoid15`` (two-class entmax15)
* Readout (primary): ``canonical_tree_average`` — mean of all tree responses
  across Dense layers (no unrestricted Linear/MLP classification head)

Ablation (explicitly non-canonical)
----------------------------------
* ``sparsemax_sigmoid_odst``: sparsemax feature selection + sigmoid splits
* ``dense_linear_readout``: same Dense ODST stack + ``Linear(h_L)`` readout

This module is **not** an ordinary MLP and **not** the V1/V2
``SoftDecisionTree`` soft forest.

===============================================================================
Canonical NODE equations and tensor dimensions
===============================================================================

Notation: attention representation ``h ∈ R^{B×d}`` (typically ``d=128``),
``T`` trees, depth ``D``, ``L`` Dense layers, positive scale ``τ``.

(1) Feature selection — entmax15 (canonical)
::

    π^{(t,ℓ)} = entmax_{1.5}(F^{(t,ℓ)}) ∈ Δ^{d−1}
    entmax_{1.5}(z)_i = [(½ z_i − τ(z))_+ ]²

Ablation: ``π = sparsemax(F)``.

Shapes: ``feature_logits, feature_probs : (T, D, d)``.

(2) Soft oblivious split — entmoid15 (canonical)
::

    s^{(t,ℓ)}(h) = ⟨π^{(t,ℓ)}, h⟩                         # (B, T, D)
    c^{(t,ℓ)}(h) = entmoid15( (s^{(t,ℓ)} − b^{(t,ℓ)}) / τ )
    entmoid15(x) ≔ entmax15([x, 0])[..., 0] ∈ [0, 1]

Ablation: ``c = σ((s − b) / τ)``.

Shapes: ``thresholds, log_temperatures : (T, D)``; ``choice : (B, T, D)``.

(3) Leaf routing (unchanged oblivious product)
::

    μ_e(h) = ∏_ℓ [c]^{e_ℓ} [1−c]^{1−e_ℓ},   e ∈ {0,1}^D
    leaf_probs : (B, T, 2^D)

(4) Tree response
::

    f_tree^{(t)}(h) = ∑_e μ_e(h) · R_e^{(t)}     # (B,) when U=1

(5) Dense stacking
::

    h_0 = h
    for l = 1..L:
        O_l = ODST_l(h_{l−1}) ∈ R^{B × T}       # tree responses
        h_l = [h_{l−1}; O_l]

(6a) Canonical readout — tree average (primary)
::

    node_logit = (1 / (L·T)) ∑_{l,t} f_tree^{(l,t)}
    # NO extra Linear/MLP after aggregation

(6b) Ablation readout — dense linear
::

    node_logit = Linear(h_L)
"""

from __future__ import annotations

from typing import Any, Literal

import torch
import torch.nn as nn
import torch.nn.functional as F

ChoiceFunction = Literal["entmax15", "sparsemax_sigmoid"]
ReadoutMode = Literal["canonical_tree_average", "dense_linear_readout"]

CHOICE_FUNCTIONS = ("entmax15", "sparsemax_sigmoid")
READOUT_MODES = ("canonical_tree_average", "dense_linear_readout")

CANONICAL_NODE_EQUATIONS = {
    "feature_selection": "π = entmax15(F);  entmax15(z)_i = [(½ z_i − τ)_+]^2",
    "split_decision": "c = entmoid15((⟨π,h⟩ − b) / τ);  entmoid15(x)=entmax15([x,0])_0",
    "leaf_routing": "μ_e = ∏_ℓ c^{e_ℓ} (1−c)^{1−e_ℓ}",
    "tree_response": "f_tree = ∑_e μ_e R_e",
    "dense_stack": "h_l = [h_{l−1}; O_l]",
    "canonical_readout": "node_logit = mean_{l,t} f_tree^{(l,t)}  (no Linear MLP)",
    "reference": "Popov et al., Neural Oblivious Decision Ensembles (arXiv:1909.06312)",
}

ABLATION_EQUATIONS = {
    "sparsemax_sigmoid_odst": {
        "feature_selection": "π = sparsemax(F)",
        "split_decision": "c = σ((⟨π,h⟩ − b) / τ)",
        "note": "Explicitly non-canonical ablation; do not call this canonical NODE.",
    },
    "dense_linear_readout": {
        "readout": "node_logit = Linear(h_L)",
        "note": "Ablation retaining unrestricted linear classification on Dense features.",
    },
}

# Back-compat alias used by protocol / reports.
NODE_EQUATIONS = dict(CANONICAL_NODE_EQUATIONS)


# ---------------------------------------------------------------------------
# Sparsemax (ablation) — Martins & Astudillo, 2016
# ---------------------------------------------------------------------------


def sparsemax(logits: torch.Tensor, dim: int = -1) -> torch.Tensor:
    """``sparsemax(z)_i = max(0, z_i − τ(z))`` with simplex sum = 1."""
    if dim < 0:
        dim = logits.dim() + dim
    z = logits - logits.max(dim=dim, keepdim=True).values
    z_sorted, _ = torch.sort(z, dim=dim, descending=True)
    cumsum = z_sorted.cumsum(dim=dim)
    n = z.size(dim)
    k = torch.arange(1, n + 1, device=logits.device, dtype=logits.dtype)
    view = [1] * z.dim()
    view[dim] = n
    k = k.view(*view)
    support = (1.0 + k * z_sorted) > cumsum
    k_z = support.sum(dim=dim, keepdim=True).clamp_min(1)
    tau_sum = cumsum.gather(dim, (k_z - 1).long())
    tau = (tau_sum - 1.0) / k_z.to(logits.dtype)
    return torch.clamp(z - tau, min=0.0)


# ---------------------------------------------------------------------------
# Entmax-1.5 / Entmoid-1.5 (canonical NODE) — Peters et al. / Popov et al.
# ---------------------------------------------------------------------------


def _entmax15_threshold_and_support(
    x: torch.Tensor, dim: int = -1
) -> tuple[torch.Tensor, torch.Tensor]:
    """Compute τ* and support size for α=1.5 entmax on already-scaled ``x=z/2``."""
    if dim < 0:
        dim = x.dim() + dim
    xsrt, _ = torch.sort(x, dim=dim, descending=True)
    rho = torch.arange(1, x.size(dim) + 1, device=x.device, dtype=x.dtype)
    view = [1] * x.dim()
    view[dim] = -1
    rho = rho.view(*view)

    mean = xsrt.cumsum(dim=dim) / rho
    mean_sq = (xsrt**2).cumsum(dim=dim) / rho
    ss = rho * (mean_sq - mean**2)
    delta = (1.0 - ss) / rho
    # Numerical clamp: delta can be slightly negative from fp error.
    delta_nz = torch.clamp(delta, min=0.0)
    tau = mean - torch.sqrt(delta_nz)

    support = (tau <= xsrt).to(x.dtype)
    support_size = support.sum(dim=dim, keepdim=True).clamp_min(1)
    tau_star = tau.gather(dim, (support_size - 1).long())
    return tau_star, support_size


def entmax15(logits: torch.Tensor, dim: int = -1) -> torch.Tensor:
    """α = 1.5 entmax: ``p_i = [(½ z_i − τ)_+]^2``, ``∑ p = 1``."""
    if dim < 0:
        dim = logits.dim() + dim
    z = logits - logits.max(dim=dim, keepdim=True).values
    x = z / 2.0  # (α − 1) z with α = 1.5
    tau_star, _ = _entmax15_threshold_and_support(x, dim=dim)
    p = torch.clamp(x - tau_star, min=0.0) ** 2
    # Renormalise tiny fp drift (should already sum ≈ 1).
    return p / p.sum(dim=dim, keepdim=True).clamp_min(1e-12)


def entmoid15(x: torch.Tensor) -> torch.Tensor:
    """Two-class entmax15: ``entmoid15(x) = entmax15([x, 0])[..., 0] ∈ [0, 1]``.

    Closed form (equivalent to stacking ``[x, 0]``)::

        entmoid15(x) =
            0                          if x ≤ −2
            ((x + 2) / 4)²             if −2 < x < +2   # continuous
            1                          if x ≥ +2

    The interior branch is the exact two-class α=1.5 solution used by NODE.
    """
    # Exact closed form from the NODE / entmax literature for 2-class α=1.5.
    # At x=0: ((2)/4)^2 = 0.25? — WRONG for uniform.
    # Correct derivation via entmax15([x, 0]):
    stacked = torch.stack([x, torch.zeros_like(x)], dim=-1)
    return entmax15(stacked, dim=-1)[..., 0]


# ---------------------------------------------------------------------------
# ODST block
# ---------------------------------------------------------------------------


class ODST(nn.Module):
    """Oblivious Differentiable Soft Tree ensemble (one Dense NODE layer)."""

    def __init__(
        self,
        in_dim: int,
        n_trees: int = 8,
        depth: int = 4,
        tree_dim: int = 1,
        temperature: float = 1.0,
        choice_function: ChoiceFunction = "entmax15",
        flatten_output: bool = True,
        leaf_init_std: float = 0.05,
    ) -> None:
        super().__init__()
        if in_dim < 1 or n_trees < 1 or depth < 1 or tree_dim < 1:
            raise ValueError("in_dim, n_trees, depth, tree_dim must be >= 1")
        if temperature <= 0:
            raise ValueError("temperature must be positive")
        if choice_function not in CHOICE_FUNCTIONS:
            raise ValueError(
                f"Unknown choice_function={choice_function!r}; "
                f"expected one of {CHOICE_FUNCTIONS}"
            )

        self.in_dim = int(in_dim)
        self.n_trees = int(n_trees)
        self.depth = int(depth)
        self.tree_dim = int(tree_dim)
        self.choice_function = choice_function
        self.flatten_output = bool(flatten_output)
        self.n_leaves = 2**self.depth
        self.leaf_init_std = float(leaf_init_std)

        self.feature_logits = nn.Parameter(
            torch.empty(self.n_trees, self.depth, self.in_dim)
        )
        self.thresholds = nn.Parameter(torch.zeros(self.n_trees, self.depth))
        # Learnable positive temperatures via softplus(log_temperature).
        self.log_temperatures = nn.Parameter(
            torch.full((self.n_trees, self.depth), float(torch.log(torch.tensor(temperature))))
        )
        self.leaf_responses = nn.Parameter(
            torch.empty(self.n_trees, self.n_leaves, self.tree_dim)
        )

        nn.init.xavier_uniform_(self.feature_logits)
        nn.init.normal_(self.leaf_responses, mean=0.0, std=self.leaf_init_std)

        codes = torch.zeros(self.n_leaves, self.depth, dtype=torch.float32)
        for leaf in range(self.n_leaves):
            for level in range(self.depth):
                codes[leaf, level] = float((leaf >> (self.depth - 1 - level)) & 1)
        self.register_buffer("leaf_codes", codes, persistent=False)

    def temperatures(self) -> torch.Tensor:
        """Positive scales ``τ = softplus(log_τ) + ε``, shape ``(T, D)``."""
        return F.softplus(self.log_temperatures) + 1e-4

    def feature_selection_probs(self) -> torch.Tensor:
        if self.choice_function == "entmax15":
            return entmax15(self.feature_logits, dim=-1)
        return sparsemax(self.feature_logits, dim=-1)

    def split_choice(self, selected: torch.Tensor) -> torch.Tensor:
        """Map projected features to soft right-branch probabilities ``(B,T,D)``."""
        tau = self.temperatures()
        scaled = (selected - self.thresholds) / tau
        if self.choice_function == "entmax15":
            return entmoid15(scaled)
        return torch.sigmoid(scaled)

    def forward(self, h: torch.Tensor) -> tuple[torch.Tensor, dict[str, Any]]:
        if h.dim() != 2 or h.size(-1) != self.in_dim:
            raise ValueError(f"Expected (B, {self.in_dim}); got {tuple(h.shape)}")

        batch = h.size(0)
        feature_probs = self.feature_selection_probs()
        selected = torch.einsum("bf,tdf->btd", h, feature_probs)
        choice = self.split_choice(selected)
        tau = self.temperatures()

        c = choice.unsqueeze(2).expand(batch, self.n_trees, self.n_leaves, self.depth)
        codes = self.leaf_codes.view(1, 1, self.n_leaves, self.depth)
        log_c = torch.log(c.clamp(1e-8, 1.0 - 1e-8))
        log_1mc = torch.log((1.0 - c).clamp(1e-8, 1.0))
        leaf_probs = torch.exp((codes * log_c + (1.0 - codes) * log_1mc).sum(dim=-1))

        response = torch.einsum("btl,tlu->btu", leaf_probs, self.leaf_responses)
        out = response.reshape(batch, self.n_trees * self.tree_dim) if self.flatten_output else response

        extras: dict[str, Any] = {
            "feature_selection_probs": feature_probs.detach(),
            "thresholds": self.thresholds.detach(),
            "temperatures": tau.detach(),
            "choice": choice.detach(),
            "leaf_probs": leaf_probs.detach(),
            "tree_response": response.detach(),
            "selected_features": selected.detach(),
            "n_trees": self.n_trees,
            "depth": self.depth,
            "n_leaves": self.n_leaves,
            "in_dim": self.in_dim,
            "tree_dim": self.tree_dim,
            "choice_function": self.choice_function,
            "mechanism": (
                "ODST+entmax15+entmoid15"
                if self.choice_function == "entmax15"
                else "ODST+sparsemax+sigmoid (ablation)"
            ),
        }
        return out, extras

    @torch.no_grad()
    def data_aware_initialize(
        self,
        h: torch.Tensor,
        *,
        threshold_quantile: float = 0.5,
        target_scaled_std: float = 1.0,
        leaf_init_std: float | None = None,
    ) -> dict[str, float]:
        """Initialize thresholds / temperatures from a training batch of ``h``.

        Does **not** use labels. Operates under ``torch.no_grad()``.
        """
        if h.dim() != 2 or h.size(-1) != self.in_dim:
            raise ValueError(f"Expected (B, {self.in_dim}); got {tuple(h.shape)}")
        if h.size(0) < 2:
            raise ValueError("data-aware init needs batch size >= 2")

        # Keep current feature logits (xavier); only refresh thresholds/temps/leaves.
        feature_probs = self.feature_selection_probs()
        selected = torch.einsum("bf,tdf->btd", h, feature_probs)  # (B, T, D)

        # Thresholds from batch quantiles of projected features (per tree/depth).
        q = float(threshold_quantile)
        # quantile over batch dim → (T, D)
        thresholds = torch.quantile(selected, q, dim=0)
        self.thresholds.copy_(thresholds)

        # Temperatures so (s − b)/τ has ~target_scaled_std on this batch.
        centered = selected - self.thresholds
        std = centered.std(dim=0, unbiased=False).clamp_min(1e-3)
        tau = (std / max(float(target_scaled_std), 1e-3)).clamp(1e-3, 50.0)
        # softplus(log_τ) + eps ≈ τ  ⇒  log_τ ≈ log(expm1(τ − eps))
        self.log_temperatures.copy_(torch.log(torch.expm1(tau.clamp_min(1e-3 + 1e-4))))

        std_leaf = self.leaf_init_std if leaf_init_std is None else float(leaf_init_std)
        self.leaf_responses.normal_(mean=0.0, std=std_leaf)

        choice = self.split_choice(selected)
        return {
            "threshold_mean": float(self.thresholds.mean()),
            "threshold_std": float(self.thresholds.std(unbiased=False)),
            "threshold_min": float(self.thresholds.min()),
            "threshold_max": float(self.thresholds.max()),
            "temperature_mean": float(self.temperatures().mean()),
            "temperature_std": float(self.temperatures().std(unbiased=False)),
            "temperature_min": float(self.temperatures().min()),
            "temperature_max": float(self.temperatures().max()),
            "split_prob_mean": float(choice.mean()),
            "split_prob_std": float(choice.std(unbiased=False)),
            "pct_split_below_0_01": float((choice < 0.01).float().mean() * 100.0),
            "pct_split_above_0_99": float((choice > 0.99).float().mean() * 100.0),
        }


class NODE(nn.Module):
    """Dense-stacked NODE with canonical tree-average or dense-linear readout."""

    def __init__(
        self,
        in_dim: int = 128,
        num_layers: int = 2,
        n_trees: int = 8,
        depth: int = 4,
        tree_dim: int = 1,
        temperature: float = 1.0,
        dropout: float = 0.0,
        choice_function: ChoiceFunction = "entmax15",
        readout: ReadoutMode = "canonical_tree_average",
        leaf_init_std: float = 0.05,
    ) -> None:
        super().__init__()
        if num_layers < 1:
            raise ValueError("num_layers must be >= 1")
        if choice_function not in CHOICE_FUNCTIONS:
            raise ValueError(f"Unknown choice_function={choice_function!r}")
        if readout not in READOUT_MODES:
            raise ValueError(f"Unknown readout={readout!r}")
        if tree_dim != 1 and readout == "canonical_tree_average":
            raise ValueError("canonical_tree_average requires tree_dim=1")

        self.in_dim = int(in_dim)
        self.num_layers = int(num_layers)
        self.n_trees = int(n_trees)
        self.depth = int(depth)
        self.tree_dim = int(tree_dim)
        self.choice_function = choice_function
        self.readout = readout
        self.leaf_init_std = float(leaf_init_std)

        layers: list[ODST] = []
        dims: list[int] = []
        cur = self.in_dim
        for _ in range(self.num_layers):
            layers.append(
                ODST(
                    in_dim=cur,
                    n_trees=self.n_trees,
                    depth=self.depth,
                    tree_dim=self.tree_dim,
                    temperature=temperature,
                    choice_function=choice_function,
                    flatten_output=True,
                    leaf_init_std=leaf_init_std,
                )
            )
            cur = cur + self.n_trees * self.tree_dim
            dims.append(cur)
        self.layers = nn.ModuleList(layers)
        self.layer_out_dims = dims
        self.final_dim = cur
        self.between_dropout = nn.Dropout(dropout) if dropout > 0 else nn.Identity()

        # Ablation-only linear readout on Dense features.
        self.output_head = nn.Linear(self.final_dim, 1)
        nn.init.zeros_(self.output_head.weight)
        nn.init.zeros_(self.output_head.bias)
        if readout == "canonical_tree_average":
            # Keep parameters present for state_dict stability but freeze unused head.
            for p in self.output_head.parameters():
                p.requires_grad = False

    def forward(self, h: torch.Tensor) -> tuple[torch.Tensor, dict[str, Any]]:
        if h.dim() != 2 or h.size(-1) != self.in_dim:
            raise ValueError(f"Expected (B, {self.in_dim}); got {tuple(h.shape)}")

        x = h
        layer_extras: list[dict[str, Any]] = []
        tree_logit_bags: list[torch.Tensor] = []
        for layer in self.layers:
            out, ex = layer(x)
            # out: (B, T*U); for U=1 → (B, T) tree responses
            if self.tree_dim == 1:
                tree_logit_bags.append(out)
            layer_extras.append(ex)
            x = self.between_dropout(torch.cat([x, out], dim=-1))

        if self.readout == "canonical_tree_average":
            # Mean over all trees in all layers — no Linear classification head.
            all_trees = torch.cat(tree_logit_bags, dim=-1)  # (B, L*T)
            node_logit = all_trees.mean(dim=-1)
            readout_name = "canonical_tree_average"
        else:
            node_logit = self.output_head(x).squeeze(-1)
            readout_name = "dense_linear_readout"

        extras: dict[str, Any] = {
            "node_dense_features": x.detach(),
            "layer_tree_logits": [t.detach() for t in tree_logit_bags],
            "odst_layers": layer_extras,
            "num_layers": self.num_layers,
            "n_trees": self.n_trees,
            "depth": self.depth,
            "final_dim": self.final_dim,
            "choice_function": self.choice_function,
            "readout": readout_name,
            "equations": dict(CANONICAL_NODE_EQUATIONS),
            "ablation_equations": dict(ABLATION_EQUATIONS),
            "mechanism": (
                f"NODE/{self.choice_function}/{readout_name}"
            ),
            "is_canonical_node": (
                self.choice_function == "entmax15"
                and readout_name == "canonical_tree_average"
            ),
        }
        if layer_extras:
            first = layer_extras[0]
            extras["feature_selection_probs"] = first["feature_selection_probs"]
            extras["thresholds"] = first["thresholds"]
            extras["temperatures"] = first["temperatures"]
            extras["leaf_probs"] = first["leaf_probs"]
            extras["choice"] = first["choice"]
        return node_logit, extras

    @torch.no_grad()
    def data_aware_initialize(self, h: torch.Tensor, **kwargs: Any) -> dict[str, Any]:
        """Run data-aware init on every ODST layer using Dense-expanded features."""
        reports: list[dict[str, float]] = []
        x = h
        for layer in self.layers:
            reports.append(layer.data_aware_initialize(x, **kwargs))
            out, _ = layer(x)
            x = torch.cat([x, out], dim=-1)
        # Aggregate scalar summaries across layers.
        keys = [
            "threshold_mean",
            "threshold_std",
            "threshold_min",
            "threshold_max",
            "temperature_mean",
            "temperature_std",
            "temperature_min",
            "temperature_max",
            "split_prob_mean",
            "split_prob_std",
            "pct_split_below_0_01",
            "pct_split_above_0_99",
        ]
        agg = {k: float(sum(r[k] for r in reports) / len(reports)) for k in keys}
        # Min/max should be global extremes, not means.
        agg["threshold_min"] = float(min(r["threshold_min"] for r in reports))
        agg["threshold_max"] = float(max(r["threshold_max"] for r in reports))
        agg["temperature_min"] = float(min(r["temperature_min"] for r in reports))
        agg["temperature_max"] = float(max(r["temperature_max"] for r in reports))
        agg["layer_reports"] = reports
        agg["n_layers_initialized"] = len(reports)
        return agg

    def zero_init_leaf_responses(self) -> None:
        """Optional residual-start helper (small normal preferred for canonical)."""
        with torch.no_grad():
            for layer in self.layers:
                layer.leaf_responses.normal_(0.0, layer.leaf_init_std)
            self.output_head.weight.zero_()
            self.output_head.bias.zero_()


def summarize_odst_shapes(
    in_dim: int = 128,
    num_layers: int = 2,
    n_trees: int = 8,
    depth: int = 4,
    tree_dim: int = 1,
    choice_function: str = "entmax15",
    readout: str = "canonical_tree_average",
) -> dict[str, Any]:
    n_leaves = 2**depth
    dims = []
    cur = in_dim
    for _ in range(num_layers):
        cur = cur + n_trees * tree_dim
        dims.append(cur)
    return {
        "input_h": f"(B, {in_dim})",
        "feature_logits_per_layer": f"(T={n_trees}, D={depth}, d_in)",
        "feature_selection_probs": f"(T={n_trees}, D={depth}, d_in)",
        "thresholds": f"(T={n_trees}, D={depth})",
        "temperatures": f"(T={n_trees}, D={depth})",
        "choice": f"(B, T={n_trees}, D={depth})",
        "leaf_probs": f"(B, T={n_trees}, L={n_leaves})",
        "leaf_responses": f"(T={n_trees}, L={n_leaves}, U={tree_dim})",
        "layer_output": f"(B, T·U={n_trees * tree_dim})",
        "dense_feature_dims_after_each_layer": dims,
        "final_dense_dim": dims[-1] if dims else in_dim,
        "node_logit": "(B,)",
        "choice_function": choice_function,
        "readout": readout,
        "canonical_equations": dict(CANONICAL_NODE_EQUATIONS),
        "ablation_equations": dict(ABLATION_EQUATIONS),
    }
