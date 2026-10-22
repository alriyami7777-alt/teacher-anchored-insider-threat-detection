"""Frozen supervised objectives O0–O4. Pair construction is deterministic within-batch."""

from __future__ import annotations

import torch
import torch.nn.functional as F

from .constants import PAIR_MAX_PER_BATCH, PAIR_NEG_PER_POS


def weighted_bce_with_logits(logits: torch.Tensor, labels: torch.Tensor, pos_weight: float) -> torch.Tensor:
    pw = torch.as_tensor(pos_weight, device=logits.device, dtype=logits.dtype)
    return F.binary_cross_entropy_with_logits(logits, labels, pos_weight=pw)


def focal_bce_with_logits(
    logits: torch.Tensor,
    labels: torch.Tensor,
    pos_weight: float,
    gamma: float,
) -> torch.Tensor:
    """Focal modulation of the producing weighted BCE (INNER_TRAIN pos_weight)."""
    pw = torch.as_tensor(pos_weight, device=logits.device, dtype=logits.dtype)
    bce = F.binary_cross_entropy_with_logits(logits, labels, pos_weight=pw, reduction="none")
    p = torch.sigmoid(logits)
    pt = torch.where(labels > 0.5, p, 1.0 - p).clamp(1e-6, 1.0 - 1e-6)
    return ((1.0 - pt) ** gamma * bce).mean()


def pairwise_ranking_loss(
    logits: torch.Tensor,
    labels: torch.Tensor,
    *,
    max_pairs: int = PAIR_MAX_PER_BATCH,
    neg_per_pos: int = PAIR_NEG_PER_POS,
) -> torch.Tensor:
    """Deterministic within-batch positive-vs-negative logistic ranking.

    L_rank = log(1 + exp(-(s+ - s-)))
    Pair index (i, j) uses round-robin over batch negatives; no RNG.
    """
    pos_idx = torch.nonzero(labels > 0.5, as_tuple=False).flatten()
    neg_idx = torch.nonzero(labels < 0.5, as_tuple=False).flatten()
    if pos_idx.numel() == 0 or neg_idx.numel() == 0:
        return logits.new_zeros(())
    n_pos = int(pos_idx.numel())
    n_neg = int(neg_idx.numel())
    k = min(int(neg_per_pos), n_neg, max(1, int(max_pairs) // n_pos))
    n_pairs = min(n_pos * k, int(max_pairs))
    # Vectorised round-robin: pair p with negative (p * k + j) % n_neg.
    pair_ids = torch.arange(n_pairs, device=logits.device)
    pos_sel = pos_idx[torch.div(pair_ids, k, rounding_mode="floor")]
    neg_sel = neg_idx[(pair_ids) % n_neg]
    # Shift negatives by positive identity so different positives get different negs.
    pos_ord = torch.div(pair_ids, k, rounding_mode="floor")
    j = pair_ids % k
    neg_sel = neg_idx[(pos_ord * k + j) % n_neg]
    s_pos = logits[pos_sel]
    s_neg = logits[neg_sel]
    return torch.log1p(torch.exp(-(s_pos - s_neg))).mean()


def combined_objective(
    logits: torch.Tensor,
    labels: torch.Tensor,
    *,
    family: str,
    pos_weight: float,
    gamma: float = 0.0,
    lambda_rank: float = 0.0,
) -> torch.Tensor:
    family = str(family).upper()
    if family in {"O0", "O3"}:
        task = weighted_bce_with_logits(logits, labels, pos_weight)
    elif family in {"O1", "O4"}:
        task = weighted_bce_with_logits(logits, labels, pos_weight)
    elif family == "O2":
        task = focal_bce_with_logits(logits, labels, pos_weight, gamma)
    else:
        raise ValueError(f"Unknown objective family {family!r}")
    if family in {"O3", "O4"} and lambda_rank > 0:
        return task + float(lambda_rank) * pairwise_ranking_loss(logits, labels)
    return task
