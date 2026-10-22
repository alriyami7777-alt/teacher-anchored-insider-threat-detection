"""Deep CORAL on attention-pooled representations. Equation is frozen."""

from __future__ import annotations

import torch

from .constants import CORAL_MIN_BATCH


def coral_loss(h_s: torch.Tensor, h_t: torch.Tensor) -> torch.Tensor:
    """L_CORAL = ||C_s - C_t||_F^2 / (4 d^2). Zero if n_s < 2 or n_t < 2."""
    if h_s.ndim != 2 or h_t.ndim != 2:
        raise ValueError(f"CORAL expects (n, d) batches, got {tuple(h_s.shape)} and {tuple(h_t.shape)}")
    n_s = int(h_s.shape[0])
    n_t = int(h_t.shape[0])
    d = int(h_s.shape[1])
    if int(h_t.shape[1]) != d:
        raise ValueError("source and target CORAL widths must match")
    if n_s < CORAL_MIN_BATCH or n_t < CORAL_MIN_BATCH:
        return h_s.new_zeros(())
    hs = h_s - h_s.mean(dim=0, keepdim=True)
    ht = h_t - h_t.mean(dim=0, keepdim=True)
    cov_s = (hs.transpose(0, 1) @ hs) / float(n_s - 1)
    cov_t = (ht.transpose(0, 1) @ ht) / float(n_t - 1)
    return (cov_s - cov_t).pow(2).sum() / (4.0 * float(d) * float(d))


def coral_discrepancy_numpy(h_s, h_t) -> float:
    """Same CORAL equation for label-blind diagnostics. Not used for gradients."""
    import numpy as np

    hs = np.asarray(h_s, dtype=np.float64)
    ht = np.asarray(h_t, dtype=np.float64)
    if hs.ndim != 2 or ht.ndim != 2:
        raise ValueError("CORAL discrepancy expects (n, d)")
    n_s, d = hs.shape
    n_t = ht.shape[0]
    if ht.shape[1] != d:
        raise ValueError("source and target CORAL widths must match")
    if n_s < CORAL_MIN_BATCH or n_t < CORAL_MIN_BATCH:
        return 0.0
    hs = hs - hs.mean(axis=0, keepdims=True)
    ht = ht - ht.mean(axis=0, keepdims=True)
    cov_s = (hs.T @ hs) / float(n_s - 1)
    cov_t = (ht.T @ ht) / float(n_t - 1)
    return float(np.square(cov_s - cov_t).sum() / (4.0 * d * d))
