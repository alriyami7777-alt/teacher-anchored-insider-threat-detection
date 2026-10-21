"""Temporal transforms and chronological flatten."""

from __future__ import annotations

from typing import Any

import numpy as np

from .constants import FLAT_DIM, N_FEATURES, SEQ_LEN, SHUFFLE_SEED, STATUS_FEATURE


def fixed_shuffle_permutation(seq_len: int = SEQ_LEN, seed: int = SHUFFLE_SEED) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.permutation(seq_len).astype(np.int64)


def train_feature_medians(X_train: np.ndarray) -> np.ndarray:
    if X_train.ndim != 3:
        raise ValueError(X_train.shape)
    return np.median(X_train.reshape(-1, X_train.shape[-1]), axis=0).astype(np.float32)


def flatten_sequences(X: np.ndarray) -> np.ndarray:
    if X.ndim != 3 or X.shape[1] != SEQ_LEN or X.shape[2] != N_FEATURES:
        from .safety import TemporalBlockedError

        raise TemporalBlockedError(STATUS_FEATURE, f"bad shape {X.shape}")
    flat = np.ascontiguousarray(X.reshape(X.shape[0], FLAT_DIM))
    if not np.array_equal(flat.reshape(-1, SEQ_LEN, N_FEATURES), X):
        from .safety import TemporalBlockedError

        raise TemporalBlockedError(STATUS_FEATURE, "flatten parity failed")
    return flat.astype(np.float32, copy=False)


def apply_condition(
    X: np.ndarray,
    *,
    condition: str,
    perm: np.ndarray,
    medians: np.ndarray,
) -> np.ndarray:
    if X.ndim != 3:
        raise ValueError(X.shape)
    out = np.array(X, copy=True, dtype=np.float32)
    t = out.shape[1]
    if condition in {"T0", "T6"}:
        return out
    if condition == "T1":
        # Reverse day blocks; keep internal 13-feature order.
        return out[:, ::-1, :].copy()
    if condition == "T2":
        if len(perm) != t:
            raise ValueError(f"perm length {len(perm)} != T={t}")
        return out[:, perm, :].copy()
    history = {"T3": 1, "T4": 5, "T5": 10}[condition]
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
                "fill": "r52_train_feature_median" if cid in {"T3", "T4", "T5"} else "none",
            }
        )
    return rows
