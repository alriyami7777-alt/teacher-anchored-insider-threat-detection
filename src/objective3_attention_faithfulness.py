#!/usr/bin/env python3
"""Attention-faithfulness helpers (timestep masking; no latent ablation).

CERT r4.2 validation pilot. Evaluates whether high-attention timesteps influence
the model’s original prediction more than low-ranked or random timesteps.
"""

from __future__ import annotations

import hashlib
from typing import Any, Sequence

import numpy as np
import torch
import torch.nn.functional as F

from models.sequence_ensemble import SequenceEnsembleModel
from prototype_v3_node.architecture import AttentionNodeEnsemble

PROTOCOL_SEED = 20260724
DEFAULT_K_VALUES: tuple[int, ...] = (1, 3, 5, 10)
DEFAULT_RANDOM_REPS = 25
EXPECTED_MANIFEST_SHA256 = (
    "5c71e234d5b4eccd48095b114ec34351d841780bd46fc0ab295d7a6d84812a10"
)
PROTOCOL_ID = "obj3_attention_faithfulness_pilot_r42_validation_multiseed"
MASKING_METHOD = (
    "timestep_mask: zero invalid inputs for encoder AND masked-softmax attention "
    "(-inf on invalid energies); chronological positions retained; no length shift"
)


def predicted_class(prob: float, threshold: float) -> int:
    return 1 if float(prob) >= float(threshold) else 0


def predicted_class_confidence(prob: float, original_pred: int) -> float:
    """Confidence in the *original* predicted class (held fixed under perturbation)."""
    p = float(prob)
    return p if int(original_pred) == 1 else (1.0 - p)


def comprehensiveness(c_original: float, c_deleted: float) -> float:
    return float(c_original) - float(c_deleted)


def sufficiency_gap(c_original: float, c_retained: float) -> float:
    return float(c_original) - float(c_retained)


def rank_timesteps(attention: np.ndarray) -> np.ndarray:
    """Return indices sorted highest-attention first; ties → lower timestep index."""
    w = np.asarray(attention, dtype=np.float64).ravel()
    # lexsort: last key primary; use -w then index
    order = np.lexsort((np.arange(w.size), -w))
    return order.astype(int)


def top_k_indices_from_rank(rank_order: np.ndarray, k: int) -> list[int]:
    k_eff = min(int(k), int(rank_order.size))
    if k_eff < 1:
        raise ValueError("effective k must be >= 1")
    return [int(i) for i in rank_order[:k_eff]]


def bottom_k_indices_from_rank(rank_order: np.ndarray, k: int) -> list[int]:
    k_eff = min(int(k), int(rank_order.size))
    if k_eff < 1:
        raise ValueError("effective k must be >= 1")
    return [int(i) for i in rank_order[-k_eff:]]


def derive_random_selection_seed(
    *,
    protocol_seed: int,
    architecture: str,
    model_seed: int,
    sample_id: str,
    k: int,
    repetition: int,
) -> int:
    payload = (
        f"{int(protocol_seed)}|{architecture}|{int(model_seed)}|"
        f"{sample_id}|{int(k)}|{int(repetition)}"
    ).encode("utf-8")
    return int(hashlib.sha256(payload).hexdigest()[:16], 16) % (2**31)


def random_k_indices(
    n_valid: int,
    k: int,
    rng_seed: int,
    *,
    valid_indices: Sequence[int] | None = None,
) -> list[int]:
    valid = list(valid_indices) if valid_indices is not None else list(range(n_valid))
    k_eff = min(int(k), len(valid))
    if k_eff < 1:
        raise ValueError("effective k must be >= 1")
    if k_eff >= len(valid):
        # Cannot mask/retain all for deletion/sufficiency safety handled by caller
        k_eff = len(valid) - 1 if len(valid) > 1 else 1
    rng = np.random.default_rng(int(rng_seed))
    chosen = rng.choice(valid, size=k_eff, replace=False)
    return sorted(int(i) for i in chosen)


def effective_k(requested_k: int, n_valid: int, *, leave_one: bool) -> int:
    """Cap k; for deletion leave_one=True ensures ≥1 valid remains."""
    if n_valid < 1:
        raise ValueError("no valid timesteps")
    k = min(int(requested_k), n_valid)
    if leave_one and k >= n_valid:
        k = n_valid - 1
    if k < 1:
        k = 1 if n_valid >= 1 else 0
    return int(k)


def build_deletion_mask(n_timesteps: int, delete_indices: Sequence[int]) -> np.ndarray:
    mask = np.ones(n_timesteps, dtype=bool)
    for i in delete_indices:
        mask[int(i)] = False
    if not mask.any():
        raise ValueError("deletion would mask all timesteps")
    return mask


def build_sufficiency_mask(n_timesteps: int, retain_indices: Sequence[int]) -> np.ndarray:
    mask = np.zeros(n_timesteps, dtype=bool)
    for i in retain_indices:
        mask[int(i)] = True
    if not mask.any():
        raise ValueError("sufficiency mask has no valid timesteps")
    return mask


def ranking_hash(model_id: str, seed: int, sample_id: str, weights: np.ndarray) -> str:
    h = hashlib.sha256()
    h.update(f"{model_id}|{seed}|{sample_id}|".encode("utf-8"))
    arr = np.ascontiguousarray(np.asarray(weights, dtype=np.float64))
    h.update(arr.tobytes())
    return h.hexdigest()


@torch.no_grad()
def forward_with_timestep_mask(
    model: torch.nn.Module,
    x: torch.Tensor,
    mask_valid: torch.Tensor,
) -> tuple[torch.Tensor, torch.Tensor]:
    """Identical masking for ODST and attention–linear.

    1. Clone inputs; zero invalid timesteps (no arbitrary non-zero fill).
    2. Masked-softmax attention: invalid energies → -inf.
    3. Aggregate only over valid positions; chronological length unchanged.
    """
    if x.dim() != 3:
        raise ValueError(f"Expected (B,T,F); got {tuple(x.shape)}")
    if mask_valid.shape != x.shape[:2]:
        raise ValueError("mask must be (B,T)")
    if mask_valid.dtype != torch.bool:
        mask_valid = mask_valid != 0
    if not bool(mask_valid.any()):
        raise ValueError("mask has no valid timesteps")
    # Per-row: at least one valid
    if bool((mask_valid.sum(dim=1) < 1).any()):
        raise ValueError("each sequence must retain ≥1 valid timestep")

    x_in = x.detach()
    m = mask_valid.detach()
    x_work = x_in * m.unsqueeze(-1).to(dtype=x_in.dtype)

    if isinstance(model, AttentionNodeEnsemble):
        hidden, _ = model.lstm(x_work)
        hidden = model.dropout(hidden)
        energies = model.attention.score(
            torch.tanh(model.attention.projection(hidden))
        ).squeeze(-1)
        energies = energies.masked_fill(~m, float("-inf"))
        attn = torch.softmax(energies, dim=1)
        # Numerical guard if any row still nan
        attn = torch.nan_to_num(attn, nan=0.0)
        aggregated = torch.bmm(attn.unsqueeze(1), hidden).squeeze(1)
        node_logit, _ = model.node_head(aggregated)
        if model.fusion_variant in {
            "canonical_entmax15_node",
            "sparsemax_sigmoid_odst",
            "dense_linear_readout_node",
        }:
            logits = node_logit
        elif model.fusion_variant == "attention_linear_reference":
            logits = model.linear_head(aggregated).squeeze(-1)
        else:
            linear_logit = model.linear_head(aggregated).squeeze(-1)
            node_bounded = torch.tanh(node_logit)
            gate = model._gate_values(aggregated)
            alpha = model.effective_alpha()
            logits = linear_logit + alpha * gate * node_bounded
        return logits, attn

    if isinstance(model, SequenceEnsembleModel):
        hidden, _ = model.lstm(x_work)
        hidden = model.dropout(hidden)
        energies = model.attention.score(
            torch.tanh(model.attention.projection(hidden))
        ).squeeze(-1)
        energies = energies.masked_fill(~m, float("-inf"))
        attn = torch.softmax(energies, dim=1)
        attn = torch.nan_to_num(attn, nan=0.0)
        z = torch.bmm(attn.unsqueeze(1), hidden).squeeze(1)
        if model.classification_head == "linear":
            assert model.linear_head is not None
            logits = model.linear_head(z).squeeze(-1)
        else:
            assert model.forest is not None
            logits, _ = model.forest(z)
        return logits, attn

    raise TypeError(f"Unsupported model type for masked forward: {type(model)}")


def area_over_perturbation_curve(
    k_values: Sequence[int],
    metric_values: Sequence[float],
) -> float:
    """Normalised trapezoidal area over k (documented convention).

    AOPC = trapz(metric, k) / (k_max - k_min)
    Interpreting metric as Comp_k or SuffGap_k: larger AOPC for Comp means
    larger average confidence drop under deletion across the k grid.
    """
    ks = np.asarray(list(k_values), dtype=np.float64)
    ys = np.asarray(list(metric_values), dtype=np.float64)
    if ks.size != ys.size or ks.size < 2:
        return float("nan")
    order = np.argsort(ks)
    ks, ys = ks[order], ys[order]
    width = float(ks[-1] - ks[0])
    if width <= 0:
        return float("nan")
    return float(np.trapezoid(ys, ks) / width)


def descriptive_stats(values: list[float]) -> dict[str, float]:
    arr = np.asarray(values, dtype=np.float64)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return {
            "count": 0,
            "mean": float("nan"),
            "std": float("nan"),
            "median": float("nan"),
            "iqr": float("nan"),
            "min": float("nan"),
            "max": float("nan"),
        }
    q75, q25 = np.percentile(arr, [75, 25])
    return {
        "count": int(arr.size),
        "mean": float(arr.mean()),
        "std": float(arr.std(ddof=1)) if arr.size > 1 else 0.0,
        "median": float(np.median(arr)),
        "iqr": float(q75 - q25),
        "min": float(arr.min()),
        "max": float(arr.max()),
    }


def assert_input_unmutated(original: np.ndarray, maybe_changed: np.ndarray) -> bool:
    return bool(np.array_equal(original, maybe_changed))


__all__ = [
    "DEFAULT_K_VALUES",
    "DEFAULT_RANDOM_REPS",
    "EXPECTED_MANIFEST_SHA256",
    "MASKING_METHOD",
    "PROTOCOL_ID",
    "PROTOCOL_SEED",
    "area_over_perturbation_curve",
    "assert_input_unmutated",
    "bottom_k_indices_from_rank",
    "build_deletion_mask",
    "build_sufficiency_mask",
    "comprehensiveness",
    "derive_random_selection_seed",
    "descriptive_stats",
    "effective_k",
    "forward_with_timestep_mask",
    "predicted_class",
    "predicted_class_confidence",
    "random_k_indices",
    "rank_timesteps",
    "ranking_hash",
    "sufficiency_gap",
    "top_k_indices_from_rank",
]
