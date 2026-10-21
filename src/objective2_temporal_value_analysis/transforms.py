"""Transforms and medians for temporal-value conditions."""

from __future__ import annotations

from typing import Any

import numpy as np

from .constants import SEQ_LEN, SHUFFLE_SEED


def fixed_shuffle_permutation(seq_len: int = SEQ_LEN, seed: int = SHUFFLE_SEED) -> np.ndarray:
    rng = np.random.default_rng(seed)
    perm = rng.permutation(seq_len)
    return perm.astype(np.int64)


def train_feature_medians(X_train: np.ndarray) -> np.ndarray:
    """Feature-wise medians over all train timesteps. Shape (F,)."""
    if X_train.ndim != 3:
        raise ValueError(f"Expected (N,T,F), got {X_train.shape}")
    flat = X_train.reshape(-1, X_train.shape[-1])
    return np.median(flat, axis=0).astype(np.float32)


def apply_condition(
    X: np.ndarray,
    *,
    condition: str,
    perm: np.ndarray,
    medians: np.ndarray,
) -> np.ndarray:
    """Return transformed copy of sequences (N, T, F)."""
    if X.ndim != 3:
        raise ValueError(X.shape)
    out = np.array(X, copy=True, dtype=np.float32)
    t = out.shape[1]
    if condition in {"T0", "T6"}:
        return out
    if condition == "T1":
        return out[:, ::-1, :].copy()
    if condition == "T2":
        if len(perm) != t:
            raise ValueError(f"perm length {len(perm)} != T={t}")
        return out[:, perm, :].copy()
    history = {"T3": 1, "T4": 5, "T5": 10}[condition]
    # Keep most recent `history` days (last axis indices); fill earlier with train medians.
    filled = np.broadcast_to(medians.reshape(1, 1, -1), out.shape).copy()
    filled[:, t - history :, :] = out[:, t - history :, :]
    return filled


def condition_metadata(perm: np.ndarray) -> list[dict[str, Any]]:
    rows = []
    for cid, kind, hist in [
        ("T0", "original", 20),
        ("T1", "reverse", 20),
        ("T2", "shuffle_fixed", 20),
        ("T3", "partial_history", 1),
        ("T4", "partial_history", 5),
        ("T5", "partial_history", 10),
        ("T6", "original_parity_with_T0", 20),
    ]:
        rows.append(
            {
                "condition": cid,
                "kind": kind,
                "history_days": hist,
                "shuffle_seed": SHUFFLE_SEED if cid == "T2" else "",
                "permutation": "|".join(str(int(x)) for x in perm) if cid == "T2" else "",
                "fill": "train_feature_median" if cid in {"T3", "T4", "T5"} else "none",
            }
        )
    return rows
