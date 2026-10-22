"""EDITOR-010 diagnostic-only ODST routing statistics. Not for manuscript figures."""

from __future__ import annotations

from typing import Any

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset

from .constants import BATCH_SIZE


@torch.no_grad()
def odst_head_diagnostics(head: nn.Module, h: np.ndarray, device: torch.device) -> dict[str, Any]:
    node = getattr(head, "node", None)
    if node is None:
        return {"status": "not_odst"}
    loader = DataLoader(
        TensorDataset(torch.from_numpy(np.asarray(h, dtype=np.float32))),
        batch_size=BATCH_SIZE,
        shuffle=False,
    )
    head.eval()
    leaf_masses: list[np.ndarray] = []
    tree_outs: list[np.ndarray] = []
    entropies: list[float] = []
    for (hb,) in loader:
        _, extras = head(hb.to(device))
        bags = extras.get("layer_tree_logits") or []
        if bags:
            trees = torch.cat(bags, dim=-1)
            tree_outs.append(trees.detach().cpu().numpy())
        layers = extras.get("odst_layers") or []
        for layer in layers:
            lp = layer["leaf_probs"]  # (B, T, L)
            p = lp.clamp_min(1e-12)
            ent = -(p * p.log()).sum(dim=-1).mean()
            entropies.append(float(ent.cpu()))
            leaf_masses.append(lp.mean(dim=0).detach().cpu().numpy())
    if not tree_outs:
        return {"status": "no_tree_outputs", "label": "EDITOR010_DIAGNOSTIC_ONLY"}
    trees = np.concatenate(tree_outs, axis=0)
    var = trees.var(axis=0)
    if trees.shape[1] > 1:
        corr = np.corrcoef(trees.T)
        off = corr[np.triu_indices_from(corr, k=1)]
        tree_corr = float(np.nanmean(off))
    else:
        tree_corr = float("nan")
    masses = None
    active = float("nan")
    if leaf_masses:
        masses = np.mean(np.stack([m.reshape(-1) for m in leaf_masses], axis=0), axis=0)
        thresh = 1.0 / max(len(masses), 1) * 0.01
        active = float((masses > thresh).mean())
    return {
        "label": "EDITOR010_DIAGNOSTIC_ONLY",
        "routing_entropy": float(np.mean(entropies)) if entropies else float("nan"),
        "effective_active_leaves_fraction": active,
        "leaf_mass_entropy": float(-np.sum(masses * np.log(np.clip(masses, 1e-12, 1)))) if masses is not None else float("nan"),
        "per_tree_output_variance_mean": float(np.mean(var)),
        "tree_output_correlation": tree_corr,
    }
