"""Deterministic sampling and SHA helpers. Negatives are never selected by score."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

import numpy as np


def sha256_utf8(text: str) -> str:
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


def sort_indices_by_sha(sequence_ids: Sequence[str], indices: np.ndarray) -> np.ndarray:
    ids = np.asarray(sequence_ids).astype(str)
    idx = np.asarray(indices, dtype=np.int64)
    keys = [sha256_utf8(ids[int(i)]) for i in idx]
    order = np.argsort(np.asarray(keys), kind="mergesort")
    return idx[order]


def negative_representation_sample(
    sequence_ids: Sequence[str],
    labels: np.ndarray,
    n: int,
) -> np.ndarray:
    """Ascending SHA256(sequence_id) among negatives. Score-independent."""
    y = np.asarray(labels).astype(int).ravel()
    neg = np.flatnonzero(y == 0)
    ordered = sort_indices_by_sha(sequence_ids, neg)
    if n < 0:
        raise ValueError("n must be non-negative")
    return ordered[: min(int(n), len(ordered))]


def representation_sample_indices(
    sequence_ids: Sequence[str],
    labels: np.ndarray,
    n_negatives: int,
) -> np.ndarray:
    y = np.asarray(labels).astype(int).ravel()
    pos = np.flatnonzero(y == 1)
    neg = negative_representation_sample(sequence_ids, y, n_negatives)
    return np.concatenate([pos, neg])


def reference_negative_cohort(
    sequence_ids: Sequence[str],
    labels: np.ndarray,
    n: int,
) -> np.ndarray:
    return negative_representation_sample(sequence_ids, labels, n)


def false_positive_cohort(
    labels: np.ndarray,
    scores: np.ndarray,
    n: int,
) -> np.ndarray:
    y = np.asarray(labels).astype(int).ravel()
    s = np.asarray(scores, dtype=np.float64).ravel()
    neg = np.flatnonzero(y == 0)
    if len(neg) == 0:
        return neg
    order = np.argsort(-s[neg], kind="mergesort")
    return neg[order[: min(int(n), len(neg))]]
