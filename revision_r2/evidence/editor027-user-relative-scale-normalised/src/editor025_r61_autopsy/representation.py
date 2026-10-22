"""Phase H — attention-pooled representation versus head. No model modification. No head swap."""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np

from .constants import REPRESENTATION_NEGATIVE_N, STUDENT_MODELS
from .sampling import representation_sample_indices


def cosine_distance_means(a: np.ndarray, b: np.ndarray) -> float:
    x = np.asarray(a, dtype=np.float64).ravel()
    y = np.asarray(b, dtype=np.float64).ravel()
    nx = np.linalg.norm(x)
    ny = np.linalg.norm(y)
    if nx == 0.0 or ny == 0.0:
        return float("nan")
    return float(1.0 - np.dot(x, y) / (nx * ny))


def covariance_frobenius_ratio(cov_target: np.ndarray, cov_ref: np.ndarray) -> float:
    a = np.asarray(cov_target, dtype=np.float64)
    b = np.asarray(cov_ref, dtype=np.float64)
    denom = np.linalg.norm(b, ord="fro")
    if denom == 0.0:
        return float("nan")
    return float(np.linalg.norm(a - b, ord="fro") / denom)


def discriminant_direction(z_pos: np.ndarray, z_neg: np.ndarray) -> np.ndarray:
    """d = mean_pos - mean_neg. No classifier fitting."""
    return np.asarray(z_pos, dtype=np.float64).mean(axis=0) - np.asarray(z_neg, dtype=np.float64).mean(axis=0)


def project(z: np.ndarray, direction: np.ndarray) -> np.ndarray:
    d = np.asarray(direction, dtype=np.float64).ravel()
    return np.asarray(z, dtype=np.float64) @ d


def representation_separation(proj_pos: np.ndarray, proj_neg: np.ndarray, neg_sd_ref: float) -> float:
    sd = float(neg_sd_ref)
    if sd == 0.0 or not np.isfinite(sd):
        return float("nan")
    return float((np.mean(proj_pos) - np.mean(proj_neg)) / sd)


def representation_transfer_ratio(r61_sep: float, r52_sep: float) -> float:
    """R61 separation / R52 separation. Sign preserved."""
    if r52_sep == 0.0 or not np.isfinite(r52_sep):
        return float("nan")
    return float(r61_sep / r52_sep)


def attention_stats(alpha: np.ndarray) -> dict[str, float]:
    a = np.asarray(alpha, dtype=np.float64)
    a = np.clip(a, 1e-12, 1.0)
    a = a / a.sum(axis=-1, keepdims=True)
    entropy = -(a * np.log(a)).sum(axis=-1)
    t = np.arange(a.shape[-1], dtype=np.float64)
    com = (a * t).sum(axis=-1)
    return {
        "attention_entropy_mean": float(entropy.mean()),
        "max_attention_weight_mean": float(a.max(axis=-1).mean()),
        "attention_centre_of_mass_mean": float(com.mean()),
    }


def sample_from_split(sequence_ids: np.ndarray, labels: np.ndarray, n_neg: int = REPRESENTATION_NEGATIVE_N) -> np.ndarray:
    return representation_sample_indices(sequence_ids, labels, n_neg)


def per_model_separation(
    *,
    z_r52: np.ndarray,
    y_r52: np.ndarray,
    z_r61: np.ndarray,
    y_r61: np.ndarray,
) -> dict[str, float]:
    d = discriminant_direction(z_r52[y_r52 == 1], z_r52[y_r52 == 0])
    p52_pos = project(z_r52[y_r52 == 1], d)
    p52_neg = project(z_r52[y_r52 == 0], d)
    p61_pos = project(z_r61[y_r61 == 1], d)
    p61_neg = project(z_r61[y_r61 == 0], d)
    sd_neg_r52 = float(p52_neg.std(ddof=0))
    r52_sep = representation_separation(p52_pos, p52_neg, sd_neg_r52)
    r61_sep = representation_separation(p61_pos, p61_neg, sd_neg_r52)
    return {
        "R52_REPRESENTATION_SEPARATION": r52_sep,
        "R61_REPRESENTATION_SEPARATION": r61_sep,
        "REPRESENTATION_TRANSFER_RATIO": representation_transfer_ratio(r61_sep, r52_sep),
        "r52_neg_proj_sd": sd_neg_r52,
        "domain_cosine_distance": cosine_distance_means(z_r61.mean(axis=0), z_r52.mean(axis=0)),
        "cov_frobenius_ratio": covariance_frobenius_ratio(
            np.cov(z_r61, rowvar=False),
            np.cov(z_r52, rowvar=False),
        ),
    }
