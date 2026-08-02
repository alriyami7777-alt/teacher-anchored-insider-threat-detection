#!/usr/bin/env python3
"""Temporal attention, soft-tree, and feature-masking analyses for Objective 3."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from objective3_locked_common import (
    DEFAULT_UNUSED_LEAF_THRESHOLD,
    SAFE_FEATURES,
    entropy_np,
    metrics_at_threshold,
    temporal_concentration,
)
from objective3_perturbations import feature_mask_all


def attention_sequence_frame(
    attn: np.ndarray,
    y: np.ndarray,
    meta: dict[str, np.ndarray],
    *,
    model_id: str,
    seed: int,
    top_k: int = 3,
) -> pd.DataFrame:
    """Per-sequence attention summary with IDs, users, and dates."""
    attn = np.asarray(attn, dtype=np.float64)
    if attn.ndim != 2:
        raise ValueError(f"Expected (N, T) attention; got {attn.shape}")
    n, t = attn.shape
    ent = entropy_np(attn, axis=1)
    max_w = attn.max(axis=1)
    conc = temporal_concentration(attn, top_k=top_k)
    rows = {
        "model_id": model_id,
        "seed": int(seed),
        "y_true": np.asarray(y).astype(np.int8),
        "label": np.where(np.asarray(y) > 0, "malicious", "benign"),
        "attention_entropy": ent.astype(np.float32),
        "attention_max_weight": max_w.astype(np.float32),
        "temporal_concentration_top3": conc.astype(np.float32),
        "attention_argmax_t": attn.argmax(axis=1).astype(np.int16),
    }
    for key in ("sequence_id", "user", "start_date", "end_date"):
        if key in meta:
            rows[key] = np.asarray(meta[key]).astype(str)
    for ti in range(t):
        rows[f"attn_t{ti:02d}"] = attn[:, ti].astype(np.float32)
    return pd.DataFrame(rows)


def attention_group_comparison(seq_df: pd.DataFrame) -> pd.DataFrame:
    """Compare malicious vs benign attention statistics."""
    metrics = [
        "attention_entropy",
        "attention_max_weight",
        "temporal_concentration_top3",
    ]
    rows: list[dict[str, Any]] = []
    for (model_id, seed), g in seq_df.groupby(["model_id", "seed"]):
        for label in ("malicious", "benign"):
            sub = g[g["label"] == label]
            for m in metrics:
                s = pd.to_numeric(sub[m], errors="coerce")
                rows.append(
                    {
                        "model_id": model_id,
                        "seed": int(seed),
                        "label": label,
                        "metric": m,
                        "mean": float(s.mean()) if len(s) else float("nan"),
                        "std": float(s.std(ddof=1)) if len(s) > 1 else 0.0,
                        "median": float(s.median()) if len(s) else float("nan"),
                        "n": int(len(s)),
                    }
                )
        # Mean attention profile by class
        attn_cols = [c for c in g.columns if c.startswith("attn_t")]
        for label in ("malicious", "benign"):
            sub = g[g["label"] == label]
            if sub.empty:
                continue
            means = sub[attn_cols].mean()
            for col, val in means.items():
                rows.append(
                    {
                        "model_id": model_id,
                        "seed": int(seed),
                        "label": label,
                        "metric": col,
                        "mean": float(val),
                        "std": float(sub[col].std(ddof=1)) if len(sub) > 1 else 0.0,
                        "median": float(sub[col].median()),
                        "n": int(len(sub)),
                    }
                )
    return pd.DataFrame(rows)


def soft_tree_analysis(
    routing: list[dict[str, np.ndarray]],
    y: np.ndarray,
    meta: dict[str, np.ndarray],
    *,
    model_id: str,
    seed: int,
    unused_leaf_threshold: float = DEFAULT_UNUSED_LEAF_THRESHOLD,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Soft-tree routing entropy, leaf utilisation, dominant paths, class comparison.

    Returns:
      sequence_df: per-sequence routing summaries
      tree_df: per-tree aggregate utilisation / unused leaves
      leaf_df: per-leaf utilisation and contribution by class
    """
    y = np.asarray(y).astype(np.int8)
    n = len(y)
    seq_rows: list[dict[str, Any]] = []
    tree_rows: list[dict[str, Any]] = []
    leaf_rows: list[dict[str, Any]] = []

    # Per-sequence mean routing entropy across trees
    per_seq_ents = np.zeros(n, dtype=np.float64)
    per_seq_max_leaf = np.zeros(n, dtype=np.float64)

    for ti, route in enumerate(routing):
        leaf = np.asarray(route["leaf_probs"], dtype=np.float64)  # (N, L)
        tree_logit = np.asarray(route["tree_logit"], dtype=np.float64)
        # Contribution of each leaf to tree logit: leaf_prob * leaf_logit_param
        # Reconstruct leaf logits from tree_logit ≈ sum(leaf_probs * leaf_logit)
        # We do not have leaf_logit params here; use leaf_probs * sign(tree_logit)
        # as a soft importance proxy, plus utilisation.
        ent = entropy_np(leaf, axis=1)
        per_seq_ents += ent
        max_leaf_prob = leaf.max(axis=1)
        per_seq_max_leaf += max_leaf_prob
        dominant_leaf = leaf.argmax(axis=1)

        util_all = leaf.mean(axis=0)
        unused = int((util_all < unused_leaf_threshold).sum())
        unused_pct = 100.0 * unused / leaf.shape[1]

        for label_name, mask in (
            ("all", np.ones(n, dtype=bool)),
            ("malicious", y == 1),
            ("benign", y == 0),
        ):
            if not mask.any():
                continue
            util = leaf[mask].mean(axis=0)
            unused_c = int((util < unused_leaf_threshold).sum())
            tree_rows.append(
                {
                    "model_id": model_id,
                    "seed": int(seed),
                    "tree_index": ti,
                    "label": label_name,
                    "routing_entropy_mean": float(ent[mask].mean()),
                    "mean_leaf_utilisation": float(util.mean()),
                    "unused_leaves": unused_c,
                    "unused_leaf_pct": 100.0 * unused_c / leaf.shape[1],
                    "n_leaves": int(leaf.shape[1]),
                    "n_sequences": int(mask.sum()),
                    "mean_tree_logit": float(tree_logit[mask].mean()),
                }
            )
            # Dominant path: most frequent argmax leaf under soft routing
            dom = dominant_leaf[mask]
            vals, counts = np.unique(dom, return_counts=True)
            top = vals[counts.argmax()]
            tree_rows[-1]["dominant_leaf"] = int(top)
            tree_rows[-1]["dominant_leaf_share"] = float(counts.max() / mask.sum())

            for leaf_i in range(leaf.shape[1]):
                # Soft contribution: mean(leaf_prob) as utilisation;
                # weighted by mean positive tree logit mass when available.
                leaf_rows.append(
                    {
                        "model_id": model_id,
                        "seed": int(seed),
                        "tree_index": ti,
                        "leaf_index": leaf_i,
                        "label": label_name,
                        "mean_leaf_prob": float(util[leaf_i]),
                        "unused": bool(util[leaf_i] < unused_leaf_threshold),
                        "mean_abs_contribution_proxy": float(
                            (leaf[mask, leaf_i] * np.abs(tree_logit[mask])).mean()
                        ),
                    }
                )

        tree_rows.append(
            {
                "model_id": model_id,
                "seed": int(seed),
                "tree_index": ti,
                "label": "overall_unused_pct",
                "routing_entropy_mean": float(ent.mean()),
                "mean_leaf_utilisation": float(util_all.mean()),
                "unused_leaves": unused,
                "unused_leaf_pct": unused_pct,
                "n_leaves": int(leaf.shape[1]),
                "n_sequences": n,
                "mean_tree_logit": float(tree_logit.mean()),
                "dominant_leaf": int(np.bincount(dominant_leaf).argmax()),
                "dominant_leaf_share": float(
                    np.bincount(dominant_leaf).max() / n
                ),
            }
        )

    n_trees = max(len(routing), 1)
    per_seq_ents /= n_trees
    per_seq_max_leaf /= n_trees

    for i in range(n):
        row: dict[str, Any] = {
            "model_id": model_id,
            "seed": int(seed),
            "y_true": int(y[i]),
            "label": "malicious" if y[i] else "benign",
            "mean_routing_entropy": float(per_seq_ents[i]),
            "mean_max_leaf_prob": float(per_seq_max_leaf[i]),
        }
        for key in ("sequence_id", "user", "start_date", "end_date"):
            if key in meta:
                row[key] = str(meta[key][i])
        # Per-tree dominant leaf
        for ti, route in enumerate(routing):
            leaf = route["leaf_probs"][i]
            row[f"tree{ti}_dominant_leaf"] = int(np.argmax(leaf))
            row[f"tree{ti}_max_leaf_prob"] = float(np.max(leaf))
            row[f"tree{ti}_routing_entropy"] = float(entropy_np(leaf[None, :], axis=1)[0])
        seq_rows.append(row)

    return pd.DataFrame(seq_rows), pd.DataFrame(tree_rows), pd.DataFrame(leaf_rows)


def soft_tree_class_comparison(seq_df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for (model_id, seed), g in seq_df.groupby(["model_id", "seed"]):
        for label in ("malicious", "benign"):
            sub = g[g["label"] == label]
            rows.append(
                {
                    "model_id": model_id,
                    "seed": int(seed),
                    "label": label,
                    "mean_routing_entropy": float(sub["mean_routing_entropy"].mean())
                    if len(sub)
                    else float("nan"),
                    "mean_max_leaf_prob": float(sub["mean_max_leaf_prob"].mean())
                    if len(sub)
                    else float("nan"),
                    "n": int(len(sub)),
                }
            )
    return pd.DataFrame(rows)


def feature_masking_analysis(
    predict_fn,
    x: np.ndarray,
    y: np.ndarray,
    *,
    threshold: float,
    model_id: str,
    seed: int,
    clean_probs: np.ndarray | None = None,
) -> pd.DataFrame:
    """Mask each of 13 features; rank by mean |Δp| and metric degradation."""
    if clean_probs is None:
        clean_out = predict_fn(x)
        clean_probs = clean_out["probs"]
    clean_metrics = metrics_at_threshold(y, clean_probs, threshold)
    rows: list[dict[str, Any]] = []
    for name, idx, x_masked in feature_mask_all(x):
        out = predict_fn(x_masked)
        probs = out["probs"]
        delta = probs - clean_probs
        m = metrics_at_threshold(y, probs, threshold)
        rows.append(
            {
                "model_id": model_id,
                "seed": int(seed),
                "feature": name,
                "feature_index": idx,
                "mean_abs_prob_change": float(np.mean(np.abs(delta))),
                "mean_prob_change": float(np.mean(delta)),
                "mean_abs_prob_change_malicious": float(np.mean(np.abs(delta[y == 1])))
                if (y == 1).any()
                else float("nan"),
                "mean_abs_prob_change_benign": float(np.mean(np.abs(delta[y == 0])))
                if (y == 0).any()
                else float("nan"),
                "pr_auc_degradation": float(clean_metrics["pr_auc"] - m["pr_auc"]),
                "f1_degradation": float(clean_metrics["f1"] - m["f1"]),
                "recall_degradation": float(clean_metrics["recall"] - m["recall"]),
                "fp_change": int(m["fp"] - clean_metrics["fp"]),
                "fn_change": int(m["fn"] - clean_metrics["fn"]),
                "clean_pr_auc": float(clean_metrics["pr_auc"]),
                "masked_pr_auc": float(m["pr_auc"]),
                "clean_f1": float(clean_metrics["f1"]),
                "masked_f1": float(m["f1"]),
            }
        )
    df = pd.DataFrame(rows)
    df["rank_by_abs_prob_change"] = df["mean_abs_prob_change"].rank(ascending=False).astype(int)
    df["rank_by_pr_auc_degradation"] = df["pr_auc_degradation"].rank(ascending=False).astype(int)
    return df.sort_values("rank_by_abs_prob_change").reset_index(drop=True)
