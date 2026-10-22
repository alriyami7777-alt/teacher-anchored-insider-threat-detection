"""Label-blind latent diagnostics. r6.1 labels are not used."""

from __future__ import annotations

import hashlib

import numpy as np

from editor025_r61_autopsy.representation import (
    discriminant_direction,
    project,
    representation_separation,
)

from .constants import DIAGNOSTIC_SAMPLE_N, SEPARATION_EPSILON


def sha256_utf8(text: str) -> str:
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


def sha256_order_indices(sequence_ids: np.ndarray, n: int = DIAGNOSTIC_SAMPLE_N) -> np.ndarray:
    """Ascending SHA256(sequence_id). No class stratification."""
    ids = np.asarray(sequence_ids).astype(str)
    keys = [sha256_utf8(s) for s in ids]
    order = np.argsort(np.asarray(keys), kind="mergesort")
    take = min(int(n), int(len(order)))
    return np.asarray(order[:take], dtype=np.int64)


def source_latent_separation(z: np.ndarray, y: np.ndarray) -> float:
    """EDITOR-025 source discriminant separation on attention representations."""
    z = np.asarray(z, dtype=np.float64)
    y = np.asarray(y).astype(int).ravel()
    pos = z[y == 1]
    neg = z[y == 0]
    if len(pos) == 0 or len(neg) < 2:
        return float("nan")
    d = discriminant_direction(pos, neg)
    p_pos = project(pos, d)
    p_neg = project(neg, d)
    sd = float(p_neg.std(ddof=0))
    if sd == 0.0:
        sd = float(SEPARATION_EPSILON)
    return representation_separation(p_pos, p_neg, sd)
