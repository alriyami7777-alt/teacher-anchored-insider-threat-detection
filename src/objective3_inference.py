#!/usr/bin/env python3
"""Locked model loading and inference for Objective 3 (no retraining).

Legacy pilot path
-----------------
``load_locked_bundle`` / ``predict_with_extras`` serve the superseded Objective 3
pilot model set (soft forest, standalone Bi-LSTM, legacy ``attention_linear``
alias, fragmented XGB). Soft-forest ``routing`` extras are **not** ODST
explanations and must not be labelled as sparsemax feature-selection.

Selected-architecture path
--------------------------
Use ``objective3_model_interface.load_objective3_model`` and
``objective3_inference`` for hash-pinned ODST and Bi-LSTM–attention–linear
checkpoints registered in ``objective3_model_registry``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import torch
from torch.utils.data import DataLoader, Dataset

from evaluate_locked_objective2 import (
    load_bilstm,
    load_sequence_ensemble,
    load_tree_classifier,
    make_loader,
    predict_tree,
    select_device,
)
from models.sequence_ensemble import SequenceEnsembleModel
from objective3_locked_common import SAFE_FEATURES
from run_bilstm_baseline import BiLSTMClassifier
from run_fragmented_hybrid_baseline import load_pretrained_encoder


@dataclass
class LockedBundle:
    model_id: str
    seed: int
    threshold: float
    kind: str  # bilstm | ensemble | fragmented
    torch_model: torch.nn.Module | None = None
    tree_model: Any = None
    encoder: SequenceEnsembleModel | None = None
    device: torch.device | None = None
    config: dict[str, Any] | None = None


class ArraySequenceDataset(Dataset):
    """In-memory (N,T,F) dataset for perturbed batches."""

    def __init__(self, x: np.ndarray, y: np.ndarray) -> None:
        self.X = np.asarray(x, dtype=np.float32)
        self.y = np.asarray(y, dtype=np.float32)
        if self.X.ndim != 3:
            raise ValueError(f"Expected 3D X; got {self.X.shape}")
        if len(self.X) != len(self.y):
            raise ValueError("X/y length mismatch")

    def __len__(self) -> int:
        return int(self.X.shape[0])

    def __getitem__(self, idx: int):
        return (
            torch.from_numpy(self.X[idx]),
            torch.tensor(self.y[idx], dtype=torch.float32),
        )


def load_locked_bundle(
    root: Path,
    entry: dict[str, Any],
    device: torch.device,
) -> LockedBundle:
    """Load frozen checkpoints from paths recorded in the Obj2 test manifest."""
    model_id = entry["model_id"]
    seed = int(entry["seed"])
    thr = float(entry["validation_threshold"])
    cfg = dict(entry.get("hyperparameters") or {})
    cfg.setdefault("seed", seed)

    if model_id == "standalone_bilstm":
        ckpt = root / entry["checkpoint_path"]
        # Config lives beside checkpoint; reconstruct from hyperparameters if needed.
        model = load_bilstm(ckpt, cfg, device)
        return LockedBundle(
            model_id=model_id,
            seed=seed,
            threshold=thr,
            kind="bilstm",
            torch_model=model,
            device=device,
            config=cfg,
        )

    if model_id in {"attention_linear", "joint_bilstm_attention_soft_forest"}:
        # Legacy pilot path only. Soft forest is superseded_model_only and is
        # not the selected ODST architecture.
        ckpt = root / entry["checkpoint_path"]
        # Ensure required keys for SequenceEnsembleModel construction.
        cfg.setdefault("classification_head", "linear" if model_id == "attention_linear" else "soft_forest")
        cfg.setdefault("temporal_aggregation", "attention")
        cfg.setdefault("hidden_size", 64)
        cfg.setdefault("dropout", 0.2)
        cfg.setdefault("attention_dim", 64)
        cfg.setdefault("n_trees", 5)
        cfg.setdefault("tree_depth", 4)
        if model_id == "joint_bilstm_attention_soft_forest":
            cfg["superseded_model_only"] = True
            cfg["not_odst"] = True
        model = load_sequence_ensemble(ckpt, cfg, device)
        return LockedBundle(
            model_id=model_id,
            seed=seed,
            threshold=thr,
            kind="ensemble",
            torch_model=model,
            device=device,
            config=cfg,
        )

    if model_id == "fragmented_bilstm_xgboost":
        enc_path = root / entry["encoder_checkpoint_path"]
        clf_path = root / entry["classifier_path"]
        encoder, _ = load_pretrained_encoder(enc_path, device)
        tree = load_tree_classifier(model_id, clf_path)
        return LockedBundle(
            model_id=model_id,
            seed=seed,
            threshold=thr,
            kind="fragmented",
            encoder=encoder,
            tree_model=tree,
            device=device,
            config=cfg,
        )

    raise ValueError(f"Unsupported Objective 3 model_id: {model_id}")


@torch.no_grad()
def predict_with_extras(
    bundle: LockedBundle,
    x: np.ndarray,
    y: np.ndarray,
    batch_size: int = 1024,
) -> dict[str, Any]:
    """Run locked legacy-pilot inference; return probs plus optional extras.

    For ``kind=="ensemble"`` with a soft-forest head, ``routing`` is soft-tree
    routing (superseded_model_only). It is not ODST sparsemax/leaf output.
    Selected ODST inference must use ``objective3_model_interface``.
    """
    device = bundle.device or torch.device("cpu")
    ds = ArraySequenceDataset(x, y)
    loader = make_loader(ds, batch_size=batch_size)

    if bundle.kind == "bilstm":
        assert isinstance(bundle.torch_model, BiLSTMClassifier)
        model = bundle.torch_model
        model.eval()
        probs: list[np.ndarray] = []
        for xb, _ in loader:
            logits = model(xb.to(device))
            probs.append(torch.sigmoid(logits).cpu().numpy())
        return {
            "probs": np.concatenate(probs, axis=0),
            "attention_weights": None,
            "routing": None,
            "aggregated": None,
        }

    if bundle.kind == "ensemble":
        assert isinstance(bundle.torch_model, SequenceEnsembleModel)
        model = bundle.torch_model
        model.eval()
        probs_l: list[np.ndarray] = []
        attn_l: list[np.ndarray] = []
        agg_l: list[np.ndarray] = []
        routing_batches: list[list[dict[str, np.ndarray]]] | None = None
        for xb, _ in loader:
            logits, extras = model(xb.to(device))
            probs_l.append(torch.sigmoid(logits).cpu().numpy())
            attn_l.append(extras["attention_weights"].cpu().numpy())
            agg_l.append(extras["aggregated"].cpu().numpy())
            routing = extras.get("routing") or []
            if routing:
                batch_routes = [
                    {
                        "leaf_probs": r["leaf_probs"].cpu().numpy(),
                        "tree_logit": r["tree_logit"].cpu().numpy(),
                        "p_left": r["p_left"].cpu().numpy(),
                        "p_right": r["p_right"].cpu().numpy(),
                    }
                    for r in routing
                ]
                if routing_batches is None:
                    routing_batches = [[] for _ in batch_routes]
                for ti, route in enumerate(batch_routes):
                    routing_batches[ti].append(route)
        merged_routing = None
        if routing_batches is not None:
            merged_routing = []
            for tree_batches in routing_batches:
                merged_routing.append(
                    {
                        "leaf_probs": np.concatenate([b["leaf_probs"] for b in tree_batches], axis=0),
                        "tree_logit": np.concatenate([b["tree_logit"] for b in tree_batches], axis=0),
                        "p_left": np.concatenate([b["p_left"] for b in tree_batches], axis=0),
                        "p_right": np.concatenate([b["p_right"] for b in tree_batches], axis=0),
                    }
                )
        return {
            "probs": np.concatenate(probs_l, axis=0),
            "attention_weights": np.concatenate(attn_l, axis=0),
            "routing": merged_routing,
            "aggregated": np.concatenate(agg_l, axis=0),
        }

    if bundle.kind == "fragmented":
        assert bundle.encoder is not None and bundle.tree_model is not None
        # Also capture encoder attention for temporal analysis.
        enc = bundle.encoder
        enc.eval()
        zs: list[np.ndarray] = []
        attn_l = []
        for xb, _ in loader:
            xb_d = xb.to(device)
            _, extras = enc(xb_d)
            zs.append(extras["aggregated"].cpu().numpy())
            attn_l.append(extras["attention_weights"].cpu().numpy())
        z = np.concatenate(zs, axis=0)
        probs_arr = predict_tree(bundle.tree_model, z)
        return {
            "probs": probs_arr.astype(np.float32),
            "attention_weights": np.concatenate(attn_l, axis=0),
            "routing": None,
            "aggregated": z,
        }

    raise ValueError(f"Unknown bundle kind: {bundle.kind}")


def load_split_arrays(
    npz_path: Path,
    *,
    max_sequences: int | None = None,
    seed: int = 42,
    stratify: bool = True,
) -> tuple[np.ndarray, np.ndarray, dict[str, np.ndarray]]:
    """Load X, y and metadata; optionally subsample for smoke runs."""
    z = np.load(npz_path, allow_pickle=True, mmap_mode="r")
    x = np.asarray(z["X"], dtype=np.float32)
    y = np.asarray(z["y"]).astype(np.int8)
    meta: dict[str, np.ndarray] = {"y": y}
    for key in ("sequence_id", "user", "start_date", "end_date"):
        if key in z.files:
            meta[key] = np.asarray(z[key]).astype(str)

    if max_sequences is not None and max_sequences < len(y):
        rng = np.random.default_rng(seed)
        if stratify and y.sum() > 0 and (len(y) - y.sum()) > 0:
            pos = np.where(y == 1)[0]
            neg = np.where(y == 0)[0]
            # Keep enough positives for stable PR-AUC / class comparisons in smoke runs.
            n_pos = min(len(pos), max(32, int(round(max_sequences * 0.25))))
            n_pos = min(n_pos, max_sequences - 1)
            n_neg = max_sequences - n_pos
            if n_neg > len(neg):
                n_neg = len(neg)
                n_pos = max_sequences - n_neg
            idx = np.concatenate(
                [
                    rng.choice(pos, size=n_pos, replace=False),
                    rng.choice(neg, size=n_neg, replace=False),
                ]
            )
            rng.shuffle(idx)
        else:
            idx = rng.choice(len(y), size=max_sequences, replace=False)
        x = np.array(x[idx], dtype=np.float32, copy=True)
        y = y[idx].copy()
        for k in list(meta.keys()):
            meta[k] = meta[k][idx]
    else:
        # Materialise a writable copy for perturbations.
        x = np.array(x, dtype=np.float32, copy=True)

    if x.shape[-1] != len(SAFE_FEATURES):
        raise ValueError(f"Expected {len(SAFE_FEATURES)} features; got {x.shape[-1]}")
    return x, y, meta


__all__ = [
    "ArraySequenceDataset",
    "LockedBundle",
    "load_locked_bundle",
    "load_split_arrays",
    "predict_with_extras",
    "select_device",
]
