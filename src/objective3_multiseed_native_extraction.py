#!/usr/bin/env python3
"""Multi-seed native explanation extraction helpers (stability, not faithfulness).

CERT r4.2 validation only. Reuses the frozen 20-sequence sample.
No latent-dimension / tree / leaf identity alignment across seeds.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from objective3_locked_common import SEQ_LEN, sha256_file
from objective3_model_registry import (
    NEURAL_REFERENCE_ARCHITECTURE,
    PRIMARY_ARCHITECTURE,
)
from objective3_native_explanation_pilot import (
    ProtocolVerificationError,
    attention_entropy,
    jaccard,
    load_frozen_threshold,
    normalised_attention_entropy,
    pearson_corr,
    section_masses,
    spearman_corr,
    timestep_calendar_dates,
    top_k_indices,
    verify_protocol,
)
from objective3_odst_loader import resolve_checkpoint_path
from objective3_model_interface import load_objective3_model, parameter_digest

EXPECTED_MANIFEST_SHA256 = (
    "5c71e234d5b4eccd48095b114ec34351d841780bd46fc0ab295d7a6d84812a10"
)
DEFAULT_SEEDS: tuple[int, ...] = (42, 52, 62)
SEED_PAIRS: tuple[tuple[int, int], ...] = ((42, 52), (42, 62), (52, 62))
ARCHITECTURES: tuple[str, ...] = (
    PRIMARY_ARCHITECTURE,
    NEURAL_REFERENCE_ARCHITECTURE,
)


def cosine_similarity(a: np.ndarray, b: np.ndarray, eps: float = 1e-12) -> float:
    a = np.asarray(a, dtype=np.float64).ravel()
    b = np.asarray(b, dtype=np.float64).ravel()
    na = np.linalg.norm(a)
    nb = np.linalg.norm(b)
    if na < eps or nb < eps:
        return float("nan")
    return float(np.dot(a, b) / (na * nb))


def jensen_shannon_divergence(a: np.ndarray, b: np.ndarray, eps: float = 1e-12) -> float:
    """JS divergence in nats between two discrete distributions."""
    p = np.asarray(a, dtype=np.float64).ravel()
    q = np.asarray(b, dtype=np.float64).ravel()
    p = np.clip(p, 0.0, None)
    q = np.clip(q, 0.0, None)
    ps, qs = p.sum(), q.sum()
    if ps <= 0 or qs <= 0:
        return float("nan")
    p = p / ps
    q = q / qs
    m = 0.5 * (p + q)

    def _kl(x: np.ndarray, y: np.ndarray) -> float:
        mask = x > 0
        return float(np.sum(x[mask] * (np.log(x[mask] + eps) - np.log(y[mask] + eps))))

    return 0.5 * _kl(p, m) + 0.5 * _kl(q, m)


def sample_order_hash(sequence_ids: Iterable[str]) -> str:
    payload = "|".join(str(s) for s in sequence_ids).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def tensor_batch_hash(x: np.ndarray) -> str:
    arr = np.ascontiguousarray(np.asarray(x, dtype=np.float32))
    h = hashlib.sha256()
    h.update(arr.shape.__repr__().encode("utf-8"))
    h.update(arr.tobytes())
    return h.hexdigest()


def verify_frozen_sample_manifest(
    manifest_path: Path,
    *,
    expected_sha256: str = EXPECTED_MANIFEST_SHA256,
) -> dict[str, Any]:
    if not manifest_path.exists():
        raise ProtocolVerificationError(f"Sample manifest missing: {manifest_path}")
    observed = sha256_file(manifest_path)
    if observed != expected_sha256:
        raise ProtocolVerificationError(
            f"Sample manifest hash mismatch: observed={observed} expected={expected_sha256}"
        )
    df = pd.read_csv(manifest_path)
    required = {
        "sample_id",
        "sequence_id",
        "user_id",
        "joint_stratum",
        "ground_truth",
        "validation_row_index",
    }
    missing = required - set(df.columns)
    if missing:
        raise ProtocolVerificationError(f"Manifest missing columns: {sorted(missing)}")
    if len(df) != 20:
        raise ProtocolVerificationError(f"Expected 20 samples; got {len(df)}")
    if df["sequence_id"].nunique() != 20:
        raise ProtocolVerificationError("Sequence IDs are not unique")
    strata = df["joint_stratum"].value_counts().to_dict()
    if len(strata) < 4:
        raise ProtocolVerificationError(f"Expected four strata; got {strata}")
    order_h = sample_order_hash(df["sequence_id"].astype(str).tolist())
    # Re-read to confirm order stability of CSV bytes already covered by file hash
    return {
        "manifest_path": str(manifest_path).replace("\\", "/"),
        "expected_hash": expected_sha256,
        "observed_hash": observed,
        "row_count": int(len(df)),
        "unique_sequence_count": int(df["sequence_id"].nunique()),
        "unique_user_count": int(df["user_id"].nunique()),
        "stratum_counts": {str(k): int(v) for k, v in strata.items()},
        "sample_order_hash": order_h,
        "sample_ids": df["sample_id"].astype(str).tolist(),
        "sequence_ids": df["sequence_id"].astype(str).tolist(),
        "verification_status": "verified",
        "strata_not_redefined_for_seeds_52_62": True,
    }


def classify_prediction_consistency(
    preds: list[int],
    y_true: int,
) -> str:
    preds_i = [int(p) for p in preds]
    if len(set(preds_i)) > 1:
        return "prediction_disagreement"
    pred = preds_i[0]
    if pred == int(y_true):
        return "prediction_unanimous_correct"
    return "prediction_unanimous_incorrect"


def effective_support(weights: np.ndarray, eps: float = 1e-12) -> float:
    """Effective number of dimensions: exp(entropy)."""
    w = np.asarray(weights, dtype=np.float64).ravel()
    w = np.clip(w, 0.0, None)
    s = w.sum()
    if s <= 0:
        return 0.0
    w = w / s
    return float(np.exp(-(w * np.log(w + eps)).sum()))


def odst_structural_summaries_from_tensors(
    *,
    feature_selection: np.ndarray,
    routing: np.ndarray,
    leaf_probs: np.ndarray,
    tree_outputs: np.ndarray | None,
    sample_index: int,
) -> dict[str, float]:
    """Distributional ODST summaries for one sample (no cross-seed identity).

    feature_selection: (n_trees, depth, d_in) — shared across batch for layer-0
    routing: (B, n_trees, depth)
    leaf_probs: (B, n_trees, n_leaves)
    tree_outputs: (B, n_trees_total) or None
    """
    fs = np.asarray(feature_selection, dtype=np.float64)
    # Aggregate selection mass across trees/depths for sample-level sparsity profile
    # (same fs for all samples in layer-0 shared tensor; still a valid structural property)
    mean_fs = fs.mean(axis=(0, 1))
    active = mean_fs > 1e-8
    n_active = int(active.sum())
    prop_active = float(n_active / mean_fs.size)
    sel_ent = attention_entropy(mean_fs) if mean_fs.sum() > 0 else float("nan")
    max_w = float(mean_fs.max()) if mean_fs.size else float("nan")
    top1 = top_k_indices(mean_fs, 1)
    top3 = top_k_indices(mean_fs, 3)
    top5 = top_k_indices(mean_fs, 5)

    choice = np.asarray(routing[sample_index], dtype=np.float64)  # (T, D)
    # Binary routing entropy per split: -p log p - (1-p) log(1-p)
    p = np.clip(choice, 1e-8, 1 - 1e-8)
    route_ent = -(p * np.log(p) + (1 - p) * np.log(1 - p))
    near_det = ((choice < 0.05) | (choice > 0.95)).mean()
    uncertain = ((choice >= 0.35) & (choice <= 0.65)).mean()

    leaf = np.asarray(leaf_probs[sample_index], dtype=np.float64)  # (T, L)
    leaf_ents = np.array([attention_entropy(leaf[t]) for t in range(leaf.shape[0])])
    dom_probs = leaf.max(axis=1)
    n_active_leaves = (leaf > 0.01).sum(axis=1)

    out: dict[str, float] = {
        "n_active_latent_dims": float(n_active),
        "prop_active_latent_dims": prop_active,
        "sparsemax_selection_entropy": float(sel_ent),
        "sparsemax_max_weight": max_w,
        "sparsemax_top1_mass": float(mean_fs[top1].sum()),
        "sparsemax_top3_mass": float(mean_fs[top3].sum()),
        "sparsemax_top5_mass": float(mean_fs[top5].sum()),
        "sparsemax_effective_dims": effective_support(mean_fs),
        "routing_entropy_mean": float(route_ent.mean()),
        "routing_entropy_min": float(route_ent.min()),
        "routing_entropy_max": float(route_ent.max()),
        "routing_near_deterministic_prop": float(near_det),
        "routing_uncertain_prop": float(uncertain),
        "routing_entropy_depth0_mean": float(route_ent[:, 0].mean())
        if route_ent.ndim == 2
        else float("nan"),
        "routing_entropy_depth_last_mean": float(route_ent[:, -1].mean())
        if route_ent.ndim == 2
        else float("nan"),
        "leaf_entropy_mean": float(leaf_ents.mean()),
        "dominant_leaf_probability_mean": float(dom_probs.mean()),
        "n_active_leaves_mean": float(n_active_leaves.mean()),
        "prop_trees_one_dominant_leaf": float((dom_probs > 0.5).mean()),
    }
    if tree_outputs is not None:
        t = np.asarray(tree_outputs[sample_index], dtype=np.float64)
        abs_t = np.abs(t)
        out.update(
            {
                "tree_output_mean_abs": float(abs_t.mean()),
                "tree_output_std": float(t.std(ddof=0)),
                "tree_output_prop_positive": float((t > 0).mean()),
                "tree_output_prop_negative": float((t < 0).mean()),
                "tree_output_abs_concentration_top3": float(
                    abs_t[top_k_indices(abs_t, min(3, abs_t.size))].sum() / max(abs_t.sum(), 1e-12)
                ),
            }
        )
    return out


def attention_pair_metrics(a: np.ndarray, b: np.ndarray) -> dict[str, float]:
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    t1a, t1b = top_k_indices(a, 1)[0], top_k_indices(b, 1)[0]
    t3a, t3b = set(top_k_indices(a, 3)), set(top_k_indices(b, 3))
    t5a, t5b = set(top_k_indices(a, 5)), set(top_k_indices(b, 5))
    centre_a = float(np.sum(np.arange(1, a.size + 1) * a))
    centre_b = float(np.sum(np.arange(1, b.size + 1) * b))
    return {
        "spearman": spearman_corr(a, b),
        "pearson": pearson_corr(a, b),
        "cosine": cosine_similarity(a, b),
        "mean_abs_diff": float(np.mean(np.abs(a - b))),
        "js_divergence": jensen_shannon_divergence(a, b),
        "top1_agreement": float(t1a == t1b),
        "top3_overlap": float(len(t3a & t3b)),
        "top5_overlap": float(len(t5a & t5b)),
        "jaccard_top3": jaccard(t3a, t3b),
        "jaccard_top5": jaccard(t5a, t5b),
        "abs_entropy_diff": abs(attention_entropy(a) - attention_entropy(b)),
        "abs_peak_diff": abs(float(a.max() - b.max())),
        "abs_temporal_centre_diff": abs(centre_a - centre_b),
    }


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


def coefficient_of_variation(values: list[float], eps: float = 1e-12) -> float:
    arr = np.asarray(values, dtype=np.float64)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return float("nan")
    mu = float(arr.mean())
    if abs(mu) < eps:
        return float("nan")
    sd = float(arr.std(ddof=1)) if arr.size > 1 else 0.0
    return sd / abs(mu)


__all__ = [
    "ARCHITECTURES",
    "DEFAULT_SEEDS",
    "EXPECTED_MANIFEST_SHA256",
    "SEED_PAIRS",
    "attention_pair_metrics",
    "classify_prediction_consistency",
    "coefficient_of_variation",
    "cosine_similarity",
    "descriptive_stats",
    "effective_support",
    "jensen_shannon_divergence",
    "odst_structural_summaries_from_tensors",
    "sample_order_hash",
    "tensor_batch_hash",
    "verify_frozen_sample_manifest",
    "verify_protocol",
    "ProtocolVerificationError",
    "PRIMARY_ARCHITECTURE",
    "NEURAL_REFERENCE_ARCHITECTURE",
    "attention_entropy",
    "normalised_attention_entropy",
    "section_masses",
    "timestep_calendar_dates",
    "top_k_indices",
    "load_frozen_threshold",
    "load_objective3_model",
    "parameter_digest",
    "resolve_checkpoint_path",
    "sha256_file",
    "SEQ_LEN",
]
